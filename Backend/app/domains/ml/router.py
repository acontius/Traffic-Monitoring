"""ML API: device health/anomalies/predictions/reconstructions, model
registry, training triggers, and monitoring metrics (spec §30).

`GET /ml/devices/{device_id}/reconstructions` is a thin wrapper over the
existing `reconstruction_log` (via `domains.reconstruction.service.list_log`)
rather than a duplicate store. `/ml/events` from the spec is exposed here as
`/ml/anomaly-events` to avoid colliding with the separate `traffic_events`
concept (spec §12) — documented in docs/ML_ARCHITECTURE.md.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.ml import service
from Backend.app.domains.ml.schemas import (
    AnomalyEventOut,
    AnomalyStatusUpdate,
    DeviceHealthOut,
    ModelOut,
    PredictionOut,
)
from Backend.app.domains.reconstruction.schemas import ReconstructionLogOut

router = APIRouter(prefix="/ml", tags=["ml"], dependencies=[Depends(get_current_user)])


@router.get("/devices/{device_id}/health", response_model=DeviceHealthOut)
async def device_health(device_id: str, pool=Depends(get_pool)):
    return await service.get_device_health(pool, device_id)


@router.get("/devices/{device_id}/anomalies", response_model=list[AnomalyEventOut])
async def device_anomalies(
    device_id: str, limit: int = Query(200, le=2000), pool=Depends(get_pool)
):
    return await service.list_anomaly_events(pool, device_id, limit)


@router.get("/anomaly-events", response_model=list[AnomalyEventOut])
async def anomaly_events(
    device_id: str | None = None,
    limit: int = Query(200, le=2000),
    pool=Depends(get_pool),
):
    return await service.list_anomaly_events(pool, device_id, limit)


@router.post("/anomaly-events/{anomaly_id}/status", response_model=AnomalyEventOut)
async def update_anomaly_status(
    anomaly_id: int,
    body: AnomalyStatusUpdate,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Operator feedback (spec §56-57): false_positive / true_anomaly /
    true_device_failure / acknowledged — the seed of future supervised
    labelling."""
    row = await service.set_anomaly_status(pool, anomaly_id, body.status, user.username)
    if row is None:
        raise HTTPException(status_code=404, detail="anomaly event not found")
    return row


@router.get("/devices/{device_id}/predictions", response_model=list[PredictionOut])
async def device_predictions(
    device_id: str, limit: int = Query(200, le=2000), pool=Depends(get_pool)
):
    return await service.list_predictions(pool, device_id, limit)


@router.get(
    "/devices/{device_id}/reconstructions", response_model=list[ReconstructionLogOut]
)
async def device_reconstructions(
    device_id: str, limit: int = Query(200, le=2000), pool=Depends(get_pool)
):
    return await service.list_reconstructions(pool, device_id, limit)


@router.post("/train")
async def train_models(pool=Depends(get_pool)):
    results = await service.train(pool)
    return {"trained": {k: bool(v) for k, v in results.items()}}


@router.post("/retrain")
async def retrain_models(pool=Depends(get_pool)):
    results = await service.train(pool)
    return {"retrained": {k: bool(v) for k, v in results.items()}}


@router.get("/models", response_model=list[ModelOut])
async def list_models(pool=Depends(get_pool)):
    return await service.list_models(pool)


@router.get("/models/{model_id}", response_model=ModelOut)
async def get_model(model_id: int, pool=Depends(get_pool)):
    row = await service.get_model(pool, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="model not found")
    return row


@router.get("/metrics")
async def metrics(pool=Depends(get_pool)):
    return await service.metrics(pool)


@router.get("/anomaly-events/{anomaly_id}/explain")
async def explain_anomaly(anomaly_id: int, pool=Depends(get_pool)):
    """Optional OpenRouter narrative (spec §25-27) — advisory only, `null`
    when AI is disabled (`TCMS_AI_ENABLED=false`, the default),
    unreachable, or fails. Never affects any stored decision."""
    explanation = await service.explain_anomaly(pool, anomaly_id)
    return explanation.model_dump() if explanation else None
