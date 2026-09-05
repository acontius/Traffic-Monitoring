"""Forwarding outbox listing + manual resend (SRS 3.5, 3.9)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.forwarding import service
from Backend.app.domains.forwarding.schemas import ForwardingLogOut

router = APIRouter(tags=["forwarding"], dependencies=[Depends(get_current_user)])


@router.get("/forwarding", response_model=list[ForwardingLogOut])
async def list_forwarding(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(200, le=2000),
    pool=Depends(get_pool),
):
    rows = await service.list_forwarding(pool, status_filter, limit)
    return [ForwardingLogOut(**dict(r)) for r in rows]


@router.post("/forwarding/{forwarding_id}/resend")
async def resend_forwarding(
    forwarding_id: int,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    ok = await service.resend(pool, forwarding_id, actor=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="forwarding row not found")
    return {"status": "ok"}
