-- Initial schema for TCMS (Traffic Count Management System).
-- Requires the TimescaleDB extension.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Devices (field traffic counters / cameras).
CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,
    location_type TEXT NOT NULL DEFAULT 'urban',
    label         TEXT,
    latitude      DOUBLE PRECISION,
    longitude     DOUBLE PRECISION,
    contractor    TEXT,
    ip_address    TEXT,
    status        TEXT NOT NULL DEFAULT 'unknown',
    expected_interval_seconds INTEGER NOT NULL DEFAULT 300,
    last_seen_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Traffic count records, one per device per interval. Supersedes the old
-- traffic_data table.
CREATE TABLE IF NOT EXISTS traffic_records (
    device_id        TEXT NOT NULL REFERENCES devices(device_id),
    timestamp        TIMESTAMPTZ NOT NULL,
    payload          JSONB NOT NULL,
    is_valid         BOOLEAN NOT NULL DEFAULT true,
    anomaly_flag     BOOLEAN NOT NULL DEFAULT false,
    anomaly_reason   TEXT,
    is_reconstructed BOOLEAN NOT NULL DEFAULT false,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, timestamp)
);

SELECT create_hypertable('traffic_records', 'timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_traffic_records_device_ts
    ON traffic_records (device_id, timestamp DESC);

-- Log of every reconstructed (gap-filled) interval, with the formula
-- snapshot/inputs used, so reconstructions stay auditable and reproducible.
CREATE TABLE IF NOT EXISTS reconstruction_log (
    id               BIGSERIAL PRIMARY KEY,
    device_id        TEXT NOT NULL REFERENCES devices(device_id),
    timestamp        TIMESTAMPTZ NOT NULL,
    method           TEXT NOT NULL,
    formula_snapshot JSONB NOT NULL,
    inputs           JSONB NOT NULL,
    manual_override  BOOLEAN NOT NULL DEFAULT false,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reconstruction_log_device
    ON reconstruction_log (device_id, timestamp DESC);

-- Configurable reconstruction formula weights, editable via API without a
-- redeploy. scope_type is 'device' or 'location_type'; scope_value is the
-- matching device_id / location_type. A row with scope_type='default'
-- applies when nothing more specific matches.
CREATE TABLE IF NOT EXISTS reconstruction_config (
    id          BIGSERIAL PRIMARY KEY,
    scope_type  TEXT NOT NULL DEFAULT 'default'
                CHECK (scope_type IN ('default', 'location_type', 'device')),
    scope_value TEXT,
    weights     JSONB NOT NULL,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope_type, scope_value)
);

-- Live/alerting events: data loss, device silence, statistical anomalies.
CREATE TABLE IF NOT EXISTS alerts (
    id               BIGSERIAL PRIMARY KEY,
    type             TEXT NOT NULL,
    device_id        TEXT REFERENCES devices(device_id),
    severity         TEXT NOT NULL DEFAULT 'info'
                     CHECK (severity IN ('info', 'warning', 'critical')),
    message          TEXT NOT NULL,
    details          JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at  TIMESTAMPTZ,
    acknowledged_by  TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts (created_at DESC);

-- Outbox for forwarding data to the road-authority (راهداری) web service,
-- with retry bookkeeping.
CREATE TABLE IF NOT EXISTS forwarding_log (
    id              BIGSERIAL PRIMARY KEY,
    device_id       TEXT NOT NULL REFERENCES devices(device_id),
    timestamp       TIMESTAMPTZ NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'failed', 'dead_letter')),
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    response_code   INTEGER,
    response_body   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_forwarding_log_status ON forwarding_log (status);

-- Users and sessions (JWT access token + DB-backed refresh token).
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens (user_id);

-- Audit trail: every ingest/reconstruct/forward/manual action and login.
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor      TEXT NOT NULL DEFAULT 'system',
    action     TEXT NOT NULL,
    entity     TEXT,
    entity_id  TEXT,
    details    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at DESC);
