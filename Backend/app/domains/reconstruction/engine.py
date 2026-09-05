"""The gap-detection and formula-based reconstruction engine itself
(SRS 3.4 / 5 — "موتور بازسازی داده"). `worker.py` schedules `run_once` on a
timer; this module holds the actual algorithm.

Every pass:

1. Finds devices that have gone silent past their expected interval, and
   rows already stored but flagged `is_valid = false` (corrupt).
2. For each gap, resolves the applicable formula weights from
   `reconstruction_config` (device-specific > location_type > default —
   see `resolve_weights`), computes a fill value from weighted historical
   averages plus environmental modifiers, and writes it back with
   `is_reconstructed = true`.
3. Logs the formula snapshot and inputs used to `reconstruction_log` so every
   reconstructed value stays auditable and reproducible (SRS 3.4 last bullet).
4. Raises an alert via `domains.notifications` and queues the row for
   forwarding via `domains.forwarding`.

All formula weights live in the DB (`reconstruction_config`), so tuning the
algorithm never requires a redeploy (SRS 5 / 11).
"""

from datetime import datetime, timedelta
from typing import Any, Optional

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.core.config import get_settings
from Backend.app.domains.devices import queries as devices_queries
from Backend.app.domains.forwarding import service as forwarding_service
from Backend.app.domains.ml import queries as ml_queries
from Backend.app.domains.ml import service as ml_service
from Backend.app.domains.notifications import service as notifications_service
from Backend.app.domains.realtime.bus import broadcast_reconstruction_event
from Backend.app.domains.reconstruction import queries
from Backend.app.domains.records.queries import upsert_reconstructed_or_manual
from Backend.app.ml import policy as ml_policy
from Backend.app.ml import reconstruction as ml_reconstruction

RECENT_TREND_SAMPLE_SIZE = 6

DEFAULT_WEIGHTS: dict[str, Any] = {
    "historical_window_days": 28,
    "time_of_day_weight": 0.6,
    "day_of_week_weight": 0.3,
    "recent_trend_weight": 0.1,
    "device_performance_coefficient": 1.0,
    "environmental_modifiers": {
        "weather": 1.0,
        "holiday": 1.0,
        "related_axis": 1.0,
        "connected_points": 1.0,
    },
}


async def resolve_weights(
    pool: asyncpg.pool.Pool, device_id: str, location_type: str
) -> dict[str, Any]:
    weights = await queries.fetch_weights_for_device(pool, device_id)
    if weights is None:
        weights = await queries.fetch_weights_for_location_type(pool, location_type)
    if weights is None:
        weights = await queries.fetch_default_weights(pool)
    return weights if weights is not None else DEFAULT_WEIGHTS


def _average_counts(samples: list[dict[str, int]]) -> dict[str, float]:
    if not samples:
        return {}
    keys = set()
    for s in samples:
        keys.update(s.keys())
    return {k: sum(s.get(k, 0) for s in samples) / len(samples) for k in keys}


async def compute_reconstructed_counts(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    weights: dict[str, Any],
) -> tuple[dict[str, int], dict[str, Any]]:
    window_days = int(weights.get("historical_window_days", 28))
    since = timestamp - timedelta(days=window_days)

    # Component A: same hour of day, any weekday, within window.
    same_hour = await queries.fetch_counts_same_hour(
        pool, device_id, since, timestamp.hour
    )
    # Component B: same weekday + hour, within window.
    same_weekday_hour = await queries.fetch_counts_same_weekday_hour(
        pool, device_id, since, timestamp.hour, timestamp.weekday()
    )
    # Component C: most recent readings, regardless of time (recent trend).
    recent = await queries.fetch_recent_counts(
        pool, device_id, RECENT_TREND_SAMPLE_SIZE
    )

    avg_a = _average_counts(same_hour)
    avg_b = _average_counts(same_weekday_hour)
    avg_c = _average_counts(recent)

    w_a = float(weights.get("time_of_day_weight", 0.6)) if avg_a else 0.0
    w_b = float(weights.get("day_of_week_weight", 0.3)) if avg_b else 0.0
    w_c = float(weights.get("recent_trend_weight", 0.1)) if avg_c else 0.0
    total_weight = w_a + w_b + w_c

    keys = set(avg_a) | set(avg_b) | set(avg_c)
    modifiers: dict[str, float] = weights.get("environmental_modifiers", {}) or {}
    modifier_product = 1.0
    for value in modifiers.values():
        try:
            modifier_product *= float(value)
        except (TypeError, ValueError):
            continue
    coefficient = float(weights.get("device_performance_coefficient", 1.0))

    counts: dict[str, int] = {}
    if total_weight > 0 and keys:
        for key in keys:
            base = (
                w_a * avg_a.get(key, 0.0)
                + w_b * avg_b.get(key, 0.0)
                + w_c * avg_c.get(key, 0.0)
            ) / total_weight
            counts[key] = max(0, round(base * coefficient * modifier_product))
    # else: no history at all yet for this device — leave counts empty; the
    # caller records this explicitly in the log so it's visible, not hidden.

    inputs = {
        "window_days": window_days,
        "samples_same_hour": len(same_hour),
        "samples_same_weekday_hour": len(same_weekday_hour),
        "samples_recent": len(recent),
        "averages": {"same_hour": avg_a, "same_weekday_hour": avg_b, "recent": avg_c},
        "modifier_product": modifier_product,
        "device_performance_coefficient": coefficient,
    }
    return counts, inputs


