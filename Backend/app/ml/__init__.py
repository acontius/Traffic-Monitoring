"""Intelligent traffic-data-quality layer: device health, statistical/ML
anomaly detection, hierarchical reconstruction, confidence-aware policy, and
an optional LLM explanation step.

Framework-agnostic core (no FastAPI/DB coupling beyond taking an `asyncpg`
pool where a module genuinely needs to read history). See
`Backend/app/domains/ml/` for the HTTP API and background workers that call
into this package, and `docs/ML_ARCHITECTURE.md` for the full design.

Every module that depends on numpy/pandas/scikit-learn imports them lazily
and degrades to a pure-Python fallback if they are unavailable — an ML
subsystem failure must never stop traffic ingestion (docs/ML_ARCHITECTURE.md
"Failure behaviour").
"""

VEHICLE_TYPES: tuple[str, ...] = ("سواری", "کامیون", "موتور", "اتوبوس", "وانت")

FEATURE_VERSION = "v1"
