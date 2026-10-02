"""M06's offline trainer: turn the base models' scores and some market/stock
context into ONE calibrated probability of reaching +8% before -4% within
15 trading days — and prove it on months no model has seen.

Candidates compared by monthly walk-forward on the unseen window:

* base_rate    everyone gets the training base rate (a reference, never chosen)
* raw_barrier  the barrier model's own score
* meta         a small logistic model on 8 inputs (META_INPUTS)
* meta_recent  the same, with its probability LEVEL re-anchored on the last
               3 months (Platt scaling) — the hit rate swings with the market
               regime (3.5% to 35% a month in 2025-26), so a level learnt
               long ago drifts

Lesson from the first real run: the lowest error alone can be won by a
constant guess that ranks nothing (AUC 0.500). So a candidate qualifies only
if it ranks better than chance (AUC >= MIN_AUC); among those the lowest
out-of-sample Brier error wins. If none qualifies, nothing is adopted.
Pure: works on a DataFrame.
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
MIN_AUC = 0.55
RECENT_MONTHS = 3
CANDIDATES = ("base_rate", "raw_barrier", "meta", "meta_recent")
# The honesty map trusts a score level only when the cases at or above it span
# this many different days: 47 stocks on one day are one market bet, not 47.
MIN_EVIDENCE_DAYS = 20


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


# --- the honesty map -------------------------------------------------------------------


@dataclass
class HonestyMap:
    """'When it said X on unseen months, Y really happened' — learnt from the
    walk-forward predictions, applied to every live score. Never claims more
    than the best level backed by MIN_EVIDENCE_DAYS different days."""

    iso: Any
    ceiling: float
    max_seen: float
    min_days: int

    def apply(self, p: np.ndarray) -> np.ndarray:
        return np.minimum(self.iso.predict(np.asarray(p, dtype=float)), self.ceiling)


def fit_honesty(
    p: np.ndarray, y: np.ndarray, days: np.ndarray, min_days: int = MIN_EVIDENCE_DAYS
) -> HonestyMap:
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p, y)
    order = np.argsort(-p, kind="stable")
    seen: set = set()
    cut = p[order[-1]]
    for i in order:  # walk down from the highest score until enough days back it
        seen.add(pd.Timestamp(days[i]).normalize())
        if len(seen) >= min_days:
            cut = p[i]
            break
    return HonestyMap(iso, float(iso.predict([cut])[0]), float(p.max()), min_days)


# --- the combiner ----------------------------------------------------------------------


@dataclass
class Combiner:
    kind: str  # base_rate | raw_barrier | calibrated_barrier | meta | meta_recent
    inputs: list[str] = field(default_factory=list)
    model: Any = None
    recalibration: Any = None  # meta_recent: Platt scaling fitted on the last months

    @classmethod
    def fit(cls, frame: pd.DataFrame, kind: str) -> Combiner:
        frame = _with_logits(frame)
        y = frame["target"].astype(int).to_numpy()
        if kind == "base_rate":
            return cls(kind, [], float(y.mean()))
        if kind == "raw_barrier":
            return cls(kind, ["p_barrier"])
        if kind == "calibrated_barrier":
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(frame["p_barrier"].to_numpy(), y)
            return cls(kind, ["p_barrier"], iso)
        if kind in ("meta", "meta_recent"):
            pipe = make_pipeline(
                SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)
            )
            pipe.fit(frame[list(META_INPUTS)].to_numpy(dtype=float), y)
            combiner = cls(kind, list(META_INPUTS), pipe)
            if kind == "meta_recent":
                combiner.recalibration = _recent_platt(frame, combiner._raw_meta(frame), y)
            return combiner
        raise ValueError(f"unknown combiner kind {kind!r}")

    def _raw_meta(self, frame: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(frame[self.inputs].to_numpy(dtype=float))[:, 1]

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        frame = _with_logits(frame)
        if self.kind == "base_rate":
            return np.full(len(frame), self.model)
        if self.kind == "raw_barrier":
            return frame["p_barrier"].to_numpy(dtype=float)
        if self.kind == "calibrated_barrier":
            return self.model.predict(frame["p_barrier"].to_numpy(dtype=float))
        score = self._raw_meta(frame)
        if self.recalibration is not None:
            return self.recalibration.predict_proba(_logit(score).reshape(-1, 1))[:, 1]
        return score


def _recent_platt(frame: pd.DataFrame, score: np.ndarray, y: np.ndarray):
    """Re-anchor the probability level on the last RECENT_MONTHS months; None
    (no re-anchoring) when those months have only one outcome."""
    months = frame["day"].dt.to_period("M")
    recent = (months >= sorted(months.unique())[-RECENT_MONTHS]).to_numpy()
    if len(set(y[recent])) < 2:
        return None
    return LogisticRegression(C=1e6, max_iter=1000).fit(_logit(score[recent]).reshape(-1, 1), y[recent])


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


def evaluate(frame: pd.DataFrame, min_train_months: int = 3) -> dict:
    frame = frame.sort_values("day").reset_index(drop=True)
    folds = monthly_folds(frame, min_train_months)
    if not folds:
        return {
            "folds": 0,
            "n_test_rows": 0,
            "chosen": None,
            "candidates": {},
            "why": "Not enough unseen months to test a combiner (need at least 4).",
        }

    preds: dict[str, list[np.ndarray]] = {kind: [] for kind in CANDIDATES}
    ys: list[np.ndarray] = []
    test_days: list[np.ndarray] = []
    for train_idx, test_idx in folds:
        train, test = frame.loc[train_idx], frame.loc[test_idx]
        for kind in CANDIDATES:
            preds[kind].append(Combiner.fit(train, kind).predict(test))
        ys.append(test["target"].astype(int).to_numpy())
        test_days.append(test["day"].to_numpy())

    y = np.concatenate(ys)
    candidates = {kind: _metrics(np.concatenate(p), y) for kind, p in preds.items()}
    reference = candidates["base_rate"]["brier"]
    qualified = {
        kind: m
        for kind, m in candidates.items()
        if kind != "base_rate" and m["auc"] is not None and m["auc"] >= MIN_AUC
    }
    if not qualified:
        chosen, why = (
            None,
            (
                f"No combiner ranks stocks better than chance (AUC below {MIN_AUC}) on unseen months, "
                "so M06 stays off."
            ),
        )
    else:
        chosen = min(qualified, key=lambda k: qualified[k]["brier"])
        m = qualified[chosen]
        why = (
            f"{chosen} ranks stocks best among those better than chance (AUC {m['auc']:.3f}); its error "
            f"{m['brier']:.4f} against {reference:.4f} for a constant guess."
        )
    honesty_map, honesty_check = None, None
    if chosen is not None:
        honesty_map, honesty_check = _honesty(preds[chosen], ys, test_days)
    return {
        "folds": len(folds),
        "n_test_rows": len(y),
        "base_rate": float(y.mean()),
        "monthly_base_rate": {
            str(k): round(float(v), 4)
            for k, v in frame.groupby(frame["day"].dt.to_period("M"))["target"].mean().items()
        },
        "window_start": str(frame["day"].min().date()),
        "window_end": str(frame["day"].max().date()),
        "candidates": candidates,
        "chosen": chosen,
        "why": why,
        "honesty_map": honesty_map,
        "honesty_check": honesty_check,
    }


def _honesty(preds: list[np.ndarray], ys: list[np.ndarray], days: list[np.ndarray]):
    """The map for live use is learnt from every test month. It is checked the
    same honest way: learnt on the earlier test months only, scored on the last
    RECENT_MONTHS it never saw."""
    p, y, d = np.concatenate(preds), np.concatenate(ys), np.concatenate(days)
    check = None
    if len(preds) > RECENT_MONTHS:
        k = len(preds) - RECENT_MONTHS
        early = fit_honesty(np.concatenate(preds[:k]), np.concatenate(ys[:k]), np.concatenate(days[:k]))
        p_late, y_late = np.concatenate(preds[k:]), np.concatenate(ys[k:])
        check = {
            "months": RECENT_MONTHS,
            "brier_raw": float(brier_score_loss(y_late, np.clip(p_late, 0, 1))),
            "brier_honest": float(brier_score_loss(y_late, early.apply(p_late))),
            "mean_raw": float(p_late.mean()),
            "mean_honest": float(early.apply(p_late).mean()),
            "actual": float(y_late.mean()),
        }
    return fit_honesty(p, y, d), check
