"""All SQL for the devices domain (the `devices` table). Also used by other
domains (ingestion, reconstruction) to read/update device rows — kept here
since this module owns that table."""

import json

import asyncpg

from Backend.app.domains.devices.schemas import DeviceCreate


async def list_devices(pool: asyncpg.pool.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as con:
        return await con.fetch("SELECT * FROM devices ORDER BY device_id")


async def get_device(pool: asyncpg.pool.Pool, device_id: str) -> asyncpg.Record | None:
    async with pool.acquire() as con:
        return await con.fetchrow(
            "SELECT * FROM devices WHERE device_id = $1", device_id
        )


async def device_exists(pool: asyncpg.pool.Pool, device_id: str) -> bool:
    async with pool.acquire() as con:
        return bool(
            await con.fetchval("SELECT 1 FROM devices WHERE device_id = $1", device_id)
        )


async def get_location_type(pool: asyncpg.pool.Pool, device_id: str) -> str | None:
    async with pool.acquire() as con:
        return await con.fetchval(
            "SELECT location_type FROM devices WHERE device_id = $1", device_id
        )


async def get_latest_record_for_device(
    pool: asyncpg.pool.Pool, device_id: str
) -> dict | None:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """
            SELECT device_id, timestamp, payload,
                   is_valid, anomaly_flag, is_reconstructed
            FROM traffic_records WHERE device_id = $1
            ORDER BY timestamp DESC LIMIT 1
            """,
            device_id,
        )
    if row is None:
        return None
    result = dict(row)
    if isinstance(result["payload"], str):
        result["payload"] = json.loads(result["payload"])
    return result


async def insert_device(
    pool: asyncpg.pool.Pool, device: DeviceCreate
) -> asyncpg.Record:
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            INSERT INTO devices
                (device_id, location_type, label, latitude, longitude,
                 contractor, expected_interval_seconds)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            device.device_id,
            device.location_type,
            device.label,
            device.latitude,
            device.longitude,
            device.contractor,
            device.expected_interval_seconds,
        )


async def update_device(
    pool: asyncpg.pool.Pool, device_id: str, fields: dict
) -> asyncpg.Record | None:
    set_clause = ", ".join(f"{key} = ${i + 2}" for i, key in enumerate(fields))
    async with pool.acquire() as con:
        return await con.fetchrow(
            f"UPDATE devices SET {set_clause} WHERE device_id = $1 RETURNING *",
            device_id,
            *fields.values(),
        )


async def mark_online(
    pool: asyncpg.pool.Pool, device_id: str, timestamp, ip_address
) -> None:
    async with pool.acquire() as con:
        await con.execute(
            """
            UPDATE devices
            SET last_seen_at = $2,
                status = 'online',
                ip_address = COALESCE($3, ip_address)
            WHERE device_id = $1
            """,
            device_id,
            timestamp,
            ip_address,
        )


async def mark_offline(pool: asyncpg.pool.Pool, device_id: str) -> None:
    async with pool.acquire() as con:
        await con.execute(
            "UPDATE devices SET status = 'offline' WHERE device_id = $1", device_id
        )
