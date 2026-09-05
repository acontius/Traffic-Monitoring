"""All SQL for the ML domain: `ml_models`, `ml_predictions`, `anomaly_events`,
`device_health_snapshots`, plus the history reads `Backend/app/ml/*` needs
from `devices`/`traffic_records`/`traffic_events`. Kept in one module per the
existing per-domain `queries.py` convention."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg


def _parse_json_fields(row: dict, *fields: str) -> dict:
    row = dict(row)
    for field in fields:
        if isinstance(row.get(field), str):
            row[field] = json.loads(row[field])
    return row


def _parse_counts(payload: Any) -> dict[str, int]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {k: int(v) for k, v in (payload.get("counts") or {}).items()}


# --- ml_models ---------------------------------------------------------


async def insert_model(
    pool: asyncpg.pool.Pool,
    model_name: str,
    model_version: str,
    model_type: str,
    feature_version: str,
    metrics: dict,
    artifact_path: str,
    checksum: str,
    training_data_range_start: Optional[datetime],
    training_data_range_end: Optional[datetime],
) -> dict:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """
            INSERT INTO ml_models
                (model_name, model_version, model_type, feature_version, metrics,
                 artifact_path, checksum, training_data_range_start,
                 training_data_range_end)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            model_name,
            model_version,
            model_type,
            feature_version,
            json.dumps(metrics),
            artifact_path,
            checksum,
            training_data_range_start,
            training_data_range_end,
        )
    return _parse_json_fields(dict(row), "metrics")


async def set_active_model(
    pool: asyncpg.pool.Pool, model_name: str, model_id: int
) -> None:
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                "UPDATE ml_models SET is_active = false WHERE model_name = $1",
                model_name,
            )
            await con.execute(
                "UPDATE ml_models SET is_active = true WHERE id = $1", model_id
            )


async def get_active_model(pool: asyncpg.pool.Pool, model_name: str) -> Optional[dict]:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT * FROM ml_models WHERE model_name = $1 AND is_active = true",
            model_name,
        )
    return _parse_json_fields(dict(row), "metrics") if row else None


async def list_models(pool: asyncpg.pool.Pool, limit: int = 200) -> list[dict]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT * FROM ml_models ORDER BY trained_at DESC LIMIT $1", limit
        )
    return [_parse_json_fields(dict(r), "metrics") for r in rows]


async def get_model(pool: asyncpg.pool.Pool, model_id: int) -> Optional[dict]:
    async with pool.acquire() as con:
        row = await con.fetchrow("SELECT * FROM ml_models WHERE id = $1", model_id)
    return _parse_json_fields(dict(row), "metrics") if row else None


# --- ml_predictions ------------------------------------------------------


async def insert_prediction(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    vehicle_type: str,
    predicted_value: float,
    interval_low: Optional[float],
    interval_high: Optional[float],
    model_id: Optional[int],
    features_used: dict,
) -> None:
    async with pool.acquire() as con:
        await con.execute(
            """
            INSERT INTO ml_predictions
                (device_id, timestamp, vehicle_type, predicted_value,
                 prediction_interval_low, prediction_interval_high, model_id,
                 features_used)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            device_id,
            timestamp,
            vehicle_type,
            predicted_value,
            interval_low,
            interval_high,
            model_id,
            json.dumps(features_used),
        )


async def list_predictions(
    pool: asyncpg.pool.Pool, device_id: str, limit: int
) -> list[dict]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT * FROM ml_predictions WHERE device_id = $1 "
            "ORDER BY timestamp DESC LIMIT $2",
            device_id,
            limit,
        )
    return [_parse_json_fields(dict(r), "features_used") for r in rows]


# --- anomaly_events ------------------------------------------------------


async def insert_anomaly_event(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    anomaly_type: str,
    severity: str,
    score: float,
    observed: dict,
    expected: Optional[dict],
    evidence: dict,
    model_id: Optional[int] = None,
) -> dict:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """
            INSERT INTO anomaly_events
                (device_id, timestamp, anomaly_type, severity, score, observed,
                 expected, evidence, model_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            device_id,
            timestamp,
            anomaly_type,
            severity,
            score,
            json.dumps(observed),
            json.dumps(expected) if expected is not None else None,
            json.dumps(evidence),
            model_id,
        )
    return _parse_json_fields(dict(row), "observed", "expected", "evidence")


async def list_anomaly_events(
    pool: asyncpg.pool.Pool, device_id: Optional[str], limit: int
) -> list[dict]:
    query = "SELECT * FROM anomaly_events"
    params: list = []
    if device_id:
        params.append(device_id)
        query += " WHERE device_id = $1"
    params.append(limit)
    query += f" ORDER BY timestamp DESC LIMIT ${len(params)}"
    async with pool.acquire() as con:
        rows = await con.fetch(query, *params)
    return [
        _parse_json_fields(dict(r), "observed", "expected", "evidence") for r in rows
    ]


async def set_anomaly_status(
    pool: asyncpg.pool.Pool, anomaly_id: int, status: str, actor: str
) -> Optional[dict]:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """
            UPDATE anomaly_events SET status = $2, resolved_at = now(), resolved_by = $3
            WHERE id = $1 RETURNING *
            """,
            anomaly_id,
            status,
            actor,
        )
    return (
        _parse_json_fields(dict(row), "observed", "expected", "evidence")
        if row
        else None
    )


