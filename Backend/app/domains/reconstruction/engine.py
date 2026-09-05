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
from typing import Any

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.core.config import get_settings
from Backend.app.domains.forwarding import service as forwarding_service
from Backend.app.domains.notifications import service as notifications_service
from Backend.app.domains.reconstruction import queries
from Backend.app.domains.records.queries import upsert_reconstructed_or_manual

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


async def _write_reconstructed_record(
    pool: asyncpg.pool.Pool,
    device_id: str,
    location_type: str,
    timestamp: datetime,
    counts: dict[str, int],
    weights: dict[str, Any],
    inputs: dict[str, Any],
    method: str,
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
        formula_snapshot=weights,
        inputs=inputs,
    )
    await record_audit(
        pool,
        actor="system",
        action="reconstruct",
        entity="traffic_records",
        entity_id=f"{device_id}@{timestamp.isoformat()}",
        details={"method": method},
    )
    await forwarding_service.enqueue(pool, device_id, timestamp, payload)


async def run_once(pool: asyncpg.pool.Pool) -> int:
    settings = get_settings()
    reconstructed = 0

    for row in await queries.find_corrupt_records(pool):
        weights = await resolve_weights(pool, row["device_id"], row["location_type"])
        counts, inputs = await compute_reconstructed_counts(
            pool, row["device_id"], row["timestamp"], weights
        )
        await _write_reconstructed_record(
            pool,
            row["device_id"],
            row["location_type"],
            row["timestamp"],
            counts,
            weights,
            inputs,
            method="weighted_historical_average(corrupt)",
        )
        reconstructed += 1

    for row in await queries.find_silent_devices(
        pool, settings.reconstruction_grace_periods
    ):
        interval = timedelta(seconds=row["expected_interval_seconds"])
        expected_ts = row["last_ts"] + interval
        weights = await resolve_weights(pool, row["device_id"], row["location_type"])
        counts, inputs = await compute_reconstructed_counts(
            pool, row["device_id"], expected_ts, weights
        )
        await _write_reconstructed_record(
            pool,
            row["device_id"],
            row["location_type"],
            expected_ts,
            counts,
            weights,
            inputs,
            method="weighted_historical_average(silence)",
        )
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
