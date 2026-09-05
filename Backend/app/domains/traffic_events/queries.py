"""All SQL for the `traffic_events` table."""

import json
from datetime import datetime
from typing import Any, Optional

import asyncpg


def _parse(row: asyncpg.Record) -> dict:
    row = dict(row)
    if isinstance(row.get("impact_scope"), str):
        row["impact_scope"] = json.loads(row["impact_scope"])
    return row


async def list_events(
    pool: asyncpg.pool.Pool,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if date_from:
        params.append(date_from)
        conditions.append(f"end_at >= ${len(params)}")
    if date_to:
        params.append(date_to)
        conditions.append(f"start_at <= ${len(params)}")
    params.append(limit)

    query = "SELECT * FROM traffic_events"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += f" ORDER BY start_at DESC LIMIT ${len(params)}"

    async with pool.acquire() as con:
        rows = await con.fetch(query, *params)
    return [_parse(r) for r in rows]


async def insert_event(
    pool: asyncpg.pool.Pool,
    name: str,
    event_type: str,
    start_at: datetime,
    end_at: datetime,
    impact_scope: Optional[dict[str, Any]],
    description: Optional[str],
    created_by: str,
) -> dict:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """
            INSERT INTO traffic_events
                (name, event_type, start_at, end_at,
                 impact_scope, description, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            name,
            event_type,
            start_at,
            end_at,
            json.dumps(impact_scope) if impact_scope is not None else None,
            description,
            created_by,
        )
    return _parse(row)
