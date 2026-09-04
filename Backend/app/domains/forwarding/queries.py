"""All SQL for the forwarding domain (the `forwarding_log` outbox table)."""

import json
from datetime import datetime
from typing import Optional

import asyncpg


async def enqueue(
    pool: asyncpg.pool.Pool, device_id: str, timestamp: datetime, payload: dict
) -> None:
    async with pool.acquire() as con:
        await con.execute(
            """
            INSERT INTO forwarding_log (device_id, timestamp, payload, status)
            VALUES ($1, $2, $3, 'pending')
            ON CONFLICT (device_id, timestamp) DO UPDATE
                SET payload = EXCLUDED.payload,
                    status = 'pending'
                WHERE forwarding_log.status = 'dead_letter'
            """,
            device_id,
            timestamp,
            json.dumps(payload),
        )


async def fetch_pending_or_failed(
    pool: asyncpg.pool.Pool, limit: int
) -> list[asyncpg.Record]:
    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT * FROM forwarding_log
            WHERE status IN ('pending', 'failed')
            ORDER BY timestamp
            LIMIT $1
            """,
            limit,
        )


async def get_by_id(
    pool: asyncpg.pool.Pool, forwarding_id: int
) -> asyncpg.Record | None:
    async with pool.acquire() as con:
        return await con.fetchrow(
            "SELECT * FROM forwarding_log WHERE id = $1", forwarding_id
        )


async def mark_pending(pool: asyncpg.pool.Pool, forwarding_id: int) -> None:
    async with pool.acquire() as con:
        await con.execute(
            "UPDATE forwarding_log SET status = 'pending' WHERE id = $1",
            forwarding_id,
        )


async def record_attempt_result(
    pool: asyncpg.pool.Pool,
    forwarding_id: int,
    status: str,
    attempt_count: int,
    response_code: int,
    response_body: str,
) -> None:
    async with pool.acquire() as con:
        await con.execute(
            """
            UPDATE forwarding_log
            SET status = $1, attempt_count = $2, last_attempt_at = now(),
                response_code = $3, response_body = $4
            WHERE id = $5
            """,
            status,
            attempt_count,
            response_code,
            response_body,
            forwarding_id,
        )


async def list_forwarding(
    pool: asyncpg.pool.Pool, status_filter: Optional[str], limit: int
) -> list[asyncpg.Record]:
    query = "SELECT * FROM forwarding_log"
    params: list = []
    if status_filter:
        params.append(status_filter)
        query += " WHERE status = $1"
    params.append(limit)
    query += f" ORDER BY timestamp DESC LIMIT ${len(params)}"

    async with pool.acquire() as con:
        return await con.fetch(query, *params)
