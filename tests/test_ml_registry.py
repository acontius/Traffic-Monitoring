"""Model artifact save/load/rollback/versioning (Backend/app/ml/registry.py),
against an in-memory fake of the `ml_models` table (monkeypatched) and a
temp artifact directory — no real DB or trained sklearn model required, so
this test never overwrites a real artifact and stays independent of whether
scikit-learn is actually installed.
"""

from datetime import datetime, timezone

from Backend.app.ml import registry
from Backend.app.ml.prediction import Model

POOL = object()


class _FakeEstimator:
    """A trivial picklable stand-in for a fitted sklearn estimator."""

    def predict(self, X):
        return [1.0 for _ in X]


class _FakeModelStore:
    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.active: dict[str, int] = {}
        self._next_id = 1

    async def insert_model(
        self,
        pool,
        model_name,
        model_version,
        model_type,
        feature_version,
        metrics,
        artifact_path,
        checksum,
        training_data_range_start,
        training_data_range_end,
    ):
        row = {
            "id": self._next_id,
            "model_name": model_name,
            "model_version": model_version,
            "model_type": model_type,
            "feature_version": feature_version,
            "metrics": metrics,
            "artifact_path": artifact_path,
            "checksum": checksum,
            "is_active": False,
        }
        self.rows[row["id"]] = row
        self._next_id += 1
        return row

    async def set_active_model(self, pool, model_name, model_id):
        for row in self.rows.values():
            if row["model_name"] == model_name:
                row["is_active"] = row["id"] == model_id
        self.active[model_name] = model_id

    async def get_active_model(self, pool, model_name):
        model_id = self.active.get(model_name)
        return self.rows.get(model_id) if model_id else None


def _make_model(vehicle_type: str) -> Model:
    model = Model(vehicle_type)
    model._estimator = _FakeEstimator()
    model._residual_std = 2.5
    return model


async def test_save_and_load_round_trips_model_state(tmp_path, monkeypatch):
    store = _FakeModelStore()
    monkeypatch.setattr(registry, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(registry.ml_queries, "insert_model", store.insert_model)
    monkeypatch.setattr(registry.ml_queries, "set_active_model", store.set_active_model)
    monkeypatch.setattr(registry.ml_queries, "get_active_model", store.get_active_model)

    model = _make_model("سواری")
    saved = await registry.save_model(
        POOL,
        model,
        metrics={"mae": 1.2},
        training_data_range=(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 6, 1, tzinfo=timezone.utc),
        ),
    )
    assert saved["is_active"] is True

    loaded = await registry.load_active_model(POOL, "سواری")
    assert loaded is not None
    assert loaded.is_trained
    assert loaded._residual_std == 2.5


async def test_rollback_switches_active_model_without_deleting_history(
    tmp_path, monkeypatch
):
    store = _FakeModelStore()
    monkeypatch.setattr(registry, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(registry.ml_queries, "insert_model", store.insert_model)
    monkeypatch.setattr(registry.ml_queries, "set_active_model", store.set_active_model)
    monkeypatch.setattr(registry.ml_queries, "get_active_model", store.get_active_model)

    first = await registry.save_model(POOL, _make_model("سواری"), {}, (None, None))
    second = await registry.save_model(POOL, _make_model("سواری"), {}, (None, None))

    active = await registry.ml_queries.get_active_model(POOL, "expected_traffic:سواری")
    assert active["id"] == second["id"]

    await registry.rollback(POOL, "expected_traffic:سواری", first["id"])
    active = await registry.ml_queries.get_active_model(POOL, "expected_traffic:سواری")
    assert active["id"] == first["id"]
    # Both versions still exist — rollback never deletes history (spec §46).
    assert len(store.rows) == 2


async def test_load_active_model_returns_none_when_missing(tmp_path, monkeypatch):
    store = _FakeModelStore()
    monkeypatch.setattr(registry, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(registry.ml_queries, "get_active_model", store.get_active_model)
    result = await registry.load_active_model(POOL, "کامیون")
    assert result is None