async def _resolve_hierarchical(
    pool: asyncpg.pool.Pool, device_id: str, location_type: str, timestamp: datetime
) -> Optional[ml_reconstruction.LevelResult]:
    """Levels 1-4 (spec §15): ML prediction -> historical analogue ->
    seasonal profile -> neighbour device. Tried in order, first usable
    result wins. Returns `None` if none of them have enough evidence, in
    which case the caller falls back to the *existing* formula (Level 5)."""
    settings = get_settings()
    if not settings.ml_enabled:
        return None

    expected_interval_seconds = await devices_queries.get_expected_interval_seconds(
        pool, device_id
    )

    result = await ml_reconstruction.try_ml_prediction(
        pool, device_id, location_type, timestamp, expected_interval_seconds
    )
    if result is None:
        result = await ml_reconstruction.try_historical_analogue(
            pool, device_id, timestamp, expected_interval_seconds
        )
    if result is None:
        result = await ml_reconstruction.try_seasonal_profile(
            pool, device_id, timestamp
        )
    if result is None and settings.ml_enable_cross_device_context:
        result = await ml_reconstruction.try_neighbor_devices(
            pool, device_id, location_type, timestamp, expected_interval_seconds
        )
    return result


async def _write_reconstructed_record(
    pool: asyncpg.pool.Pool,
    device_id: str,
    location_type: str,
    timestamp: datetime,
    counts: dict[str, int],
    formula_snapshot: dict[str, Any],
    evidence: dict[str, Any],
    method: str,
    confidence: Optional[float],
    review_status: str,
    model_version: Optional[str],
    forward: bool,
) -> None:
    payload = {
        "device_id": device_id,
        "location_type": location_type,
        "timestamp": timestamp.isoformat(),
        "counts": counts,
        "reconstructed": True,
    }
    await upsert_reconstructed_or_manual(pool, device_id, timestamp, payload)
    await queries.insert_log_entry(
        pool,
        device_id=device_id,
        timestamp=timestamp,
        method=method,
        formula_snapshot=formula_snapshot,
        inputs=evidence,
    )
    # The richer confidence/level/model_version/review_status columns aren't
    # part of the original insert_log_entry signature (kept unchanged so the
    # formula-only call sites elsewhere stay untouched) — set separately.
    if confidence is not None or review_status != "auto":
        async with pool.acquire() as con:
            await con.execute(
                """
                UPDATE reconstruction_log
                SET confidence = $3, reconstruction_level = $4,
                    model_version = $5, review_status = $6
                WHERE device_id = $1 AND timestamp = $2
                  AND id = (SELECT id FROM reconstruction_log
                             WHERE device_id = $1 AND timestamp = $2
                             ORDER BY created_at DESC LIMIT 1)
                """,
                device_id,
                timestamp,
                confidence,
                method,
                model_version,
                review_status,
            )
    await record_audit(
        pool,
        actor="system",
        action="reconstruct",
        entity="traffic_records",
        entity_id=f"{device_id}@{timestamp.isoformat()}",
        details={
            "method": method,
            "confidence": confidence,
            "review_status": review_status,
        },
    )
    await broadcast_reconstruction_event(
        {
            "device_id": device_id,
            "timestamp": timestamp.isoformat(),
            "method": method,
            "confidence": confidence,
            "review_status": review_status,
        }
    )
    if forward:
        await forwarding_service.enqueue(
            pool, device_id, timestamp, payload, data_classification="reconstructed"
        )


