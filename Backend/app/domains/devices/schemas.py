"""Request/response contracts for the devices domain (SRS 3.6)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DeviceOut(BaseModel):
    device_id: str
    location_type: str
    label: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    contractor: Optional[str]
    ip_address: Optional[str]
    status: str
    expected_interval_seconds: int
    last_seen_at: Optional[datetime]


class DeviceCreate(BaseModel):
    device_id: str
    location_type: str = "urban"
    label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contractor: Optional[str] = None
    expected_interval_seconds: int = 300


class DeviceUpdate(BaseModel):
    label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contractor: Optional[str] = None
    expected_interval_seconds: Optional[int] = None
