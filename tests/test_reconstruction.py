from datetime import datetime, timedelta, timezone

from Backend.app.domains.forwarding.service import _due_predicate
from Backend.app.domains.reconstruction.engine import _average_counts


def test_average_counts_empty():
    assert _average_counts([]) == {}


def test_average_counts_simple_mean():
    samples = [{"سواری": 10, "کامیون": 2}, {"سواری": 20, "کامیون": 4}]
    result = _average_counts(samples)
    assert result == {"سواری": 15.0, "کامیون": 3.0}


def test_average_counts_handles_missing_keys_across_samples():
    samples = [{"سواری": 10}, {"سواری": 20, "کامیون": 4}]
    result = _average_counts(samples)
    assert result["سواری"] == 15.0
    assert result["کامیون"] == 2.0  # missing counted as 0 for that sample


def test_due_predicate_first_attempt_is_always_due():
    assert _due_predicate(0, None, base_seconds=10) is True


def test_due_predicate_not_due_before_backoff_elapses():
    now = datetime.now(timezone.utc)
    assert _due_predicate(1, now, base_seconds=100) is False


def test_due_predicate_due_after_backoff_elapses():
    past = datetime.now(timezone.utc) - timedelta(seconds=200)
    assert _due_predicate(1, past, base_seconds=10) is True


def test_due_predicate_backoff_grows_with_attempt_count():
    # attempt_count=3 -> backoff = base * 2^2 = 4*base
    recent = datetime.now(timezone.utc) - timedelta(seconds=15)
    assert _due_predicate(3, recent, base_seconds=10) is False
