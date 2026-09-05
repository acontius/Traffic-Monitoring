"""Chronological (never random) train/validation/test splitting
(Backend/app/ml/training.py) — spec §21's data-leakage prevention."""

from Backend.app.ml.training import chronological_split


def test_split_preserves_chronological_order_and_ratios():
    rows = list(range(100))  # already "sorted ascending" by construction
    train, val, test = chronological_split(rows)
    assert train == rows[:70]
    assert val == rows[70:85]
    assert test == rows[85:]


def test_split_never_shuffles():
    rows = list(range(20))
    train, val, test = chronological_split(rows)
    assert train + val + test == rows
    # The oldest examples must all precede the newest ones across splits.
    assert max(train) < min(val)
    assert max(val) < min(test)


def test_split_handles_small_datasets():
    rows = list(range(3))
    train, val, test = chronological_split(rows)
    assert train + val + test == rows
