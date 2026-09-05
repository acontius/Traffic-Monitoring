"""Ingestion edge cases (Backend/app/domains/ingestion/service.py) not
covered by the pure validate_structure tests in test_validation.py: invalid
JSON, wrong device_id, and confirming a rejected message never reaches
persistence/forwarding. Same house style as test_ml_reconstruction.py — no
real DB/socket, monkeypatched collaborators, `_async_return` fakes."""

from datetime import datetime, timezone

from Backend.app.domains.ingestion import service as ingestion_service

POOL = object()  # never actually touched by the monkeypatched collaborators


def _async_return(value=None):
    async def _fn(*args, **kwargs):
        return value

    return _fn


def _recorder():
    calls = []

    async def _fn(*args, **kwargs):
        calls.append((args, kwargs))

    _fn.calls = calls
    return _fn


def _patch_collaborators(monkeypatch):
    """Every downstream call `handle_message` could make, replaced with a
    recorder so a test can assert exactly which ones actually ran."""
    raise_alert = _recorder()
    record_audit = _recorder()
    upsert_ingested = _recorder()
    mark_online = _recorder()
    enqueue = _recorder()
    broadcast = _recorder()

    monkeypatch.setattr(ingestion_service.notifications_service, "raise_alert", raise_alert)
    monkeypatch.setattr(ingestion_service, "record_audit", record_audit)
    monkeypatch.setattr(ingestion_service.records_queries, "upsert_ingested", upsert_ingested)
    monkeypatch.setattr(ingestion_service.devices_queries, "mark_online", mark_online)
    monkeypatch.setattr(ingestion_service.forwarding_service, "enqueue", enqueue)
    monkeypatch.setattr(ingestion_service, "broadcast_device_update", broadcast)

    return {
        "raise_alert": raise_alert,
        "record_audit": record_audit,
        "upsert_ingested": upsert_ingested,
        "mark_online": mark_online,
        "enqueue": enqueue,
        "broadcast": broadcast,
    }


async def test_invalid_json_raises_alert_and_does_not_crash(monkeypatch):
    calls = _patch_collaborators(monkeypatch)

    await ingestion_service.handle_message(
        POOL, "cam-01", "urban", "{invalid-json", ip_address=None
    )

    assert len(calls["raise_alert"].calls) == 1
    (_, kwargs) = calls["raise_alert"].calls[0]
    assert kwargs["alert_type"] == "invalid_payload"
    assert not calls["upsert_ingested"].calls
    assert not calls["enqueue"].calls


async def test_invalid_structure_rejected_with_alert_and_audit(monkeypatch):
    calls = _patch_collaborators(monkeypatch)
    message = '{"device_id": "cam-01", "foo": "bar"}'

    await ingestion_service.handle_message(
        POOL, "cam-01", "urban", message, ip_address=None
    )

    assert len(calls["raise_alert"].calls) == 1
    assert len(calls["record_audit"].calls) == 1
    (_, kwargs) = calls["record_audit"].calls[0]
    assert kwargs["action"] == "ingest_rejected"
    assert not calls["upsert_ingested"].calls
    assert not calls["enqueue"].calls


async def test_negative_counts_rejected_before_persistence(monkeypatch):
    calls = _patch_collaborators(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    message = (
        '{"device_id": "cam-01", "timestamp": "%s", '
        '"counts": {"سواری": -10}}' % now
    )

    await ingestion_service.handle_message(
        POOL, "cam-01", "urban", message, ip_address=None
    )

    assert len(calls["raise_alert"].calls) == 1
    assert len(calls["record_audit"].calls) == 1
    assert not calls["upsert_ingested"].calls


async def test_wrong_device_id_rejected_no_persistence(monkeypatch):
    """Connection authenticated as cam-01, payload claims to be cam-99 —
    the mismatch check in handle_message must reject it without storing
    anything (no ValidationError is raised here, this is a separate check)."""
    calls = _patch_collaborators(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    message = (
        '{"device_id": "cam-99", "timestamp": "%s", '
        '"counts": {"سواری": 10}}' % now
    )

    await ingestion_service.handle_message(
        POOL, "cam-01", "urban", message, ip_address=None
    )

    assert len(calls["raise_alert"].calls) == 1
    (_, kwargs) = calls["raise_alert"].calls[0]
    assert kwargs["alert_type"] == "invalid_payload"
    assert not calls["upsert_ingested"].calls
    assert not calls["enqueue"].calls
