"""Training pipeline for Model A (spec §19-§22).

Builds a dataset from trusted `traffic_records` (excludes reconstructed rows
by default — `TCMS_ML_TRAIN_ON_RECONSTRUCTED=false` — to avoid the
feedback-loop risk spec §20 calls out), splits it **chronologically** (never
randomly, spec §21 — oldest 70% train / next 15% validation / latest 15%
test), trains one `prediction.Model` per vehicle type, evaluates it, and
registers it via `registry.save_model`.
"""

import logging
from typing import Any, Optional

import asyncpg

from Backend.app.core.config import get_settings
from Backend.app.domains.ml import queries as ml_queries
from Backend.app.ml import VEHICLE_TYPES
from Backend.app.ml.evaluation import regression_metrics
from Backend.app.ml.features import build_feature_row, feature_vector
from Backend.app.ml.prediction import Model
from Backend.app.ml.registry import save_model

logger = logging.getLogger("tcms.ml")


def chronological_split(rows: list[Any]) -> tuple[list[Any], list[Any], list[Any]]:
    """Oldest 70% / next 15% / latest 15% — `rows` must already be sorted
    ascending by timestamp. Never shuffles (spec §21)."""
    n = len(rows)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    return rows[:train_end], rows[train_end:val_end], rows[val_end:]


async def build_training_examples(
    pool: asyncpg.pool.Pool, vehicle_type: str
) -> list[dict]:
    """One example per device: builds a feature row for every record from
    that record's own device-scoped, strictly-earlier history — this is
    where leakage would sneak in if the history slice weren't trimmed per
    record, so it's trimmed explicitly for every row instead of once."""
    settings = get_settings()
    device_rows = await ml_queries.fetch_trusted_records_by_device(
        pool, include_reconstructed=settings.ml_train_on_reconstructed
    )
    examples: list[dict] = []
    for device_id, location_type, expected_interval_seconds, records in device_rows:
        for idx, record in enumerate(records):
            history = records[:idx]
            if not history:
                continue
            row = build_feature_row(
                history,
                record["timestamp"],
                location_type,
                vehicle_type,
                expected_interval_seconds,
            )
            target = float(record["counts"].get(vehicle_type, 0))
            examples.append(
                {"features": row, "target": target, "timestamp": record["timestamp"]}
            )
    examples.sort(key=lambda e: e["timestamp"])
    return examples


async def train_vehicle_type(
    pool: asyncpg.pool.Pool, vehicle_type: str
) -> Optional[dict]:
    settings = get_settings()
    examples = await build_training_examples(pool, vehicle_type)
    if len(examples) < settings.ml_min_history_points:
        logger.info(
            "skipping training for %s: only %d examples (need >= %d)",
            vehicle_type,
            len(examples),
            settings.ml_min_history_points,
        )
        return None

    train, val, test = chronological_split(examples)
    model = Model(vehicle_type)
    X_train = [feature_vector(e["features"]) for e in train]
    y_train = [e["target"] for e in train]
    fit_metrics = model.fit(_impute_nan(X_train), y_train)

    val_metrics = _evaluate_split(model, val)
    test_metrics = _evaluate_split(model, test)

    metrics = {
        "train_examples": len(train),
        "val_examples": len(val),
        "test_examples": len(test),
        "fit": fit_metrics,
        "validation": val_metrics,
        "test": test_metrics,
    }
    training_range = (
        (examples[0]["timestamp"], examples[-1]["timestamp"])
        if examples
        else (None, None)
    )
    return await save_model(pool, model, metrics, training_range)


def _impute_nan(rows: list[list[float]]) -> list[list[float]]:
    # HistGradientBoostingRegressor accepts NaN natively; kept as a no-op
    # hook so a future model type that can't handle NaN has one place to
    # plug an imputer into.
    return rows


def _evaluate_split(model: Model, examples: list[dict]) -> dict[str, float]:
    if not examples:
        return {}
    y_true = [e["target"] for e in examples]
    y_pred = []
    for e in examples:
        row = e["features"]
        pred = model.predict(row)
        y_pred.append(pred.value if pred else 0.0)
    return regression_metrics(y_true, y_pred)


async def train_all(pool: asyncpg.pool.Pool) -> dict[str, Any]:
    results = {}
    for vehicle_type in VEHICLE_TYPES:
        result = await train_vehicle_type(pool, vehicle_type)
        results[vehicle_type] = result
    return results
