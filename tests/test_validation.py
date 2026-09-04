from datetime import datetime, timedelta, timezone

import pytest

from Backend.app.domains.ingestion.validation import ValidationError, validate_structure


def _valid_payload(**overrides):
    payload = {
        "device_id": "cam-01",
        "location_type": "urban",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "interval_minutes": 5,
        "counts": {"سواری": 10, "کامیون": 2},
    }
    payload.update(overrides)
    return payload


def test_validate_structure_accepts_well_formed_payload():
    device_id, timestamp, counts, interval = validate_structure(_valid_payload())
    assert device_id == "cam-01"
    assert counts == {"سواری": 10, "کامیون": 2}
    assert interval == 5


def test_validate_structure_rejects_missing_device_id():
    with pytest.raises(ValidationError):
        validate_structure(_valid_payload(device_id=""))


def test_validate_structure_rejects_bad_timestamp():
    with pytest.raises(ValidationError):
        validate_structure(_valid_payload(timestamp="not-a-date"))


def test_validate_structure_rejects_future_timestamp():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with pytest.raises(ValidationError):
        validate_structure(_valid_payload(timestamp=future))


def test_validate_structure_rejects_stale_timestamp():
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with pytest.raises(ValidationError):
        validate_structure(_valid_payload(timestamp=old))


def test_validate_structure_rejects_negative_counts():
    with pytest.raises(ValidationError):
        validate_structure(_valid_payload(counts={"سواری": -1}))


def test_validate_structure_rejects_empty_counts():
    with pytest.raises(ValidationError):
        validate_structure(_valid_payload(counts={}))
