"""Forwarding outbox (Backend/app/domains/forwarding/service.py, SRS 3.5/3.9):
enqueue -> data_classification passthrough, and run_once's send/dead-letter
paths. Complements the pure-function `_due_predicate` coverage already in
test_reconstruction.py. Monkeypatched collaborators, no real DB/HTTP."""

from datetime import datetime, timezone

from Backend.app.domains.forwarding import service as forwarding_service

POOL = object()


def _recorder(return_value=None):
    calls = []

    async def _fn(*args, **kwargs):
        calls.append((args, kwargs))
        return return_value

    _fn.calls = calls
    return _fn


async def test_enqueue_forwards_data_classification_to_queries(monkeypatch):
    """Guards against exactly the kind of signature drift where a caller
    passes `data_classification=` as a keyword but the callee dropped it —
    every call site in this codebase (ingestion/records/reconstruction)
    relies on this staying in sync."""
    queries_enqueue = _recorder()
    monkeypatch.setattr(forwarding_service.queries, "enqueue", queries_enqueue)

    timestamp = datetime.now(timezone.utc)
    await forwarding_service.enqueue(
        POOL, "cam-01", timestamp, {"counts": {"سواری": 5}},
        data_classification="reconstructed",
    )

    assert len(queries_enqueue.calls) == 1
    args, _kwargs = queries_enqueue.calls[0]
    assert args[1] == "cam-01"
    assert args[2] == timestamp
    assert args[4] == "reconstructed"


async def test_run_once_marks_successful_send(monkeypatch):
    row = {
        "id": 1,
        "device_id": "cam-01",
        "payload": {"device_id": "cam-01"},
        "attempt_count": 0,
        "last_attempt_at": None,
    }
    fetch_pending = _recorder(return_value=[row])
    record_attempt_result = _recorder()
    record_audit = _recorder()
    raise_alert = _recorder()

    monkeypatch.setattr(
        forwarding_service.queries, "fetch_pending_or_failed", fetch_pending
    )
    monkeypatch.setattr(
        forwarding_service.queries, "record_attempt_result", record_attempt_result
    )
    monkeypatch.setattr(forwarding_service, "record_audit", record_audit)
    monkeypatch.setattr(forwarding_service, "raise_alert", raise_alert)

    async def fake_send(client, url, api_key, payload):
        return 200, "ok"

    monkeypatch.setattr(forwarding_service, "_send", fake_send)

    sent = await forwarding_service.run_once(POOL)

    assert sent == 1
    assert len(record_attempt_result.calls) == 1
    args, _ = record_attempt_result.calls[0]
    assert args[2] == "sent"  # new_status
    assert not raise_alert.calls  # success never raises a forwarding alert


async def test_run_once_marks_dead_letter_after_max_attempts(monkeypatch):
    row = {
        "id": 2,
        "device_id": "cam-01",
        "payload": {"device_id": "cam-01"},
        "attempt_count": 7,  # settings.forwarding_max_attempts default is 8
        "last_attempt_at": None,
    }
    fetch_pending = _recorder(return_value=[row])
    record_attempt_result = _recorder()
    record_audit = _recorder()
    raise_alert = _recorder()

    monkeypatch.setattr(
        forwarding_service.queries, "fetch_pending_or_failed", fetch_pending
    )
    monkeypatch.setattr(
        forwarding_service.queries, "record_attempt_result", record_attempt_result
    )
    monkeypatch.setattr(forwarding_service, "record_audit", record_audit)
    monkeypatch.setattr(forwarding_service, "raise_alert", raise_alert)

    async def fake_send(client, url, api_key, payload):
        return 500, "server error"

    monkeypatch.setattr(forwarding_service, "_send", fake_send)

    await forwarding_service.run_once(POOL)

    args, _ = record_attempt_result.calls[0]
    assert args[2] == "dead_letter"
    assert len(raise_alert.calls) == 1
    (_, alert_kwargs) = raise_alert.calls[0]
    assert alert_kwargs["alert_type"] == "forwarding_failed"
    assert alert_kwargs["severity"] == "critical"