# --- device_health_snapshots ----------------------------------------------


async def insert_health_snapshot(
    pool: asyncpg.pool.Pool, device_id: str, health_status: str, signals: dict
) -> dict:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """
            INSERT INTO device_health_snapshots (device_id, health_status, signals)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            device_id,
            health_status,
            json.dumps(signals),
        )
    return _parse_json_fields(dict(row), "signals")


async def get_latest_health(pool: asyncpg.pool.Pool, device_id: str) -> Optional[dict]:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT * FROM device_health_snapshots WHERE device_id = $1 "
            "ORDER BY snapshot_at DESC LIMIT 1",
            device_id,
        )
    return _parse_json_fields(dict(row), "signals") if row else None


async def list_devices_for_health_scan(pool: asyncpg.pool.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as con:
        return await con.fetch(
            "SELECT device_id, location_type, expected_interval_seconds FROM devices"
        )


# --- history reads used by Backend/app/ml/* -------------------------------


async def fetch_device_history(
    pool: asyncpg.pool.Pool, device_id: str, before_ts: datetime, limit: int = 500
) -> list[dict]:
    """Ascending, strictly-before `before_ts`, trusted rows only — the exact
    slice `features.py`/`training.py` need to avoid leakage."""
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT timestamp, payload
            FROM traffic_records
            WHERE device_id = $1 AND timestamp < $2 AND is_valid = true
            ORDER BY timestamp DESC
            LIMIT $3
            """,
            device_id,
            before_ts,
            limit,
        )
    result = [
        {"timestamp": r["timestamp"], "counts": _parse_counts(r["payload"])}
        for r in rows
    ]
    result.reverse()
    return result


async def fetch_recent_health_records(
    pool: asyncpg.pool.Pool, device_id: str, limit: int = 50
) -> list[dict]:
    """Includes `created_at` as a stand-in "received_at" for burst/drift
    detection (health.py) — the actual ingest-time write, not the device's
    own claimed timestamp."""
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT timestamp, payload, created_at
            FROM traffic_records
            WHERE device_id = $1
            ORDER BY timestamp DESC
            LIMIT $2
            """,
            device_id,
            limit,
        )
    result = [
        {
            "timestamp": r["timestamp"],
            "counts": _parse_counts(r["payload"]),
            "received_at": r["created_at"],
        }
        for r in rows
    ]
    result.reverse()
    return result


async def fetch_historically_nonzero_keys(
    pool: asyncpg.pool.Pool, device_id: str, lookback_days: int = 14
) -> set[str]:
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT payload FROM traffic_records WHERE device_id = $1 "
            "AND timestamp >= $2 AND is_valid = true LIMIT 500",
            device_id,
            since,
        )
    keys: set[str] = set()
    for r in rows:
        counts = _parse_counts(r["payload"])
        keys.update(k for k, v in counts.items() if v > 0)
    return keys


async def fetch_same_hour_history(
    pool: asyncpg.pool.Pool, device_id: str, hour: int, limit: int = 200
) -> list[dict]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT timestamp, payload FROM traffic_records
            WHERE device_id = $1 AND is_valid = true
              AND EXTRACT(HOUR FROM timestamp) = $2
            ORDER BY timestamp DESC LIMIT $3
            """,
            device_id,
            hour,
            limit,
        )
    return [
        {"timestamp": r["timestamp"], "counts": _parse_counts(r["payload"])}
        for r in rows
    ]


