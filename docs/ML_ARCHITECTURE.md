# ML Architecture

## Purpose

TCMS's existing pipeline (ingest → structural validation → store → formula
reconstruction → forward) has no way to tell a genuine traffic change from a
device failure, no confidence on a reconstructed value, and no calendar
awareness. This layer adds that on top of the existing architecture — it
does not replace any of it.

## Layers

1. **Rule-based validation** (unchanged) —
   `Backend/app/domains/ingestion/validation.py:validate_structure`. Rejects
   malformed payloads outright, before they ever reach storage.
2. **Device health** — `Backend/app/ml/health.py`. Independent of value
   anomaly detection: `SILENT_DEVICE`, `INTERMITTENT_DEVICE`,
   `CONSTANT_VALUE_DEVICE`, `PARTIAL_FAILURE`, `BURSTING_DEVICE`,
   `TIMESTAMP_DRIFT`, `RATE_MISMATCH` → one of
   `HEALTHY`/`DEGRADED`/`SUSPICIOUS`/`OFFLINE`/`RECOVERING`. Scanned every
   `TCMS_DEVICE_HEALTH_SCAN_INTERVAL_SECONDS` by
   `Backend/app/domains/ml/workers.py:run_health_scan_forever`, written to
   `device_health_snapshots`.
3. **Context-aware anomaly detection** — `Backend/app/ml/anomaly.py` +
   `features.py` + `calendar.py`. See
   [ANOMALY_DETECTION.md](ANOMALY_DETECTION.md).
4. **Hierarchical reconstruction** — `Backend/app/ml/reconstruction.py`. See
   [RECONSTRUCTION.md](RECONSTRUCTION.md).
5. **Confidence + policy engine** — `Backend/app/ml/policy.py`. A pure,
   deterministic decision table; never delegated to the LLM.
6. **Optional AI explanation** — `Backend/app/ml/ai_explain.py`. See
   [AI_INTEGRATION.md](AI_INTEGRATION.md).

## Model choice and why

**`sklearn.ensemble.HistGradientBoostingRegressor`**, one per vehicle
category, trained on pooled data from *all* devices (not one model per
device). Rationale:

- Single extra dependency (`scikit-learn`, which pulls in `numpy`/`scipy`),
  no separate native build like LightGBM/XGBoost need.
- Natively handles `NaN` features — this is what makes cold-start work for
  free: a brand-new device has empty lag/rolling features (all `NaN`) and
  the model falls back to whatever it learned from
  temporal/calendar/location-type features alone, without a separate code
  path.
- Device identity isn't an input feature; a device's own recent behaviour
  (lag/rolling stats) plus its `location_type` carries that signal instead,
  so the feature space doesn't grow with the fleet.

This is a first production baseline (spec: "start with a strong
tabular/time-series baseline, don't blindly choose deep learning"). The
`Model`/`registry` interfaces in `Backend/app/ml/prediction.py` don't leak
the model type, so swapping it later (LightGBM, a per-device model, a
proper quantile-regression interval) doesn't require touching callers.

## Feature list (feature_version "v1")

`hour_sin/cos`, `dow_sin/cos`, `doy_sin/cos`, `is_weekend`, `is_holiday`,
`is_special_event`, `month`, `loc_urban/highway/industrial`,
`lag_1/2/3/12/24` (in units of the device's own `expected_interval_seconds`,
**not** fixed minutes), `rolling_mean/std/median/min/max` (last 12 samples).
See `Backend/app/ml/features.py`.

## Failure behaviour

Every dependency beyond the standard library is imported lazily and
degrades gracefully:

| Missing dependency | Effect |
|---|---|
| `scikit-learn` | `prediction.Model.predict` always returns `None`; reconstruction falls through to historical-analogue/seasonal/neighbour/formula levels; anomaly scoring falls back to the pure-Python MAD/rule-based `quick_score`. |
| `jdatetime` | Persian-calendar fields (`persian_year/month/day`) are `None`; Gregorian-based features (weekday, weekend, month, season) still work. |
| OpenRouter unreachable/disabled | `ai_explain.explain` returns `None`; every decision was already made by `policy.py`, so nothing is blocked. |
| No trained model yet | Reconstruction uses Levels 2-5; anomaly detection uses `quick_score` only. |
| Insufficient history for any level | Level 6: `MANUAL_REVIEW`, nothing is written as a trusted value (spec: never fabricate a confident number). |

An ML-layer exception anywhere is caught and logged
(`Backend/app/domains/ml/service.py:enrich_and_score`) — it never propagates
into the ingestion WebSocket loop.

## Performance

Ingestion stays `INGEST → VALIDATE → STORE → FAST SCORE → EVENT`: the cheap
`anomaly.quick_score` runs inline; the model-backed
`enrich_and_score` (loads models, computes features, scores, may write an
anomaly event/alert) is dispatched via `asyncio.create_task` so it never
blocks the WebSocket loop. Training/retraining runs as a separate scheduled
`asyncio` background loop (`TCMS_ML_RETRAIN_INTERVAL_HOURS`), the same
pattern as the existing reconstruction/forwarding workers — no
Celery/Redis/RabbitMQ introduced.

## Database

New tables (`Database/migrations/0003_ml_layer.sql`): `ml_models`,
`ml_predictions`, `anomaly_events`, `traffic_events`,
`device_health_snapshots`. Extended tables: `traffic_records`
(`raw_payload`, `data_quality_status`), `reconstruction_log` (`confidence`,
`reconstruction_level`, `model_version`, `evidence`, `review_status`),
`forwarding_log` (`data_classification`). No existing column's meaning
changed.

## API

See `Backend/app/domains/ml/router.py` (prefix `/ml`) and
`Backend/app/domains/traffic_events/router.py`. Note: the spec's
`GET /ml/events` is exposed as `GET /ml/anomaly-events` to avoid colliding
with the separate `traffic_events` (custom calendar events) concept.

## Limitations

- No real labelled anomaly/reconstruction ground truth exists yet — every
  anomaly-detection metric is evaluated against simulator-generated
  synthetic anomalies and labelled as such (see MODEL_TRAINING.md).
- No role-based auth exists in TCMS yet, so `POST /ml/train`/`/ml/retrain`
  use the same single authenticated-user dependency as every other domain
  route; restricting them to an admin role is a follow-up once TCMS has
  roles.
- The neighbour-device (Level 4) and cross-device context use
  `location_type` as the only "corridor" grouping available in the current
  schema — a real road-corridor/axis relationship would need a new
  `devices` column or table.
