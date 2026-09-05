# TCMS — Traffic Count Management System

A hub that ingests per-interval vehicle counts from field cameras over
WebSocket, validates them, detects anomalies (statistical + a trained ML
model), reconstructs missing/corrupt intervals through a confidence-gated
hierarchy, forwards accepted data to a road-authority web service with
retry, raises live alerts, and exposes a dashboard, CSV reporting, JWT
authentication, and audit logging.

**A note on requirements**: no formal SRS document exists in this
repository. The code contains scattered `# SRS x.y` comments citing section
numbers of a requirements document that isn't checked in anywhere in this
history — this README and the docs below describe what is actually
implemented, not a claimed one-to-one mapping to an external spec.

## Problem statement

Municipal/road-authority traffic counting relies on field cameras that
periodically report vehicle counts by category. Left unmanaged, this raises
several concrete problems: devices go silent or send corrupted data with no
automatic detection; obviously wrong readings (spikes, drops, negative
counts) get mixed in with real data; gaps in the time series break any
downstream reporting; and there's no audit trail for who changed what. TCMS
addresses each of these directly: structural validation at the point of
ingestion, statistical + ML-based anomaly detection, an audited
reconstruction pipeline for gaps, and a full audit log for every
system/operator action.

## Objectives

- Accept and validate high-frequency device readings over WebSocket without
  ever crashing the ingestion loop on bad input.
- Detect anomalous readings and missing intervals automatically, using
  transparent statistical rules plus an optional trained model — never an
  unexplainable black box.
- Reconstruct missing data with a documented, confidence-gated method
  (never fabricate a value silently) and let an operator override any
  reconstructed value by hand.
- Forward validated/reconstructed data to an external system with durable
  retry.
- Give an operator a dashboard, alerts, and CSV reports without needing
  direct database access.

## Architecture

- **Backend** (`Backend/app`): FastAPI. WebSocket ingestion gateway
  (`domains/ingestion`), live dashboard/alert push (`domains/realtime`),
  structural validation + statistical anomaly detection, a hierarchical
  reconstruction engine, a forwarding outbox with retry/backoff,
  notifications (in-app + SMS), JWT auth, audit logging, CSV/JSON
  reporting. See [docs/ARCHITECTURE_DIAGRAM.md](docs/ARCHITECTURE_DIAGRAM.md).
- **ML layer** (`Backend/app/ml`, `Backend/app/domains/ml`,
  `Backend/app/domains/traffic_events`): device health, statistical + ML
  anomaly scoring, hierarchical confidence-gated reconstruction, calendar
  context, and an optional OpenRouter explanation step. See
  **[docs/ML_ARCHITECTURE.md](docs/ML_ARCHITECTURE.md)** and the honest
  "AI/ML reality" section below.
- **Database** (`Database/migrations`): Postgres + TimescaleDB. Migrations
  `0001_init.sql`, `0002_seed.sql`, `0003_ml_layer.sql` are applied
  automatically on first container boot (mounted as
  `/docker-entrypoint-initdb.d`) — no manual setup needed. See
  [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).
- **Frontend** (`Frontend/`): Angular app — login, dashboard/map, device
  detail, alerts, reports, manual control (override + traffic events +
  forwarding resend).
- **Device simulator** (`Backend/Devices/cameras.py`): generates realistic
  traffic counts and pushes them into the hub's ingestion WebSocket
  continuously; supports controllable anomaly scenarios
  (`TCMS_SIMULATOR_ANOMALY_MODE`) for exercising the ML layer end to end.
- **Controlled test CLI** (`Backend/Devices/test_scenarios.py`) and
  **demo runner** (`Backend/Devices/demo.py`): one-shot, scriptable
  scenarios for a live demo/report — see "Controlled testing" and "Demo"
  below.
- **Mock external services** (`Backend/mock_external/server.py`): stands in
  for the road-authority webhook and SMS gateway during dev/test.

```
Traffic Cameras (or the simulator) ──WebSocket──▶ FastAPI Backend
                                                     │  validation
                                                     │  anomaly/ML scoring
                                                     │  reconstruction
                                                     │  alerts
                                                     │  forwarding
                                                     │  auth / reporting
                                                     ▼
                                          PostgreSQL + TimescaleDB
Angular Frontend ──REST + WebSocket──────────────────┘
Backend ──HTTP──▶ Mock external (road authority + SMS gateway)
```

