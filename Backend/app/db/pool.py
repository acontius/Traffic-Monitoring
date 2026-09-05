"""asyncpg connection pool, shared across the app via FastAPI's app.state."""

import asyncpg
from fastapi import Request

from Backend.app.core.config import get_settings

_pool: asyncpg.pool.Pool | None = None


async def connect() -> asyncpg.pool.Pool:
    global _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(settings.db_dsn)
    return _pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool_unsafe() -> asyncpg.pool.Pool:
    """For use by background workers/tasks that don't have a Request."""
    if _pool is None:
        raise RuntimeError("DB pool not initialised yet")
    return _pool


async def get_pool(request: Request) -> asyncpg.pool.Pool:
    return request.app.state.pool
