"""Central runtime configuration, read from environment variables.

Keeping every tunable here (rather than scattered literals) is what lets the
reconstruction/forwarding/notification modules be reconfigured without a
redeploy, per the SRS non-functional requirements.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": the shared .env also carries TCMS_-prefixed settings for
    # the device simulator and the create_admin script (TCMS_HUB_WS_URL,
    # TCMS_ADMIN_USERNAME, ...) that aren't fields of the app's own Settings.
    model_config = SettingsConfigDict(
        env_prefix="TCMS_", env_file=".env", extra="ignore"
    )

    # Database
    db_dsn: str = "postgresql://acontius:1234@localhost:5432/traffic_monitoring"

    # Auth / JWT
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expires_minutes: int = 15
    refresh_token_expires_days: int = 7

    # CORS
    cors_origins: list[str] = ["*"]

    # Ingestion
    device_shared_token: str = "change-me-device-token"

    # Reconstruction engine
    reconstruction_scan_interval_seconds: int = 60
    reconstruction_grace_periods: int = 1  # missed intervals before reconstructing

    # Forwarding (road-authority / راهداری web service)
    road_authority_webhook_url: str = "http://localhost:9100/mock-road-authority"
    road_authority_api_key: str = ""
    forwarding_worker_interval_seconds: int = 15
    forwarding_max_attempts: int = 8
    forwarding_backoff_base_seconds: int = 10

    # SMS gateway (used for critical alerts)
    sms_gateway_url: str = "http://localhost:9100/mock-sms"
    sms_gateway_api_key: str = ""
    sms_recipients: list[str] = []

    # Reporting
    report_default_page_size: int = 1000

    # Traffic timezone — every temporal/calendar feature the ML layer builds
    # is computed in this zone, never the server's local zone.
    traffic_timezone: str = "Asia/Tehran"

    # ML layer (docs/ML_ARCHITECTURE.md)
    ml_enabled: bool = True
    ml_model_type: str = "hist_gradient_boosting"
    ml_retrain_interval_hours: int = 24
    ml_min_history_points: int = 200
    ml_min_confidence: float = 0.80
    ml_review_confidence: float = 0.60
    ml_anomaly_threshold: float = 0.5
    ml_high_anomaly_threshold: float = 0.8
    ml_enable_cross_device_context: bool = True
    ml_enable_event_context: bool = True
    ml_train_on_reconstructed: bool = False
    device_health_scan_interval_seconds: int = 60
    forward_low_confidence_reconstructions: bool = False

    # Optional OpenRouter explanation service — advisory only, never used for
    # the numerical pipeline. Disabled by default; the system is fully
    # functional with ml_ai_enabled=false.
    ai_enabled: bool = False
    ai_provider: str = "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    ai_timeout_seconds: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
