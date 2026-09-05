"""Statistical + (optional) ML anomaly scoring (spec §7-§10).

Two speeds, both exposed here:

* `quick_score` — pure Python (no numpy), rule violations + robust
  MAD z-score + compositional/multivariate ratio checks. Cheap enough to run
  synchronously inline during ingestion (spec §44: never block the WS loop).
* `residual_score` — adds a model-prediction residual (needs a loaded
  `prediction.Model`) and an isolation-forest-style novelty score (needs
  scikit-learn). Both are optional: if the model/sklearn aren't available,
  the combined score simply falls back to the quick-score components, which
  is why `combine` documents every weight instead of hiding them.

The combined `anomaly_score` is always in [0, 1] with a `breakdown` of every
contributing signal, so nothing is presented to an operator as "just a
number" (spec §9 last line).
"""

import statistics
from dataclasses import dataclass, field
from typing import Optional

from Backend.app.ml import VEHICLE_TYPES
from Backend.app.ml.features import compositional_ratios, total_count

MAD_SCALE = 1.4826  # normal-distribution consistency constant
RULE_VIOLATION_WEIGHT = 0.35
ROBUST_DEVIATION_WEIGHT = 0.35
RESIDUAL_WEIGHT = 0.20
ISOLATION_WEIGHT = 0.10

DOMINANCE_RATIO_THRESHOLD = 0.85  # one category > 85% of total is suspicious
COLLAPSE_RATIO_THRESHOLD = 0.1  # < 10% of the historical mean total


@dataclass
class AnomalyResult:
    score: float
    anomaly_type: Optional[str]
    breakdown: dict[str, float] = field(default_factory=dict)
    rule_violations: list[str] = field(default_factory=list)


def robust_z_scores(values: list[float], x: float) -> float:
    """Median Absolute Deviation based z-score — robust to the very outliers
    it's trying to detect, unlike a plain mean/stdev z-score."""
    if len(values) < 2:
        return 0.0
    median = statistics.median(values)
    deviations = [abs(v - median) for v in values]
    mad = statistics.median(deviations) * MAD_SCALE
    if mad == 0:
        return 0.0 if x == median else 8.0  # degenerate: any difference is extreme
    return abs(x - median) / mad


def _normalize(z: float, saturate_at: float = 8.0) -> float:
    return max(0.0, min(1.0, z / saturate_at))


def rule_violations(counts: dict[str, int]) -> list[str]:
    """Multivariate / compositional checks (spec §10) — relationships
    between categories, not just per-category magnitude."""
    violations = []
    ratios = compositional_ratios(counts)
    total = total_count(counts)
    if total > 0:
        for vehicle in VEHICLE_TYPES:
            if ratios[f"ratio_{vehicle}"] >= DOMINANCE_RATIO_THRESHOLD:
                violations.append(f"category_dominance:{vehicle}")
    if total == 0:
        violations.append("total_collapse")
    if any(v < 0 for v in counts.values()):
        violations.append("negative_count")
    return violations


def quick_score(
    counts: dict[str, int], historical_totals: list[float]
) -> AnomalyResult:
    total = float(total_count(counts))
    violations = rule_violations(counts)

    robust_z = robust_z_scores(historical_totals, total) if historical_totals else 0.0
    robust_component = _normalize(robust_z)

    collapse = False
    if historical_totals:
        mean_hist = statistics.mean(historical_totals)
        if mean_hist > 0 and total < mean_hist * COLLAPSE_RATIO_THRESHOLD:
            collapse = True
            violations.append("traffic_collapse")

    rule_component = min(1.0, len(violations) * 0.4)

    breakdown = {
        "robust_deviation": robust_component,
        "rule_penalty": rule_component,
        "robust_z_score": robust_z,
    }
    score = min(
        1.0,
        RULE_VIOLATION_WEIGHT * rule_component
        + (ROBUST_DEVIATION_WEIGHT + RESIDUAL_WEIGHT + ISOLATION_WEIGHT)
        * robust_component,
    )

    anomaly_type = None
    if violations:
        if "total_collapse" in violations or collapse:
            anomaly_type = "distribution_anomaly" if total > 0 else "value_anomaly"
        elif any(v.startswith("category_dominance") for v in violations):
            anomaly_type = "distribution_anomaly"
        else:
            anomaly_type = "value_anomaly"
    elif robust_component >= 0.5:
        anomaly_type = "statistical_anomaly"

    return AnomalyResult(
        score=score,
        anomaly_type=anomaly_type,
        breakdown=breakdown,
        rule_violations=violations,
    )


def residual_score(
    counts: dict[str, int],
    predicted: dict[str, float],
    historical_totals: list[float],
    isolation_score: Optional[float] = None,
) -> AnomalyResult:
    """Combines the cheap `quick_score` with a model-residual component
    (spec §9's "prediction residual" + "relative residual") and an optional
    isolation-forest novelty score. All weights sum to 1.0 and are
    documented above rather than left as magic numbers."""
    base = quick_score(counts, historical_totals)

    residual_component = 0.0
    predicted_total = sum(predicted.values())
    observed_total = float(total_count(counts))
    if predicted_total > 0:
        relative_residual = abs(observed_total - predicted_total) / predicted_total
        residual_component = _normalize(relative_residual, saturate_at=2.0)

    isolation_component = (
        max(0.0, min(1.0, isolation_score)) if isolation_score is not None else 0.0
    )

    score = min(
        1.0,
        RULE_VIOLATION_WEIGHT * min(1.0, len(base.rule_violations) * 0.4)
        + ROBUST_DEVIATION_WEIGHT * base.breakdown["robust_deviation"]
        + RESIDUAL_WEIGHT * residual_component
        + ISOLATION_WEIGHT * isolation_component,
    )

    breakdown = dict(base.breakdown)
    breakdown["prediction_residual"] = residual_component
    breakdown["isolation_score"] = isolation_component

    anomaly_type = base.anomaly_type
    if anomaly_type is None and residual_component >= 0.5:
        anomaly_type = "statistical_anomaly"

    return AnomalyResult(
        score=score,
        anomaly_type=anomaly_type,
        breakdown=breakdown,
        rule_violations=base.rule_violations,
    )


def severity_for_score(score: float, high_threshold: float) -> str:
    if score >= high_threshold:
        return "critical"
    if score >= high_threshold * 0.6:
        return "warning"
    return "info"
