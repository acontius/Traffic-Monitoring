# Report 1 — Project Objective and Related Work

## Project goal

Build a Traffic Count Management System (TCMS) that ingests per-interval
vehicle counts from field cameras, guarantees the data reaching downstream
consumers (a road authority, reports, dashboards) is validated and
quality-flagged, and automatically fills gaps left by device failures with
a transparent, auditable method — rather than leaving gaps in the record or
silently fabricating values.

## Problem

Traffic-counting camera networks are unreliable at the edge: devices go
offline, send corrupted payloads, or occasionally report physically
implausible counts (a spike from a sensor fault, a collapse to zero from a
lens obstruction). Naively storing whatever arrives corrupts every report
and statistic built on top of it; naively rejecting anything unusual
creates gaps with no record of why. Operators also need a way to see *why*
a value was flagged or reconstructed, and to override the system's decision
when they have better field information than the automated pipeline.

## Motivation

This is a recurring, generic data-quality problem for any IoT-style sensor
network feeding a decision system, not one unique to traffic counting:
ingest → validate → detect anomalies → decide whether to
accept/reconstruct/reject → keep an audit trail. Traffic counting was
chosen as the concrete domain because it has a clear real-world consumer
(a road authority) and a natural periodic-data shape that makes gap
detection and anomaly scoring well-defined problems.

## Related approaches (qualitative, not benchmarked against this project)

Anomaly detection over periodic sensor/time-series data is generally
approached with one of, or a combination of, these strategies:

- **Rule-based/threshold checks** — simple, fully explainable, cheap to
  run inline, but brittle to context (a legitimate holiday spike looks
  identical to a sensor fault under a fixed threshold).
- **Classical statistical methods** (z-score, robust/MAD-based deviation,
  seasonal decomposition) — still explainable, more resilient to outliers
  than a fixed threshold, but only "know" what a stationary or seasonally
  adjusted baseline looks like.
- **Supervised/learned models** (regression, gradient boosting, isolation
  forests) — can capture more complex seasonal/contextual structure, at the
  cost of needing labelled or at least representative training data, and
  being harder to explain to a non-technical operator without extra
  tooling.
- **Hybrid pipelines** — rule/statistical checks as a fast first pass,
  a learned model as a second opinion or for reconstruction, with a
  deterministic policy layer deciding what to do with either signal. This
  is the category TCMS falls into, and is a common pragmatic choice when
  full labelled ground truth doesn't exist yet (as is the case here — see
  the honest anomaly-detection assessment in `docs/ML_ARCHITECTURE.md`).

Gap-filling/imputation for missing time-series intervals is similarly
approached along a spectrum from simple carry-forward/moving-average
methods to model-based imputation; a well-known cross-cutting principle in
that literature is confidence-aware imputation — never presenting a filled
value with the same trust level as an observed one. TCMS's hierarchical,
confidence-gated reconstruction (Level 1 ML prediction down to Level 5
formula, always logged, with a `MANUAL_REVIEW` path when no level is
confident enough) follows that same principle.

## Proposed solution (this project)

- A WebSocket ingestion gateway that structurally validates every message
  before it can reach storage, and never crashes on malformed input.
- Two independent statistical anomaly checks running inline, plus an
  optional trained `HistGradientBoostingRegressor`-based residual check as
  a second opinion — combined into one weighted score.
- A 5-level, confidence-gated reconstruction hierarchy with a deterministic
  policy layer, full audit logging of every attempt (including ones that
  fall through to manual review), and an operator override path.
- A durable forwarding outbox with retry/backoff to the external road
  authority system.
- Full JWT authentication, an audit log for every consequential action, and
  a dashboard/reports UI so an operator never needs direct database access.

See [docs/IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) for the full
implementation detail and
[docs/REPORT_2_ANALYSIS_AND_DESIGN.md](REPORT_2_ANALYSIS_AND_DESIGN.md) for
requirements/design.
