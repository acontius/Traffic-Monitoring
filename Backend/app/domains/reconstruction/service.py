"""Business logic behind the reconstruction config/log HTTP API (SRS 5, 11)
and the shared "log a manual override" write path used by the records
domain (SRS 3.9)."""

from datetime import datetime
from typing import Any, Optional

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.domains.reconstruction import queries


class InvalidConfigScopeError(Exception):
    pass


async def list_config(pool: asyncpg.pool.Pool) -> list[dict]:
    return await queries.list_config(pool)


async def upsert_config(
    pool: asyncpg.pool.Pool,
    scope_type: str,
    scope_value: Optional[str],
    weights: dict[str, Any],
    actor: str,
) -> dict:
    if scope_type != "default" and not scope_value:
        raise InvalidConfigScopeError(
            "scope_value required unless scope_type is 'default'"
        )

    result = await queries.upsert_config(pool, scope_type, scope_value, weights, actor)
    await record_audit(
        pool,
        actor=actor,
        action="update_reconstruction_config",
        entity="reconstruction_config",
        entity_id=f"{scope_type}:{scope_value}",
        details=weights,
    )
    return result


async def list_log(
    pool: asyncpg.pool.Pool, device_id: Optional[str], limit: int
) -> list[dict]:
    return await queries.list_log(pool, device_id, limit)


async def log_manual_override(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    reason: Optional[str],
    counts: dict[str, int],
    actor: str,
) -> None:
    """Records an operator's manual override in the same audit trail the
    automated engine writes to (SRS 3.9 "امکان بازنویسی تصمیم بازسازی")."""
    await queries.insert_log_entry(
        pool,
        device_id=device_id,
        timestamp=timestamp,
        method="manual_override",
        formula_snapshot={},
        inputs={"reason": reason, "counts": counts},
        manual_override=True,
        created_by=actor,
    )
