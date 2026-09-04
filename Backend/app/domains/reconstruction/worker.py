"""Background scheduler for the reconstruction engine (SRS 3.4)."""

import asyncio
import logging
from typing import Optional

import asyncpg

from Backend.app.core.config import get_settings
from Backend.app.domains.reconstruction.engine import run_once

logger = logging.getLogger("tcms.reconstruction")


async def run_forever(
    pool: asyncpg.pool.Pool, stop_event: Optional[asyncio.Event] = None
) -> None:
    settings = get_settings()
    while stop_event is None or not stop_event.is_set():
        try:
            count = await run_once(pool)
            if count:
                logger.info("reconstruction pass filled %d record(s)", count)
        except Exception:
            logger.exception("reconstruction pass failed")
        await asyncio.sleep(settings.reconstruction_scan_interval_seconds)
