"""All SQL for the records domain (reads/writes on `traffic_records`)."""

import json
from datetime import datetime
from typing import Optional

import asyncpg


def _parse_payload(row: dict) -> dict:
    row = dict(row)
    if isinstance(row.get("payload"), str):
        row["payload"] = json.loads(row["payload"])
    return row


async def get_latest_all(pool: asyncpg.pool.Pool) -> list[dict]:
    query = """
        SELECT DISTINCT ON (device_id)
            device_id, timestamp, payload, is_valid, anomaly_flag, is_reconstructed
        FROM traffic_records
        ORDER BY device_id, timestamp DESC
    """
    async with pool.acquire() as con:
        rows = await con.fetch(query)
    return [_parse_payload(r) for r in rows]


async def get_history(
    pool: asyncpg.pool.Pool,
    device_id: str,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    limit: int,
) -> list[dict]:
    conditions = ["device_id = $1"]
    params: list = [device_id]
    if date_from:
        params.append(date_from)
        conditions.append(f"timestamp >= ${len(params)}")
    if date_to:
        params.append(date_to)
        conditions.append(f"timestamp <= ${len(params)}")
    params.append(limit)

    query = f"""
        SELECT device_id, timestamp, payload, is_valid, anomaly_flag, is_reconstructed
        FROM traffic_records
        WHERE {' AND '.join(conditions)}
        ORDER BY timestamp DESC
        LIMIT ${len(params)}
    """
    async with pool.acquire() as con:
        rows = await con.fetch(query, *params)
    return [_parse_payload(r) for r in rows]


async def upsert_reconstructed_or_manual(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    payload: dict,
) -> None:
    """Shared write path for both the reconstruction engine and manual
    overrides (SRS 3.4, 3.9): always leaves the row `is_valid = true,
    is_reconstructed = true`. Also used directly by
    `domains.reconstruction.engine` — this table belongs to the records
    domain, same pattern as `notifications` writing to `alerts` via
    `domains.alerts.queries` directly."""
    async with pool.acquire() as con:
        await con.execute(
            """
            INSERT INTO traffic_records
                (device_id, timestamp, payload,
                 is_valid, anomaly_flag, is_reconstructed)
            VALUES ($1, $2, $3, true, false, true)
            ON CONFLICT (device_id, timestamp) DO UPDATE
                SET payload = EXCLUDED.payload,
                    is_valid = true,
                    is_reconstructed = true
            """,
            device_id,
            timestamp,
            json.dumps(payload),
        )


async def upsert_ingested(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    payload: dict,
    anomaly_flag: bool,
    anomaly_reason: Optional[str],
) -> None:
    """Write path for a freshly-ingested device reading (SRS 3.2). Always
    `is_valid = true` (structurally-invalid payloads are rejected before
    reaching this point — see `domains.ingestion.validation`); leaves
    `is_reconstructed` alone. Used directly by `domains.ingestion.service`,
    same shared-table pattern as `upsert_reconstructed_or_manual`."""
    async with pool.acquire() as con:
        await con.execute(
            """
            INSERT INTO traffic_records
                (device_id, timestamp, payload, is_valid, anomaly_flag, anomaly_reason)
            VALUES ($1, $2, $3, true, $4, $5)
            ON CONFLICT (device_id, timestamp) DO UPDATE
                SET payload = EXCLUDED.payload,
                    anomaly_flag = EXCLUDED.anomaly_flag,
                    anomaly_reason = EXCLUDED.anomaly_reason
            """,
            device_id,
            timestamp,
            json.dumps(payload),
            anomaly_flag,
            anomaly_reason,
        )