Full diagram: [docs/ARCHITECTURE_DIAGRAM.md](docs/ARCHITECTURE_DIAGRAM.md).

## Technologies

- **Backend**: Python 3.14, FastAPI, uvicorn, `asyncpg`, PyJWT, bcrypt,
  Pydantic/`pydantic-settings`.
- **ML**: `scikit-learn` (`HistGradientBoostingRegressor`), `numpy`,
  `pandas`, `scipy`, `jdatetime` (Persian calendar).
- **Database**: PostgreSQL 16 + TimescaleDB (hypertable on
  `traffic_records`).
- **Frontend**: Angular, Leaflet (map), nginx (production serving).
- **Infra**: Docker Compose (5 services: `db`, `app`, `mock-external`,
  `simulator`, `frontend`) — no Redis/Celery/Kubernetes; none of the
  pipeline needs them at this scale.

## Installation / Docker setup

```bash
git clone <this repo>
cd Traffic-Monitoring
cp .env.example .env       # adjust secrets/URLs if needed — defaults work out of the box
docker compose up -d --build
docker compose ps
```

Expected services, all `Up`:

```
tcms-app             app
tcms-db              db
tcms-frontend         frontend
tcms-mock-external   mock-external
tcms-simulator       simulator
```

No manual database setup is required — the `db` service mounts
`Database/migrations` as `/docker-entrypoint-initdb.d` and Postgres runs
every `*.sql` file there in filename order on first boot.

Create the first admin user once the DB is up:

```bash
docker compose exec app python -m Backend.scripts.create_admin \
  --username admin --password <secret>
```

Open http://localhost:4200 and log in. Swagger UI is at
http://localhost:8000/docs.

For a full guided manual walkthrough (login, watching devices report in,
reading alerts/reports/reconstructions, registering a new device), see
**[SMOKE_TEST.md](SMOKE_TEST.md)**.

### Running without Docker

```bash
pip install -r requirements.txt
uvicorn Backend.app.main:app --reload

# separate terminals:
uvicorn Backend.mock_external.server:app --port 9100
python -m Backend.Devices.cameras

cd Frontend && npm install && npm start
```

## Environment variables

Full reference: [.env.example](.env.example) (every variable is commented
inline). Grouped summary:

| Group | Key variables | Purpose |
| --- | --- | --- |
| Database | `TCMS_DB_DSN` | Postgres connection string |
| Auth | `TCMS_JWT_SECRET`, `TCMS_ACCESS_TOKEN_EXPIRES_MINUTES`, `TCMS_REFRESH_TOKEN_EXPIRES_DAYS`, `TCMS_CORS_ORIGINS` | JWT signing + token lifetimes + CORS |
| Ingestion | `TCMS_DEVICE_SHARED_TOKEN` | Shared token every device authenticates with on `/ws/ingest` |
| Reconstruction | `TCMS_RECONSTRUCTION_SCAN_INTERVAL_SECONDS`, `TCMS_RECONSTRUCTION_GRACE_PERIODS` | Background worker cadence + missed-interval tolerance |
| Forwarding | `TCMS_ROAD_AUTHORITY_WEBHOOK_URL`, `TCMS_ROAD_AUTHORITY_API_KEY`, `TCMS_FORWARDING_WORKER_INTERVAL_SECONDS`, `TCMS_FORWARDING_MAX_ATTEMPTS`, `TCMS_FORWARDING_BACKOFF_BASE_SECONDS` | Outbox retry/backoff to the external webhook |
| Notifications | `TCMS_SMS_GATEWAY_URL`, `TCMS_SMS_GATEWAY_API_KEY`, `TCMS_SMS_RECIPIENTS` | Critical-alert SMS delivery |
| Reporting | `TCMS_REPORT_DEFAULT_PAGE_SIZE` | Default report page size |
| Simulator | `TCMS_HUB_WS_URL`, `TCMS_DEVICE_TOKEN`, `TCMS_SIMULATOR_INTERVAL_SECONDS`, `TCMS_SIMULATOR_ANOMALY_MODE`, `TCMS_SIMULATOR_DEVICE_SCENARIOS` | Continuous device simulator + controlled scenarios |
| Bootstrap | `TCMS_ADMIN_USERNAME`, `TCMS_ADMIN_PASSWORD` | `create_admin` script |
| ML layer | `TCMS_TRAFFIC_TIMEZONE`, `TCMS_ML_ENABLED`, `TCMS_ML_MODEL_TYPE`, `TCMS_ML_RETRAIN_INTERVAL_HOURS`, `TCMS_ML_MIN_HISTORY_POINTS`, `TCMS_ML_MIN_CONFIDENCE`, `TCMS_ML_REVIEW_CONFIDENCE`, `TCMS_ML_ANOMALY_THRESHOLD`, `TCMS_ML_HIGH_ANOMALY_THRESHOLD`, `TCMS_ML_ENABLE_CROSS_DEVICE_CONTEXT`, `TCMS_ML_ENABLE_EVENT_CONTEXT`, `TCMS_ML_TRAIN_ON_RECONSTRUCTED`, `TCMS_DEVICE_HEALTH_SCAN_INTERVAL_SECONDS`, `TCMS_FORWARD_LOW_CONFIDENCE_RECONSTRUCTIONS` | See [docs/ML_ARCHITECTURE.md](docs/ML_ARCHITECTURE.md) |
| Optional AI explanation | `TCMS_AI_ENABLED`, `TCMS_AI_PROVIDER`, `TCMS_OPENROUTER_API_KEY`, `TCMS_OPENROUTER_MODEL`, `TCMS_AI_TIMEOUT_SECONDS` | Narrative-only, disabled by default |

