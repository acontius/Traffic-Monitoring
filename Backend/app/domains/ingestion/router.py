"""WebSocket gateway devices connect to and push traffic-count payloads
into (SRS 2.1 "درگاه دریافت WebSocket", 3.2).

Connect as: ws://<host>/ws/ingest?device_id=cam-01&token=<shared-token>

Every message is expected to be the JSON produced by
`Backend/Devices/cameras.py`'s `TrafficRecord.to_json()`:
    {"device_id": ..., "location_type": ..., "timestamp": ...,
     "interval_minutes": ..., "counts": {...}}
"""

import logging

import asyncpg
from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from Backend.app.domains.ingestion import service

logger = logging.getLogger("tcms.ingestion")

router = APIRouter()


@router.websocket("/ws/ingest")
async def ws_ingest(websocket: WebSocket) -> None:
    pool: asyncpg.pool.Pool = websocket.app.state.pool

    try:
        device_id = await service.authenticate(
            pool,
            websocket.query_params.get("device_id"),
            websocket.query_params.get("token"),
        )
    except service.AuthenticationError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    ip_address = websocket.client.host if websocket.client else None
    logger.info("device connected: %s from %s", device_id, ip_address)

    location_type = await service.get_location_type(pool, device_id)

    try:
        async for message in websocket.iter_text():
            await service.handle_message(
                pool, device_id, location_type, message, ip_address
            )
    except WebSocketDisconnect:
        pass
    finally:
        await service.handle_disconnect(pool, device_id)
        logger.info("device disconnected: %s", device_id)
