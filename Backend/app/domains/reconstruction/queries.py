"""All SQL for the reconstruction domain: `reconstruction_config`,
`reconstruction_log`, plus the historical-payload/gap-detection reads the
engine needs from `devices`/`traffic_records`."""

import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg


def _parse_json_fields(row: dict, *fields: str) -> dict:
    row = dict(row)
    for field in fields:
        if isinstance(row.get(field), str):
            row[field] = json.loads(row[field])
    return row


# --- reconstruction_config -------------------------------------------------


async def list_config(pool: asyncpg.pool.Pool) -> list[dict]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT * FROM reconstruction_config ORDER BY scope_type, scope_value"
        )
    return [_parse_json_fields(dict(r), "weights") for r in rows]


async def upsert_config(
    pool: asyncpg.pool.Pool,
    scope_type: str,
    scope_value: Optional[str],
    weights: dict,
    updated_by: str,
) -> dict:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """
            INSERT INTO reconstruction_config
                (scope_type, scope_value, weights, updated_by)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (scope_type, scope_value) DO UPDATE
                SET weights = EXCLUDED.weights,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
            RETURNING *
            """,
            scope_type,
            scope_value,
            json.dumps(weights),
            updated_by,
        )
    return _parse_json_fields(dict(row), "weights")


async def fetch_weights_for_device(
    pool: asyncpg.pool.Pool, device_id: str
) -> Optional[dict]:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT weights FROM reconstruction_config "
            "WHERE scope_type = 'device' AND scope_value = $1",
            device_id,
        )
    return _json(row)


async def fetch_weights_for_location_type(
    pool: asyncpg.pool.Pool, location_type: str
) -> Optional[dict]:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT weights FROM reconstruction_config "
            "WHERE scope_type = 'location_type' AND scope_value = $1",
            location_type,
        )
    return _json(row)


async def fetch_default_weights(pool: asyncpg.pool.Pool) -> Optional[dict]:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT weights FROM reconstruction_config WHERE scope_type = 'default'"
        )
    return _json(row)


def _json(row: asyncpg.Record | None) -> Optional[dict]:
    if row is None:
        return None
    weights = row["weights"]
    return json.loads(weights) if isinstance(weights, str) else weights


# --- reconstruction_log -----------------------------------------------------


async def list_log(
    pool: asyncpg.pool.Pool, device_id: Optional[str], limit: int
) -> list[dict]:
    query = "SELECT * FROM reconstruction_log"
    params: list = []
    if device_id:
        params.append(device_id)
        query += " WHERE device_id = $1"
    params.append(limit)
    query += f" ORDER BY created_at DESC LIMIT ${len(params)}"

    async with pool.acquire() as con:
        rows = await con.fetch(query, *params)
    return [_parse_json_fields(dict(r), "formula_snapshot", "inputs") for r in rows]


async def insert_log_entry(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    method: str,
    formula_snapshot: dict,
    inputs: dict,
    manual_override: bool = False,
    created_by: Optional[str] = None,
) -> None:
    async with pool.acquire() as con:
        await con.execute(
            """
            INSERT INTO reconstruction_log
                (device_id, timestamp, method, formula_snapshot,
                 inputs, manual_override, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            device_id,
            timestamp,
            method,
            json.dumps(formula_snapshot),
            json.dumps(inputs),
            manual_override,
            created_by,
        )


# --- gap detection (reads devices + traffic_records) ------------------------


async def find_silent_devices(
    pool: asyncpg.pool.Pool, grace_periods: int
) -> list[asyncpg.Record]:
    now = datetime.now(timezone.utc)
    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT d.device_id, d.location_type, d.expected_interval_seconds,
                   COALESCE(MAX(t.timestamp), d.created_at) AS last_ts
            FROM devices d
            LEFT JOIN traffic_records t
                ON t.device_id = d.device_id AND t.is_valid = true
            GROUP BY d.device_id, d.location_type,
                     d.expected_interval_seconds, d.created_at
            HAVING $1 - COALESCE(MAX(t.timestamp), d.created_at)
                   > (d.expected_interval_seconds * (1 + $2)) * interval '1 second'
            """,
            now,
            grace_periods,
        )


async def find_corrupt_records(pool: asyncpg.pool.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as con:
        return await con.fetch("""
            SELECT r.device_id, r.timestamp, d.location_type
            FROM traffic_records r
            JOIN devices d ON d.device_id = r.device_id
            WHERE r.is_valid = false AND r.is_reconstructed = false
            ORDER BY r.timestamp
            LIMIT 500
            """)


# --- historical samples used by the weighted-average formula ----------------


def _extract_counts(rows: list[asyncpg.Record]) -> list[dict[str, int]]:
    result = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        counts = payload.get("counts")
        if counts:
            result.append({k: int(v) for k, v in counts.items()})
    return result


async def fetch_counts_same_hour(
    pool: asyncpg.pool.Pool, device_id: str, since: datetime, hour: int
) -> list[dict[str, int]]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT payload FROM traffic_records
            WHERE device_id = $1 AND is_valid = true
              AND timestamp >= $2 AND EXTRACT(HOUR FROM timestamp) = $3
            ORDER BY timestamp DESC
            LIMIT 200
            """,
            device_id,
            since,
            hour,
        )
    return _extract_counts(rows)


async def fetch_counts_same_weekday_hour(
    pool: asyncpg.pool.Pool, device_id: str, since: datetime, hour: int, weekday: int
) -> list[dict[str, int]]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT payload FROM traffic_records
            WHERE device_id = $1 AND is_valid = true
              AND timestamp >= $2 AND EXTRACT(HOUR FROM timestamp) = $3
              AND EXTRACT(DOW FROM timestamp) = $4
            ORDER BY timestamp DESC
            LIMIT 200
            """,
            device_id,
            since,
            hour,
            weekday,
        )
    return _extract_counts(rows)


async def fetch_recent_counts(
    pool: asyncpg.pool.Pool, device_id: str, limit: int
) -> list[dict[str, int]]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT payload FROM traffic_records
            WHERE device_id = $1 AND is_valid = true
            ORDER BY timestamp DESC
            LIMIT $2
            """,
            device_id,
            limit,
        )
    return _extract_counts(rows)
