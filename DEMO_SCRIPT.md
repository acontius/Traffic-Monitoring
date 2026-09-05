# Demo script (3–5 minutes)

A presentation-ready walkthrough combining the frontend and the CLI tools.
Every step was run against a live stack while writing this doc — nothing
here is a fabricated transcript.

**Before recording**: `docker compose up -d --build`, create the admin
user, and — important — run the demo against a **freshly-seeded device**
or restart the stack first if you've already run `test_scenarios.py`
against `cam-01`, since its recent history will already contain the
spike/drop values from testing and will skew the "normal" baseline. Use a
device that hasn't been hit with scenarios yet (e.g. `cam-02`) for a clean
run, or `docker compose down -v && docker compose up -d --build` to reset.

## Sequence

1. **Login** (~20s) — open http://localhost:4200, log in as the admin
   user created via `create_admin.py`.
2. **Dashboard** (~20s) — point out the live map with `cam-01`..`cam-05`,
   the status list (online/offline), and mention it updates over
   `/ws/live` with no polling.
3. **Devices** (~20s) — open a device's detail page: show its recent
   history and metadata.
4. **Normal incoming data** (~20s) — run
   `docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario normal`
   in a terminal; point out the new reading appearing live on the
   dashboard/device detail with no anomaly flag.
5. **Controlled anomaly** (~30s) — run
   `docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario spike`;
   switch to the Alerts tab or the device's anomaly list
   (`GET /ml/devices/{id}/anomalies`) and show the anomaly event with its
   type/score.
6. **Alert** (~20s) — show the alert appearing in the Alerts tab
   (unread badge in the nav), acknowledge it.
7. **Missing interval** (~20s) — explain that a missing interval is the
   *absence* of a message (stop a device's simulator connection, or use
   `--scenario missing` to force an immediate reconstruction pass rather
   than waiting for the scheduled worker).
8. **Reconstruction** (~30s) — show the resulting entry in
   `GET /reconstruction/log?device_id=...` (method, confidence,
   review_status) — or the Manual Control page's history if a gap already
   exists — and point out the confidence-gated policy (AUTO_RECONSTRUCT vs
   MANUAL_REVIEW).
9. **Report** (~20s) — open the Reports tab, filter by device/date range,
   export CSV.
10. **Swagger** (~20s) — open http://localhost:8000/docs, show the grouped
    endpoint tags (auth, devices, records, alerts, forwarding,
    reconstruction, ml, reports, traffic-events).

## One-command alternative

If a live click-through isn't needed, the entire pipeline (normal → spike →
reconstruction pass → alert → forwarding → report) can be shown with a
single command that prints every real API response as it happens:

```bash
docker compose exec simulator python -m Backend.Devices.demo
```
