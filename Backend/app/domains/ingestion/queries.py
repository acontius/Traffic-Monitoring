"""Reads needed only by the ingestion domain's anomaly detector — a
narrower slice of `traffic_records` than the general-purpose reads in
`domains.records.queries`."""

import json

import asyncpg


async def fetch_recent_payloads_near_hour(
    pool: asyncpg.pool.Pool, device_id: str, hour_lo: int, hour_hi: int, limit: int
) -> list[dict]:
    query = """
        SELECT payload
        FROM traffic_records
        WHERE device_id = $1
          AND is_valid = true
          AND EXTRACT(HOUR FROM timestamp) BETWEEN $2 AND $3
        ORDER BY timestamp DESC
        LIMIT $4
    """
    async with pool.acquire() as con:
        rows = await con.fetch(query, device_id, hour_lo, hour_hi, limit)

    payloads = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        payloads.append(payload)
    return payloads
