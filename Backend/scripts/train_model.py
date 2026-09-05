"""CLI: train Model A (expected-traffic regressor) for every vehicle type.

Usage (matches the existing `Backend/scripts/create_admin.py` convention):
    python -m Backend.scripts.train_model
    docker compose exec app python -m Backend.scripts.train_model
"""

import asyncio
import json
import logging

from Backend.app.db import pool as db_pool
from Backend.app.ml import training

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    pool = await db_pool.connect()
    try:
        results = await training.train_all(pool)
        summary = {
            vehicle_type: (
                {
                    "trained": True,
                    "model_version": row["model_version"],
                    "metrics": row["metrics"],
                }
                if row
                else {"trained": False, "reason": "insufficient trusted history"}
            )
            for vehicle_type, row in results.items()
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    finally:
        await db_pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
