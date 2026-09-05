"""core.audit.record — the shared audit-trail writer used by auth, ingestion,
manual override, reconstruction, and forwarding. No real DB: a minimal fake
pool/connection records the exact SQL args passed, matching the row shape
in Database/migrations/0001_init.sql's audit_log table."""

import json

from Backend.app.core.audit import record


class _FakeConnection:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self):
        self.connection = _FakeConnection()

    def acquire(self):
        return self.connection


async def test_record_writes_expected_row_shape():
    pool = _FakePool()

    await record(
        pool,
        actor="admin",
        action="manual_override",
        entity="traffic_records",
        entity_id="cam-01@2026-01-01T00:00:00+00:00",
        details={"counts": {"سواری": 10}, "reason": "test"},
    )

    assert len(pool.connection.executed) == 1
    query, args = pool.connection.executed[0]
    assert "INSERT INTO audit_log" in query
    actor, action, entity, entity_id, details_json = args
    assert actor == "admin"
    assert action == "manual_override"
    assert entity == "traffic_records"
    assert entity_id == "cam-01@2026-01-01T00:00:00+00:00"
    assert json.loads(details_json) == {"counts": {"سواری": 10}, "reason": "test"}


async def test_record_allows_details_none():
    pool = _FakePool()

    await record(pool, actor="system", action="login_failed")

    _, args = pool.connection.executed[0]
    *_, details_json = args
    assert details_json is None
