# Screenshot guide

Capture these against a live stack (`docker compose up -d --build`) after
running through [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Save into
`docs/screenshots/` with these exact filenames. No screenshots are provided
here — capture your own from the running system.

| Filename | What to capture |
| --- | --- |
| `01-login.png` | The login page (http://localhost:4200/login) |
| `02-dashboard.png` | Dashboard tab: live map + device status list |
| `03-devices.png` | A device detail page showing recent history |
| `04-anomaly-alert.png` | Alerts tab showing a `statistical_anomaly`/`distribution_anomaly`/`value_anomaly` alert (trigger with `test_scenarios.py --scenario spike`) |
| `05-reconstruction.png` | The reconstruction log for a device (Manual Control page, or `GET /reconstruction/log`) showing method/confidence/review_status |
| `06-reports.png` | Reports tab with a filter applied and the CSV export button |
| `07-swagger.png` | http://localhost:8000/docs — the full endpoint list grouped by tag |
| `08-database-or-audit.png` | Either `psql` output of `SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 10;`, or the audit trail visible via the API |

Optional extras if useful for the report:

| Filename | What to capture |
| --- | --- |
| `09-manual-override.png` | Manual Control page's override form + resulting entry |
| `10-openapi-schema.png` | http://localhost:8000/openapi.json rendered/pretty-printed |
