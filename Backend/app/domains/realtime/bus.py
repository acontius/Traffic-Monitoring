"""Live push channel for the dashboard: device status changes and new
alerts, so the panel doesn't need to poll (SRS 3.6/3.8). This is the
connection registry + broadcast helpers; `router.py` owns the actual
WebSocket endpoint."""

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("tcms.realtime")

_clients: set[WebSocket] = set()


async def register_and_serve(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)
    logger.info("dashboard client connected (%d total)", len(_clients))
    try:
        while True:
            # The dashboard doesn't need to send anything; just keep the
            # connection open and drain whatever it sends (e.g. pings).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        logger.info("dashboard client disconnected (%d total)", len(_clients))


async def _broadcast(message: dict) -> None:
    if not _clients:
        return
    text = json.dumps(message, ensure_ascii=False, default=str)
    stale = set()
    for client in _clients:
        try:
            await client.send_text(text)
        except Exception:
            stale.add(client)
    _clients.difference_update(stale)


async def broadcast_alert(alert: dict) -> None:
    await _broadcast({"event": "alert", "data": alert})


async def broadcast_device_update(
    device_id: str, status: str, latest: dict | None
) -> None:
    await _broadcast(
        {
            "event": "device_update",
            "data": {"device_id": device_id, "status": status, "latest": latest},
        }
    )


async def broadcast_anomaly_event(event: dict) -> None:
    await _broadcast({"event": "anomaly_detected", "data": event})


async def broadcast_reconstruction_event(event: dict) -> None:
    await _broadcast({"event": "reconstruction_completed", "data": event})


async def broadcast_device_health(event: dict) -> None:
    await _broadcast({"event": "device_health_changed", "data": event})
