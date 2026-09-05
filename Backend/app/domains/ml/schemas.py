"""Request/response contracts for the ML API (spec §30)."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class DeviceHealthOut(BaseModel):
    device_id: str
    health_status: str
    snapshot_at: Optional[datetime] = None
    signals: dict[str, Any] = {}


class AnomalyEventOut(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    anomaly_type: str
    severity: str
    score: float
    observed: Any
    expected: Any
    evidence: Any
    status: str
    created_at: datetime


class PredictionOut(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    vehicle_type: str
    predicted_value: float
    prediction_interval_low: Optional[float]
    prediction_interval_high: Optional[float]
    model_id: Optional[int]
    created_at: datetime


class ModelOut(BaseModel):
    id: int
    model_name: str
    model_version: str
    model_type: str
    trained_at: datetime
    training_data_range_start: Optional[datetime]
    training_data_range_end: Optional[datetime]
    feature_version: str
    metrics: Any
    is_active: bool
    created_at: datetime


class AnomalyStatusUpdate(BaseModel):
    status: str
