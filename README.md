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
- **Database** (`Database/migrations`): Postgres + TimescaleDB. Apply
  `0001_init.sql` then `0002_seed.sql`.
- **Frontend** (`Frontend/`): Angular app — dashboard/map, device detail,
  alerts, reports, manual control.
- **Device simulator** (`Backend/Devices/cameras.py`): generates realistic
  traffic counts and pushes them into the hub's ingestion WebSocket.
- **Mock external services** (`Backend/mock_external/server.py`): stands in
  for the road-authority webhook and SMS gateway during dev/test.

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

## Tests

```bash
pytest
```
