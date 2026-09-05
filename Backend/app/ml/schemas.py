"""Pydantic contracts shared between the ML engine and its callers — kept in
the engine package (rather than only in `domains/ml/schemas.py`) because
`ai_explain.py` validates the LLM's response against `Explanation` here,
independent of any HTTP framing."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Explanation(BaseModel):
    """Strict contract for the optional OpenRouter explanation (spec §25,
    §27). The LLM never returns numbers that get used — only these four
    narrative fields."""

    likely_cause: str
    explanation: str
    severity: Literal["info", "warning", "critical"]
    recommended_action: str


class AnomalyEvidence(BaseModel):
    """The minimal, already-computed structured evidence sent to the LLM
    (spec §25, §43) — never raw payloads, credentials, or IPs."""

    device_id: str
    timestamp: str
    observed_total: float
    expected_total: Optional[float] = None
    anomaly_score: float
    device_health: str
    historical_mean: Optional[float] = None
    neighbor_totals: list[float] = Field(default_factory=list)
    is_holiday: bool = False
    is_special_event: bool = False