async def fetch_neighbor_recent(
    pool: asyncpg.pool.Pool,
    location_type: str,
    exclude_device_id: str,
    around_ts: datetime,
    tolerance_seconds: int,
) -> list[dict]:
    lo = around_ts - timedelta(seconds=tolerance_seconds)
    hi = around_ts + timedelta(seconds=tolerance_seconds)
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT r.device_id, r.timestamp, r.payload
            FROM traffic_records r
            JOIN devices d ON d.device_id = r.device_id
            WHERE d.location_type = $1 AND r.device_id != $2
              AND r.timestamp BETWEEN $3 AND $4 AND r.is_valid = true
            """,
            location_type,
            exclude_device_id,
            lo,
            hi,
        )
    return [
        {
            "device_id": r["device_id"],
            "timestamp": r["timestamp"],
            "counts": _parse_counts(r["payload"]),
        }
        for r in rows
    ]


async def fetch_device_mean_totals(
    pool: asyncpg.pool.Pool, device_id: str, limit: int = 200
) -> Optional[float]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT payload FROM traffic_records WHERE device_id = $1 "
            "AND is_valid = true ORDER BY timestamp DESC LIMIT $2",
            device_id,
            limit,
        )
    totals = [sum(_parse_counts(r["payload"]).values()) for r in rows]
    return (sum(totals) / len(totals)) if totals else None


async def fetch_active_events(pool: asyncpg.pool.Pool, ts: datetime) -> list[dict]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT * FROM traffic_events WHERE start_at <= $1 AND end_at >= $1", ts
        )
    return [_parse_json_fields(dict(r), "impact_scope") for r in rows]


async def fetch_trusted_records_by_device(
    pool: asyncpg.pool.Pool, include_reconstructed: bool
) -> list[tuple[str, str, int, list[dict]]]:
    """Returns, per device, its ordered trusted history for training
    (spec §20: excludes reconstructed rows unless explicitly opted in)."""
    condition = (
        "is_valid = true"
        if include_reconstructed
        else "is_valid = true AND is_reconstructed = false"
    )
    async with pool.acquire() as con:
        devices = await con.fetch(
            "SELECT device_id, location_type, expected_interval_seconds FROM devices"
        )
        result = []
        for d in devices:
            rows = await con.fetch(
                f"""
                SELECT timestamp, payload FROM traffic_records
                WHERE device_id = $1 AND {condition}
                ORDER BY timestamp ASC
                """,
                d["device_id"],
            )
            records = [
                {"timestamp": r["timestamp"], "counts": _parse_counts(r["payload"])}
                for r in rows
            ]
            result.append(
                (
                    d["device_id"],
                    d["location_type"],
                    d["expected_interval_seconds"],
                    records,
                )
            )
    return result


async def mark_record_quality(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    status: str,
    is_valid: Optional[bool] = None,
) -> None:
    if is_valid is None:
        async with pool.acquire() as con:
            await con.execute(
                "UPDATE traffic_records SET data_quality_status = $3 "
                "WHERE device_id = $1 AND timestamp = $2",
                device_id,
                timestamp,
                status,
            )
    else:
        async with pool.acquire() as con:
            await con.execute(
                "UPDATE traffic_records SET data_quality_status = $3, is_valid = $4 "
                "WHERE device_id = $1 AND timestamp = $2",
                device_id,
                timestamp,
                status,
                is_valid,
            )


async def monitoring_metrics(pool: asyncpg.pool.Pool) -> dict[str, Any]:
    async with pool.acquire() as con:
        anomalies_24h = await con.fetchval(
            "SELECT count(*) FROM anomaly_events "
            "WHERE timestamp >= now() - interval '24 hours'"
        )
        reconstructions_24h = await con.fetchval(
            "SELECT count(*) FROM reconstruction_log "
            "WHERE created_at >= now() - interval '24 hours'"
        )
        auto_reconstructions_24h = await con.fetchval(
            "SELECT count(*) FROM reconstruction_log "
            "WHERE created_at >= now() - interval '24 hours' "
            "AND review_status = 'auto'"
        )
        manual_review_24h = await con.fetchval(
            "SELECT count(*) FROM reconstruction_log "
            "WHERE created_at >= now() - interval '24 hours' "
            "AND review_status = 'pending_review'"
        )
        silent_devices = await con.fetchval(
            "SELECT count(*) FROM devices WHERE status = 'offline'"
        )
        total_devices = await con.fetchval("SELECT count(*) FROM devices")
        quality_breakdown = await con.fetch("""
            SELECT data_quality_status, count(*) AS n FROM traffic_records
            WHERE timestamp >= now() - interval '24 hours'
            GROUP BY data_quality_status
            """)
    return {
        "anomalies_per_24h": anomalies_24h,
        "reconstructions_per_24h": reconstructions_24h,
        "auto_reconstruction_rate": (
            (auto_reconstructions_24h / reconstructions_24h)
            if reconstructions_24h
            else None
        ),
        "manual_review_rate": (
            (manual_review_24h / reconstructions_24h) if reconstructions_24h else None
        ),
        "device_silence_rate": (
            (silent_devices / total_devices) if total_devices else None
        ),
        "trusted_data_coverage": {
            row["data_quality_status"]: row["n"] for row in quality_breakdown
        },
    }
