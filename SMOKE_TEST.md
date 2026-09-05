# Smoke test walkthrough

A step-by-step run through TCMS as an operator would use it: bring the stack
up, log in, watch devices report in, observe alerts/reports, then register a
brand-new counting device. Every step below was run against a live stack
while writing this doc.

## 1. Bring the stack up

```bash
cp .env.example .env
docker compose up -d --build
```

Five containers start: `db` (TimescaleDB, runs the migrations in
`Database/migrations/` on first boot), `app` (the FastAPI hub), `mock-external`
(stand-in for the road-authority webhook + SMS gateway), `simulator` (5 fake
cameras: `cam-01`..`cam-05`), `frontend` (Angular via Nginx on :4200).

```bash
docker compose ps
```
```
NAME                 STATUS
tcms-app             Up
tcms-db              Up
tcms-frontend        Up
tcms-mock-external   Up
tcms-simulator       Up
```

## 2. Create the admin login

```bash
docker compose exec app python -m Backend.scripts.create_admin \
  --username admin --password changeme
```

## 3. Log in

Open **http://localhost:4200**, sign in with `admin` / `changeme`.

Or from the API directly:

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeme"}'
# → {"access_token": "...", "refresh_token": "...", "token_type": "bearer"}
```

Everything below the login uses `TOKEN=<access_token>` and
`-H "Authorization: Bearer $TOKEN"` when hitting the API directly; the UI
handles this for you automatically after login.

## 4. See the devices

**UI**: the Dashboard tab shows the map with `cam-01`..`cam-05` and a status
list. They flip to "فعال" (active) as soon as each one sends its first
reading — with the default 300s simulator interval that can take up to 5
minutes; set `TCMS_SIMULATOR_INTERVAL_SECONDS=15` in `.env` and
`docker compose up -d simulator` for a faster loop while testing.

**API**:

```bash
curl -s http://localhost:8000/devices -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -s http://localhost:8000/records/latest -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

## 5. Observe

- **Live status**: the Dashboard map/list updates in real time over
  `/ws/live` — no polling, no refresh needed.
- **Device history**: click a device on the dashboard (or
  `GET /records/{device_id}/history`) to see its recorded readings,
  reconstruction history, and metadata.
- **Alerts**: the Alerts tab shows data-gap, invalid-payload, and
  statistical-anomaly alerts as they happen, with an unread badge in the nav.
  Acknowledge one from the UI or `POST /alerts/{id}/acknowledge`.
- **Forwarding**: every valid/reconstructed reading is sent to the
  road-authority webhook (the `mock-external` container in dev).
  `GET /forwarding?status=sent` confirms delivery;
  `docker compose logs mock-external` shows what it received.
- **Reports**: the Reports tab filters by device/axis/date range and
  exports CSV (`GET /reports?format=csv`).
- **Reconstruction**: stop a device
  (`docker compose stop simulator`, or delete it — see below) and wait past
  its `expected_interval_seconds × (1 + grace)` (~10 min by default); a
  `data_gap` alert appears and `GET /reconstruction/log?device_id=cam-01`
  shows the formula-filled value.

## 6. Add a new counting device

A device must be registered before the ingestion gateway will accept a
connection from it (`GET /devices` uses this table; unknown `device_id`s are
rejected at the WebSocket handshake). Register one:

```bash
curl -s -X POST http://localhost:8000/devices \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "device_id": "cam-06",
        "location_type": "urban",
        "label": "دوربین جدید",
        "latitude": 35.71,
        "longitude": 51.40,
        "expected_interval_seconds": 300
      }'
```

Then point either a real device or another simulator instance at the hub
using that `device_id` and the shared token
(`TCMS_DEVICE_SHARED_TOKEN` in `.env`, default `change-me-device-token`):

```
ws://<host>:8000/ws/ingest?device_id=cam-06&token=change-me-device-token
```

To spin up one more simulated camera for it without editing
`build_default_devices()`:

```bash
docker compose run --rm simulator python -c "
import asyncio
from Backend.Devices.cameras import TrafficDevice, run_device
asyncio.run(run_device(
    TrafficDevice('cam-06', 'urban'),
    'ws://app:8000/ws/ingest', 'change-me-device-token', 300,
))"
```

It shows up on the dashboard map and in `/devices` immediately, and starts
appearing in `/records/latest` after its first reading.

**Renaming/repositioning/re-assigning a contractor** for an existing device:

```bash
curl -s -X PATCH http://localhost:8000/devices/cam-06 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"contractor": "شرکت راهسازی الف", "label": "دوربین بازبینی‌شده"}'
```

There's no delete endpoint yet (device history should generally be kept for
audit); to remove a test device entirely, drop its rows directly:

```bash
docker compose exec db psql -U acontius -d traffic_monitoring -c "
  DELETE FROM reconstruction_log WHERE device_id='cam-06';
  DELETE FROM forwarding_log WHERE device_id='cam-06';
  DELETE FROM traffic_records WHERE device_id='cam-06';
  DELETE FROM alerts WHERE device_id='cam-06';
  DELETE FROM devices WHERE device_id='cam-06';
"
```

## ML layer walkthrough (device health, anomalies, reconstruction confidence)

