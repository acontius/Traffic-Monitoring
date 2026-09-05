"""Device-health / silence detection (spec §6) — deliberately independent
from traffic-*value* anomaly detection (`anomaly.py`): a device can be
perfectly healthy while reporting an anomalous value (genuine traffic
event), and can be unhealthy while its last few values look statistically
unremarkable (about to go silent).

Every detector is a pure function over already-fetched records — no I/O here
so this stays trivially testable; `Backend/app/domains/ml/service.py` does
the fetching and turns the result into a `device_health_snapshots` row.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

Record = dict[
    str, Any
]  # {"timestamp": datetime, "counts": dict, "received_at": datetime}

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
SUSPICIOUS = "SUSPICIOUS"
OFFLINE = "OFFLINE"
RECOVERING = "RECOVERING"

CONSTANT_VALUE_MIN_REPEATS = 6
INTERMITTENT_MISSING_RATIO = 0.3
INTERMITTENT_WINDOW = 12
BURST_GAP_MULTIPLE = 2.0
BURST_ARRIVAL_GAP_SECONDS = 5.0
TIMESTAMP_DRIFT_SECONDS = 60.0
RATE_MISMATCH_RATIO = 0.5


@dataclass
class HealthAssessment:
    status: str
    signals: dict[str, Any] = field(default_factory=dict)


def _sorted(records: list[Record]) -> list[Record]:
    return sorted(records, key=lambda r: r["timestamp"])


def detect_silent(
    records: list[Record],
    expected_interval_seconds: int,
    grace_periods: int,
    now: datetime,
) -> Optional[dict]:
    if not records:
        return {"reason": "no_history"}
    last_ts = _sorted(records)[-1]["timestamp"]
    allowed = timedelta(seconds=expected_interval_seconds * (1 + grace_periods))
    if now - last_ts > allowed:
        return {
            "last_seen_at": last_ts.isoformat(),
            "silence_seconds": (now - last_ts).total_seconds(),
        }
    return None


def detect_intermittent(
    records: list[Record], expected_interval_seconds: int
) -> Optional[dict]:
    ordered = _sorted(records)[-INTERMITTENT_WINDOW:]
    if len(ordered) < 3:
        return None
    interval = timedelta(seconds=expected_interval_seconds)
    missing = 0
    for prev, nxt in zip(ordered, ordered[1:]):
        gap = nxt["timestamp"] - prev["timestamp"]
        missing += max(0, round(gap / interval) - 1)
    ratio = missing / max(1, len(ordered) - 1)
    if ratio >= INTERMITTENT_MISSING_RATIO:
        return {"missing_ratio": ratio, "window": len(ordered)}
    return None


def detect_constant_value(
    records: list[Record], min_repeats: int = CONSTANT_VALUE_MIN_REPEATS
) -> Optional[dict]:
    ordered = _sorted(records)[-min_repeats:]
    if len(ordered) < min_repeats:
        return None
    first = ordered[0]["counts"]
    if all(r["counts"] == first for r in ordered):
        return {"repeated_value": first, "repeats": len(ordered)}
    return None


def detect_partial_failure(
    records: list[Record], historically_nonzero_keys: set[str], min_repeats: int = 6
) -> Optional[dict]:
    ordered = _sorted(records)[-min_repeats:]
    if len(ordered) < min_repeats or not historically_nonzero_keys:
        return None
    frozen_zero: set[str] = set()
    for key in historically_nonzero_keys:
        if all(r["counts"].get(key, 0) == 0 for r in ordered):
            frozen_zero.add(key)
    if frozen_zero:
        return {"frozen_zero_categories": sorted(frozen_zero), "window": len(ordered)}
    return None


def detect_bursting(
    records: list[Record], expected_interval_seconds: int
) -> Optional[dict]:
    """Several observations whose *own* timestamps are properly spaced but
    which all arrived at the server within a few seconds of each other —
    i.e. the device buffered readings during an outage and flushed them."""
    ordered = _sorted(records)
    bursts = 0
    for prev, nxt in zip(ordered, ordered[1:]):
        recv_prev = prev.get("received_at")
        recv_nxt = nxt.get("received_at")
        if recv_prev is None or recv_nxt is None:
            continue
        own_gap = (nxt["timestamp"] - prev["timestamp"]).total_seconds()
        arrival_gap = (recv_nxt - recv_prev).total_seconds()
        if (
            own_gap >= expected_interval_seconds * BURST_GAP_MULTIPLE
            and arrival_gap <= BURST_ARRIVAL_GAP_SECONDS
        ):
            bursts += 1
    if bursts:
        return {"burst_count": bursts}
    return None


def detect_timestamp_drift(records: list[Record]) -> Optional[dict]:
    ordered = _sorted(records)
    deltas = []
    for r in ordered:
        recv_at = r.get("received_at")
        if recv_at is None:
            continue
        deltas.append((recv_at - r["timestamp"]).total_seconds())
    if len(deltas) < 3:
        return None
    mean_delta = statistics.mean(deltas)
    if abs(mean_delta) >= TIMESTAMP_DRIFT_SECONDS:
        return {"mean_clock_delta_seconds": mean_delta, "samples": len(deltas)}
    return None


def detect_rate_mismatch(
    records: list[Record], expected_interval_seconds: int
) -> Optional[dict]:
    ordered = _sorted(records)
    if len(ordered) < 4:
        return None
    gaps = [
        (nxt["timestamp"] - prev["timestamp"]).total_seconds()
        for prev, nxt in zip(ordered, ordered[1:])
    ]
    median_gap = statistics.median(gaps)
    ratio = abs(median_gap - expected_interval_seconds) / max(
        1.0, expected_interval_seconds
    )
    if ratio >= RATE_MISMATCH_RATIO:
        return {
            "median_interval_seconds": median_gap,
            "expected_interval_seconds": expected_interval_seconds,
        }
    return None


def assess_health(
    records: list[Record],
    expected_interval_seconds: int,
    grace_periods: int,
    historically_nonzero_keys: set[str],
    now: Optional[datetime] = None,
    previous_status: Optional[str] = None,
) -> HealthAssessment:
    now = now or datetime.now(timezone.utc)
    signals: dict[str, Any] = {}

    silent = detect_silent(records, expected_interval_seconds, grace_periods, now)
    if silent is not None:
        signals["silent_device"] = silent
        return HealthAssessment(OFFLINE, signals)

    constant = detect_constant_value(records)
    if constant is not None:
        signals["constant_value_device"] = constant
    partial = detect_partial_failure(records, historically_nonzero_keys)
    if partial is not None:
        signals["partial_failure"] = partial
    intermittent = detect_intermittent(records, expected_interval_seconds)
    if intermittent is not None:
        signals["intermittent_device"] = intermittent
    bursting = detect_bursting(records, expected_interval_seconds)
    if bursting is not None:
        signals["bursting_device"] = bursting
    drift = detect_timestamp_drift(records)
    if drift is not None:
        signals["timestamp_drift"] = drift
    rate_mismatch = detect_rate_mismatch(records, expected_interval_seconds)
    if rate_mismatch is not None:
        signals["rate_mismatch"] = rate_mismatch

    if constant is not None or partial is not None:
        status = SUSPICIOUS
    elif (
        intermittent is not None
        or bursting is not None
        or rate_mismatch is not None
        or drift is not None
    ):
        status = DEGRADED
    elif previous_status in (OFFLINE, DEGRADED, SUSPICIOUS):
        status = RECOVERING
    else:
        status = HEALTHY

    return HealthAssessment(status, signals)
