"""Validates incoming device payloads and flags statistically-odd data.

Two independent checks run on every message the WebSocket ingestion gateway
receives (SRS 3.2):

1. `validate_structure` — is this even a well-formed traffic record? Bad
   structure/timestamp/type is rejected outright (never stored). Pure
   function, no I/O.
2. `detect_anomaly` — is a structurally-valid record statistically unusual
   for this device? Anomalies are still stored (so nothing is silently lost)
   but flagged for review and to trigger an alert.
"""

import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from Backend.app.domains.ingestion import queries

MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_BACKDATE = timedelta(hours=24)
ANOMALY_Z_SCORE = 3.0
MIN_HISTORY_SAMPLES = 8
HISTORY_SAMPLE_LIMIT = 200


class ValidationError(Exception):
    pass


def validate_structure(raw: dict) -> tuple[str, datetime, dict[str, int], int]:
    """Returns (device_id, timestamp, counts, interval_minutes) or raises
    ValidationError."""
    device_id = raw.get("device_id")
    if not device_id or not isinstance(device_id, str):
        raise ValidationError("missing or invalid device_id")

    timestamp_raw = raw.get("timestamp")
    if not timestamp_raw:
        raise ValidationError("missing timestamp")
    try:
        timestamp = datetime.fromisoformat(str(timestamp_raw))
    except ValueError as exc:
        raise ValidationError(f"unparseable timestamp: {timestamp_raw}") from exc
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if timestamp > now + MAX_CLOCK_SKEW:
        raise ValidationError("timestamp too far in the future")
    if timestamp < now - MAX_BACKDATE:
        raise ValidationError("timestamp too far in the past")

    counts = raw.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise ValidationError("missing or invalid counts")
    clean_counts: dict[str, int] = {}
    for key, value in counts.items():
        if not isinstance(value, (int, float)) or value < 0:
            raise ValidationError(f"invalid count for {key!r}: {value!r}")
        clean_counts[str(key)] = int(value)

    interval_minutes = raw.get("interval_minutes", 5)
    if not isinstance(interval_minutes, (int, float)) or interval_minutes <= 0:
        raise ValidationError("invalid interval_minutes")

    return device_id, timestamp, clean_counts, int(interval_minutes)


async def detect_anomaly(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    counts: dict[str, int],
) -> tuple[bool, Optional[str]]:
    """Flags a record as anomalous when its total count is far outside the
    historical distribution for this device at a similar time of day."""
    hour = timestamp.hour
    lo, hi = max(0, hour - 1), min(23, hour + 1)
    payloads = await queries.fetch_recent_payloads_near_hour(
        pool, device_id, lo, hi, HISTORY_SAMPLE_LIMIT
    )

    if len(payloads) < MIN_HISTORY_SAMPLES:
        return False, None

    historical_totals = []
    for payload in payloads:
        hist_counts = payload.get("counts", {})
        if hist_counts:
            historical_totals.append(sum(hist_counts.values()))

    if len(historical_totals) < MIN_HISTORY_SAMPLES:
        return False, None

    mean = statistics.mean(historical_totals)
    stdev = statistics.pstdev(historical_totals) or 1.0
    total = sum(counts.values())
    z_score = abs(total - mean) / stdev

    if z_score >= ANOMALY_Z_SCORE:
        direction = "بالاتر" if total > mean else "پایین‌تر"
        reason = (
            f"مجموع تردد ({total}) به‌طور غیرعادی {direction} از میانگین "
            f"تاریخی ({mean:.1f} ± {stdev:.1f}) است (z={z_score:.1f})"
        )
        return True, reason

    return False, None
