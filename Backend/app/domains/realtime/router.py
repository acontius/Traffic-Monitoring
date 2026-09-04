"""The /ws/live WebSocket endpoint (SRS 3.6/3.8 live dashboard push)."""

from fastapi import APIRouter, WebSocket

from Backend.app.domains.realtime.bus import register_and_serve

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await register_and_serve(websocket)
