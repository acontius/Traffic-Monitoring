# Traffic Count Management System — Implementation Report

This report describes the implementation honestly: what exists, what it
actually does, and what its limitations are. It is written to be usable as
the source for a submitted PDF (each section below maps to a heading you
can paste directly into a document).

## 1. Introduction

TCMS ingests per-interval vehicle counts from field cameras over
WebSocket, validates and quality-flags every reading, reconstructs missing
intervals through an auditable confidence-gated hierarchy, forwards
accepted data to an external road-authority system, and exposes a
dashboard, reports, authentication, and a full audit trail.

## 2. Project objective

See [REPORT_1_OBJECTIVE_AND_RELATED_WORK.md](REPORT_1_OBJECTIVE_AND_RELATED_WORK.md).

## 3. Problem statement

See [REPORT_1_OBJECTIVE_AND_RELATED_WORK.md](REPORT_1_OBJECTIVE_AND_RELATED_WORK.md).

## 4. Requirements summary

See [REPORT_2_ANALYSIS_AND_DESIGN.md](REPORT_2_ANALYSIS_AND_DESIGN.md).
**No formal SRS document exists in this repository** — requirements here
are reconstructed from the implemented behaviour, not an external spec.

## 5. System architecture

See [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md). Five Docker Compose
services (`db`, `app`, `mock-external`, `simulator`, `frontend`); the
backend is organised as one folder per bounded context under
`Backend/app/domains/` (auth, devices, ingestion, realtime, records,
alerts, forwarding, reconstruction, ml, reports, traffic_events), plus a
framework-agnostic statistics/ML engine in `Backend/app/ml/`.

## 6. Technologies

FastAPI, `asyncpg`, PyJWT, bcrypt, Pydantic (backend); `scikit-learn`,
`numpy`, `pandas`, `scipy`, `jdatetime` (ML); PostgreSQL 16 + TimescaleDB
(database); Angular + Leaflet (frontend); Docker Compose (infra). Full list
in `requirements.txt` / `Frontend/package.json`.

## 7. Database design

See [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md) for the topology and
[DATA_DICTIONARY.md](DATA_DICTIONARY.md) for the schema. 12 tables across
three migration files; `traffic_records` is a TimescaleDB hypertable
partitioned on `timestamp`.

## 8. Data dictionary

See [DATA_DICTIONARY.md](DATA_DICTIONARY.md) — every table/field/type/key
transcribed directly from `Database/migrations/*.sql`.

## 9. API documentation / Swagger

Live at http://localhost:8000/docs (Swagger UI) and
http://localhost:8000/openapi.json, verified against a running stack: 30
REST paths across 10 tagged groups (auth, devices, records, alerts,
reports, reconstruction, forwarding, ml, traffic-events, plus `/health`).
WebSocket endpoints (`/ws/ingest`, `/ws/live`) aren't representable in
OpenAPI (a spec/tooling limitation) and are documented in prose in the
README and in `domains/ingestion/router.py` / `domains/realtime/router.py`.

## 10. Authentication

JWT access tokens + rotating, hashed opaque refresh tokens
(`Backend/app/core/security.py`); bcrypt password hashing. Devices
authenticate to the ingestion WebSocket separately, via a shared static
token (`TCMS_DEVICE_SHARED_TOKEN`), not JWT. `users.role` exists in the
schema but is not currently used to enforce distinct permission levels —
stated plainly, not glossed over.

## 11. Device ingestion

`Backend/app/domains/ingestion/` — a WebSocket gateway
(`router.py::ws_ingest`) that authenticates the connection, then for every
message: parse JSON → structural validation → device_id match check →
anomaly scoring → persist → alert if needed → enqueue for forwarding →
broadcast live → background ML scoring. Verified to never crash the socket
on malformed input (`test_scenarios.py --scenario invalid-json` /
`invalid-structure`), and to never persist a device_id-mismatched record
(`--scenario wrong-device`, verified against the live API in
`SMOKE_TEST.md`).

## 12. Validation

`Backend/app/domains/ingestion/validation.py::validate_structure` — pure
function, no I/O: rejects missing/invalid `device_id`, unparseable or
out-of-clock-skew-bounds timestamps, missing/negative/non-numeric counts.
7 deterministic unit tests in `tests/test_validation.py`.

## 13. Anomaly detection / ML — honesty section

**There is a genuinely trained ML model, layered over statistical/rule-based
logic.** See the README's "AI/ML/anomaly detection — what this system
actually uses" section for the full breakdown, and
[ML_ARCHITECTURE.md](ML_ARCHITECTURE.md) /
[ANOMALY_DETECTION.md](ANOMALY_DETECTION.md) for the design. In summary:

- Rule-based structural validation (always runs, no statistics).
- Two statistical checks (z-score against recent history; robust MAD-based
  deviation + rule violations) — always run inline, either can flag a
  record on their own.
- A trained `sklearn.ensemble.HistGradientBoostingRegressor` (one per
  vehicle category, pooled across devices) contributing a prediction
  residual to a combined weighted score — degrades to `None` (pure
  statistics take over) if unavailable/untrained/insufficient history.
- A deterministic threshold-based decision policy, not an LLM.
- An optional, disabled-by-default OpenRouter narrative explanation —
  advisory text only, never affects a stored decision.

