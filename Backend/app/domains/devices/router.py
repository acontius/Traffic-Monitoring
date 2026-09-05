"""Device registry + dashboard-facing status endpoints (SRS 3.6)."""

from fastapi import APIRouter, Depends, HTTPException

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.devices import service
from Backend.app.domains.devices.schemas import DeviceCreate, DeviceOut, DeviceUpdate

router = APIRouter(
    prefix="/devices", tags=["devices"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[DeviceOut])
async def list_devices(pool=Depends(get_pool)):
    rows = await service.list_devices(pool)
    return [DeviceOut(**dict(r)) for r in rows]


@router.post("", response_model=DeviceOut, status_code=201)
async def create_device(
    body: DeviceCreate,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    try:
        row = await service.create_device(pool, body, actor=user.username)
    except service.DeviceAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="device_id already exists") from exc
    return DeviceOut(**dict(row))


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: str, pool=Depends(get_pool)):
    row = await service.get_device(pool, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return DeviceOut(**dict(row))


@router.get("/{device_id}/latest")
async def get_device_latest(device_id: str, pool=Depends(get_pool)):
    result = await service.get_latest_record(pool, device_id)
    if result is None:
        raise HTTPException(status_code=404, detail="no data for device")
    return result


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: str,
    body: DeviceUpdate,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")

    row = await service.update_device(pool, device_id, fields, actor=user.username)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return DeviceOut(**dict(row))
