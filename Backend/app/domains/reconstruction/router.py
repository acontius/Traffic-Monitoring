"""Reconstruction formula config (redeploy-free tuning, SRS 5/11) and the
reconstruction audit log."""

from fastapi import APIRouter, Depends, HTTPException, Query

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.reconstruction import service
from Backend.app.domains.reconstruction.schemas import (
    ReconstructionConfigIn,
    ReconstructionConfigOut,
    ReconstructionLogOut,
)

router = APIRouter(tags=["reconstruction"], dependencies=[Depends(get_current_user)])


@router.get("/reconstruction/config", response_model=list[ReconstructionConfigOut])
async def list_config(pool=Depends(get_pool)):
    rows = await service.list_config(pool)
    return [ReconstructionConfigOut(**r) for r in rows]


@router.put("/reconstruction/config", response_model=ReconstructionConfigOut)
async def upsert_config(
    body: ReconstructionConfigIn,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    try:
        result = await service.upsert_config(
            pool, body.scope_type, body.scope_value, body.weights, user.username
        )
    except service.InvalidConfigScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReconstructionConfigOut(**result)


@router.get("/reconstruction/log", response_model=list[ReconstructionLogOut])
async def list_reconstruction_log(
    device_id: str | None = None,
    limit: int = Query(200, le=2000),
    pool=Depends(get_pool),
):
    rows = await service.list_log(pool, device_id, limit)
    return [ReconstructionLogOut(**r) for r in rows]
