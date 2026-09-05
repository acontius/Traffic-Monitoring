"""Model artifact storage + versioning (spec §18, §46). Development-grade
local filesystem artifacts (a pickle per trained model) plus a DB row
(`ml_models`) recording version/checksum/metrics/training range/feature
version — never overwritten in place, so rollback is just flipping
`is_active` back to a previous version.
"""

import hashlib
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg

from Backend.app.domains.ml import queries as ml_queries
from Backend.app.ml import FEATURE_VERSION
from Backend.app.ml.prediction import Model

logger = logging.getLogger("tcms.ml")

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_NAME_PREFIX = "expected_traffic"


def _artifact_path(model_name: str, version: str) -> Path:
    return ARTIFACT_DIR / f"{model_name}__{version}.pkl"


def model_name_for(vehicle_type: str) -> str:
    return f"{MODEL_NAME_PREFIX}:{vehicle_type}"


async def save_model(
    pool: asyncpg.pool.Pool,
    model: Model,
    metrics: dict[str, Any],
    training_data_range: tuple[Optional[datetime], Optional[datetime]],
) -> dict:
    model_name = model_name_for(model.vehicle_type)
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = _artifact_path(model_name, version)

    payload = pickle.dumps(model.to_state())
    path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()

    row = await ml_queries.insert_model(
        pool,
        model_name=model_name,
        model_version=version,
        model_type="hist_gradient_boosting",
        feature_version=FEATURE_VERSION,
        metrics=metrics,
        artifact_path=str(path),
        checksum=checksum,
        training_data_range_start=training_data_range[0],
        training_data_range_end=training_data_range[1],
    )
    await ml_queries.set_active_model(pool, model_name, row["id"])
    logger.info(
        "saved model %s version %s (checksum %s)", model_name, version, checksum[:12]
    )
    return row


async def load_active_model(
    pool: asyncpg.pool.Pool, vehicle_type: str
) -> Optional[Model]:
    model_name = model_name_for(vehicle_type)
    row = await ml_queries.get_active_model(pool, model_name)
    if row is None or not row.get("artifact_path"):
        return None
    path = Path(row["artifact_path"])
    if not path.exists():
        logger.warning("model artifact missing on disk: %s", path)
        return None
    try:
        state = pickle.loads(path.read_bytes())
        return Model.from_state(state)
    except Exception:
        logger.exception("failed to load model artifact %s", path)
        return None


async def rollback(pool: asyncpg.pool.Pool, model_name: str, model_id: int) -> None:
    await ml_queries.set_active_model(pool, model_name, model_id)
