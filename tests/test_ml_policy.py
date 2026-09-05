"""The deterministic automatic-repair policy (Backend/app/ml/policy.py) —
spec's decision table: AUTO_RECONSTRUCT / RECONSTRUCT_AND_ALERT /
MANUAL_REVIEW / IGNORE_ANOMALY."""

from Backend.app.core.config import get_settings
from Backend.app.ml.policy import (
    Decision,
    decide_anomaly,
    decide_reconstruction,
    formula_fallback_confidence,
)


def test_high_confidence_healthy_device_auto_reconstructs():
    settings = get_settings()
    result = decide_reconstruction(
        confidence=settings.ml_min_confidence + 0.05, device_health="HEALTHY"
    )
    assert result.decision == Decision.AUTO_RECONSTRUCT


def test_mid_confidence_reconstructs_but_flags():
    settings = get_settings()
    mid = (settings.ml_min_confidence + settings.ml_review_confidence) / 2
    result = decide_reconstruction(confidence=mid, device_health="HEALTHY")
    assert result.decision == Decision.RECONSTRUCT_AND_ALERT


def test_low_confidence_goes_to_manual_review():
    settings = get_settings()
    result = decide_reconstruction(
        confidence=settings.ml_review_confidence - 0.05, device_health="HEALTHY"
    )
    assert result.decision == Decision.MANUAL_REVIEW


def test_high_confidence_but_unhealthy_device_does_not_auto_reconstruct():
    settings = get_settings()
    result = decide_reconstruction(
        confidence=settings.ml_min_confidence + 0.05, device_health="SUSPICIOUS"
    )
    assert result.decision != Decision.AUTO_RECONSTRUCT


def test_never_fabricates_high_confidence_from_no_evidence():
    # Zero samples anywhere -> confidence must be 0, never a confident number.
    assert formula_fallback_confidence({}) == 0.0


def test_anomaly_below_threshold_is_ignored():
    settings = get_settings()
    result = decide_anomaly(
        settings.ml_anomaly_threshold - 0.1,
        device_health="HEALTHY",
        is_special_event=False,
    )
    assert result.decision == Decision.IGNORE_ANOMALY


def test_anomaly_during_special_event_is_ignored_unless_extreme():
    settings = get_settings()
    result = decide_anomaly(
        settings.ml_high_anomaly_threshold - 0.1,
        device_health="HEALTHY",
        is_special_event=True,
    )
    assert result.decision == Decision.IGNORE_ANOMALY


def test_extreme_anomaly_during_special_event_still_flagged():
    settings = get_settings()
    result = decide_anomaly(
        settings.ml_high_anomaly_threshold + 0.01,
        device_health="HEALTHY",
        is_special_event=True,
    )
    assert result.decision != Decision.IGNORE_ANOMALY


def test_anomaly_on_unhealthy_device_routes_to_manual_review():
    settings = get_settings()
    result = decide_anomaly(
        settings.ml_high_anomaly_threshold,
        device_health="OFFLINE",
        is_special_event=False,
    )
    assert result.decision == Decision.MANUAL_REVIEW
