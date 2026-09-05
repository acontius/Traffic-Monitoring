"""Hierarchical reconstruction engine (spec §14-§15).

Exposes one `try_*` resolver per level (1-4); each returns `None` if it
can't produce an estimate, so the caller (`domains/reconstruction/engine.py`)
tries them in order and falls back to the *existing* formula-based
`compute_reconstructed_counts` for Level 5, then Level 6 (manual review) if
even that has no data. This module deliberately does **not** import
`domains.reconstruction.engine` — that would be circular, since the engine
is the one calling into here; the engine keeps owning Level 5/6 itself.

Every level returns a `LevelResult` with a confidence in [0, 1] and the
evidence that produced it, so `policy.decide_reconstruction` (and the
audit trail in `reconstruction_log`) never has to trust a bare number.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import asyncpg

from Backend.app.domains.ml import queries as ml_queries
from Backend.app.ml import VEHICLE_TYPES, registry
from Backend.app.ml.features import (
    LAG_INTERVALS,
    average_counts,
    build_feature_row,
    historical_analogues,
)

MIN_ANALOGUE_SAMPLES = 3
MIN_SEASONAL_SAMPLES = 3
MIN_NEIGHBOR_DEVICES = 2


@dataclass
class LevelResult:
    counts: dict[str, int]
    confidence: float
    level: str
    evidence: dict[str, Any] = field(default_factory=dict)
    model_version: Optional[str] = None


def _round_counts(values: dict[str, float]) -> dict[str, int]:
    return {k: max(0, round(v)) for k, v in values.items()}


async def try_ml_prediction(
    pool: asyncpg.pool.Pool,
    device_id: str,
    location_type: str,
    timestamp: datetime,
    expected_interval_seconds: int,
) -> Optional[LevelResult]:
    history = await ml_queries.fetch_device_history(
        pool, device_id, before_ts=timestamp, limit=500
    )
    if len(history) < MIN_ANALOGUE_SAMPLES:
        return None
    events = await ml_queries.fetch_active_events(pool, timestamp)

    counts: dict[str, float] = {}
    coverages: list[float] = []
    per_vehicle_evidence: dict[str, Any] = {}
    model_versions: dict[str, str] = {}

    for vehicle_type in VEHICLE_TYPES:
        row = build_feature_row(
            history,
            timestamp,
            location_type,
            vehicle_type,
            expected_interval_seconds,
            events,
        )
        model = await registry.load_active_model(pool, vehicle_type)
        if model is not None and model.is_trained:
            prediction = model.predict(row)
            if prediction is not None:
                counts[vehicle_type] = prediction.value
                lag_values = [row[f"lag_{n}"] for n in LAG_INTERVALS]
                coverage = sum(1 for v in lag_values if not math.isnan(v)) / len(
                    lag_values
                )
                coverages.append(coverage)
                per_vehicle_evidence[vehicle_type] = {
                    "predicted": prediction.value,
                    "interval": [prediction.interval_low, prediction.interval_high],
                }
                model_row = await ml_queries.get_active_model(
                    pool, registry.model_name_for(vehicle_type)
                )
                if model_row:
                    model_versions[vehicle_type] = model_row["model_version"]
                continue
        rolling_mean = row.get("rolling_mean")
        counts[vehicle_type] = (
            0.0 if rolling_mean is None or math.isnan(rolling_mean) else rolling_mean
        )

    if not per_vehicle_evidence:
        return None  # no trained model contributed anything — not really "Level 1"

    coverage = sum(coverages) / len(coverages) if coverages else 0.0
    confidence = round(min(0.95, 0.5 + 0.45 * coverage), 4)
    return LevelResult(
        counts=_round_counts(counts),
        confidence=confidence,
        level="level1_ml_prediction",
        evidence={"feature_coverage": coverage, "per_vehicle": per_vehicle_evidence},
        model_version=",".join(f"{k}={v}" for k, v in model_versions.items()) or None,
    )


async def try_historical_analogue(
    pool: asyncpg.pool.Pool,
    device_id: str,
    timestamp: datetime,
    expected_interval_seconds: int,
) -> Optional[LevelResult]:
    history = await ml_queries.fetch_device_history(
        pool, device_id, before_ts=timestamp, limit=2000
    )
    matches = historical_analogues(history, timestamp, expected_interval_seconds)
    if len(matches) < MIN_ANALOGUE_SAMPLES:
        return None
    counts = average_counts(matches)
    confidence = round(min(0.85, 0.4 + 0.35 * min(1.0, len(matches) / 20)), 4)
    return LevelResult(
        counts=_round_counts(counts),
        confidence=confidence,
        level="level2_historical_analogue",
        evidence={"samples": len(matches)},
    )


async def try_seasonal_profile(
    pool: asyncpg.pool.Pool, device_id: str, timestamp: datetime
) -> Optional[LevelResult]:
    samples = await ml_queries.fetch_same_hour_history(
        pool, device_id, timestamp.hour, limit=200
    )
    if len(samples) < MIN_SEASONAL_SAMPLES:
        return None
    counts = average_counts(samples)
    confidence = round(min(0.7, 0.3 + 0.3 * min(1.0, len(samples) / 20)), 4)
    return LevelResult(
        counts=_round_counts(counts),
        confidence=confidence,
        level="level3_seasonal_profile",
        evidence={"samples": len(samples)},
    )


async def try_neighbor_devices(
    pool: asyncpg.pool.Pool,
    device_id: str,
    location_type: str,
    timestamp: datetime,
    expected_interval_seconds: int,
) -> Optional[LevelResult]:
    neighbors = await ml_queries.fetch_neighbor_recent(
        pool,
        location_type,
        exclude_device_id=device_id,
        around_ts=timestamp,
        tolerance_seconds=expected_interval_seconds * 2,
    )
    devices_seen = {n["device_id"] for n in neighbors}
    if len(devices_seen) < MIN_NEIGHBOR_DEVICES:
        return None

    own_baseline = await ml_queries.fetch_device_mean_totals(pool, device_id, limit=200)
    neighbor_baseline = 0.0
    neighbor_baseline_samples = 0
    for neighbor_device in devices_seen:
        mean_total = await ml_queries.fetch_device_mean_totals(
            pool, neighbor_device, limit=200
        )
        if mean_total:
            neighbor_baseline += mean_total
            neighbor_baseline_samples += 1
    neighbor_baseline = (
        (neighbor_baseline / neighbor_baseline_samples)
        if neighbor_baseline_samples
        else None
    )

    scale = 1.0
    if own_baseline and neighbor_baseline:
        scale = own_baseline / neighbor_baseline

    counts = average_counts(neighbors)
    scaled_counts = {k: v * scale for k, v in counts.items()}
    confidence = round(min(0.55, 0.2 + 0.3 * min(1.0, len(devices_seen) / 3)), 4)
    return LevelResult(
        counts=_round_counts(scaled_counts),
        confidence=confidence,
        level="level4_neighbor_device",
        evidence={"neighbor_devices": sorted(devices_seen), "scale_factor": scale},
    )
