"""Traffic record retrieval + manual override business logic (SRS 3.6, 3.9)."""

from datetime import datetime
from typing import Optional

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.domains.devices import queries as devices_queries
from Backend.app.domains.forwarding import service as forwarding_service
from Backend.app.domains.reconstruction import service as reconstruction_service
from Backend.app.domains.records import queries


async def latest_all(pool: asyncpg.pool.Pool) -> list[dict]:
    return await queries.get_latest_all(pool)


async def history(
    pool: asyncpg.pool.Pool,
    device_id: str,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    limit: int,
) -> list[dict]:
    return await queries.get_history(pool, device_id, date_from, date_to, limit)


async def manual_override(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    counts: dict[str, int],
    reason: Optional[str],
    actor: str,
) -> None:
    """Lets an operator overwrite a reconstructed (or bad) value by hand
    (SRS 3.9 "امکان بازنویسی تصمیم بازسازی")."""
    location_type = await devices_queries.get_location_type(pool, device_id)
    payload = {
        "device_id": device_id,
        "location_type": location_type,
        "timestamp": timestamp.isoformat(),
        "counts": counts,
        "manual_override": True,
    }

    await queries.upsert_reconstructed_or_manual(pool, device_id, timestamp, payload)
    await reconstruction_service.log_manual_override(
        pool, device_id, timestamp, reason, counts, actor
    )
    await record_audit(
        pool,
        actor=actor,
        action="manual_override",
        entity="traffic_records",
        entity_id=f"{device_id}@{timestamp.isoformat()}",
        details={"counts": counts, "reason": reason},
    )
    await forwarding_service.enqueue(pool, device_id, timestamp, payload)
