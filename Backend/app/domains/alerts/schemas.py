"""Request/response contracts for the alerts domain (SRS 3.8)."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AlertOut(BaseModel):
    id: int
    type: str
    device_id: Optional[str]
    severity: str
    message: str
    details: Any
    created_at: datetime
    acknowledged_at: Optional[datetime]
    acknowledged_by: Optional[str]
