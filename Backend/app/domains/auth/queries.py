"""All SQL for the auth domain (users + refresh_tokens tables). Nothing
outside this module should touch those tables directly."""

from datetime import datetime

import asyncpg


async def get_user_by_username(
    pool: asyncpg.pool.Pool, username: str
) -> asyncpg.Record | None:
    async with pool.acquire() as con:
        return await con.fetchrow(
            "SELECT id, username, password_hash, role FROM users WHERE username = $1",
            username,
        )


async def insert_refresh_token(
    pool: asyncpg.pool.Pool, user_id: int, token_hash: str, expires_at: datetime
) -> None:
    async with pool.acquire() as con:
        await con.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            """,
            user_id,
            token_hash,
            expires_at,
        )


async def get_refresh_token_with_user(
    pool: asyncpg.pool.Pool, token_hash: str
) -> asyncpg.Record | None:
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            SELECT rt.id, rt.expires_at, rt.revoked_at,
                   u.id AS user_id, u.username, u.role
            FROM refresh_tokens rt
            JOIN users u ON u.id = rt.user_id
            WHERE rt.token_hash = $1
            """,
            token_hash,
        )


async def rotate_refresh_token(
    pool: asyncpg.pool.Pool,
    old_token_id: int,
    user_id: int,
    new_token_hash: str,
    expires_at: datetime,
) -> None:
    async with pool.acquire() as con, con.transaction():
        await con.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE id = $1",
            old_token_id,
        )
        await con.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            """,
            user_id,
            new_token_hash,
            expires_at,
        )


async def revoke_refresh_token(pool: asyncpg.pool.Pool, token_hash: str) -> None:
    async with pool.acquire() as con:
        await con.execute(
            "UPDATE refresh_tokens SET revoked_at = now() "
            "WHERE token_hash = $1 AND revoked_at IS NULL",
            token_hash,
        )
