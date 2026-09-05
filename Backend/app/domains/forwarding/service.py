"""Forwards valid/reconstructed data to the road-authority (راهداری) web
service, with a durable retry outbox (SRS 3.5 / 10).

Every row that should be forwarded is written to `forwarding_log` first
(`enqueue`); `worker.run_forever` drains pending/failed rows here on a timer
via `run_once`, POSTing them to `settings.road_authority_webhook_url` with
exponential backoff up to `forwarding_max_attempts`, after which a row is
marked `dead_letter` and can only be retried manually (`resend`,
SRS 3.9 / `POST /forwarding/{id}/resend`).
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
import httpx

from Backend.app.core.audit import record as record_audit
from Backend.app.core.config import get_settings
from Backend.app.domains.forwarding import queries
from Backend.app.domains.notifications.service import raise_alert


async def enqueue(
    pool: asyncpg.pool.Pool, device_id: str, timestamp: datetime, payload: dict
) -> None:
    await queries.enqueue(pool, device_id, timestamp, payload)


async def list_forwarding(
    pool: asyncpg.pool.Pool, status_filter: str | None, limit: int
) -> list[asyncpg.Record]:
    return await queries.list_forwarding(pool, status_filter, limit)


async def _send(
    client: httpx.AsyncClient, url: str, api_key: str, payload: Any
) -> tuple[int, str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = await client.post(url, json=payload, headers=headers, timeout=15)
    return response.status_code, response.text[:2000]


async def _attempt_row(pool: asyncpg.pool.Pool, row: asyncpg.Record) -> None:
    settings = get_settings()
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    async with httpx.AsyncClient() as client:
        try:
            status_code, body = await _send(
                client,
                settings.road_authority_webhook_url,
                settings.road_authority_api_key,
                payload,
            )
        except httpx.HTTPError as exc:
            status_code, body = 0, str(exc)

    success = 200 <= status_code < 300
    attempt_count = row["attempt_count"] + 1
    new_status = (
        "sent"
        if success
        else (
            "dead_letter"
            if attempt_count >= settings.forwarding_max_attempts
            else "failed"
        )
    )

    await queries.record_attempt_result(
        pool, row["id"], new_status, attempt_count, status_code, body
    )
    await record_audit(
        pool,
        actor="system",
        action="forward",
        entity="forwarding_log",
        entity_id=str(row["id"]),
        details={
            "status": new_status,
            "attempt_count": attempt_count,
            "response_code": status_code,
        },
    )

    if new_status == "dead_letter":
        await raise_alert(
            pool,
            alert_type="forwarding_failed",
            device_id=row["device_id"],
            severity="critical",
            message=(
                f"ارسال داده دستگاه {row['device_id']} به وب‌سرویس راهداری "
                f"پس از {attempt_count} تلاش ناموفق بود"
            ),
        )


def _due_predicate(
    attempt_count: int, last_attempt_at: datetime | None, base_seconds: int
) -> bool:
    if last_attempt_at is None:
        return True
    backoff = base_seconds * (2 ** max(0, attempt_count - 1))
    return datetime.now(timezone.utc) >= last_attempt_at + timedelta(seconds=backoff)


async def run_once(pool: asyncpg.pool.Pool) -> int:
    settings = get_settings()
    rows = await queries.fetch_pending_or_failed(pool, limit=100)

    sent = 0
    for row in rows:
        if not _due_predicate(
            row["attempt_count"],
            row["last_attempt_at"],
            settings.forwarding_backoff_base_seconds,
        ):
            continue
        await _attempt_row(pool, row)
        sent += 1
    return sent


async def resend(pool: asyncpg.pool.Pool, forwarding_id: int, actor: str) -> bool:
    """Manual operator-triggered resend (SRS 3.9), regardless of backoff."""
    row = await queries.get_by_id(pool, forwarding_id)
    if row is None:
        return False

    await queries.mark_pending(pool, forwarding_id)
    row = await queries.get_by_id(pool, forwarding_id)

    await _attempt_row(pool, row)
    await record_audit(
        pool,
        actor=actor,
        action="manual_resend",
        entity="forwarding_log",
        entity_id=str(forwarding_id),
    )
    return True
