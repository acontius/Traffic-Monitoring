"""Request/response contracts for the forwarding domain (SRS 3.5, 3.9)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ForwardingLogOut(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    status: str
    attempt_count: int
    last_attempt_at: Optional[datetime]
    response_code: Optional[int]
    response_body: Optional[str]