The simulator supports controllable anomaly scenarios
(`TCMS_SIMULATOR_ANOMALY_MODE`, or per-device via
`TCMS_SIMULATOR_DEVICE_SCENARIOS`) so the ML layer (docs/ML_ARCHITECTURE.md)
can be exercised end to end without waiting for real anomalies.

**Silence → `DEVICE_SILENCE` alert + device health `OFFLINE`:**

```bash
docker compose stop simulator   # or: run one device with mode "missing_data"
# wait > expected_interval_seconds * (1 + grace) + one health-scan interval
curl -s http://localhost:8000/ml/devices/cam-01/health -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/alerts -H "Authorization: Bearer $TOKEN" | grep device_silence
```

**Spike → anomaly event + alert:**

```bash
docker compose run --rm -e TCMS_SIMULATOR_ANOMALY_MODE=spike simulator
curl -s http://localhost:8000/ml/devices/cam-01/anomalies -H "Authorization: Bearer $TOKEN"
```

**Constant values → device health `SUSPICIOUS`:**

```bash
docker compose run --rm -e TCMS_SIMULATOR_ANOMALY_MODE=constant_value simulator
curl -s http://localhost:8000/ml/devices/cam-01/health -H "Authorization: Bearer $TOKEN"
```

**Missing interval with good history → auto-reconstruction with confidence:**
After training a model (`docker compose exec app python -m
Backend.scripts.train_model`) and letting a device run normally for a while,
stop it briefly, then:

```bash
curl -s "http://localhost:8000/ml/devices/cam-01/reconstructions" \
  -H "Authorization: Bearer $TOKEN"
```

Look for `confidence`, `reconstruction_level`, `model_version`, and
`review_status: "auto"`.

**Missing interval with poor/no history → manual review:** a brand-new
device (register one, per the "adding a new device" section above) that
goes silent immediately has no history for any level to use — expect
`review_status` never reaches `"auto"`, a `manual_review_required` alert,
and no value silently presented as trusted.

**Model status:**

```bash
curl -s http://localhost:8000/ml/models -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/ml/metrics -H "Authorization: Bearer $TOKEN"
```

## Controlled protocol/data-quality scenarios

The scenarios above cover normal operation, silence, spike, and constant
values. The rest of the negative/edge cases are exercised by
`Backend/Devices/test_scenarios.py` — a one-shot CLI that sends exactly one
deliberately-shaped message and reports what happened, verified against a
live stack:

```bash
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario invalid-json
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario invalid-structure
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario wrong-device
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario negative
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario timestamp --variant malformed
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario timestamp --variant future
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario timestamp --variant duplicate
docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario timestamp --variant out-of-order
```

Verify the actual outcome of each (not just that the socket stayed open):

```bash
curl -s http://localhost:8000/alerts -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Confirmed behaviour, run against a live stack while writing this doc:

- **Invalid JSON** (`{invalid-json`): `json.loads` fails inside
  `handle_message`, an `invalid_payload` alert is raised, the connection
  stays open — every other device keeps ingesting normally.
- **Invalid structure** (`{"device_id": "cam-01", "foo": "bar"}`):
  `validate_structure` raises `ValidationError`, an `invalid_payload` alert
  is raised, and an `ingest_rejected` row is written to `audit_log`. No
  `traffic_records` row is created.
- **Wrong device_id** (connected as `cam-01`, payload claims `cam-99`): the
  mismatch is detected, an `invalid_payload` alert is raised, and nothing is
  persisted for either device — confirmed via `GET /records/cam-99/history`
  returning `[]` and `GET /devices/cam-99` returning `404` (cam-99 was never
  registered).
- **Negative count** (`"سواری": -10`): rejected the same way as invalid
  structure (`ValidationError: invalid count for 'سواری': -10`).
- **Timestamp — malformed**: rejected (`unparseable timestamp`).
- **Timestamp — future** (>5 min clock skew): rejected (`timestamp too far
  in the future`).
- **Timestamp — duplicate**: **not rejected.** `traffic_records`'s primary
  key is `(device_id, timestamp)` and the insert is an `ON CONFLICT ... DO
  UPDATE` — the second message silently overwrites the first. This is the
  actual implemented behaviour; there is no duplicate-specific alert.
- **Timestamp — out-of-order** (an earlier timestamp sent after later
  readings, still within the 24h backdate window): accepted normally —
  there is no monotonic-ordering check in `validate_structure`, only the
  future/backdate bounds.

Manual override (operator overwrites a stored/reconstructed value by hand):

```bash
curl -s -X POST http://localhost:8000/records/manual-override \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "device_id": "cam-01",
        "timestamp": "2026-01-01T08:00:00+00:00",
        "counts": {"سواری": 18, "کامیون": 3},
        "reason": "camera was obstructed, operator estimate from field report"
      }'

curl -s "http://localhost:8000/reconstruction/log?device_id=cam-01&limit=1" \
  -H "Authorization: Bearer $TOKEN"
# → method: "manual_override", manual_override: true, created_by: "admin"
```

Also exposed in the frontend's Manual Control page.

## What this walkthrough actually exercises

Login → auth (JWT) → device registry → WebSocket ingestion → validation →
storage → live push (`/ws/live`) → forwarding outbox → reconstruction engine
→ alerts → reports → device health/anomaly detection/confidence-gated
reconstruction (ML layer). If any step above doesn't behave as described,
that's a real bug worth filing, not an environment quirk — it's the same
path this doc was verified against.
