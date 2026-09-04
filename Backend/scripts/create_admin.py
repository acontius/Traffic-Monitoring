"""One-off bootstrap: creates (or updates the password of) the initial
system-manager user (SRS 2.2). Run after applying the DB migrations:

    python -m Backend.scripts.create_admin --username admin --password <secret>

Or set TCMS_ADMIN_USERNAME / TCMS_ADMIN_PASSWORD and run with no args.
"""

import argparse
import asyncio
import os

import asyncpg

from Backend.app.core.config import get_settings
from Backend.app.core.security import hash_password


async def create_admin(username: str, password: str) -> None:
    settings = get_settings()
    pool = await asyncpg.create_pool(settings.db_dsn)
    try:
        async with pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO users (username, password_hash, role)
                VALUES ($1, $2, 'admin')
                ON CONFLICT (username) DO UPDATE
                    SET password_hash = EXCLUDED.password_hash
                """,
                username,
                hash_password(password),
            )
        print(f"Admin user '{username}' is ready.")
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--username", default=os.environ.get("TCMS_ADMIN_USERNAME", "admin")
    )
    parser.add_argument("--password", default=os.environ.get("TCMS_ADMIN_PASSWORD"))
    args = parser.parse_args()

    if not args.password:
        parser.error("--password (or TCMS_ADMIN_PASSWORD) is required")

    asyncio.run(create_admin(args.username, args.password))


if __name__ == "__main__":
    main()
