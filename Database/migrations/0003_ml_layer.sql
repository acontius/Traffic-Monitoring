-- ML / intelligent traffic-data-quality layer (docs/ML_ARCHITECTURE.md).
-- Additive only: no existing column semantics change, no existing rows are
-- rewritten except the one-time raw_payload backfill below.

-- Preserve the original incoming payload forever, even once `payload` is
-- later overwritten by reconstruction/manual-override. `data_quality_status`
-- is a superset label the new ML layer uses for triage; the existing
-- is_valid/anomaly_flag/is_reconstructed booleans keep their current meaning
-- and behaviour untouched.
ALTER TABLE traffic_records
    ADD COLUMN IF NOT EXISTS raw_payload JSONB,
    ADD COLUMN IF NOT EXISTS data_quality_status TEXT NOT NULL DEFAULT 'valid'
        CHECK (data_quality_status IN
            ('valid', 'suspect', 'corrupt', 'reconstructed', 'manual_review'));

UPDATE traffic_records SET raw_payload = payload WHERE raw_payload IS NULL;

-- Richer, versioned reconstruction audit trail. All nullable so the existing
-- formula-only write path (`method`, `formula_snapshot`, `inputs`) keeps
-- working unchanged; the ML reconstruction engine populates the new columns.
ALTER TABLE reconstruction_log
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS reconstruction_level TEXT,
    ADD COLUMN IF NOT EXISTS model_version TEXT,
    ADD COLUMN IF NOT EXISTS evidence JSONB,
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'auto'
        CHECK (review_status IN
            ('auto', 'pending_review', 'accepted', 'rejected', 'edited'));

-- So the forwarding pipeline (and the road authority) can distinguish
-- original device data from reconstructed/manually-overridden data.
ALTER TABLE forwarding_log
    ADD COLUMN IF NOT EXISTS data_classification TEXT NOT NULL DEFAULT 'original'
        CHECK (data_classification IN
            ('original', 'validated', 'reconstructed', 'manual_override'));

-- Registry of trained model artifacts (Model A: expected-traffic regressor,
-- one row per vehicle_type per training run). Never overwritten in place —
-- rollback just flips is_active.
CREATE TABLE IF NOT EXISTS ml_models (
    id                        BIGSERIAL PRIMARY KEY,
    model_name                TEXT NOT NULL,
    model_version             TEXT NOT NULL,
    model_type                TEXT NOT NULL,
    trained_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    training_data_range_start TIMESTAMPTZ,
    training_data_range_end   TIMESTAMPTZ,
    feature_version           TEXT NOT NULL,
    metrics                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_path             TEXT,
    checksum                  TEXT,
    is_active                 BOOLEAN NOT NULL DEFAULT false,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model_name, model_version)
);

CREATE INDEX IF NOT EXISTS idx_ml_models_active
    ON ml_models (model_name, is_active);

-- Point predictions (used both as anomaly-detection evidence and as
-- reconstruction evidence) so every expected-value number shown to an
-- operator is reproducible back to a model version and its inputs.
CREATE TABLE IF NOT EXISTS ml_predictions (
    id                     BIGSERIAL PRIMARY KEY,
    device_id              TEXT NOT NULL REFERENCES devices(device_id),
    timestamp              TIMESTAMPTZ NOT NULL,
    vehicle_type           TEXT NOT NULL,
    predicted_value        DOUBLE PRECISION NOT NULL,
    prediction_interval_low  DOUBLE PRECISION,
    prediction_interval_high DOUBLE PRECISION,
    model_id               BIGINT REFERENCES ml_models(id),
    features_used          JSONB,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ml_predictions_device_ts
    ON ml_predictions (device_id, timestamp DESC);

-- Anomaly detections. `status` doubles as the operator-feedback/labelling
-- store (false_positive / true_anomaly / true_device_failure), which is the
-- seed of future supervised training.
CREATE TABLE IF NOT EXISTS anomaly_events (
    id            BIGSERIAL PRIMARY KEY,
    device_id     TEXT NOT NULL REFERENCES devices(device_id),
    timestamp     TIMESTAMPTZ NOT NULL,
    anomaly_type  TEXT NOT NULL,
    severity      TEXT NOT NULL DEFAULT 'info'
                  CHECK (severity IN ('info', 'warning', 'critical')),
    score         DOUBLE PRECISION NOT NULL,
    observed      JSONB,
    expected      JSONB,
    evidence      JSONB,
    model_id      BIGINT REFERENCES ml_models(id),
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN
                      ('open', 'acknowledged', 'false_positive',
                       'true_anomaly', 'true_device_failure')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ,
    resolved_by   TEXT
);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_device_ts
    ON anomaly_events (device_id, timestamp DESC);

-- Custom, operator-defined calendar events (built-in holidays/Nowruz are
-- computed in code via jdatetime, not stored here — see ml/calendar.py).
CREATE TABLE IF NOT EXISTS traffic_events (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    start_at      TIMESTAMPTZ NOT NULL,
    end_at        TIMESTAMPTZ NOT NULL,
    impact_scope  JSONB,
    description   TEXT,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_traffic_events_window
    ON traffic_events (start_at, end_at);

-- Point-in-time device health assessments (silence/intermittent/constant
-- value/partial failure/bursting/timestamp drift/rate mismatch -> a single
-- HEALTHY/DEGRADED/SUSPICIOUS/OFFLINE/RECOVERING state).
CREATE TABLE IF NOT EXISTS device_health_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    device_id     TEXT NOT NULL REFERENCES devices(device_id),
    snapshot_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    health_status TEXT NOT NULL
                  CHECK (health_status IN
                      ('HEALTHY', 'DEGRADED', 'SUSPICIOUS', 'OFFLINE', 'RECOVERING')),
    signals       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_device_health_snapshots_device
    ON device_health_snapshots (device_id, snapshot_at DESC);
