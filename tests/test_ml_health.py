"""Device-health detectors (Backend/app/ml/health.py)."""

from datetime import datetime, timedelta, timezone

from Backend.app.ml.health import (
    HEALTHY,
    OFFLINE,
    SUSPICIOUS,
    assess_health,
    detect_bursting,
    detect_constant_value,
    detect_intermittent,
    detect_partial_failure,
    detect_rate_mismatch,
    detect_silent,
    detect_timestamp_drift,
)

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
INTERVAL = 300


def _records(n: int, step: int = INTERVAL, counts_fn=None) -> list[dict]:
    counts_fn = counts_fn or (lambda i: {"سواری": 10, "موتور": 5})
    return [
        {"timestamp": NOW - timedelta(seconds=step * (n - i)), "counts": counts_fn(i)}
        for i in range(n)
    ]


def test_detect_silent_when_beyond_grace_period():
    records = [{"timestamp": NOW - timedelta(hours=2), "counts": {"سواری": 1}}]
    result = detect_silent(records, INTERVAL, grace_periods=1, now=NOW)
    assert result is not None


def test_detect_silent_none_when_recent():
    records = [{"timestamp": NOW - timedelta(seconds=10), "counts": {"سواری": 1}}]
    assert detect_silent(records, INTERVAL, grace_periods=1, now=NOW) is None


def test_detect_constant_value():
    records = _records(8, counts_fn=lambda i: {"سواری": 10})
    result = detect_constant_value(records, min_repeats=6)
    assert result is not None
    assert result["repeated_value"] == {"سواری": 10}


def test_detect_constant_value_none_when_varying():
    records = _records(8, counts_fn=lambda i: {"سواری": 10 + i})
    assert detect_constant_value(records, min_repeats=6) is None


def test_detect_partial_failure_frozen_category():
    records = _records(8, counts_fn=lambda i: {"سواری": 10 + i, "موتور": 0})
    result = detect_partial_failure(
        records, historically_nonzero_keys={"موتور"}, min_repeats=6
    )
    assert result is not None
    assert "موتور" in result["frozen_zero_categories"]


def test_detect_intermittent_missing_ratio():
    records = []
    ts = NOW - timedelta(seconds=INTERVAL * 12)
    for i in range(6):
        ts += timedelta(seconds=INTERVAL * 2)  # every other interval missing
        records.append({"timestamp": ts, "counts": {"سواری": 10}})
    result = detect_intermittent(records, INTERVAL)
    assert result is not None
    assert result["missing_ratio"] >= 0.3


def test_detect_rate_mismatch():
    records = [
        {"timestamp": NOW - timedelta(seconds=60 * (4 - i)), "counts": {"سواری": 10}}
        for i in range(4)
    ]  # actual cadence 60s vs expected 300s
    result = detect_rate_mismatch(records, expected_interval_seconds=300)
    assert result is not None


def test_detect_timestamp_drift():
    records = [
        {
            "timestamp": NOW - timedelta(seconds=INTERVAL * (4 - i)),
            "counts": {"سواری": 10},
            "received_at": NOW
            - timedelta(seconds=INTERVAL * (4 - i))
            + timedelta(seconds=120),
        }
        for i in range(4)
    ]
    result = detect_timestamp_drift(records)
    assert result is not None


def test_detect_bursting():
    base_recv = NOW
    records = [
        {
            "timestamp": NOW - timedelta(seconds=INTERVAL * 6),
            "counts": {"سواری": 10},
            "received_at": base_recv,
        },
        {
            "timestamp": NOW - timedelta(seconds=INTERVAL * 1),
            "counts": {"سواری": 10},
            "received_at": base_recv + timedelta(seconds=1),
        },
    ]
    result = detect_bursting(records, INTERVAL)
    assert result is not None


def test_assess_health_offline_beats_everything():
    records = [{"timestamp": NOW - timedelta(hours=5), "counts": {"سواری": 10}}]
    assessment = assess_health(
        records, INTERVAL, grace_periods=1, historically_nonzero_keys=set(), now=NOW
    )
    assert assessment.status == OFFLINE


def test_assess_health_healthy_for_normal_records():
    records = _records(10, counts_fn=lambda i: {"سواری": 10 + (i % 3)})
    assessment = assess_health(
        records, INTERVAL, grace_periods=1, historically_nonzero_keys=set(), now=NOW
    )
    assert assessment.status == HEALTHY


def test_assess_health_suspicious_for_constant_value():
    records = _records(8, counts_fn=lambda i: {"سواری": 10})
    assessment = assess_health(
        records, INTERVAL, grace_periods=1, historically_nonzero_keys=set(), now=NOW
    )
    assert assessment.status == SUSPICIOUS
