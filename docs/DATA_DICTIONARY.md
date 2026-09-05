# Data Dictionary

Generated directly from `Database/migrations/0001_init.sql`,
`0002_seed.sql`, and `0003_ml_layer.sql` — every field listed here exists in
those files exactly as described. `0002_seed.sql` adds no schema, only
default rows (5 seed devices `cam-01`..`cam-05`, and a `default`-scope
`reconstruction_config` row).

The database is PostgreSQL 16 with the TimescaleDB extension
(`CREATE EXTENSION IF NOT EXISTS timescaledb`).

## devices

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| device_id | TEXT | NOT NULL | PK | Unique device identifier, e.g. `cam-01` |
| location_type | TEXT | NOT NULL (default `'urban'`) | | `urban` / `highway` / `industrial` — drives simulator profile + neighbour grouping |
| label | TEXT | nullable | | Human-readable name |
| latitude | DOUBLE PRECISION | nullable | | Map position |
| longitude | DOUBLE PRECISION | nullable | | Map position |
| contractor | TEXT | nullable | | Maintaining contractor |
| ip_address | TEXT | nullable | | Last-seen source IP |
| status | TEXT | NOT NULL (default `'unknown'`) | | `online` / `offline` / `unknown` |
| expected_interval_seconds | INTEGER | NOT NULL (default `300`) | | Expected reporting cadence, used for gap/health detection |
| last_seen_at | TIMESTAMPTZ | nullable | | Last accepted reading |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

## traffic_records

TimescaleDB hypertable, partitioned on `timestamp`
(`create_hypertable(..., if_not_exists=>TRUE)`).

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| device_id | TEXT | NOT NULL | PK (composite), FK → devices | |
| timestamp | TIMESTAMPTZ | NOT NULL | PK (composite) | Interval start |
| payload | JSONB | NOT NULL | | The stored (possibly reconstructed) reading |
| is_valid | BOOLEAN | NOT NULL (default `true`) | | |
| anomaly_flag | BOOLEAN | NOT NULL (default `false`) | | |
| anomaly_reason | TEXT | nullable | | Human-readable reason string |
| is_reconstructed | BOOLEAN | NOT NULL (default `false`) | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |
| raw_payload *(0003)* | JSONB | nullable | | The original device observation — never overwritten once set, even if the row is later reconstructed/overridden |
| data_quality_status *(0003)* | TEXT | NOT NULL (default `'valid'`) | CHECK IN (`valid`,`suspect`,`corrupt`,`reconstructed`,`manual_review`) | |

Index: `idx_traffic_records_device_ts` on `(device_id, timestamp DESC)`.

## reconstruction_log

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| device_id | TEXT | NOT NULL | FK → devices | |
| timestamp | TIMESTAMPTZ | NOT NULL | | Interval that was reconstructed |
| method | TEXT | NOT NULL | | e.g. `manual_override`, or a hierarchy level name |
| formula_snapshot | JSONB | NOT NULL | | The formula/weights in effect at the time |
| inputs | JSONB | NOT NULL | | Inputs used to produce the value |
| manual_override | BOOLEAN | NOT NULL (default `false`) | | |
| created_by | TEXT | nullable | | Actor (username, or `system`) |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |
| confidence *(0003)* | DOUBLE PRECISION | nullable | | |
| reconstruction_level *(0003)* | TEXT | nullable | | Which hierarchy level produced this |
| model_version *(0003)* | TEXT | nullable | | |
| evidence *(0003)* | JSONB | nullable | | |
| review_status *(0003)* | TEXT | NOT NULL (default `'auto'`) | CHECK IN (`auto`,`pending_review`,`accepted`,`rejected`,`edited`) | |

Index: `idx_reconstruction_log_device` on `(device_id, timestamp DESC)`.

## reconstruction_config

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| scope_type | TEXT | NOT NULL (default `'default'`) | CHECK IN (`default`,`location_type`,`device`) | |
| scope_value | TEXT | nullable | | e.g. a specific `device_id` or `location_type` |
| weights | JSONB | NOT NULL | | Formula weights (see 0002 seed for the default shape) |
| updated_by | TEXT | nullable | | |
| updated_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

Unique constraint: `(scope_type, scope_value)`.

## alerts

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| type | TEXT | NOT NULL | | e.g. `invalid_payload`, `statistical_anomaly`, `forwarding_failed` |
| device_id | TEXT | nullable | FK → devices | |
| severity | TEXT | NOT NULL (default `'info'`) | CHECK IN (`info`,`warning`,`critical`) | |
| message | TEXT | NOT NULL | | |
| details | JSONB | nullable | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |
| acknowledged_at | TIMESTAMPTZ | nullable | | |
| acknowledged_by | TEXT | nullable | | |

Index: `idx_alerts_created` on `(created_at DESC)`.

## forwarding_log

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| device_id | TEXT | NOT NULL | FK → devices | |
| timestamp | TIMESTAMPTZ | NOT NULL | | |
| payload | JSONB | NOT NULL | | |
| status | TEXT | NOT NULL (default `'pending'`) | CHECK IN (`pending`,`sent`,`failed`,`dead_letter`) | |
| attempt_count | INTEGER | NOT NULL (default `0`) | | |
| last_attempt_at | TIMESTAMPTZ | nullable | | |
| response_code | INTEGER | nullable | | |
| response_body | TEXT | nullable | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |
| data_classification *(0003)* | TEXT | NOT NULL (default `'original'`) | CHECK IN (`original`,`validated`,`reconstructed`,`manual_override`) | Not currently exposed in the `GET /forwarding` API response schema, though stored |

Unique: `(device_id, timestamp)`. Index: `idx_forwarding_log_status` on `(status)`.

## users

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| username | TEXT | NOT NULL | UNIQUE | |
| password_hash | TEXT | NOT NULL | | bcrypt |
| role | TEXT | NOT NULL (default `'admin'`) | | Present in schema; not currently enforced for authorization (see README Limitations) |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

## refresh_tokens

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| user_id | BIGINT | NOT NULL | FK → users | |
| token_hash | TEXT | NOT NULL | UNIQUE | SHA-256 of the opaque refresh token — the raw token is never stored |
| expires_at | TIMESTAMPTZ | NOT NULL | | |
| revoked_at | TIMESTAMPTZ | nullable | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

Index: `idx_refresh_tokens_user` on `(user_id)`.

## audit_log

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| actor | TEXT | NOT NULL (default `'system'`) | | Username, `device:<id>`, or `system` |
| action | TEXT | NOT NULL | | e.g. `login`, `login_failed`, `ingest_rejected`, `manual_override`, `manual_resend`, `forward`, `acknowledge_alert`, `update_reconstruction_config` |
| entity | TEXT | nullable | | Table/domain the action affected |
| entity_id | TEXT | nullable | | |
| details | JSONB | nullable | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

Index: `idx_audit_log_created` on `(created_at DESC)`.

## ml_models *(0003)*

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| model_name | TEXT | NOT NULL | | e.g. per-vehicle-type model name |
| model_version | TEXT | NOT NULL | | |
| model_type | TEXT | NOT NULL | | e.g. `hist_gradient_boosting` |
| trained_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |
| training_data_range_start | TIMESTAMPTZ | nullable | | |
| training_data_range_end | TIMESTAMPTZ | nullable | | |
| feature_version | TEXT | NOT NULL | | |
| metrics | JSONB | NOT NULL (default `{}`) | | MAE/RMSE/MAPE/SMAPE etc |
| artifact_path | TEXT | nullable | | On-disk pickle path |
| checksum | TEXT | nullable | | |
| is_active | BOOLEAN | NOT NULL (default `false`) | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

Unique: `(model_name, model_version)`. Index: `idx_ml_models_active` on `(model_name, is_active)`.

## ml_predictions *(0003)*

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| device_id | TEXT | NOT NULL | FK → devices | |
| timestamp | TIMESTAMPTZ | NOT NULL | | |
| vehicle_type | TEXT | NOT NULL | | |
| predicted_value | DOUBLE PRECISION | NOT NULL | | |
| prediction_interval_low | DOUBLE PRECISION | nullable | | |
| prediction_interval_high | DOUBLE PRECISION | nullable | | |
| model_id | BIGINT | nullable | FK → ml_models(id) | |
| features_used | JSONB | nullable | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

Index: `idx_ml_predictions_device_ts` on `(device_id, timestamp DESC)`.

## anomaly_events *(0003)*

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| device_id | TEXT | NOT NULL | FK → devices | |
| timestamp | TIMESTAMPTZ | NOT NULL | | |
| anomaly_type | TEXT | NOT NULL | | e.g. `distribution_anomaly`, `statistical_anomaly`, `value_anomaly` |
| severity | TEXT | NOT NULL (default `'info'`) | CHECK IN (`info`,`warning`,`critical`) | |
| score | DOUBLE PRECISION | NOT NULL | | Combined weighted anomaly score |
| observed | JSONB | nullable | | |
| expected | JSONB | nullable | | |
| evidence | JSONB | nullable | | |
| model_id | BIGINT | nullable | FK → ml_models(id) | |
| status | TEXT | NOT NULL (default `'open'`) | CHECK IN (`open`,`acknowledged`,`false_positive`,`true_anomaly`,`true_device_failure`) | Operator feedback, seed of future supervised labelling |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |
| resolved_at | TIMESTAMPTZ | nullable | | |
| resolved_by | TEXT | nullable | | |

Index: `idx_anomaly_events_device_ts` on `(device_id, timestamp DESC)`.

## traffic_events *(0003)*

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| name | TEXT | NOT NULL | | |
| event_type | TEXT | NOT NULL | | e.g. holiday, road closure |
| start_at | TIMESTAMPTZ | NOT NULL | | |
| end_at | TIMESTAMPTZ | NOT NULL | | |
| impact_scope | JSONB | nullable | | Which devices/areas this affects |
| description | TEXT | nullable | | |
| created_by | TEXT | nullable | | |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

Index: `idx_traffic_events_window` on `(start_at, end_at)`.

## device_health_snapshots *(0003)*

| Field | Type | Nullable | Key | Description |
| --- | --- | --- | --- | --- |
| id | BIGSERIAL | NOT NULL | PK | |
| device_id | TEXT | NOT NULL | FK → devices | |
| snapshot_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |
| health_status | TEXT | NOT NULL | CHECK IN (`HEALTHY`,`DEGRADED`,`SUSPICIOUS`,`OFFLINE`,`RECOVERING`) | |
| signals | JSONB | NOT NULL (default `{}`) | | Which detector(s) contributed |
| created_at | TIMESTAMPTZ | NOT NULL (default `now()`) | | |

Index: `idx_device_health_snapshots_device` on `(device_id, snapshot_at DESC)`.
