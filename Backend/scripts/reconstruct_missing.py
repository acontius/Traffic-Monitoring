"""CLI: run one reconstruction pass immediately (rather than waiting for the
scheduled worker, `TCMS_RECONSTRUCTION_SCAN_INTERVAL_SECONDS`).

Usage: python -m Backend.scripts.reconstruct_missing
"""

import asyncio
import logging

from Backend.app.db import pool as db_pool
from Backend.app.domains.reconstruction.engine import run_once

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tcms.reconstruction")


async def main() -> None:
    pool = await db_pool.connect()
    try:
        count = await run_once(pool)
        logger.info("reconstruction pass filled %d record(s)", count)
    finally:
        await db_pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