Anomaly-detection precision/recall/F1 figures produced by
`evaluate_model.py` are computed against the **synthetic simulator**, not
real-world labelled data (explicitly flagged `"synthetic": true" in the
output — see [MODEL_TRAINING.md](MODEL_TRAINING.md)).

## 14. Reconstruction

5-level confidence-gated hierarchy (ML prediction → historical analogue →
seasonal profile → neighbour devices → weighted-formula), a deterministic
policy layer (`AUTO_RECONSTRUCT` / `RECONSTRUCT_AND_ALERT` /
`MANUAL_REVIEW`), full logging of every attempt, raw-payload preservation,
and a manual override endpoint. See [RECONSTRUCTION.md](RECONSTRUCTION.md).
Verified end to end: `POST /records/manual-override` was exercised against
a live stack and produced a `reconstruction_log` row with
`method="manual_override"`.

## 15. Alerts

Raised from ingestion, device-health scanning, reconstruction, and
forwarding; persisted, pushed live over `/ws/live`, and SMS-delivered only
for `severity="critical"`. Verified live: spike/drop/negative/invalid
scenarios all produced real alert rows retrievable via `GET /alerts`.

## 16. Forwarding

A durable outbox (`forwarding_log`) drained by a background worker with
exponential backoff up to `TCMS_FORWARDING_MAX_ATTEMPTS`, after which a row
is marked `dead_letter` and raises a critical alert; `POST
/forwarding/{id}/resend` for manual retry. Verified live: normal ingestion
produced a `pending`→ (worker-processed) row forwarded to
`mock-external`'s `/mock-road-authority`, confirmed in `app` container
logs (`HTTP Request: POST http://mock-external:9100/mock-road-authority
"HTTP/1.1 200 OK"`).

## 17. Reporting

`GET /reports?format=json|csv`, filterable by device/location/date range;
CSV streams as a file download. Exposed in the frontend's Reports page.

## 18. Frontend

Angular app: Login (JWT storage + auto-refresh interceptor), Dashboard
(live map + status list over `/ws/live`), Device detail (history,
reconstructions, ML health/anomalies), Alerts (list + acknowledge), Reports
(filter + CSV export), Manual Control (override form, traffic events,
failed-forwarding resend). All pages call real backend endpoints — no mock
data in the UI layer.

## 19. Testing

`pytest` — 83 deterministic unit tests (see below for the full breakdown),
no live DB/socket/wall-clock/random dependency; every DB or model
dependency is monkeypatched with an in-memory fake, matching the existing
project convention.

| File | What it covers |
| --- | --- |
| `test_validation.py` | Structural validation (7 tests) |
| `test_reconstruction.py` | Formula averaging + forwarding backoff timing (7) |
| `test_ml_anomaly.py` | Robust z-score, rule violations, quick/residual scoring (9) |
| `test_ml_calendar.py` | Timezone/Persian calendar/weekend/event window (6) |
| `test_ml_features.py` | Feature engineering, no-future-leakage (7) |
| `test_ml_health.py` | Device health detectors + aggregation (12) |
| `test_ml_policy.py` | Reconstruction/anomaly decision table (9) |
| `test_ml_registry.py` | Model save/load/rollback (3) |
| `test_ml_training_leakage.py` | Chronological train/val/test split (3) |
| `test_ml_reconstruction.py` | Hierarchical reconstruction levels (8) |
| `test_ingestion.py` *(new)* | Invalid JSON, invalid structure, wrong device_id, negative counts at the ingestion-service level (4) |
| `test_manual_override.py` *(new)* | Manual override → reconstruction_log + audit_log + forwarding (1) |
| `test_audit.py` *(new)* | `core.audit.record` row shape (2) |
| `test_alerts.py` *(new)* | `raise_alert` persistence/broadcast/SMS-on-critical-only (2) |
| `test_forwarding.py` *(new)* | `enqueue` data_classification passthrough, `run_once` send/dead-letter (3) |

## 20. Controlled test scenarios

`Backend/Devices/test_scenarios.py` (one-shot CLI) and
`Backend/Devices/demo.py` (end-to-end runner) — see README "Controlled
testing" / "Demo" and [SMOKE_TEST.md](../SMOKE_TEST.md) for every scenario
and its actually-observed outcome, verified against a live stack.

## 21. Sequence diagrams

See [SEQUENCE_DIAGRAMS.md](SEQUENCE_DIAGRAMS.md).

## 22. Use case diagram

See [USE_CASE_DIAGRAM.md](USE_CASE_DIAGRAM.md).

## 23. Screenshots

None are fabricated here. See [SCREENSHOT_GUIDE.md](../SCREENSHOT_GUIDE.md)
for exactly which 8 (or 10) screenshots to capture from a live stack and
where to save them.

## 24. Deployment with Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Verified live: all 5 services (`db`, `app`, `mock-external`, `simulator`,
`frontend`) reach `Up` with no manual database setup — migrations apply
automatically on first `db` boot via the mounted
`Database/migrations/` → `/docker-entrypoint-initdb.d`.

## 25. Limitations

See README "Limitations" — no role-based authorization enforcement yet,
synthetic-only anomaly evaluation metrics, `location_type`-only neighbour
grouping, pinned ML dependencies, no formal SRS in-repo, no frontend test
coverage.

## 26. Future improvements

See README "Future work" — role-based authorization, real labelled anomaly
data, frontend test coverage, a real road-corridor topology for
reconstruction.

## 27. Conclusion

TCMS implements a complete ingest → validate → detect → reconstruct →
alert → forward → report pipeline with a hybrid statistical/ML anomaly
layer, honestly documented rather than oversold, full audit logging, JWT
authentication, and a working Angular dashboard — all runnable from a clean
checkout with a single `docker compose up -d --build` and verifiable with
`pytest` plus the controlled test scenarios in this report.
