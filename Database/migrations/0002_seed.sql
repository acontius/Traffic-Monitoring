-- Default reconstruction formula weights. Editable later via
-- PUT /reconstruction/config — this is only the fallback used when no
-- device- or location_type-specific row exists.
INSERT INTO reconstruction_config (scope_type, scope_value, weights)
VALUES (
    'default',
    NULL,
    '{
        "historical_window_days": 28,
        "time_of_day_weight": 0.6,
        "day_of_week_weight": 0.3,
        "recent_trend_weight": 0.1,
        "device_performance_coefficient": 1.0,
        "environmental_modifiers": {
            "weather": 1.0,
            "holiday": 1.0,
            "related_axis": 1.0,
            "connected_points": 1.0
        }
    }'::jsonb
)
ON CONFLICT (scope_type, scope_value) DO NOTHING;

-- Seed devices matching the existing simulator fleet
-- (Backend/Devices/cameras.py: build_default_devices).
INSERT INTO devices (device_id, location_type, label, latitude, longitude, expected_interval_seconds)
VALUES
    ('cam-01', 'urban',      'دوربین شهری ۱',  35.7008, 51.3890, 300),
    ('cam-02', 'urban',      'دوربین شهری ۲',  35.7095, 51.4060, 300),
    ('cam-03', 'highway',    'دوربین اتوبان ۱', 35.7340, 51.4480, 300),
    ('cam-04', 'industrial', 'دوربین صنعتی',   35.7685, 51.4870, 300),
    ('cam-05', 'highway',    'دوربین اتوبان ۲', 35.7440, 51.4625, 300)
ON CONFLICT (device_id) DO NOTHING;
