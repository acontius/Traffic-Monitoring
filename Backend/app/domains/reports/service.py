"""JSON/CSV report assembly (SRS 3.7)."""

import csv
import io
import json
from datetime import datetime
from typing import Optional

import asyncpg

from Backend.app.domains.reports import queries


async def get_json(
    pool: asyncpg.pool.Pool,
    device_id: Optional[str],
    location_type: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> list[dict]:
    rows = await queries.fetch_report_rows(
        pool, device_id, location_type, date_from, date_to
    )
    result = []
    for r in rows:
        item = dict(r)
        if isinstance(item["payload"], str):
            item["payload"] = json.loads(item["payload"])
        result.append(item)
    return result


async def get_csv(
    pool: asyncpg.pool.Pool,
    device_id: Optional[str],
    location_type: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> str:
    rows = await queries.fetch_report_rows(
        pool, device_id, location_type, date_from, date_to
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "device_id",
            "location_type",
            "contractor",
            "timestamp",
            "counts",
            "is_valid",
            "anomaly_flag",
            "is_reconstructed",
        ]
    )
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        writer.writerow(
            [
                r["device_id"],
                r["location_type"],
                r["contractor"] or "",
                r["timestamp"].isoformat(),
                json.dumps(payload.get("counts", {}), ensure_ascii=False),
                r["is_valid"],
                r["anomaly_flag"],
                r["is_reconstructed"],
            ]
        )
    buffer.seek(0)
    return buffer.getvalue()
