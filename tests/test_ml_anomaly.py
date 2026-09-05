"""Robust MAD z-score, rule violations, multivariate/compositional anomaly
checks, and score normalisation (Backend/app/ml/anomaly.py)."""

from Backend.app.ml.anomaly import (
    quick_score,
    residual_score,
    robust_z_scores,
    rule_violations,
    severity_for_score,
)


def test_robust_z_score_zero_for_median_value():
    values = [10, 11, 9, 10, 12, 10]
    assert robust_z_scores(values, 10) == 0.0 or robust_z_scores(values, 10) < 1.0


def test_robust_z_score_high_for_extreme_outlier():
    values = [10, 11, 9, 10, 12, 10, 11]
    z = robust_z_scores(values, 500)
    assert z > 5.0


def test_rule_violations_flags_category_dominance():
    counts = {"سواری": 1, "موتور": 99}
    violations = rule_violations(counts)
    assert any(v.startswith("category_dominance:موتور") for v in violations)


def test_rule_violations_flags_total_collapse():
    violations = rule_violations({"سواری": 0, "موتور": 0})
    assert "total_collapse" in violations


def test_rule_violations_flags_negative_count():
    violations = rule_violations({"سواری": -5})
    assert "negative_count" in violations


def test_quick_score_is_bounded_to_unit_interval():
    historical = [10.0] * 20
    result = quick_score({"سواری": 500}, historical)
    assert 0.0 <= result.score <= 1.0
    assert result.anomaly_type is not None


def test_quick_score_no_anomaly_for_typical_value():
    historical = [10.0, 11.0, 9.0, 10.0, 12.0, 10.0, 11.0, 9.0]
    result = quick_score({"سواری": 10}, historical)
    assert result.score < 0.5


def test_residual_score_flags_large_relative_residual():
    result = residual_score(
        counts={"سواری": 200}, predicted={"سواری": 20}, historical_totals=[20.0] * 10
    )
    assert result.score > 0.3
    assert 0.0 <= result.score <= 1.0


def test_severity_for_score_thresholds():
    assert severity_for_score(0.9, high_threshold=0.8) == "critical"
    assert severity_for_score(0.5, high_threshold=0.8) == "warning"
    assert severity_for_score(0.1, high_threshold=0.8) == "info"
