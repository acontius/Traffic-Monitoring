# Anomaly Detection

## Two independent axes

- **Device health** (`Backend/app/ml/health.py`) — is the *device*
  behaving normally (sending on schedule, varying values, all categories
  live)? Computed on a schedule, not per-message.
- **Value anomaly** (`Backend/app/ml/anomaly.py`) — is this *observation*
  statistically/physically unusual? Computed on every ingested message.

A device can be `HEALTHY` while reporting a genuine, legitimate spike (a
real traffic jam); it can be `SUSPICIOUS` (constant values) while every
individual reading looks unremarkable. Conflating the two would misdiagnose
both cases, so `policy.decide_anomaly` takes both as separate inputs.

## Two speeds

| | Where | Cost | What |
|---|---|---|---|
| `anomaly.quick_score` | Inline in `ingestion/service.py:handle_message` | No model load, no extra DB round trip beyond what the existing z-score check already fetches | Rule violations (category dominance, total collapse, negative count) + robust MAD z-score of the total against recent same-hour history |
| `anomaly.residual_score` (via `domains.ml.service.enrich_and_score`) | `asyncio.create_task`, fire-and-forget from ingestion | Loads the active model per vehicle type, builds features, predicts | Adds a model-prediction residual + (future) isolation-style novelty score on top of everything `quick_score` computes |

Both return an `AnomalyResult(score, anomaly_type, breakdown, rule_violations)`
with `score` always in `[0, 1]` and every contributing signal broken out —
never a bare number.

## Score composition

```
anomaly_score =
    0.35 * rule_penalty           (rule_violations, capped)
  + 0.35 * robust_deviation       (MAD z-score, normalised)
  + 0.20 * prediction_residual    (only when a model is loaded)
  + 0.10 * isolation_score        (reserved; 0 until an isolation-forest is added)
```

Weights are constants at the top of `Backend/app/ml/anomaly.py`, not magic
numbers buried in the formula.

## Multivariate / compositional checks

`anomaly.rule_violations` looks at the *vector* of vehicle counts, not just
the total: `category_dominance:<vehicle>` when one category exceeds 85% of
the total (motorcycles suddenly dominating cars), `total_collapse` when
every category is zero, `traffic_collapse` when the total falls below 10%
of the historical mean. Ratios are computed by
`features.compositional_ratios`, safe against a zero total.

## Calendar/event context

`policy.decide_anomaly` takes `is_special_event` (holiday, Nowruz, or an
active custom `traffic_events` row) as an input: a below-high-threshold
anomaly during a known special day is `IGNORE_ANOMALY` rather than raised,
so a legitimate holiday traffic pattern doesn't spam alerts — but an
*extreme* anomaly still gets through even during a special event.

## Cross-device context

Reserved for reconstruction (Level 4, see RECONSTRUCTION.md) rather than
anomaly scoring in this version — using neighbour devices as anomaly
*evidence* (not just reconstruction evidence) is a documented future
improvement (see "Recommended next ML improvements" in the engineering
report).

## Policy, not the LLM

`Backend/app/ml/policy.py:decide_anomaly` turns `(score, device_health,
is_special_event)` into one of `AUTO_RECONSTRUCT` (n/a here) /
`RECONSTRUCT_AND_ALERT` / `MANUAL_REVIEW` / `IGNORE_ANOMALY` — a plain,
testable decision table. `TCMS_ML_ANOMALY_THRESHOLD` /
`TCMS_ML_HIGH_ANOMALY_THRESHOLD` are the only tunables; nothing here calls
an LLM.
