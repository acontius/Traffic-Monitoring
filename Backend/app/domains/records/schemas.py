"""Request/response contracts for the records domain (SRS 3.6, 3.9)."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class TrafficRecordOut(BaseModel):
    device_id: str
    timestamp: datetime
    payload: Any
    is_valid: bool
    anomaly_flag: bool
    anomaly_reason: Optional[str]
    is_reconstructed: bool


class ManualOverrideRequest(BaseModel):
    device_id: str
    timestamp: datetime
    counts: dict[str, int]
    reason: Optional[str] = None
