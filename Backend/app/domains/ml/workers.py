"""Background loops for the ML layer, following the exact
`asyncio.create_task` + `while not stop_event.is_set(): ... sleep(...)`
pattern already used by `domains.reconstruction.worker` /
`domains.forwarding.worker` (spec §44: no Celery/Redis, reuse the existing
worker architecture).
"""

import asyncio
import logging
from typing import Optional

import asyncpg

from Backend.app.core.config import get_settings
from Backend.app.domains.ml import service

logger = logging.getLogger("tcms.ml")


async def run_health_scan_forever(
    pool: asyncpg.pool.Pool, stop_event: Optional[asyncio.Event] = None
) -> None:
    settings = get_settings()
    while stop_event is None or not stop_event.is_set():
        try:
            checked = await service.run_health_scan(pool)
            logger.debug("device health scan checked %d device(s)", checked)
        except Exception:
            logger.exception("device health scan failed")
        await asyncio.sleep(settings.device_health_scan_interval_seconds)


async def run_retrain_forever(
    pool: asyncpg.pool.Pool, stop_event: Optional[asyncio.Event] = None
) -> None:
    settings = get_settings()
    if not settings.ml_enabled:
        return
    while stop_event is None or not stop_event.is_set():
        await asyncio.sleep(settings.ml_retrain_interval_hours * 3600)
        try:
            results = await service.train(pool)
            logger.info(
                "scheduled retrain finished: %s",
                {k: bool(v) for k, v in results.items()},
            )
        except Exception:
            logger.exception("scheduled retrain failed")
