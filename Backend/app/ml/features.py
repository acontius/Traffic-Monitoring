"""Feature engineering shared by anomaly scoring and the expected-traffic
model (spec §7, §8, §10, §13).

Lag/rolling windows are expressed in *intervals*, not fixed minutes — the
actual `expected_interval_seconds` for the device is always what converts an
interval count into a time offset, per spec §8's "adapt lag values to the
actual interval" instruction. `LAG_INTERVALS` (1, 2, 3, 12, 24) reduces to
"1 hour ago"/"1 day ago" etc. only for a 5-minute device; for any other
interval it means something else, which is the point — the model learns
from a device's own cadence.

Every function here is pure/synchronous given already-fetched history, so
this module has zero DB/network dependencies and is fully unit-testable.
"""

import math
import statistics
from datetime import datetime, timedelta
from typing import Optional

from Backend.app.ml import VEHICLE_TYPES
from Backend.app.ml.calendar import classify_day, day_class_key, find_active_events

LAG_INTERVALS = (1, 2, 3, 12, 24)
ROLLING_WINDOW = 12
LAG_TOLERANCE_RATIO = 0.25  # how close a candidate record must be to count as "lag N"

FEATURE_NAMES: tuple[str, ...] = (
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "doy_sin",
    "doy_cos",
    "is_weekend",
    "is_holiday",
    "is_special_event",
    "month",
    "loc_urban",
    "loc_highway",
    "loc_industrial",
    *(f"lag_{n}" for n in LAG_INTERVALS),
    "rolling_mean",
    "rolling_std",
    "rolling_median",
    "rolling_min",
    "rolling_max",
)

NAN = float("nan")


def _cyclic(value: float, period: float) -> tuple[float, float]:
    angle = 2 * math.pi * (value / period)
    return math.sin(angle), math.cos(angle)


def _find_lag_value(
    history: list[dict], target_ts: datetime, offset_seconds: float, vehicle_type: str
) -> float:
    """History must be sorted ascending and contain only records strictly
    before `target_ts` (no leakage — enforced by the caller)."""
    wanted_ts = target_ts - timedelta(seconds=offset_seconds)
    tolerance = (
        timedelta(seconds=offset_seconds * LAG_TOLERANCE_RATIO)
        if offset_seconds
        else timedelta(seconds=1)
    )
    best = None
    best_delta = None
    for record in reversed(history):
        delta = abs(record["timestamp"] - wanted_ts)
        if delta <= tolerance and (best_delta is None or delta < best_delta):
            best, best_delta = record, delta
        if record["timestamp"] < wanted_ts - tolerance:
            break
    if best is None:
        return NAN
    return float(best["counts"].get(vehicle_type, 0))


def total_count(counts: dict[str, int]) -> int:
    return sum(counts.values())


def compositional_ratios(counts: dict[str, int]) -> dict[str, float]:
    """Vehicle-type / total ratios, safe against a zero total (spec §10)."""
    total = total_count(counts)
    if total <= 0:
        return {f"ratio_{v}": 0.0 for v in VEHICLE_TYPES}
    return {f"ratio_{v}": counts.get(v, 0) / total for v in VEHICLE_TYPES}


def build_feature_row(
    history: list[dict],
    target_ts: datetime,
    location_type: str,
    vehicle_type: str,
    expected_interval_seconds: int,
    events: Optional[list[dict]] = None,
) -> dict[str, float]:
    """`history` must already be filtered to strictly-earlier-than-`target_ts`
    records for the same device, sorted ascending, each
    `{"timestamp": datetime, "counts": dict}` — enforced by the caller so
    this function can never leak future values into a feature (spec §21).
    """
    day_ctx = classify_day(target_ts)
    hour_frac = day_ctx.local_ts.hour + day_ctx.local_ts.minute / 60.0
    hour_sin, hour_cos = _cyclic(hour_frac, 24.0)
    dow_sin, dow_cos = _cyclic(day_ctx.local_ts.weekday(), 7.0)
    doy_sin, doy_cos = _cyclic(day_ctx.local_ts.timetuple().tm_yday, 365.25)

    active_events = find_active_events(target_ts, events or [])

    row: dict[str, float] = {
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "dow_sin": dow_sin,
        "dow_cos": dow_cos,
        "doy_sin": doy_sin,
        "doy_cos": doy_cos,
        "is_weekend": float(day_ctx.is_weekend),
        "is_holiday": float(day_ctx.is_official_holiday),
        "is_special_event": float(bool(active_events)),
        "month": float(day_ctx.month),
        "loc_urban": float(location_type == "urban"),
        "loc_highway": float(location_type == "highway"),
        "loc_industrial": float(location_type == "industrial"),
    }

    for n in LAG_INTERVALS:
        row[f"lag_{n}"] = _find_lag_value(
            history, target_ts, n * expected_interval_seconds, vehicle_type
        )

    recent = history[-ROLLING_WINDOW:]
    values = [float(r["counts"].get(vehicle_type, 0)) for r in recent]
    if values:
        row["rolling_mean"] = statistics.mean(values)
        row["rolling_std"] = statistics.pstdev(values) if len(values) > 1 else 0.0
        row["rolling_median"] = statistics.median(values)
        row["rolling_min"] = min(values)
        row["rolling_max"] = max(values)
    else:
        row["rolling_mean"] = row["rolling_std"] = NAN
        row["rolling_median"] = row["rolling_min"] = row["rolling_max"] = NAN

    return row


def feature_vector(row: dict[str, float]) -> list[float]:
    return [row[name] for name in FEATURE_NAMES]


def historical_analogues(
    history: list[dict],
    target_ts: datetime,
    expected_interval_seconds: int,
    max_candidates: int = 20,
    interval_of_day_tolerance_intervals: int = 1,
) -> list[dict]:
    """Finds past records matching interval-of-day (within tolerance) and
    the same day-class (weekday/weekend/holiday) as `target_ts` (spec §13).
    Ordered most-recent-first so callers can prefer recent evidence."""
    target_local = classify_day(target_ts).local_ts
    target_minutes = target_local.hour * 60 + target_local.minute
    target_class = day_class_key(target_ts)
    tolerance_minutes = (
        max(1, expected_interval_seconds // 60) * interval_of_day_tolerance_intervals
    )

    matches = []
    for record in history:
        rec_local = classify_day(record["timestamp"]).local_ts
        rec_minutes = rec_local.hour * 60 + rec_local.minute
        if abs(rec_minutes - target_minutes) > tolerance_minutes:
            continue
        if day_class_key(record["timestamp"]) != target_class:
            continue
        matches.append(record)

    matches.sort(key=lambda r: r["timestamp"], reverse=True)
    return matches[:max_candidates]


def average_counts(samples: list[dict]) -> dict[str, float]:
    counts_list = [s["counts"] for s in samples]
    if not counts_list:
        return {}
    keys = set()
    for c in counts_list:
        keys.update(c.keys())
    return {k: sum(c.get(k, 0) for c in counts_list) / len(counts_list) for k in keys}
