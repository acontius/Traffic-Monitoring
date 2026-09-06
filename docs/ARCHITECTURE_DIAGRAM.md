# Architecture Diagram

Matches the real `docker-compose.yml` topology (5 services) and the
backend's actual domain breakdown (`Backend/app/domains/*`).

```mermaid
graph TB
    subgraph Devices["Field devices"]
        Cam["Traffic Cameras<br/>(or Backend/Devices/cameras.py simulator)"]
    end

    subgraph AppContainer["app (FastAPI, :8000)"]
        WS["/ws/ingest, /ws/live"]
        Val["Validation<br/>(ingestion.validation)"]
        Anomaly["Anomaly / ML scoring<br/>(ml.anomaly, ml.prediction)"]
        Recon["Reconstruction engine<br/>(reconstruction.engine, ml.reconstruction)"]
        Alerts["Alerts<br/>(notifications.service)"]
        Fwd["Forwarding outbox<br/>(forwarding.service/worker)"]
        Auth["Auth (JWT)<br/>(auth.service, core.security)"]
        Reports["Reporting<br/>(reports.service)"]
    end

    subgraph DB["db (TimescaleDB / PostgreSQL 16, :5432)"]
        Tables[("devices, traffic_records (hypertable),<br/>reconstruction_log/config, alerts,<br/>forwarding_log, users, refresh_tokens,<br/>audit_log, ml_models, ml_predictions,<br/>anomaly_events, traffic_events,<br/>device_health_snapshots")]
    end

    subgraph FE["frontend (Angular via nginx, :4200 -> :80)"]
        UI["Login, Dashboard, Device detail,<br/>Alerts, Reports, Manual Control"]
    end

    subgraph Mock["mock-external (:9100)"]
        RoadAuth["/mock-road-authority"]
        SMSGw["/mock-sms"]
    end

    Cam -->|WebSocket| WS
    WS --> Val --> Anomaly --> Recon
    Anomaly --> Alerts
    Recon --> Alerts
    Val -->|reject invalid| Alerts
    WS --> Fwd
    Recon --> Fwd
    AppContainer <-->|SQL| DB
    FE -->|REST + WebSocket, proxied via nginx /api/| AppContainer
    Fwd -->|HTTP POST, retry+backoff| RoadAuth
    Alerts -->|critical only, HTTP POST| SMSGw
```

Five Docker Compose services, no additional infrastructure (no
Redis/Celery/Kubernetes — the pipeline runs entirely inside `app`'s own
background asyncio tasks: reconstruction worker, forwarding worker, ML
health-scan worker, ML retrain worker, all started in `main.py`'s
`lifespan`).