## Database

PostgreSQL 16 + the TimescaleDB extension; `traffic_records` is a
hypertable partitioned on `timestamp`. Schema is defined entirely by the
three migration files in `Database/migrations/`, applied in order on first
container boot. Full table-by-table reference:
**[docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)**.

## Authentication

JWT-based (`Backend/app/core/security.py`): bcrypt password hashing,
short-lived access tokens + longer-lived opaque refresh tokens (hashed
before storage, rotated on every refresh, revocable on logout). Every
protected REST endpoint depends on a bearer token; the device WebSocket
gateway (`/ws/ingest`) uses a **separate** mechanism — a shared static
token (`TCMS_DEVICE_SHARED_TOKEN`), not JWT, since devices aren't users.

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<secret>"}'
# → {"access_token": "...", "refresh_token": "...", "token_type": "bearer"}
```

**Note**: the `users` table has a `role` column but the codebase does not
currently enforce distinct Administrator/Operator permission levels — every
authenticated user has the same access. See Limitations.

## Device simulator

`Backend/Devices/cameras.py` connects to `/ws/ingest` as a WebSocket client
and pushes a realistic reading every `TCMS_SIMULATOR_INTERVAL_SECONDS` for
each of 5 seeded devices (`cam-01`..`cam-05`). It supports 11 controllable
corruption modes via `TCMS_SIMULATOR_ANOMALY_MODE` (or per-device via
`TCMS_SIMULATOR_DEVICE_SCENARIOS`, a JSON map): `missing_data, zero_data,
spike, drop, constant_value, category_corruption, timestamp_drift, burst,
holiday_pattern, event_pattern, gradual_drift` — see the `ScenarioController`
docstring in that file.

## Controlled testing

For a single deliberate scenario without editing any code, use
`Backend/Devices/test_scenarios.py` — a one-shot CLI that connects once and
sends exactly one deliberately-shaped message, then reports what actually
happened:

```bash
docker compose exec simulator python -m Backend.Devices.test_scenarios --list
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario normal
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario missing
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario invalid-json
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario invalid-structure
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario wrong-device
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario spike
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario drop
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario negative
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario timestamp --variant future
```

Every scenario was run against a live stack while writing this doc; see
[SMOKE_TEST.md](SMOKE_TEST.md) for the exact API calls used to verify each
outcome (alert raised, record rejected/stored, anomaly flagged, etc).

## AI/ML/anomaly detection — what this system actually uses

**There is a genuinely trained ML model, layered over statistical/rule-based
logic — not a marketing label, and not "just heuristics" either.**

- **Rule-based validation** (`Backend/app/domains/ingestion/validation.py`):
  structural checks (types, required fields, negative counts, clock-skew
  bounds) — deterministic, no statistics involved. Runs on every message.
- **Statistical anomaly detection**: a z-score check against the device's
  own recent history (`ingestion/validation.py`) plus a robust
  MAD-z-score + rule-violation check (`Backend/app/ml/anomaly.py`,
  `quick_score`) — both run inline during ingestion as independent
  "opinions"; either can flag a record.
- **Trained ML model**: `sklearn.ensemble.HistGradientBoostingRegressor`,
  one model per vehicle category, pooled across all devices
  (`Backend/app/ml/prediction.py`). Trained via
  `python -m Backend.scripts.train_model` on strictly-earlier data only
  (chronological 70/15/15 split, never shuffled —
  `Backend/app/ml/training.py`). Its prediction residual feeds into a
  combined anomaly score (`Backend/app/ml/anomaly.py::residual_score`):
  `0.35·rule_penalty + 0.35·robust_deviation + 0.20·prediction_residual +
  0.10·isolation_score` (the isolation term is reserved, currently 0).
- **Graceful degradation**: if `scikit-learn` isn't installed, no model has
  been trained yet, or history is too short, the model prediction is `None`
  and the system falls back to pure statistics/rules automatically — it
  never fails to start and never fabricates a model-backed number it
  doesn't have.
- **Decision layer** (`Backend/app/ml/policy.py`) is a deterministic
  threshold table (`AUTO_RECONSTRUCT` / `RECONSTRUCT_AND_ALERT` /
  `MANUAL_REVIEW` / `IGNORE_ANOMALY`) — an LLM never makes this decision.
- **Optional LLM narrative** (`Backend/app/ml/ai_explain.py`,
  `TCMS_AI_ENABLED=false` by default): OpenRouter turns already-computed
  evidence into human-readable text for `GET
  /ml/anomaly-events/{id}/explain`. It never sees raw data beyond that
  evidence, never executes anything, and any failure silently returns
  `null` — it is advisory only and never affects a stored decision.

Details: [docs/ML_ARCHITECTURE.md](docs/ML_ARCHITECTURE.md),
[docs/ANOMALY_DETECTION.md](docs/ANOMALY_DETECTION.md),
[docs/AI_INTEGRATION.md](docs/AI_INTEGRATION.md).

**Known limitation**: `numpy`/`pandas`/`scikit-learn`/`jdatetime` are pinned
in `requirements.txt`; the anomaly-detection evaluation metrics
(precision/recall/F1) reported by `evaluate_model.py` are computed against
the **synthetic simulator**, not real-world labelled data — see
docs/MODEL_TRAINING.md, which explicitly flags them `"synthetic": true`.

## Reconstruction

A 5-level confidence-gated hierarchy (`Backend/app/ml/reconstruction.py`,
`Backend/app/domains/reconstruction/engine.py`): ML prediction → historical
analogue → seasonal profile → neighbour devices → the original
weighted-formula engine, each level either returns a confidence-scored
estimate or `None` (never fabricates a confident number it doesn't have).
The confidence + device-health state then feeds `policy.decide_reconstruction`
to choose `AUTO_RECONSTRUCT`, `RECONSTRUCT_AND_ALERT`, or `MANUAL_REVIEW`.
Every attempt — including manual-review outcomes with no counts — is logged
to `reconstruction_log`, and the original raw payload is never overwritten.

**Manual override**: `POST /records/manual-override` lets an operator
overwrite any value by hand; it writes to the same `reconstruction_log`
audit trail (`method="manual_override"`), a generic `audit_log` entry, and
re-queues the corrected value for forwarding. Exposed in the frontend's
Manual Control page. Details: [docs/RECONSTRUCTION.md](docs/RECONSTRUCTION.md).

## Alerts

Raised by ingestion (invalid payload, statistical anomaly), device-health
scanning, reconstruction (data gap, manual review required, low-confidence
reconstruction), and forwarding (dead-letter). Persisted to `alerts`,
pushed live over `/ws/live`, and — for `severity="critical"` only — sent
via SMS (mocked in dev). `GET /alerts`, `POST /alerts/{id}/acknowledge`.

## Forwarding

Every accepted/reconstructed/overridden reading is queued in
`forwarding_log` and drained by a background worker with exponential
backoff, up to `TCMS_FORWARDING_MAX_ATTEMPTS` attempts before being marked
`dead_letter` (which raises a critical alert). `GET /forwarding`,
`POST /forwarding/{id}/resend` for a manual retry regardless of backoff.

## Reports

`GET /reports?format=json|csv`, filterable by `device_id`, `location_type`,
`date_from`, `date_to`. CSV export streams as a file download
(`Content-Disposition: attachment`). Exposed in the frontend's Reports page.

## Swagger

FastAPI's auto-generated docs are live at http://localhost:8000/docs
(Swagger UI) and http://localhost:8000/openapi.json (raw schema) — verified
against a running stack while writing this doc (30 REST paths documented).
WebSocket endpoints (`/ws/ingest`, `/ws/live`) can't be represented in
OpenAPI/Swagger (a FastAPI/OpenAPI limitation, not a gap here) — they're
documented in prose in this README and in the module docstrings of
`domains/ingestion/router.py` / `domains/realtime/router.py`.

## API examples

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<secret>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/devices -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/records/latest -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/alerts -H "Authorization: Bearer $TOKEN"
curl -s "http://localhost:8000/ml/devices/cam-01/anomalies" -H "Authorization: Bearer $TOKEN"
curl -s "http://localhost:8000/reconstruction/log?device_id=cam-01" -H "Authorization: Bearer $TOKEN"
curl -s "http://localhost:8000/reports?device_id=cam-01&format=json" -H "Authorization: Bearer $TOKEN"
```

More examples (including registering a device, manual override, and the
ML-layer walkthrough): [SMOKE_TEST.md](SMOKE_TEST.md).

## ML training / evaluation CLI

```bash
docker compose exec app python -m Backend.scripts.train_model
docker compose exec app python -m Backend.scripts.evaluate_model
docker compose exec app python -m Backend.scripts.detect_anomalies --device cam-01
docker compose exec app python -m Backend.scripts.reconstruct_missing
```

(Or run the same commands directly, without `docker compose exec app`, in
the non-Docker setup above.) Model training needs at least
`TCMS_ML_MIN_HISTORY_POINTS` trusted observations per vehicle type — run the
simulator for a while first, or see docs/MODEL_TRAINING.md for generating a
synthetic dataset.

## Tests

```bash
pytest
```

83 deterministic unit tests across validation, statistical/ML anomaly
scoring, the reconstruction hierarchy, device health, calendar/feature
engineering, chronological train/val/test splitting, the model registry,
ingestion edge cases (invalid JSON, invalid structure, wrong device_id),
manual override, audit logging, alerts, and forwarding. No test depends on
a live database, socket, wall-clock timing, or randomness — every DB/model
dependency is monkeypatched with an in-memory fake.

## Demo

One command runs the full pipeline against a live stack and prints the
real API responses at every stage (no fabricated output):

