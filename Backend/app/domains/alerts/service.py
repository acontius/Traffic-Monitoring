"""Alert listing + acknowledgement business logic (SRS 3.8)."""

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.domains.alerts import queries


async def list_alerts(
    pool: asyncpg.pool.Pool, unacknowledged_only: bool, limit: int
) -> list[asyncpg.Record]:
    return await queries.list_alerts(pool, unacknowledged_only, limit)


async def acknowledge_alert(
    pool: asyncpg.pool.Pool, alert_id: int, actor: str
) -> asyncpg.Record | None:
    row = await queries.acknowledge_alert(pool, alert_id, actor)
    if row is not None:
        await record_audit(
            pool,
            actor=actor,
            action="acknowledge_alert",
            entity="alerts",
            entity_id=str(alert_id),
        )
    return row
