"""Alert listing + acknowledgement (SRS 3.8)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.alerts import service
from Backend.app.domains.alerts.schemas import AlertOut

router = APIRouter(
    prefix="/alerts", tags=["alerts"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    unacknowledged_only: bool = Query(False),
    limit: int = Query(200, le=2000),
    pool=Depends(get_pool),
):
    rows = await service.list_alerts(pool, unacknowledged_only, limit)
    return [AlertOut(**dict(r)) for r in rows]


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: int,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    row = await service.acknowledge_alert(pool, alert_id, user.username)
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return AlertOut(**dict(row))
