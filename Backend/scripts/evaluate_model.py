"""CLI: print the stored evaluation metrics for the currently active models
(computed at training time by `Backend/app/ml/training.py` — this script
does not re-run training, it just surfaces what's already in `ml_models`).

Usage: python -m Backend.scripts.evaluate_model
"""

import asyncio
import json
import logging

from Backend.app.db import pool as db_pool
from Backend.app.domains.ml import queries as ml_queries

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    pool = await db_pool.connect()
    try:
        models = await ml_queries.list_models(pool)
        active = [m for m in models if m["is_active"]]
        print(json.dumps(active, ensure_ascii=False, indent=2, default=str))
        if not active:
            print(
                "No active models yet — run "
                "`python -m Backend.scripts.train_model` first."
            )
    finally:
        await db_pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
