# AI (OpenRouter) Integration

## Off by default

`TCMS_AI_ENABLED=false` by default. The entire numerical pipeline — device
health, anomaly scoring, reconstruction, confidence, policy — runs without
ever calling `Backend/app/ml/ai_explain.py`. Turning AI on only adds a
narrative explanation alongside a decision already made deterministically.

## What it's for

Per spec, an LLM is never the numerical prediction model. It is only used
to turn already-computed structured evidence into operator-readable text:
likely cause, explanation, severity, and a recommended action
(`Backend/app/ml/schemas.py:Explanation`).

## What gets sent

`Backend/app/ml/schemas.py:AnomalyEvidence` — device id, timestamp,
observed/expected totals, anomaly score, device health, holiday/event
flags, historical mean, neighbour totals. No raw payloads, no credentials,
no IP addresses, no database dumps.

## Safety boundary

The LLM:

- never executes SQL, shell commands, or any tool;
- never writes to the database directly;
- never decides `AUTO_RECONSTRUCT`/`MANUAL_REVIEW`/etc — `policy.py` already
  decided that before `ai_explain.explain` is ever called;
- can only return the four fields in `Explanation`, strictly validated by
  Pydantic (`Explanation.model_validate`) — malformed JSON or an unexpected
  shape is caught and treated as "no explanation available", not passed
  through.

## Failure handling

Disabled, no API key, timeout (`TCMS_AI_TIMEOUT_SECONDS`), non-2xx response,
or malformed JSON — every one of these is caught inside `ai_explain.explain`
and returns `None`. Callers must treat the explanation as optional
enrichment; nothing in the ingestion/anomaly/reconstruction pipeline waits
on it or changes behaviour based on its absence.

## Configuration

```
TCMS_AI_ENABLED=false
TCMS_AI_PROVIDER=openrouter
TCMS_OPENROUTER_API_KEY=
TCMS_OPENROUTER_MODEL=
TCMS_AI_TIMEOUT_SECONDS=20
```

## Where it's wired in

`GET /ml/anomaly-events/{id}/explain` — on demand, per anomaly, not an
always-on side effect of every detection (spec §44 performance: nothing in
the ingestion/scoring path calls out to an LLM). Returns `null` when
disabled/unavailable, never an error.

## Limitations

- Only reachable through that one endpoint today; a future "operator
  assistant" that also answers free-form historical questions (spec §51) is
  a natural next step, using the same `ai_explain`/`Explanation` boundary.
