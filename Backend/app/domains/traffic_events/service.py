from datetime import datetime
from typing import Any, Optional

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.domains.traffic_events import queries


async def list_events(
    pool: asyncpg.pool.Pool,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    limit: int,
) -> list[dict]:
    return await queries.list_events(pool, date_from, date_to, limit)


async def create_event(
    pool: asyncpg.pool.Pool,
    name: str,
    event_type: str,
    start_at: datetime,
    end_at: datetime,
    impact_scope: Optional[dict[str, Any]],
    description: Optional[str],
    actor: str,
) -> dict:
    row = await queries.insert_event(
        pool, name, event_type, start_at, end_at, impact_scope, description, actor
    )
    await record_audit(
        pool,
        actor=actor,
        action="create_traffic_event",
        entity="traffic_events",
        entity_id=str(row["id"]),
        details={"name": name, "event_type": event_type},
    )
    return row
