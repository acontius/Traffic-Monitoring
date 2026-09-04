"""Request/response contracts for the reconstruction domain (SRS 3.4, 5, 11)."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ReconstructionConfigIn(BaseModel):
    scope_type: str = Field(pattern="^(default|location_type|device)$")
    scope_value: Optional[str] = None
    weights: dict[str, Any]


class ReconstructionConfigOut(ReconstructionConfigIn):
    id: int
    updated_at: datetime
    updated_by: Optional[str]


class ReconstructionLogOut(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    method: str
    formula_snapshot: Any
    inputs: Any
    manual_override: bool
    created_by: Optional[str]
    created_at: datetime
