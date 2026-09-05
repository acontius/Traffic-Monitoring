# Reconstruction

## The existing engine (kept, unchanged)

`Backend/app/domains/reconstruction/engine.py` already finds gaps (silent
devices past their grace period, rows flagged `is_valid = false`) and fills
them with a configurable weighted-average formula
(`compute_reconstructed_counts`, weights from `reconstruction_config`). This
stays exactly as it was — it's now **Level 5** of a hierarchy instead of the
only option.

## The hierarchy (spec: never fabricate a confident number)

For every gap, `engine._reconstruct_one` tries, in order, the first level
that returns a usable estimate:

1. **`try_ml_prediction`** (`Backend/app/ml/reconstruction.py`) — the active
   `HistGradientBoostingRegressor` per vehicle type (see
   `ML_ARCHITECTURE.md`). Confidence scales with how much of the device's own
   lag/rolling history was actually available (`0.5 + 0.45 * coverage`,
   capped at 0.95).
2. **`try_historical_analogue`** — past records matching interval-of-day
   (± the device's own interval) *and* day-class (weekday/weekend/holiday —
   `calendar.day_class_key`), most recent first
   (`features.historical_analogues`). Confidence scales with sample count.
3. **`try_seasonal_profile`** — same device, same hour, any day (looser than
   Level 2 — no day-class match). Lower confidence ceiling (0.7).
4. **`try_neighbor_devices`** — other devices sharing `location_type`, near
   the same timestamp, scaled by the ratio of this device's own historical
   baseline to the neighbours' (so a device that's always quieter than its
   neighbours isn't inflated to match them). Requires ≥2 neighbour devices;
   confidence ceiling 0.55 (this is supporting evidence, not ground truth —
   spec §11).
5. **The existing formula** (`compute_reconstructed_counts`) if none of the
   above had enough evidence. Confidence is derived from the same sample
   counts the formula already logs
   (`policy.formula_fallback_confidence`) — the formula itself has no
   concept of confidence, so one is computed from its own inputs rather than
   invented.
6. **Manual review** — if even the formula produced nothing (`counts` empty)
   or confidence is below `TCMS_ML_REVIEW_CONFIDENCE`: nothing is written as
   a trusted value. The row (if one exists) is marked
   `data_quality_status = 'manual_review'`, a `manual_review_required` alert
   is raised, and the attempt is logged to `reconstruction_log` with
   `review_status = 'pending_review'` and no `counts` — so it stays visible,
   but is never presented as a confident number.

## Confidence-gated policy

`Backend/app/ml/policy.py:decide_reconstruction(confidence, device_health)`:

| Confidence | Device health | Decision |
|---|---|---|
| ≥ `TCMS_ML_MIN_CONFIDENCE` | HEALTHY/RECOVERING | `AUTO_RECONSTRUCT` |
| ≥ `TCMS_ML_MIN_CONFIDENCE` | otherwise | `RECONSTRUCT_AND_ALERT` |
| ≥ `TCMS_ML_REVIEW_CONFIDENCE` | any | `RECONSTRUCT_AND_ALERT` |
| below | any | `MANUAL_REVIEW` |

`AUTO_RECONSTRUCT` writes the value and forwards it exactly like before.
`RECONSTRUCT_AND_ALERT` writes the value (so operators see it) but raises a
`low_reconstruction_confidence` alert and — unless
`TCMS_FORWARD_LOW_CONFIDENCE_RECONSTRUCTIONS=true` — withholds it from the
road-authority forwarding queue until reviewed.

## Auditability

Every attempt is logged to `reconstruction_log` (existing table, extended
with `confidence`, `reconstruction_level`, `model_version`, `evidence`,
`review_status`) — including manual-review attempts, which log with no
`counts` but full evidence of why. The original observation is never lost:
`traffic_records.raw_payload` is set once on first insert and never
overwritten by any reconstruction/manual-override write path.

## Manual override

Unchanged: `POST /records/manual-override` still lets an operator overwrite
any value, logged via the same `reconstruction_log` path
(`method = "manual_override"`, `manual_override = true`).
