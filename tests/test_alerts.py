"""notifications.service.raise_alert (SRS 3.8): persists the alert, pushes
it to the live dashboard bus, and sends SMS only for critical severity.
Monkeypatched collaborators, no real DB/socket — same style as
test_ingestion.py."""

from datetime import datetime, timezone

from Backend.app.domains.notifications import service as notifications_service

POOL = object()


def _recorder(return_value=None):
    calls = []

    async def _fn(*args, **kwargs):
        calls.append((args, kwargs))
        return return_value

    _fn.calls = calls
    return _fn


async def test_raise_alert_persists_and_broadcasts_without_sms_by_default(monkeypatch):
    row = {"id": 42, "created_at": datetime.now(timezone.utc)}
    insert_alert = _recorder(return_value=row)
    broadcast_alert = _recorder()
    send_sms_alert = _recorder()

    monkeypatch.setattr(notifications_service.alerts_queries, "insert_alert", insert_alert)
    monkeypatch.setattr(notifications_service, "broadcast_alert", broadcast_alert)
    monkeypatch.setattr(notifications_service, "send_sms_alert", send_sms_alert)

    alert_id = await notifications_service.raise_alert(
        POOL,
        alert_type="invalid_payload",
        message="داده نامعتبر",
        severity="warning",
        device_id="cam-01",
    )

    assert alert_id == 42
    assert len(insert_alert.calls) == 1
    assert len(broadcast_alert.calls) == 1
    (broadcast_args, _) = broadcast_alert.calls[0]
    assert broadcast_args[0]["type"] == "invalid_payload"
    assert broadcast_args[0]["device_id"] == "cam-01"
    # warning severity must not trigger SMS
    assert not send_sms_alert.calls


async def test_raise_alert_sends_sms_only_for_critical_severity(monkeypatch):
    row = {"id": 7, "created_at": datetime.now(timezone.utc)}
    insert_alert = _recorder(return_value=row)
    broadcast_alert = _recorder()
    send_sms_alert = _recorder()

    monkeypatch.setattr(notifications_service.alerts_queries, "insert_alert", insert_alert)
    monkeypatch.setattr(notifications_service, "broadcast_alert", broadcast_alert)
    monkeypatch.setattr(notifications_service, "send_sms_alert", send_sms_alert)

    await notifications_service.raise_alert(
        POOL,
        alert_type="forwarding_failed",
        message="ارسال ناموفق بود",
        severity="critical",
        device_id="cam-01",
    )

    assert len(send_sms_alert.calls) == 1
    (sms_args, _) = send_sms_alert.calls[0]
    assert sms_args[0] == "ارسال ناموفق بود"
