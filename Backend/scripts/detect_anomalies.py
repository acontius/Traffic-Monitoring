"""CLI: run the anomaly scoring pass over a device's recent history and
print the results, without writing anything (a dry-run / diagnostic tool —
the real detection path runs inline during ingestion, see
`Backend/app/domains/ml/service.py:enrich_and_score`).

Usage: python -m Backend.scripts.detect_anomalies --device cam-01 --limit 50
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone

from Backend.app.db import pool as db_pool
from Backend.app.domains.ml import queries as ml_queries
from Backend.app.ml import anomaly

logging.basicConfig(level=logging.INFO)


async def main(device_id: str, limit: int) -> None:
    pool = await db_pool.connect()
    try:
        history = await ml_queries.fetch_device_history(
            pool, device_id, before_ts=datetime.now(timezone.utc), limit=limit + 50
        )
        results = []
        for idx, record in enumerate(
            history[-limit:], start=max(0, len(history) - limit)
        ):
            totals = [float(sum(r["counts"].values())) for r in history[:idx]]
            result = anomaly.quick_score(record["counts"], totals)
            results.append(
                {
                    "timestamp": record["timestamp"].isoformat(),
                    "score": result.score,
                    "anomaly_type": result.anomaly_type,
                    "rule_violations": result.rule_violations,
                }
            )
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        await db_pool.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    asyncio.run(main(args.device, args.limit))
