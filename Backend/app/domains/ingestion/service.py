"""Orchestrates one WebSocket connection from a device (SRS 2.1, 3.2):
authenticate, then for each message validate -> detect anomaly -> persist ->
alert on problems -> enqueue for forwarding -> push a live dashboard update.

`router.py` owns the actual `WebSocket` protocol handling (accept/receive
loop); this module contains no FastAPI-specific code so it can be tested
without a live socket.
"""

import json
import logging
from typing import Optional

import asyncpg

from Backend.app.core.audit import record as record_audit
from Backend.app.core.config import get_settings
from Backend.app.domains.devices import queries as devices_queries
from Backend.app.domains.forwarding import service as forwarding_service
from Backend.app.domains.ingestion import validation
from Backend.app.domains.notifications import service as notifications_service
from Backend.app.domains.realtime.bus import broadcast_device_update
from Backend.app.domains.records import queries as records_queries

logger = logging.getLogger("tcms.ingestion")


class AuthenticationError(Exception):
    pass


async def authenticate(
    pool: asyncpg.pool.Pool, device_id: Optional[str], token: Optional[str]
) -> str:
    settings = get_settings()
    if not device_id or token != settings.device_shared_token:
        raise AuthenticationError("unauthorized")
    if not await devices_queries.device_exists(pool, device_id):
        raise AuthenticationError("unknown device")
    return device_id


async def get_location_type(pool: asyncpg.pool.Pool, device_id: str) -> str:
    return await devices_queries.get_location_type(pool, device_id) or "urban"


async def handle_invalid_json(pool: asyncpg.pool.Pool, device_id: str) -> None:
    await notifications_service.raise_alert(
        pool,
        alert_type="invalid_payload",
        device_id=device_id,
        severity="warning",
        message=f"JSON نامعتبر از دستگاه {device_id}",
    )


async def handle_message(
    pool: asyncpg.pool.Pool,
    device_id: str,
    location_type: str,
    message: str,
    ip_address: Optional[str],
) -> None:
    try:
        raw = json.loads(message)
    except json.JSONDecodeError:
        await handle_invalid_json(pool, device_id)
        return

    try:
        parsed_device_id, timestamp, counts, interval_minutes = (
            validation.validate_structure(raw)
        )
    except validation.ValidationError as exc:
        await notifications_service.raise_alert(
            pool,
            alert_type="invalid_payload",
            device_id=device_id,
            severity="warning",
            message=f"داده نامعتبر از دستگاه {device_id}: {exc}",
        )
        await record_audit(
            pool,
            actor=f"device:{device_id}",
            action="ingest_rejected",
            entity="traffic_records",
            details={"error": str(exc)},
        )
        return

    if parsed_device_id != device_id:
        await notifications_service.raise_alert(
            pool,
            alert_type="invalid_payload",
            device_id=device_id,
            severity="warning",
            message=(
                f"عدم تطابق شناسه دستگاه: اتصال {device_id} "
                f"اما payload {parsed_device_id}"
            ),
        )
        return

    is_anomaly, anomaly_reason = await validation.detect_anomaly(
        pool, device_id, timestamp, counts
    )

    payload = {
        "device_id": device_id,
        "location_type": location_type,
        "timestamp": timestamp.isoformat(),
        "interval_minutes": interval_minutes,
        "counts": counts,
    }

    await records_queries.upsert_ingested(
        pool, device_id, timestamp, payload, is_anomaly, anomaly_reason
    )
    await devices_queries.mark_online(pool, device_id, timestamp, ip_address)

    if is_anomaly:
        await notifications_service.raise_alert(
            pool,
            alert_type="statistical_anomaly",
            device_id=device_id,
            severity="warning",
            message=anomaly_reason or "الگوی ترافیک غیرعادی",
        )

    await forwarding_service.enqueue(pool, device_id, timestamp, payload)
    await broadcast_device_update(device_id, "online", payload)


async def handle_disconnect(pool: asyncpg.pool.Pool, device_id: str) -> None:
    await devices_queries.mark_offline(pool, device_id)
    await broadcast_device_update(device_id, "offline", None)
