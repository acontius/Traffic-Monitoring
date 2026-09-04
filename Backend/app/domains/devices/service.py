"""Device registry business logic (SRS 3.2/3.6)."""

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.domains.devices import queries
from Backend.app.domains.devices.schemas import DeviceCreate


class DeviceAlreadyExistsError(Exception):
    pass


async def list_devices(pool: asyncpg.pool.Pool) -> list[asyncpg.Record]:
    return await queries.list_devices(pool)


async def get_device(pool: asyncpg.pool.Pool, device_id: str) -> asyncpg.Record | None:
    return await queries.get_device(pool, device_id)


async def get_latest_record(pool: asyncpg.pool.Pool, device_id: str) -> dict | None:
    return await queries.get_latest_record_for_device(pool, device_id)


async def create_device(
    pool: asyncpg.pool.Pool, body: DeviceCreate, actor: str
) -> asyncpg.Record:
    """Registers a new counting device (SRS 3.2 "شناسه دستگاه" /
    "مدیریت اطلاعات تجهیزات تردد‌شمار"). Only a registered device_id is
    accepted by the WebSocket ingestion gateway, so this must run before a
    new physical/simulated device can connect."""
    if await queries.device_exists(pool, body.device_id):
        raise DeviceAlreadyExistsError(body.device_id)

    row = await queries.insert_device(pool, body)
    await record_audit(
        pool,
        actor=actor,
        action="create_device",
        entity="devices",
        entity_id=body.device_id,
        details=body.model_dump(),
    )
    return row


async def update_device(
    pool: asyncpg.pool.Pool, device_id: str, fields: dict, actor: str
) -> asyncpg.Record | None:
    row = await queries.update_device(pool, device_id, fields)
    if row is not None:
        await record_audit(
            pool,
            actor=actor,
            action="update_device",
            entity="devices",
            entity_id=device_id,
            details=fields,
        )
    return row
