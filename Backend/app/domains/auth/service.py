"""Login/refresh/logout business logic (SRS 3.1). Raises domain exceptions
rather than HTTPException — router.py maps those to HTTP responses."""

from datetime import datetime, timezone

import asyncpg

from Backend.app.core import security
from Backend.app.core.audit import record as record_audit
from Backend.app.domains.auth import queries
from Backend.app.domains.auth.schemas import TokenResponse


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


async def login(pool: asyncpg.pool.Pool, username: str, password: str) -> TokenResponse:
    user = await queries.get_user_by_username(pool, username)

    if user is None or not security.verify_password(password, user["password_hash"]):
        await record_audit(pool, actor=username, action="login_failed")
        raise InvalidCredentialsError

    access_token = security.create_access_token(
        user["id"], user["username"], user["role"]
    )
    refresh_token = security.generate_refresh_token()

    await queries.insert_refresh_token(
        pool,
        user["id"],
        security.hash_refresh_token(refresh_token),
        security.refresh_token_expiry(),
    )
    await record_audit(pool, actor=user["username"], action="login")
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def refresh(pool: asyncpg.pool.Pool, refresh_token: str) -> TokenResponse:
    token_hash = security.hash_refresh_token(refresh_token)
    row = await queries.get_refresh_token_with_user(pool, token_hash)

    if (
        row is None
        or row["revoked_at"] is not None
        or row["expires_at"] < datetime.now(timezone.utc)
    ):
        raise InvalidRefreshTokenError

    new_refresh_token = security.generate_refresh_token()
    await queries.rotate_refresh_token(
        pool,
        old_token_id=row["id"],
        user_id=row["user_id"],
        new_token_hash=security.hash_refresh_token(new_refresh_token),
        expires_at=security.refresh_token_expiry(),
    )

    access_token = security.create_access_token(
        row["user_id"], row["username"], row["role"]
    )
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


async def logout(pool: asyncpg.pool.Pool, actor: str, refresh_token: str) -> None:
    await queries.revoke_refresh_token(pool, security.hash_refresh_token(refresh_token))
    await record_audit(pool, actor=actor, action="logout")
