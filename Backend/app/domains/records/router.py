"""Traffic record retrieval + manual override (SRS 3.6, 3.9)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.records import service
from Backend.app.domains.records.schemas import ManualOverrideRequest

router = APIRouter(
    prefix="/records", tags=["records"], dependencies=[Depends(get_current_user)]
)


@router.get("/latest")
async def latest_all(pool=Depends(get_pool)):
    """Latest reading per device — feeds the dashboard map/status list."""
    return await service.latest_all(pool)


@router.get("/{device_id}/history")
async def device_history(
    device_id: str,
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(500, le=5000),
    pool=Depends(get_pool),
):
    return await service.history(pool, device_id, date_from, date_to, limit)


@router.post("/manual-override")
async def manual_override(
    body: ManualOverrideRequest,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    await service.manual_override(
        pool, body.device_id, body.timestamp, body.counts, body.reason, user.username
    )
    return {"status": "ok"}
