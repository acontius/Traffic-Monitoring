# Model Training & Evaluation

## Data source (spec: don't train on reconstructed data by default)

`Backend/app/domains/ml/queries.py:fetch_trusted_records_by_device` reads,
per device, `is_valid = true` rows — and by default also excludes
`is_reconstructed = true` rows, to avoid a feedback loop where the model
learns to reproduce its own (or the formula's) past reconstructions. Set
`TCMS_ML_TRAIN_ON_RECONSTRUCTED=true` to opt into including them (e.g. once
enough real data exists that reconstructed rows are a small minority).

## Splitting (never random)

`Backend/app/ml/training.py:chronological_split` — oldest 70% train / next
15% validation / latest 15% test, always in timestamp order. Every feature
in `features.build_feature_row` is built only from records strictly earlier
than the target timestamp, so no rolling/lag statistic can see the future.

## Training a model

```bash
docker compose exec app python -m Backend.scripts.train_model
```

Trains one `HistGradientBoostingRegressor` per vehicle type
(`Backend/app/ml/prediction.py`), skipping any vehicle type with fewer than
`TCMS_ML_MIN_HISTORY_POINTS` examples (logged, not a hard failure). Each
trained model is versioned and registered via
`Backend/app/ml/registry.py:save_model` — a timestamp-based version, a
SHA-256 checksum of the pickled artifact, the training data's actual
timestamp range, and `feature_version = "v1"` — then activated
(`is_active = true`), never overwriting the previous version's row or
artifact file.

Retraining also happens automatically every
`TCMS_ML_RETRAIN_INTERVAL_HOURS` (default 24) via
`Backend/app/domains/ml/workers.py:run_retrain_forever`, or on demand via
`POST /ml/train` / `POST /ml/retrain`.

## Cold start

A brand-new device has no lag/rolling history — those features come back
`NaN`, which `HistGradientBoostingRegressor` handles natively, so the model
falls back to whatever it learned from location-type + temporal/calendar
features across the whole fleet. As the device accumulates history, its own
lag/rolling features start contributing without any code-path change.

## Evaluation

`Backend/app/ml/evaluation.py`:

- **Prediction**: MAE, RMSE, MAPE (undefined/`None` when a true value is 0),
  SMAPE — computed on the validation and test splits during every training
  run, stored in `ml_models.metrics`. Inspect the currently active models':

  ```bash
  docker compose exec app python -m Backend.scripts.evaluate_model
  ```

- **Anomaly detection**: precision/recall/F1/false-positive-rate
  (`classification_metrics`). **No real labelled anomaly data exists** —
  any such evaluation must be run against simulator-generated synthetic
  anomalies (`TCMS_SIMULATOR_ANOMALY_MODE`) and is always reported with
  `"synthetic": true`. Do not report these numbers as real-world accuracy.
- **Reconstruction**: MAE/RMSE against a known ground truth is only
  meaningful with synthetic data where the "true" value was recorded before
  corruption was simulated.

## Real-data caveat

This repository ships with a small seed fleet (5 devices) and whatever the
simulator has generated. Model quality (the actual MAE/RMSE numbers)
depends entirely on how much real historical data has accumulated — this
document deliberately does not claim a specific accuracy figure. Run
`evaluate_model` after your own deployment has collected meaningful history
and use *those* numbers.
