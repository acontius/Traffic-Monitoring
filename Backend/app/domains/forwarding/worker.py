"""Background scheduler that drains the forwarding outbox (SRS 3.5)."""

import asyncio
import logging
from typing import Optional

import asyncpg

from Backend.app.core.config import get_settings
from Backend.app.domains.forwarding.service import run_once

logger = logging.getLogger("tcms.forwarding")


async def run_forever(
    pool: asyncpg.pool.Pool, stop_event: Optional[asyncio.Event] = None
) -> None:
    settings = get_settings()
    while stop_event is None or not stop_event.is_set():
        try:
            count = await run_once(pool)
            if count:
                logger.info("forwarding pass attempted %d row(s)", count)
        except Exception:
            logger.exception("forwarding pass failed")
        await asyncio.sleep(settings.forwarding_worker_interval_seconds)
