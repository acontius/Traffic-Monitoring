PROJECT STATUS
==============

Verified against a live stack on 2026-09-06 (`docker compose up -d --build`
from a clean checkout, then `pytest`).

Build: PASS
Docker: PASS (db, app, mock-external, simulator, frontend all reach `Up`/`running` with no manual DB setup)
Database: PASS (migrations auto-applied, all 12 tables present, hypertable confirmed)
Backend: PASS (`GET /health` → 200; all 30 REST paths reachable)
Frontend: PASS (served by nginx at :4200, reverse-proxies /api to the backend, 200 OK)
Swagger: PASS (`/docs` and `/openapi.json` both 200; 30 paths across 10 tags)
Authentication: PASS (login issues JWT + refresh token; protected endpoints reject without one)
Simulator: PASS (5 default devices connect and push readings continuously)
Controlled testing: PASS (`Backend/Devices/test_scenarios.py`, all 9 scenarios run against a live stack: normal, missing, invalid-json, invalid-structure, wrong-device, spike, drop, negative, timestamp × 4 variants — none crashed the ingestion loop, all produced the documented outcome, verified via the real API)
Anomaly detection: PASS (spike/drop produced real `anomaly_flag=true` records and `anomaly_events` rows with type/score; negative/malformed/future-timestamp payloads correctly rejected before persistence)
ML: PASS with caveats (hybrid statistical + trained `HistGradientBoostingRegressor` pipeline confirmed wired end to end; see "AI/ML reality" below — no real-world labelled evaluation data exists, only synthetic)
Reconstruction: PASS (hierarchy + policy engine confirmed present and wired; manual override verified end to end against a live stack — produced a `reconstruction_log` row with `method="manual_override"`)
Alerts: PASS (invalid_payload/statistical_anomaly/distribution_anomaly/value_anomaly alerts all confirmed via `GET /alerts` after running the controlled scenarios)
Forwarding: PASS (confirmed via `app` container logs: normal ingestion produced a real `HTTP/1.1 200 OK` POST to `mock-external`'s `/mock-road-authority`)
Reports: PASS (`GET /reports?format=json` returned real rows for a tested device)
Tests: PASS (83/83 — 71 pre-existing + 12 added for previously-uncovered ingestion edge cases, manual override, audit logging, alerts, and forwarding)
Documentation: PASS (README, SMOKE_TEST, DEMO_SCRIPT, SCREENSHOT_GUIDE, data dictionary, sequence/use-case/architecture diagrams, and academic report material all added/updated this pass)

AI/ML reality
-------------
The system is a **hybrid**, not a pure rule-based system and not an
unqualified "AI" claim:
- Rule-based structural validation always runs (no statistics).
- Two statistical anomaly checks (z-score; robust MAD-based deviation +
  rule violations) always run inline.
- A genuinely trained `sklearn.ensemble.HistGradientBoostingRegressor`
  (one per vehicle category) contributes a prediction-residual term to a
  combined weighted anomaly score, and feeds the top level of the
  reconstruction hierarchy — but degrades to `None` automatically (pure
  statistics take over) if the library, a trained model, or enough history
  isn't available.
- The reconstruction/anomaly decision policy is a deterministic threshold
  table, never an LLM.
- An optional OpenRouter LLM step exists purely to turn already-computed
  evidence into human-readable narrative text for one endpoint
  (`GET /ml/anomaly-events/{id}/explain`); disabled by default, advisory
  only, never affects a stored decision.
- Anomaly-detection precision/recall/F1 metrics reported by
  `evaluate_model.py` are computed against the **synthetic simulator**, not
  real-world labelled data — this project does not claim a real-world
  accuracy figure.

SRS coverage
------------
No SRS document exists in this repository, so a percentage-against-spec
figure would be fabricated and is deliberately not given. What can be
stated: the codebase contains ~30 scattered `# SRS x.y` code comments
citing section numbers of a document that isn't checked in; every
functional area those comments reference (auth, ingestion, validation,
reconstruction, forwarding, alerts, reporting, audit) has a corresponding
working implementation verified in this pass. Whether that implementation
satisfies the *actual* SRS text is unverifiable without that document.

Known limitations
------------------
- No role-based authorization enforcement (`users.role` column exists,
  unused for access control — every authenticated user has equal access).
- Anomaly-detection evaluation metrics are synthetic-only.
- Neighbour-device grouping for reconstruction uses `location_type` only,
  not a real road-corridor relationship.
- `scikit-learn`/`pandas`/`numpy`/`jdatetime` are version-pinned; a future
  Python upgrade without prebuilt wheels degrades the ML layer to its
  pure-Python fallback automatically rather than failing to start.
- No frontend automated test coverage (Angular's default boilerplate spec
  only).
- `forwarding_log.data_classification` is stored in the database but not
  currently exposed in the `GET /forwarding` API response schema.

Recommended remaining work
---------------------------
- Add role-based authorization (Administrator vs Operator) if the
  submission requires demonstrating access control.
- Capture the screenshots listed in SCREENSHOT_GUIDE.md before recording
  the demo video.
- If real-world accuracy figures are needed for the academic report, either
  source labelled real data or explicitly caveat every reported metric as
  synthetic (already done in docs/MODEL_TRAINING.md).
