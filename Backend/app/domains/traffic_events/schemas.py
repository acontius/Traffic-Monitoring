"""Request/response contracts for custom operator-defined calendar events
(spec §12) — built-in holidays/Nowruz are computed in code
(`Backend/app/ml/calendar.py`), not stored here."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class TrafficEventIn(BaseModel):
    name: str
    event_type: str
    start_at: datetime
    end_at: datetime
    impact_scope: Optional[dict[str, Any]] = None
    description: Optional[str] = None


class TrafficEventOut(TrafficEventIn):
    id: int
    created_by: Optional[str]
    created_at: datetime
