"""The filtered SQL behind reporting (SRS 3.7). Reads `traffic_records`
joined with `devices` — reports has no table of its own."""

from datetime import datetime
from typing import Optional

import asyncpg


async def fetch_report_rows(
    pool: asyncpg.pool.Pool,
    device_id: Optional[str],
    location_type: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> list[asyncpg.Record]:
    conditions = ["1 = 1"]
    params: list = []
    if device_id:
        params.append(device_id)
        conditions.append(f"r.device_id = ${len(params)}")
    if location_type:
        params.append(location_type)
        conditions.append(f"d.location_type = ${len(params)}")
    if date_from:
        params.append(date_from)
        conditions.append(f"r.timestamp >= ${len(params)}")
    if date_to:
        params.append(date_to)
        conditions.append(f"r.timestamp <= ${len(params)}")

    query = f"""
        SELECT r.device_id, d.location_type, d.contractor, r.timestamp,
               r.payload, r.is_valid, r.anomaly_flag, r.is_reconstructed
        FROM traffic_records r
        JOIN devices d ON d.device_id = r.device_id
        WHERE {' AND '.join(conditions)}
        ORDER BY r.timestamp DESC
        LIMIT 20000
    """
    async with pool.acquire() as con:
        return await con.fetch(query, *params)
