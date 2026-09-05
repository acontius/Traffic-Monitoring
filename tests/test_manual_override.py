"""Manual override (Backend/app/domains/records/service.py::manual_override,
SRS 3.9): an operator must be able to overwrite a reconstructed (or bad)
value by hand, with the result logged to reconstruction_log, audit_log, and
re-queued for forwarding. Same monkeypatched-collaborators style as
test_ingestion.py — no real DB."""

from datetime import datetime, timezone

from Backend.app.domains.records import service as records_service

POOL = object()


def _recorder():
    calls = []

    async def _fn(*args, **kwargs):
        calls.append((args, kwargs))

    _fn.calls = calls
    return _fn


async def test_manual_override_logs_reconstruction_audit_and_forwarding(monkeypatch):
    async def _location_type(*args, **kwargs):
        return "urban"

    upsert = _recorder()
    log_manual_override = _recorder()
    record_audit = _recorder()
    enqueue = _recorder()

    monkeypatch.setattr(records_service.devices_queries, "get_location_type", _location_type)
    monkeypatch.setattr(records_service.queries, "upsert_reconstructed_or_manual", upsert)
    monkeypatch.setattr(
        records_service.reconstruction_service, "log_manual_override", log_manual_override
    )
    monkeypatch.setattr(records_service, "record_audit", record_audit)
    monkeypatch.setattr(records_service.forwarding_service, "enqueue", enqueue)

    timestamp = datetime.now(timezone.utc)
    counts = {"سواری": 22, "کامیون": 4}

    await records_service.manual_override(
        POOL,
        device_id="cam-01",
        timestamp=timestamp,
        counts=counts,
        reason="camera was offline, operator estimate",
        actor="admin",
    )

    assert len(upsert.calls) == 1
    ((_, dev_id, ts, payload), _kwargs) = upsert.calls[0]
    assert dev_id == "cam-01"
    assert ts == timestamp
    assert payload["counts"] == counts
    assert payload["manual_override"] is True

    assert len(log_manual_override.calls) == 1
    log_args = log_manual_override.calls[0][0]
    # call site: reconstruction_service.log_manual_override(pool, device_id,
    # timestamp, reason, counts, actor)
    assert log_args[1] == "cam-01"  # device_id
    assert log_args[5] == "admin"  # actor

    assert len(record_audit.calls) == 1
    (_, audit_kwargs) = record_audit.calls[0]
    assert audit_kwargs["actor"] == "admin"
    assert audit_kwargs["action"] == "manual_override"
    assert audit_kwargs["details"]["counts"] == counts

    # This is exactly the call site that would raise TypeError if
    # forwarding_service.enqueue's signature ever drifted from its callers
    # (data_classification is passed as a keyword by every caller in this
    # codebase) — verified here rather than assumed.
    assert len(enqueue.calls) == 1
    (_, enqueue_kwargs) = enqueue.calls[0]
    assert enqueue_kwargs["data_classification"] == "manual_override"