async def _reconstruct_one(
    pool: asyncpg.pool.Pool,
    device_id: str,
    location_type: str,
    timestamp: datetime,
    trigger: str,
) -> bool:
    """Runs the full hierarchical + confidence-gated pipeline for one gap.
    Returns True if a value was actually written (auto or flagged), False if
    it went straight to manual review with nothing written (spec §15 Level
    6 — never fabricate a confident number)."""
    settings = get_settings()

    level_result = await _resolve_hierarchical(
        pool, device_id, location_type, timestamp
    )
    if level_result is not None:
        counts, confidence, level, evidence, model_version = (
            level_result.counts,
            level_result.confidence,
            level_result.level,
            level_result.evidence,
            level_result.model_version,
        )
        formula_snapshot: dict[str, Any] = {"level": level}
        method = level
    else:
        weights = await resolve_weights(pool, device_id, location_type)
        counts, inputs = await compute_reconstructed_counts(
            pool, device_id, timestamp, weights
        )
        confidence = (
            ml_policy.formula_fallback_confidence(inputs)
            if settings.ml_enabled
            else None
        )
        evidence = inputs
        formula_snapshot = weights
        method = f"weighted_historical_average({trigger})"
        model_version = None

    if confidence is None:
        # ML layer disabled: preserve the exact pre-existing behaviour.
        await _write_reconstructed_record(
            pool,
            device_id,
            location_type,
            timestamp,
            counts,
            formula_snapshot,
            evidence,
            method,
            confidence=None,
            review_status="auto",
            model_version=None,
            forward=True,
        )
        return True

    health_assessment = await ml_service.compute_health(
        pool,
        device_id,
        await devices_queries.get_expected_interval_seconds(pool, device_id),
    )
    decision = ml_policy.decide_reconstruction(confidence, health_assessment.status)

    if decision.decision == ml_policy.Decision.MANUAL_REVIEW or not counts:
        # Don't re-log/re-alert every scan interval for a gap already
        # flagged — the corrupt-record loop is separately guarded via
        # `data_quality_status`; this covers the silent-device loop, which
        # has no row of its own to mark until it's actually reconstructed.
        already_flagged = await queries.has_pending_manual_review(
            pool, device_id, timestamp
        )
        if not already_flagged:
            await queries.insert_log_entry(
                pool,
                device_id=device_id,
                timestamp=timestamp,
                method=f"{method}(manual_review)",
                formula_snapshot=formula_snapshot,
                inputs={**evidence, "policy_reason": decision.reason},
            )
            await ml_queries.mark_record_quality(
                pool, device_id, timestamp, "manual_review"
            )
            await notifications_service.raise_alert(
                pool,
                alert_type="manual_review_required",
                device_id=device_id,
                severity="warning",
                message=(
                    f"داده {device_id}@{timestamp.isoformat()} قابل بازسازی "
                    "خودکار نیست؛ نیاز به بررسی دستی"
                ),
                details={"reason": decision.reason, "confidence": confidence},
            )
        return False

    review_status = (
        "auto"
        if decision.decision == ml_policy.Decision.AUTO_RECONSTRUCT
        else "pending_review"
    )
    forward = review_status == "auto" or settings.forward_low_confidence_reconstructions
    await _write_reconstructed_record(
        pool,
        device_id,
        location_type,
        timestamp,
        counts,
        formula_snapshot,
        evidence,
        method,
        confidence=confidence,
        review_status=review_status,
        model_version=model_version,
        forward=forward,
    )
    if review_status == "pending_review":
        await notifications_service.raise_alert(
            pool,
            alert_type="low_reconstruction_confidence",
            device_id=device_id,
            severity="warning",
            message=(
                f"بازسازی {device_id}@{timestamp.isoformat()} با اطمینان "
                f"پایین ({confidence:.2f}) انجام شد"
            ),
            details={"confidence": confidence, "method": method},
        )
    return True


async def run_once(pool: asyncpg.pool.Pool) -> int:
    settings = get_settings()
    reconstructed = 0

    for row in await queries.find_corrupt_records(pool):
        if await _reconstruct_one(
            pool, row["device_id"], row["location_type"], row["timestamp"], "corrupt"
        ):
            reconstructed += 1

    for row in await queries.find_silent_devices(
        pool, settings.reconstruction_grace_periods
    ):
        interval = timedelta(seconds=row["expected_interval_seconds"])
        expected_ts = row["last_ts"] + interval
        wrote = await _reconstruct_one(
            pool, row["device_id"], row["location_type"], expected_ts, "silence"
        )
        if wrote:
            await notifications_service.raise_alert(
                pool,
                alert_type="data_gap",
                device_id=row["device_id"],
                severity="warning",
                message=(
                    f"دستگاه {row['device_id']} سکوت کرده؛ "
                    f"بازه {expected_ts.isoformat()} بازسازی شد"
                ),
            )
            reconstructed += 1

    return reconstructed
