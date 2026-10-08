"""Probability calibration for the barrier model (opt-in).

`class_weight="balanced"` makes the raw model over-state its confidence: when
only ~25% of bars hit +8% before -4%, a raw "0.70" does not mean "hits 70% of
the time". The wrapper below learns the real hit rate for each raw score on a
LATER slice of the training window and replays it at serve time.

It exposes `predict_proba`, `predict` and `feature_importances_` like a plain
scikit-learn estimator, so every existing serving path (ml/predict.py,
strategies/ml_swing.py, long_term_value.py) uses it without any change.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression

RELIABILITY_EDGES = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0000001)


class CalibratedEstimator:
    def __init__(self, base: Any, calibrator: IsotonicRegression):
        self.base = base
        self.calibrator = calibrator

    @classmethod
    def fit(cls, base: Any, x_cal: np.ndarray, y_cal: np.ndarray) -> CalibratedEstimator:
        raw = base.predict_proba(x_cal)[:, 1]
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(raw, y_cal)
        return cls(base, iso)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        raw = self.base.predict_proba(x)[:, 1]
        p = np.clip(self.calibrator.predict(raw), 0.0, 1.0)
        return np.column_stack([1.0 - p, p])

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.base.predict(x)

    @property
    def feature_importances_(self) -> np.ndarray:
        return self.base.feature_importances_


def reliability_table(y_true: np.ndarray, proba: np.ndarray) -> list[dict[str, Any]]:
    """Per confidence band: how many predictions, mean stated confidence, and
    the share that really hit target-before-stop."""
    rows: list[dict[str, Any]] = []
    for lo, hi in pairwise(RELIABILITY_EDGES):
        mask = (proba >= lo) & (proba < hi)
        n = int(mask.sum())
        rows.append(
            {
                "band": f"{lo:.2f}-{min(hi, 1.0):.2f}",
                "n": n,
                "mean_confidence": float(proba[mask].mean()) if n else None,
                "hit_rate": float(y_true[mask].mean()) if n else None,
            }
        )
    return rows
