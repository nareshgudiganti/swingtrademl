"""M06's offline trainer: turn the base models' scores and some market/stock
context into ONE calibrated probability of reaching +8% before -4% within
15 trading days — and prove it on months no model has seen.

Three candidates are compared by monthly walk-forward on the unseen window:

* raw_barrier        the barrier model's own score (reported, never chosen)
* calibrated_barrier that score passed through isotonic calibration
* meta               a small logistic model on 8 inputs (META_INPUTS)

The meta-model is adopted only if its out-of-sample Brier score beats the
calibrated barrier's (by `prefer_simpler_margin`); otherwise the simpler
calibration wins and the report says why. Pure: works on a DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

LABEL_HORIZON_DAYS = 15
META_INPUTS: tuple[str, ...] = (
    "logit_barrier",
    "logit_swing",
    "nifty_trend_regime",
    "breadth_pct_above_sma50",
    "vix_percentile_rank",
    "relative_strength_20d",
    "high_52w_dist",
    "sector_trend_regime",
)
BUCKET_EDGES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0)


def _logit(p: pd.Series | np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _with_logits(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["logit_barrier"] = _logit(out["p_barrier"])
    out["logit_swing"] = _logit(out["p_swing"]) if "p_swing" in out else 0.0
    return out


# --- splitting -------------------------------------------------------------------


def unseen_rows(
    frame: pd.DataFrame, train_end: pd.Timestamp, purge_days: int = LABEL_HORIZON_DAYS
) -> pd.DataFrame:
    """Rows the base models never saw: after `train_end`, plus a purge long
    enough that no label window reaches back into the training period."""
    start = pd.Timestamp(train_end) + BDay(purge_days)
    return frame[frame["day"] > start].reset_index(drop=True)


def monthly_folds(frame: pd.DataFrame, min_train_months: int = 3) -> list[tuple[pd.Index, pd.Index]]:
    """Expanding monthly walk-forward. Training rows whose 15-day label window
    reaches into the test month are dropped (their outcome depends on prices
    the test month is about)."""
    months = frame["day"].dt.to_period("M")
    ordered = sorted(months.unique())
    folds = []
    for i in range(min_train_months, len(ordered)):
        test_month = ordered[i]
        test_start = test_month.to_timestamp()
        purge_from = test_start - BDay(LABEL_HORIZON_DAYS)
        train_idx = frame.index[(months < test_month) & (frame["day"] < purge_from)]
        test_idx = frame.index[months == test_month]
        if len(train_idx) and len(test_idx):
            folds.append((train_idx, test_idx))
    return folds


# --- calibration ---------------------------------------------------------------------


def calibration_buckets(p: np.ndarray, y: np.ndarray, edges: tuple[float, ...] = BUCKET_EDGES) -> list[dict]:
    """For each probability band: how many cases, the average promised chance,
    and how often it really happened."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    out = []
    for i, (lo, hi) in enumerate(pairwise(edges)):
        last = i == len(edges) - 2
        mask = (p >= lo) & ((p <= hi) if last else (p < hi))
        n = int(mask.sum())
        if n:
            out.append(
                {
                    "low": lo,
                    "high": hi,
                    "n": n,
                    "mean_p": float(p[mask].mean()),
                    "actual": float(y[mask].mean()),
                }
            )
    return out


# --- the combiner ----------------------------------------------------------------------


@dataclass
class Combiner:
    kind: str  # raw_barrier | calibrated_barrier | meta
    inputs: list[str] = field(default_factory=list)
    model: Any = None

    @classmethod
    def fit(cls, frame: pd.DataFrame, kind: str) -> Combiner:
        frame = _with_logits(frame)
        y = frame["target"].astype(int).to_numpy()
        if kind == "raw_barrier":
            return cls(kind, ["p_barrier"])
        if kind == "calibrated_barrier":
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(frame["p_barrier"].to_numpy(), y)
            return cls(kind, ["p_barrier"], iso)
        if kind == "meta":
            pipe = make_pipeline(
                SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)
            )
            pipe.fit(frame[list(META_INPUTS)].to_numpy(dtype=float), y)
            return cls(kind, list(META_INPUTS), pipe)
        raise ValueError(f"unknown combiner kind {kind!r}")

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        frame = _with_logits(frame)
        if self.kind == "raw_barrier":
            return frame["p_barrier"].to_numpy(dtype=float)
        if self.kind == "calibrated_barrier":
            return self.model.predict(frame["p_barrier"].to_numpy(dtype=float))
        return self.model.predict_proba(frame[self.inputs].to_numpy(dtype=float))[:, 1]


# --- evaluation ----------------------------------------------------------------------------


def _metrics(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    top = p >= np.quantile(p, 0.9)
    return {
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "auc": float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
        "top_decile_hit_rate": float(y[top].mean()) if top.any() else None,
        "calibration": calibration_buckets(p, y),
    }


def evaluate(frame: pd.DataFrame, min_train_months: int = 3, prefer_simpler_margin: float = 0.0005) -> dict:
    frame = frame.sort_values("day").reset_index(drop=True)
    folds = monthly_folds(frame, min_train_months)
    preds: dict[str, list[np.ndarray]] = {"raw_barrier": [], "calibrated_barrier": [], "meta": []}
    ys: list[np.ndarray] = []
    for train_idx, test_idx in folds:
        train, test = frame.loc[train_idx], frame.loc[test_idx]
        for kind in preds:
            preds[kind].append(Combiner.fit(train, kind).predict(test))
        ys.append(test["target"].astype(int).to_numpy())

    if not folds:
        return {
            "folds": 0,
            "n_test_rows": 0,
            "chosen": None,
            "why": "Not enough unseen months to test a combiner (need at least 4).",
            "candidates": {},
        }

    y = np.concatenate(ys)
    candidates = {kind: _metrics(np.concatenate(p), y) for kind, p in preds.items()}
    meta, cal = candidates["meta"]["brier"], candidates["calibrated_barrier"]["brier"]
    if meta < cal - prefer_simpler_margin:
        chosen, why = (
            "meta",
            f"The meta-model's error {meta:.4f} beat calibration alone ({cal:.4f}) on unseen months.",
        )
    else:
        chosen, why = (
            "calibrated_barrier",
            (
                f"The meta-model ({meta:.4f}) did not beat calibration alone ({cal:.4f}) by enough, "
                "so the simpler calibrated barrier score is used."
            ),
        )
    return {
        "folds": len(folds),
        "n_test_rows": len(y),
        "base_rate": float(y.mean()),
        "window_start": str(frame["day"].min().date()),
        "window_end": str(frame["day"].max().date()),
        "candidates": candidates,
        "chosen": chosen,
        "why": why,
    }
