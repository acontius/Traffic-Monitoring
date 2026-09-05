"""Hierarchical reconstruction level selection (Backend/app/ml/reconstruction.py).
Since there's no DB test harness in this repo, the DB reads
(`domains.ml.queries`) and model loading (`registry.load_active_model`) are
monkeypatched with in-memory fakes rather than a real pool — every resolver
here is otherwise a pure function of its history/samples.
"""

from datetime import datetime, timedelta, timezone

from Backend.app.ml import reconstruction as recon

NOW = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
POOL = object()  # never actually used by the monkeypatched queries


async def test_try_historical_analogue_none_with_too_few_samples(monkeypatch):
    monkeypatch.setattr(recon.ml_queries, "fetch_device_history", _async_return([]))
    result = await recon.try_historical_analogue(POOL, "cam-01", NOW, 300)
    assert result is None


async def test_try_historical_analogue_returns_confident_estimate(monkeypatch):
    history = [
        {"timestamp": NOW - timedelta(days=7 * w), "counts": {"سواری": 20 + w}}
        for w in range(1, 6)
    ]
    monkeypatch.setattr(
        recon.ml_queries, "fetch_device_history", _async_return(history)
    )
    result = await recon.try_historical_analogue(POOL, "cam-01", NOW, 300)
    assert result is not None
    assert result.level == "level2_historical_analogue"
    assert 0.0 < result.confidence <= 0.85
    assert result.counts["سواری"] > 0


async def test_try_seasonal_profile_none_with_too_few_samples(monkeypatch):
    monkeypatch.setattr(recon.ml_queries, "fetch_same_hour_history", _async_return([]))
    result = await recon.try_seasonal_profile(POOL, "cam-01", NOW)
    assert result is None


async def test_try_seasonal_profile_returns_estimate(monkeypatch):
    samples = [
        {"timestamp": NOW - timedelta(days=d), "counts": {"سواری": 15}}
        for d in range(1, 6)
    ]
    monkeypatch.setattr(
        recon.ml_queries, "fetch_same_hour_history", _async_return(samples)
    )
    result = await recon.try_seasonal_profile(POOL, "cam-01", NOW)
    assert result is not None
    assert result.level == "level3_seasonal_profile"
    assert result.counts["سواری"] == 15


async def test_try_neighbor_devices_none_with_too_few_neighbors(monkeypatch):
    monkeypatch.setattr(
        recon.ml_queries,
        "fetch_neighbor_recent",
        _async_return(
            [{"device_id": "cam-02", "timestamp": NOW, "counts": {"سواری": 30}}]
        ),
    )
    result = await recon.try_neighbor_devices(POOL, "cam-01", "urban", NOW, 300)
    assert result is None


async def test_try_neighbor_devices_scales_by_baseline_ratio(monkeypatch):
    neighbors = [
        {"device_id": "cam-02", "timestamp": NOW, "counts": {"سواری": 40}},
        {"device_id": "cam-03", "timestamp": NOW, "counts": {"سواری": 40}},
    ]
    monkeypatch.setattr(
        recon.ml_queries, "fetch_neighbor_recent", _async_return(neighbors)
    )

    async def fake_mean_totals(pool, device_id, limit=200):
        # cam-01 (the target) historically runs at half the neighbours' level.
        return {"cam-01": 20.0, "cam-02": 40.0, "cam-03": 40.0}[device_id]

    monkeypatch.setattr(recon.ml_queries, "fetch_device_mean_totals", fake_mean_totals)

    result = await recon.try_neighbor_devices(POOL, "cam-01", "urban", NOW, 300)
    assert result is not None
    assert result.level == "level4_neighbor_device"
    # Scaled down towards cam-01's own baseline (~half of the raw neighbour average).
    assert result.counts["سواری"] < 40


async def test_try_ml_prediction_none_with_insufficient_history(monkeypatch):
    monkeypatch.setattr(recon.ml_queries, "fetch_device_history", _async_return([]))
    result = await recon.try_ml_prediction(POOL, "cam-01", "urban", NOW, 300)
    assert result is None


async def test_try_ml_prediction_none_when_no_model_trained(monkeypatch):
    history = [
        {"timestamp": NOW - timedelta(minutes=5 * i), "counts": {"سواری": 10}}
        for i in range(1, 10)
    ]
    monkeypatch.setattr(
        recon.ml_queries, "fetch_device_history", _async_return(history)
    )
    monkeypatch.setattr(recon.ml_queries, "fetch_active_events", _async_return([]))
    monkeypatch.setattr(recon.registry, "load_active_model", _async_return(None))
    result = await recon.try_ml_prediction(POOL, "cam-01", "urban", NOW, 300)
    assert result is None  # no model contributed anything — never claim Level 1


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn
