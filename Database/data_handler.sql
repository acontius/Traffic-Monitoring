CREATE TABLE traffic_data
(
    device_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    payload   JSONB NOT NULL,
    PRIMARY KEY (device_id, timestamp)
);

SELECT create_hypertable('traffic_data', 'timestamp');

SELECT * FROM traffic_data;
