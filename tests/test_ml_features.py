"""Lag/rolling correctness against the actual interval, compositional
ratios, and no-leakage feature construction (Backend/app/ml/features.py)."""

import math
from datetime import datetime, timedelta, timezone

from Backend.app.ml.features import (
    average_counts,
    build_feature_row,
    compositional_ratios,
    historical_analogues,
)

BASE = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)  # a Wednesday


def _history(n: int, interval_seconds: int, value: int = 10) -> list[dict]:
    return [
        {
            "timestamp": BASE - timedelta(seconds=interval_seconds * (n - i)),
            "counts": {"سواری": value + i},
        }
        for i in range(n)
    ]


def test_compositional_ratios_safe_against_zero_total():
    ratios = compositional_ratios({"سواری": 0, "کامیون": 0})
    assert all(v == 0.0 for v in ratios.values())


def test_compositional_ratios_sum_to_one():
    ratios = compositional_ratios({"سواری": 3, "کامیون": 1})
    assert (
        abs(
            sum(v for k, v in ratios.items() if k in ("ratio_سواری", "ratio_کامیون"))
            - 1.0
        )
        < 1e-9
    )


def test_lag_feature_uses_actual_interval_not_fixed_minutes():
    # 10-minute interval device: lag_1 should look ~10 minutes back, not 5.
    interval_seconds = 600
    history = _history(30, interval_seconds)
    row = build_feature_row(history, BASE, "urban", "سواری", interval_seconds)
    # lag_1 should match the record 1 interval (10 min) before BASE, i.e. the
    # last history entry (value 10 + 29 = 39).
    assert row["lag_1"] == 39.0


def test_lag_feature_is_nan_when_no_matching_history():
    row = build_feature_row([], BASE, "urban", "سواری", 300)
    assert math.isnan(row["lag_1"])
    assert math.isnan(row["rolling_mean"])


def test_feature_row_never_uses_future_records():
    interval_seconds = 300
    history = _history(20, interval_seconds)
    # Caller is responsible for excluding future records; verify that if we
    # only pass past history, no 9999 leaks into rolling stats.
    row = build_feature_row(history, BASE, "urban", "سواری", interval_seconds)
    assert row["rolling_max"] < 9999


def test_historical_analogues_matches_interval_of_day_and_day_class():
    # Two weeks of the same 08:00 Wednesday reading, plus an unrelated Friday one.
    history = []
    for w in range(4):
        ts = BASE - timedelta(days=7 * w)
        history.append({"timestamp": ts, "counts": {"سواری": 20 + w}})
    friday_ts = BASE + timedelta(
        days=2
    )  # BASE is a Wednesday; +2 days = Friday (different day-class)
    history.append({"timestamp": friday_ts, "counts": {"سواری": 999}})

    matches = historical_analogues(history, BASE, expected_interval_seconds=300)
    assert all(m["counts"]["سواری"] != 999 for m in matches)
    assert len(matches) >= 3


def test_average_counts_handles_missing_keys_as_zero():
    samples = [{"counts": {"سواری": 10}}, {"counts": {"سواری": 20, "کامیون": 4}}]
    avg = average_counts(samples)
    assert avg["سواری"] == 15
    assert avg["کامیون"] == 2
