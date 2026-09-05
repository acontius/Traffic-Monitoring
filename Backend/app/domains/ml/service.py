"""Orchestrates the ML engine (`Backend/app/ml/*`) for the ingestion
gateway, the background workers, and the HTTP API. This is the only module
that wires the framework-agnostic engine to DB access, alerts, and realtime
push — the engine itself stays independent of all three.
"""

import logging
from datetime import datetime
from typing import Any, Optional

import asyncpg

from Backend.app.core.config import get_settings
from Backend.app.domains.ingestion import queries as ingestion_queries
from Backend.app.domains.ml import queries as ml_queries
from Backend.app.domains.notifications import service as notifications_service
from Backend.app.domains.realtime.bus import (
    broadcast_anomaly_event,
    broadcast_device_health,
)
from Backend.app.domains.reconstruction import service as reconstruction_service
from Backend.app.ml import (
    VEHICLE_TYPES,
    ai_explain,
    anomaly,
    calendar,
    features,
    health,
    policy,
    registry,
    training,
)
from Backend.app.ml.schemas import AnomalyEvidence, Explanation

logger = logging.getLogger("tcms.ml")


async def quick_score(
    pool: asyncpg.pool.Pool, device_id: str, timestamp: datetime, counts: dict[str, int]
) -> anomaly.AnomalyResult:
    """Cheap, synchronous, no-model-load scoring safe to call inline during
    ingestion (spec §44) — reuses the same short history slice the existing
    z-score check already fetches, so this stays a second opinion, not a
    second DB round-trip pattern."""
    hour = timestamp.hour
    lo, hi = max(0, hour - 1), min(23, hour + 1)
    payloads = await ingestion_queries.fetch_recent_payloads_near_hour(
        pool, device_id, lo, hi, 200
    )
    totals = [
        float(sum(p.get("counts", {}).values())) for p in payloads if p.get("counts")
    ]
    return anomaly.quick_score(counts, totals)


async def compute_health(
    pool: asyncpg.pool.Pool, device_id: str, expected_interval_seconds: int
) -> health.HealthAssessment:
    settings = get_settings()
    records = await ml_queries.fetch_recent_health_records(pool, device_id, limit=50)
    nonzero_keys = await ml_queries.fetch_historically_nonzero_keys(pool, device_id)
    latest = await ml_queries.get_latest_health(pool, device_id)
    previous_status = latest["health_status"] if latest else None
    return health.assess_health(
        records,
        expected_interval_seconds,
        settings.reconstruction_grace_periods,
        nonzero_keys,
        previous_status=previous_status,
    )


async def get_device_health(pool: asyncpg.pool.Pool, device_id: str) -> dict:
    snapshot = await ml_queries.get_latest_health(pool, device_id)
    if snapshot is None:
        return {
            "device_id": device_id,
            "health_status": "HEALTHY",
            "snapshot_at": None,
            "signals": {},
        }
    return {
        "device_id": device_id,
        "health_status": snapshot["health_status"],
        "snapshot_at": snapshot["snapshot_at"],
        "signals": snapshot["signals"],
    }


async def enrich_and_score(
    pool: asyncpg.pool.Pool,
    device_id: str,
    location_type: str,
    timestamp: datetime,
    counts: dict[str, int],
    expected_interval_seconds: int,
) -> None:
    """Heavier, model-backed anomaly scoring. Dispatched via
    `asyncio.create_task` from `domains.ingestion.service` so it never blocks
    the WebSocket loop (spec §44). Never raises — a failure here must not be
    allowed to look like an ingestion failure."""
    try:
        settings = get_settings()
        history = await ml_queries.fetch_device_history(
            pool, device_id, before_ts=timestamp, limit=500
        )
        events = (
            await ml_queries.fetch_active_events(pool, timestamp)
            if settings.ml_enable_event_context
            else []
        )

        predicted: dict[str, float] = {}
        model_id: Optional[int] = None
        for vehicle_type in VEHICLE_TYPES:
            model = await registry.load_active_model(pool, vehicle_type)
            if model is None or not model.is_trained:
                continue
            row = features.build_feature_row(
                history,
                timestamp,
                location_type,
                vehicle_type,
                expected_interval_seconds,
                events,
            )
            prediction = model.predict(row)
            if prediction is None:
                continue
            predicted[vehicle_type] = prediction.value
            model_row = await ml_queries.get_active_model(
                pool, registry.model_name_for(vehicle_type)
            )
            if model_row:
                model_id = model_row["id"]
                await ml_queries.insert_prediction(
                    pool,
                    device_id,
                    timestamp,
                    vehicle_type,
                    prediction.value,
                    prediction.interval_low,
                    prediction.interval_high,
                    model_row["id"],
                    row,
                )

        totals = [float(sum(r["counts"].values())) for r in history[-50:]]
        result = (
            anomaly.residual_score(counts, predicted, totals)
            if predicted
            else anomaly.quick_score(counts, totals)
        )

        health_assessment = await compute_health(
            pool, device_id, expected_interval_seconds
        )
        day_ctx = calendar.classify_day(timestamp)
        is_special = day_ctx.is_official_holiday or bool(events)
        decision = policy.decide_anomaly(
            result.score, health_assessment.status, is_special
        )

        if (
            result.anomaly_type is None
            or decision.decision == policy.Decision.IGNORE_ANOMALY
        ):
            return

        severity = anomaly.severity_for_score(
            result.score, settings.ml_high_anomaly_threshold
        )
        event_row = await ml_queries.insert_anomaly_event(
            pool,
            device_id,
            timestamp,
            result.anomaly_type,
            severity,
            result.score,
            observed={"counts": counts},
            expected={"counts": predicted} if predicted else None,
            evidence={
                "breakdown": result.breakdown,
                "rule_violations": result.rule_violations,
                "policy_decision": decision.decision.value,
                "policy_reason": decision.reason,
                "device_health": health_assessment.status,
                "is_special_event": is_special,
            },
            model_id=model_id,
        )
        await broadcast_anomaly_event(
            {
                "device_id": device_id,
                "timestamp": timestamp.isoformat(),
                "severity": severity,
                "score": result.score,
                "anomaly_type": result.anomaly_type,
            }
        )

        alert_type = (
            result.anomaly_type
            if result.anomaly_type
            in (
                "value_anomaly",
                "distribution_anomaly",
                "statistical_anomaly",
            )
            else "statistical_anomaly"
        )
        await notifications_service.raise_alert(
            pool,
            alert_type=alert_type,
            device_id=device_id,
            severity=severity,
            message=f"{result.anomaly_type} شناسایی شد (score={result.score:.2f})",
            details={
                "anomaly_event_id": event_row["id"],
                "policy": decision.decision.value,
            },
        )
    except Exception:
        logger.exception("ML enrichment/scoring failed for %s@%s", device_id, timestamp)


