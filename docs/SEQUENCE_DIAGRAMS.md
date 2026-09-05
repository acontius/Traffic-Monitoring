# Sequence Diagrams

Every actor and step name below matches a real function/endpoint in the
codebase (file references given), not a generic placeholder.

## A. Device ingestion

Files: `Backend/app/domains/ingestion/router.py`,
`Backend/app/domains/ingestion/service.py::handle_message`.

```mermaid
sequenceDiagram
    participant Cam as Camera / Simulator
    participant WS as /ws/ingest (router.py)
    participant Svc as ingestion.service.handle_message
    participant Val as ingestion.validation
    participant ML as ml.service.quick_score / enrich_and_score
    participant DB as PostgreSQL
    participant Alert as notifications.service.raise_alert
    participant Fwd as forwarding.service.enqueue
    participant Live as realtime.bus (/ws/live)

    Cam->>WS: connect ?device_id&token
    WS->>Svc: authenticate()
    Svc->>DB: device_exists()
    alt unauthenticated / unknown device
        WS-->>Cam: close(1008 policy violation)
    else authenticated
        WS-->>Cam: accept()
        loop every reading
            Cam->>WS: send(JSON payload)
            WS->>Svc: handle_message(message)
            Svc->>Svc: json.loads
            alt invalid JSON
                Svc->>Alert: raise_alert(invalid_payload)
                Svc-->>WS: return (connection stays open)
            else valid JSON
                Svc->>Val: validate_structure(raw)
                alt structurally invalid / negative counts / bad timestamp
                    Svc->>Alert: raise_alert(invalid_payload)
                    Svc->>DB: audit_log(ingest_rejected)
                    Svc-->>WS: return
                else device_id mismatch
                    Svc->>Alert: raise_alert(invalid_payload)
                    Svc-->>WS: return
                else valid
                    Svc->>Val: detect_anomaly (z-score)
                    Svc->>ML: quick_score (MAD/rule violations)
                    Svc->>DB: upsert_ingested(payload, anomaly_flag)
                    Svc->>DB: mark_online(device_id)
                    opt anomaly detected
                        Svc->>Alert: raise_alert(statistical_anomaly)
                    end
                    Svc->>Fwd: enqueue(payload, data_classification=original)
                    Svc->>Live: broadcast_device_update
                    Svc->>ML: enrich_and_score (background task)
                end
            end
        end
    end
```

## B. Missing data / reconstruction

Files: `Backend/app/domains/reconstruction/engine.py`,
`Backend/app/ml/reconstruction.py`, `Backend/app/ml/health.py`.

```mermaid
sequenceDiagram
    participant Worker as reconstruction.worker (timer)
    participant Engine as reconstruction.engine.run_once
    participant Health as ml.health.assess_health
    participant Hier as ml.reconstruction (4-level hierarchy)
    participant Policy as ml.policy.decide_reconstruction
    participant DB as PostgreSQL
    participant Alert as notifications.service.raise_alert
    participant Live as realtime.bus (/ws/live)

    Note over Worker: fires every TCMS_RECONSTRUCTION_SCAN_INTERVAL_SECONDS
    Worker->>Engine: run_once(pool)
    Engine->>DB: find devices with a gap past expected_interval * (1+grace)
    loop each gap found
        Engine->>Health: assess_health(recent records)
        Engine->>Hier: try_ml_prediction / try_historical_analogue / try_seasonal_profile / try_neighbor_devices
        Hier-->>Engine: LevelResult(counts, confidence, level) or None per level
        alt no level produced a result
            Engine->>Engine: legacy weighted-formula engine (level 5)
        end
        Engine->>Policy: decide_reconstruction(confidence, health)
        alt AUTO_RECONSTRUCT
            Engine->>DB: upsert_reconstructed_or_manual
            Engine->>DB: reconstruction_log (method, confidence, level)
            Engine->>Live: broadcast_reconstruction_event
        else RECONSTRUCT_AND_ALERT
            Engine->>DB: upsert_reconstructed_or_manual
            Engine->>DB: reconstruction_log
            Engine->>Alert: raise_alert(low_reconstruction_confidence)
        else MANUAL_REVIEW
            Engine->>DB: reconstruction_log (no counts, review_status=pending_review)
            Engine->>Alert: raise_alert(manual_review_required)
        end
    end
```

## C. Authentication

Files: `Backend/app/domains/auth/router.py`,
`Backend/app/domains/auth/service.py`, `Backend/app/core/security.py`.

```mermaid
sequenceDiagram
    participant User as Operator
    participant FE as Angular Frontend
    participant API as POST /auth/login
    participant Svc as auth.service.login
    participant Sec as core.security
    participant DB as PostgreSQL

    User->>FE: enter username/password
    FE->>API: POST /auth/login
    API->>Svc: login(username, password)
    Svc->>DB: get_user_by_username
    Svc->>Sec: verify_password(bcrypt)
    alt invalid credentials
        Svc->>DB: audit_log(login_failed)
        API-->>FE: 401
    else valid
        Svc->>Sec: create_access_token (JWT, short-lived)
        Svc->>Sec: generate_refresh_token (opaque, hashed before storage)
        Svc->>DB: insert_refresh_token
        Svc->>DB: audit_log(login)
        API-->>FE: {access_token, refresh_token}
        FE->>FE: store both, attach Bearer header on every request
    end
    Note over FE,API: on 401, auth.interceptor.ts calls POST /auth/refresh automatically
```

## D. Reporting

Files: `Backend/app/domains/reports/router.py`,
`Backend/app/domains/reports/service.py`.

```mermaid
sequenceDiagram
    participant User as Operator
    participant FE as Angular Frontend (Reports page)
    participant API as GET /reports
    participant Svc as reports.service
    participant DB as PostgreSQL

    User->>FE: choose filters (device/location/date range/format)
    FE->>API: GET /reports?device_id&location_type&date_from&date_to&format
    alt format=json
        API->>Svc: get_json(filters)
        Svc->>DB: SELECT ... traffic_records
        Svc-->>API: rows
        API-->>FE: JSON array
    else format=csv
        API->>Svc: get_csv(filters)
        Svc->>DB: SELECT ... traffic_records
        Svc-->>API: CSV text
        API-->>FE: StreamingResponse (Content-Disposition: attachment)
    end
```
