"""All SQL for the alerts domain (the `alerts` table). `insert_alert` is
also called directly by `domains.notifications.service` — that domain owns
alert *delivery* (live push + SMS) but this one owns the table."""

import json
from typing import Any, Optional

import asyncpg


async def list_alerts(
    pool: asyncpg.pool.Pool, unacknowledged_only: bool, limit: int
) -> list[asyncpg.Record]:
    query = "SELECT * FROM alerts"
    if unacknowledged_only:
        query += " WHERE acknowledged_at IS NULL"
    query += " ORDER BY created_at DESC LIMIT $1"
    async with pool.acquire() as con:
        return await con.fetch(query, limit)


async def insert_alert(
    pool: asyncpg.pool.Pool,
    alert_type: str,
    message: str,
    severity: str,
    device_id: Optional[str],
    details: Optional[dict[str, Any]],
) -> asyncpg.Record:
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            INSERT INTO alerts (type, device_id, severity, message, details)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, created_at
            """,
            alert_type,
            device_id,
            severity,
            message,
            json.dumps(details) if details is not None else None,
        )


async def acknowledge_alert(
    pool: asyncpg.pool.Pool, alert_id: int, actor: str
) -> asyncpg.Record | None:
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            UPDATE alerts SET acknowledged_at = now(), acknowledged_by = $2
            WHERE id = $1
            RETURNING *
            """,
            alert_id,
            actor,
        )
