"""TCMS FastAPI application: composition root. Every domain owns its own
router (REST or WebSocket); this module only wires them together and starts
the two background workers (reconstruction, forwarding)."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from Backend.app.core.config import get_settings
from Backend.app.db import pool as db_pool
from Backend.app.domains.alerts.router import router as alerts_router
from Backend.app.domains.auth.router import router as auth_router
from Backend.app.domains.devices.router import router as devices_router
from Backend.app.domains.forwarding.router import router as forwarding_router
from Backend.app.domains.forwarding.worker import run_forever as run_forwarding_forever
from Backend.app.domains.ingestion.router import router as ingestion_router
from Backend.app.domains.ml.router import router as ml_router
from Backend.app.domains.ml.workers import (
    run_health_scan_forever,
    run_retrain_forever,
)
from Backend.app.domains.realtime.router import router as realtime_router
from Backend.app.domains.reconstruction.router import router as reconstruction_router
from Backend.app.domains.reconstruction.worker import (
    run_forever as run_reconstruction_forever,
)
from Backend.app.domains.records.router import router as records_router
from Backend.app.domains.reports.router import router as reports_router
from Backend.app.domains.traffic_events.router import router as traffic_events_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db_pool.connect()
    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(run_reconstruction_forever(app.state.pool, stop_event)),
        asyncio.create_task(run_forwarding_forever(app.state.pool, stop_event)),
        asyncio.create_task(run_health_scan_forever(app.state.pool, stop_event)),
        asyncio.create_task(run_retrain_forever(app.state.pool, stop_event)),
    ]
    try:
        yield
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await db_pool.disconnect()


app = FastAPI(title="Traffic Count Management System (TCMS)", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for domain_router in (
    auth_router,
    devices_router,
    records_router,
    alerts_router,
    reports_router,
    reconstruction_router,
    forwarding_router,
    ingestion_router,
    realtime_router,
    ml_router,
    traffic_events_router,
):
    app.include_router(domain_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
