"""Evaluation metrics for prediction, anomaly detection, and reconstruction
(spec §37). Pure Python (no numpy dependency) so metrics can always be
computed even in the degraded/no-sklearn mode.

Anomaly-detection metrics require labelled data, which doesn't exist for
real traffic — every anomaly-metric result here must be computed against
simulator-generated synthetic anomalies and is labelled `"synthetic": True`
in its output so it's never mistaken for a real-world accuracy claim
(spec §37, §52).
"""

import math
from typing import Optional


def regression_metrics(y_true: list[float], y_pred: list[float]) -> dict[str, float]:
    n = len(y_true)
    if n == 0:
        return {}
    errors = [t - p for t, p in zip(y_true, y_pred)]
    abs_errors = [abs(e) for e in errors]
    mae = sum(abs_errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)

    mape_terms = [abs(e) / t for e, t in zip(errors, y_true) if t != 0]
    mape = (sum(mape_terms) / len(mape_terms) * 100) if mape_terms else None

    smape_terms = [
        abs(t - p) / ((abs(t) + abs(p)) / 2)
        for t, p in zip(y_true, y_pred)
        if (abs(t) + abs(p)) > 0
    ]
    smape = (sum(smape_terms) / len(smape_terms) * 100) if smape_terms else None

    return {"mae": mae, "rmse": rmse, "mape": mape, "smape": smape, "n": n}


def prediction_interval_coverage(
    y_true: list[float], interval_low: list[float], interval_high: list[float]
) -> Optional[float]:
    if not y_true:
        return None
    covered = sum(
        1 for t, lo, hi in zip(y_true, interval_low, interval_high) if lo <= t <= hi
    )
    return covered / len(y_true)


def classification_metrics(y_true: list[bool], y_pred: list[bool]) -> dict[str, float]:
    """Precision/recall/F1/false-positive-rate for anomaly detection.
    Callers MUST label the result `synthetic: True` unless evaluated against
    real, operator-confirmed labels (spec §37)."""
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fpr,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }
