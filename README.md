# TCMS — Traffic Count Management System

A hub that ingests per-interval traffic counts from field devices over
WebSocket, validates and flags anomalies, reconstructs missing/corrupt
intervals with a configurable formula, forwards data to a road-authority
(راهداری) web service with retry, raises live alerts, and exposes a
dashboard, CSV reporting, auth, and audit logging. Implements the SRS in
`document.pdf`.

## Architecture

- **Backend** (`Backend/app`): FastAPI. WebSocket ingestion gateway
  (`ws/ingest.py`), live dashboard/alert push (`ws/live.py`), validation,
  reconstruction engine, forwarding outbox, notifications (in-app + SMS),
  JWT auth, audit logging, reporting.
- **ML layer** (`Backend/app/ml`, `Backend/app/domains/ml`,
  `Backend/app/domains/traffic_events`): device health, statistical/ML
  anomaly detection, hierarchical confidence-gated reconstruction, calendar
  context, and an optional OpenRouter explanation step. See
  **[docs/ML_ARCHITECTURE.md](docs/ML_ARCHITECTURE.md)**.
- **Database** (`Database/migrations`): Postgres + TimescaleDB. Apply
  `0001_init.sql`, `0002_seed.sql`, then `0003_ml_layer.sql` in order.
- **Frontend** (`Frontend/`): Angular app — dashboard/map, device detail,
  alerts, reports, manual control.
- **Device simulator** (`Backend/Devices/cameras.py`): generates realistic
  traffic counts and pushes them into the hub's ingestion WebSocket; supports
  controllable anomaly scenarios (`TCMS_SIMULATOR_ANOMALY_MODE`) for
  exercising the ML layer end to end.
- **Mock external services** (`Backend/mock_external/server.py`): stands in
  for the road-authority webhook and SMS gateway during dev/test.

## ML / intelligent data-quality layer

Device-health detection, statistical + ML anomaly scoring, hierarchical
reconstruction with confidence gating, calendar/holiday context, and an
**optional** OpenRouter explanation step (`TCMS_AI_ENABLED=false` by
default — the system is fully functional without it). See:

- [docs/ML_ARCHITECTURE.md](docs/ML_ARCHITECTURE.md) — overall design
- [docs/ANOMALY_DETECTION.md](docs/ANOMALY_DETECTION.md) — device health +
  anomaly scoring
- [docs/RECONSTRUCTION.md](docs/RECONSTRUCTION.md) — hierarchical
  reconstruction + confidence policy
- [docs/MODEL_TRAINING.md](docs/MODEL_TRAINING.md) — training/evaluation
- [docs/AI_INTEGRATION.md](docs/AI_INTEGRATION.md) — the LLM explanation
  boundary

New environment variables are documented inline in `.env.example`
(`TCMS_ML_*`, `TCMS_AI_*`, `TCMS_TRAFFIC_TIMEZONE`,
`TCMS_SIMULATOR_ANOMALY_MODE`).

**Known limitation**: `numpy`/`pandas`/`scikit-learn`/`jdatetime` are pinned
in `requirements.txt` for the project's Python version; if a future Python
upgrade lacks prebuilt wheels for one of them, the ML layer degrades to its
pure-Python fallback path automatically (rule-based validation, MAD/z-score
anomaly detection, formula-based reconstruction) rather than failing to
start — see "Failure behaviour" in docs/ML_ARCHITECTURE.md.

## Running locally

```bash
cp .env.example .env   # adjust as needed
docker compose up --build
```

This starts: `db` (Timescale/Postgres, migrations auto-applied on first
boot), `app` (FastAPI hub on :8000), `mock-external` (:9100), `simulator`
(pushes simulated device data into the hub), and `frontend` (Angular via
Nginx on :4200, proxying `/api` to the hub).

Create the first admin user once the DB is up:

```bash
docker compose exec app python -m Backend.scripts.create_admin \
  --username admin --password <secret>
```

Open http://localhost:4200 and log in.

For a full guided tour past this point — login, watching devices report in,
reading alerts/reports/reconstructions, and registering a brand-new
counting device — see **[SMOKE_TEST.md](SMOKE_TEST.md)**.

## Running without Docker

```bash
pip install -r requirements.txt
uvicorn Backend.app.main:app --reload

# separate terminals:
uvicorn Backend.mock_external.server:app --port 9100
python -m Backend.Devices.cameras

cd Frontend && npm install && npm start
```

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
