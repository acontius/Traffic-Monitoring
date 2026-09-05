"""Model A: expected-traffic regressor (spec §8), one
`HistGradientBoostingRegressor` per vehicle type, trained on pooled data from
all devices (device identity is implicit in the lag/rolling features, not an
input — see `docs/ML_ARCHITECTURE.md` for why).

`scikit-learn` is imported lazily. `HistGradientBoostingRegressor` natively
handles `NaN` features, which is what makes the cold-start story work: a
brand-new device has no lag/rolling history (all `NaN`) and the model falls
back to whatever it learned from the temporal/calendar/location-type
features alone — a location-type/global-temporal profile, exactly as spec
§22 asks for, without a separate code path.

If scikit-learn is unavailable, `Model.predict` always returns `None` and
callers fall back further down the reconstruction hierarchy — never to a
fabricated number.
"""

import logging
import statistics
from dataclasses import dataclass
from typing import Any, Optional

from Backend.app.ml.features import FEATURE_NAMES

logger = logging.getLogger("tcms.ml")

try:
    from sklearn.ensemble import HistGradientBoostingRegressor

    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    _HAS_SKLEARN = False
    logger.warning(
        "scikit-learn not available; ML prediction falls back to statistical "
        "methods only"
    )


@dataclass
class PredictionResult:
    value: float
    interval_low: float
    interval_high: float
    features_used: dict[str, float]


class Model:
    """Wraps one `HistGradientBoostingRegressor` for one vehicle type plus
    the residual quantiles needed for a prediction interval (a plain
    residual-based interval, not a second quantile-regression model, to keep
    training cheap and the interface swappable later — spec §51)."""

    def __init__(self, vehicle_type: str):
        self.vehicle_type = vehicle_type
        self._estimator: Optional[Any] = None
        self._residual_std: float = 0.0

    @property
    def is_trained(self) -> bool:
        return self._estimator is not None

    def fit(self, X: list[list[float]], y: list[float]) -> dict[str, float]:
        if not _HAS_SKLEARN:
            raise RuntimeError("scikit-learn is not installed")
        self._estimator = HistGradientBoostingRegressor(random_state=42)
        self._estimator.fit(X, y)
        residuals = [
            abs(actual - pred) for actual, pred in zip(y, self._estimator.predict(X))
        ]
        self._residual_std = statistics.pstdev(residuals) if len(residuals) > 1 else 0.0
        return {
            "train_residual_mad": statistics.median(residuals) if residuals else 0.0
        }

    def predict(self, row: dict[str, float]) -> Optional[PredictionResult]:
        if not self.is_trained:
            return None
        vector = [[row[name] for name in FEATURE_NAMES]]
        value = float(self._estimator.predict(vector)[0])
        value = max(0.0, value)
        margin = 1.96 * self._residual_std
        return PredictionResult(
            value=value,
            interval_low=max(0.0, value - margin),
            interval_high=value + margin,
            features_used=dict(row),
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "vehicle_type": self.vehicle_type,
            "estimator": self._estimator,
            "residual_std": self._residual_std,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "Model":
        model = cls(state["vehicle_type"])
        model._estimator = state["estimator"]
        model._residual_std = state["residual_std"]
        return model


def seasonal_profile_estimate(
    history: list[dict], vehicle_type: str
) -> Optional[PredictionResult]:
    """Cold-start / no-model fallback: a plain average over whatever
    same-interval-of-day history is available (spec §22 step 3/4). Callers
    typically pass `features.historical_analogues(...)` as `history`."""
    values = [float(r["counts"].get(vehicle_type, 0)) for r in history]
    if not values:
        return None
    mean = statistics.mean(values)
    std = statistics.pstdev(values) if len(values) > 1 else mean * 0.5
    return PredictionResult(
        value=mean,
        interval_low=max(0.0, mean - 1.96 * std),
        interval_high=mean + 1.96 * std,
        features_used={"samples": len(values)},
    )