```bash
docker compose exec simulator python -m Backend.Devices.demo
```

See [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for a 3–5 minute presentation script
built around this and the frontend.

## Project structure

```
Backend/
  app/
    core/           settings, JWT/security, audit log writer
    db/              connection pool
    domains/         one folder per bounded context (see below)
    ml/              framework-agnostic ML/statistics engine
    main.py          composition root: wires routers + background workers
  Devices/
    cameras.py        continuous device simulator + ScenarioController
    test_scenarios.py controlled one-shot test CLI
    demo.py           end-to-end demo runner
  mock_external/       mock road-authority + SMS gateway
  scripts/             create_admin, train/evaluate model, reconstruct/detect CLIs
Database/migrations/   0001_init, 0002_seed, 0003_ml_layer
Frontend/src/app/       Angular UI (login, dashboard, device detail, alerts, reports, manual control)
docs/                   ML/architecture/data-dictionary/diagram/report docs
tests/                  pytest suite
```

`Backend/app/domains/` — one folder per bounded context: `auth`, `devices`,
`ingestion`, `realtime`, `records`, `alerts`, `forwarding`,
`reconstruction`, `ml`, `reports`, `traffic_events`.

## Limitations

- No distinct Administrator/Operator role enforcement yet (single
  authenticated-user permission level; `users.role` exists but is unused
  for authorization).
- Anomaly-detection evaluation metrics are computed against the synthetic
  simulator, not real-world labelled data.
- Neighbour-device grouping for reconstruction is by `location_type` only,
  not a real road-corridor relationship.
- `scikit-learn`/`pandas`/`numpy`/`jdatetime` are pinned; a future Python
  upgrade without prebuilt wheels for one of them degrades the ML layer to
  its pure-Python fallback path rather than failing to start.
- No formal SRS document is checked into this repository (see the top of
  this README).
- No automated frontend tests (Angular's default boilerplate spec only).

## Future work

- Role-based authorization (Administrator vs Operator).
- Real labelled anomaly data for honest precision/recall reporting.
- Frontend unit/e2e test coverage.
- A real road-corridor topology for neighbour-device reconstruction instead
  of `location_type` grouping.