async def run_health_scan(pool: asyncpg.pool.Pool) -> int:
    checked = 0
    for row in await ml_queries.list_devices_for_health_scan(pool):
        device_id = row["device_id"]
        assessment = await compute_health(
            pool, device_id, row["expected_interval_seconds"]
        )
        previous = await ml_queries.get_latest_health(pool, device_id)
        await ml_queries.insert_health_snapshot(
            pool, device_id, assessment.status, assessment.signals
        )
        checked += 1

        previous_status = previous["health_status"] if previous else "HEALTHY"
        if assessment.status != previous_status and assessment.status in (
            "OFFLINE",
            "SUSPICIOUS",
            "DEGRADED",
        ):
            alert_type = {
                "OFFLINE": "device_silence",
                "SUSPICIOUS": "device_degraded",
                "DEGRADED": "device_degraded",
            }[assessment.status]
            severity = "critical" if assessment.status == "OFFLINE" else "warning"
            await notifications_service.raise_alert(
                pool,
                alert_type=alert_type,
                device_id=device_id,
                severity=severity,
                message=(
                    f"وضعیت سلامت دستگاه {device_id} به "
                    f"{assessment.status} تغییر کرد"
                ),
                details=assessment.signals,
            )
        await broadcast_device_health(
            {
                "device_id": device_id,
                "health_status": assessment.status,
                "signals": assessment.signals,
            }
        )
    return checked


async def train(pool: asyncpg.pool.Pool) -> dict[str, Any]:
    return await training.train_all(pool)


async def list_models(pool: asyncpg.pool.Pool) -> list[dict]:
    return await ml_queries.list_models(pool)


async def get_model(pool: asyncpg.pool.Pool, model_id: int) -> Optional[dict]:
    return await ml_queries.get_model(pool, model_id)


async def list_anomaly_events(
    pool: asyncpg.pool.Pool, device_id: Optional[str], limit: int
) -> list[dict]:
    return await ml_queries.list_anomaly_events(pool, device_id, limit)


async def set_anomaly_status(
    pool: asyncpg.pool.Pool, anomaly_id: int, status: str, actor: str
) -> Optional[dict]:
    return await ml_queries.set_anomaly_status(pool, anomaly_id, status, actor)


async def list_predictions(
    pool: asyncpg.pool.Pool, device_id: str, limit: int
) -> list[dict]:
    return await ml_queries.list_predictions(pool, device_id, limit)


async def list_reconstructions(
    pool: asyncpg.pool.Pool, device_id: str, limit: int
) -> list[dict]:
    return await reconstruction_service.list_log(pool, device_id, limit)


async def metrics(pool: asyncpg.pool.Pool) -> dict[str, Any]:
    return await ml_queries.monitoring_metrics(pool)


async def explain_anomaly(
    pool: asyncpg.pool.Pool, anomaly_id: int
) -> Optional[Explanation]:
    """Optional, advisory-only narrative for one anomaly event (spec §25-27).
    Returns `None` if AI is disabled/unavailable/fails — callers must treat
    that exactly like "no explanation available", never as an error."""
    rows = await ml_queries.list_anomaly_events(pool, device_id=None, limit=1000)
    row = next((r for r in rows if r["id"] == anomaly_id), None)
    if row is None:
        return None

    observed = row.get("observed") or {}
    expected = row.get("expected") or {}
    evidence = row.get("evidence") or {}
    observed_total = float(sum((observed.get("counts") or {}).values()))
    expected_total = sum((expected.get("counts") or {}).values()) if expected else None

    health_row = await ml_queries.get_latest_health(pool, row["device_id"])
    neighbor_totals = evidence.get("neighbor_totals", [])

    ev = AnomalyEvidence(
        device_id=row["device_id"],
        timestamp=row["timestamp"].isoformat(),
        observed_total=observed_total,
        expected_total=float(expected_total) if expected_total is not None else None,
        anomaly_score=row["score"],
        device_health=health_row["health_status"] if health_row else "HEALTHY",
        historical_mean=evidence.get("historical_mean"),
        neighbor_totals=neighbor_totals,
        is_holiday=bool(evidence.get("is_special_event")),
        is_special_event=bool(evidence.get("is_special_event")),
    )
    return await ai_explain.explain(ev)
