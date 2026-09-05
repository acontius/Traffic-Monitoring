"""Custom operator-defined calendar events (spec §12)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.traffic_events import service
from Backend.app.domains.traffic_events.schemas import TrafficEventIn, TrafficEventOut

router = APIRouter(tags=["traffic-events"], dependencies=[Depends(get_current_user)])


@router.get("/traffic-events", response_model=list[TrafficEventOut])
async def list_events(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(500, le=5000),
    pool=Depends(get_pool),
):
    return await service.list_events(pool, date_from, date_to, limit)


@router.post("/traffic-events", response_model=TrafficEventOut)
async def create_event(
    body: TrafficEventIn,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    return await service.create_event(
        pool,
        body.name,
        body.event_type,
        body.start_at,
        body.end_at,
        body.impact_scope,
        body.description,
        user.username,
    )
