"""Deterministic automatic-repair policy (spec §16, §28). This is the one
place that decides what actually happens to a reconstruction/anomaly — an
LLM never makes this decision (spec §26/§28); `ai_explain.py` only narrates
a decision already made here.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from Backend.app.core.config import get_settings


class Decision(str, Enum):
    AUTO_RECONSTRUCT = "AUTO_RECONSTRUCT"
    RECONSTRUCT_AND_ALERT = "RECONSTRUCT_AND_ALERT"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    IGNORE_ANOMALY = "IGNORE_ANOMALY"


@dataclass
class PolicyResult:
    decision: Decision
    reason: str


def decide_reconstruction(
    confidence: float,
    device_health: str,
    forward_low_confidence: Optional[bool] = None,
) -> PolicyResult:
    settings = get_settings()
    min_conf = settings.ml_min_confidence
    review_conf = settings.ml_review_confidence

    if confidence >= min_conf and device_health in ("HEALTHY", "RECOVERING"):
        return PolicyResult(
            Decision.AUTO_RECONSTRUCT,
            f"confidence {confidence:.2f} >= min {min_conf:.2f}",
        )
    if confidence >= review_conf:
        return PolicyResult(
            Decision.RECONSTRUCT_AND_ALERT,
            f"confidence {confidence:.2f} in [{review_conf:.2f}, {min_conf:.2f}) "
            "— reconstructed but flagged",
        )
    return PolicyResult(
        Decision.MANUAL_REVIEW,
        f"confidence {confidence:.2f} < review threshold {review_conf:.2f} "
        "— insufficient evidence",
    )


def decide_anomaly(
    anomaly_score: float,
    device_health: str,
    is_special_event: bool,
) -> PolicyResult:
    settings = get_settings()
    if is_special_event and anomaly_score < settings.ml_high_anomaly_threshold:
        return PolicyResult(
            Decision.IGNORE_ANOMALY,
            "score below high-anomaly threshold during a known special event/holiday",
        )
    if device_health in ("OFFLINE", "SUSPICIOUS"):
        return PolicyResult(
            Decision.MANUAL_REVIEW,
            f"device health is {device_health}; anomaly likely device-caused, "
            "needs operator attention",
        )
    if anomaly_score < settings.ml_anomaly_threshold:
        return PolicyResult(Decision.IGNORE_ANOMALY, "score below anomaly threshold")
    if anomaly_score >= settings.ml_high_anomaly_threshold:
        return PolicyResult(
            Decision.RECONSTRUCT_AND_ALERT, "score above high-anomaly threshold"
        )
    return PolicyResult(Decision.RECONSTRUCT_AND_ALERT, "score above anomaly threshold")


def formula_fallback_confidence(inputs: dict) -> float:
    """Heuristic confidence for the existing weighted-formula reconstruction
    (Level 5) based on how much historical evidence actually fed it — the
    formula itself never produces a confidence, so this is where one is
    derived, using only inputs the formula already logs."""
    samples = (
        inputs.get("samples_same_hour", 0)
        + inputs.get("samples_same_weekday_hour", 0)
        + inputs.get("samples_recent", 0)
    )
    settings = get_settings()
    coverage = min(1.0, samples / max(1, settings.ml_min_history_points))
    return round(0.5 * coverage, 4)
