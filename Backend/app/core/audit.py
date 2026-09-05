"""Audit trail writer. Every ingest/reconstruct/forward/manual action and
login should call `record` so operators can reconstruct "who did what when"
(SRS section 8)."""

import json

import asyncpg


async def record(
    pool: asyncpg.pool.Pool,
    actor: str,
    action: str,
    entity: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
) -> None:
    async with pool.acquire() as con:
        await con.execute(
            """
            INSERT INTO audit_log (actor, action, entity, entity_id, details)
            VALUES ($1, $2, $3, $4, $5)
            """,
            actor,
            action,
            entity,
            entity_id,
            json.dumps(details) if details is not None else None,
        )
