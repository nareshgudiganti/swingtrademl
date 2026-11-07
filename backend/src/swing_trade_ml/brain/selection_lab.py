# backend/src/swing_trade_ml/brain/selection_lab.py
# ruff: noqa: E501 (long lines are protocol sentences)
"""Selection lab (15-day stock selection experiments): building blocks, protocol `sl-protocol-v1.1`.

Design: `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` (rev 3). Nothing here runs an
experiment, trains a model, writes to the database or is imported by live code. This first piece is the label of
section 4.1: whether a stock "beats the day's median" over the next 15 trading days.
"""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

HORIZON_BARS = 15
TOP_SHARE = 0.30  # label 1 = in the top 30% of the reference group's excess return
MIN_REFERENCE = 10  # fewer reference stocks with a valid return on a day means no labels that day
_TOL = 1e-12  # float noise only: a value exactly on the cut-off must count as on it


def forward_return(bars: pd.DataFrame, decision_day: date) -> float | None:
    """r(s,d) = close of day 15 / open of day 1 - 1, gross of costs. Day 1 is the first bar after the decision day.
    None when the window is incomplete or either price is not a positive number."""
    days = list(bars["day"])
    k = bisect.bisect_right(days, decision_day)  # first bar strictly after the decision day
    if k + HORIZON_BARS - 1 >= len(days):
        return None
    entry_open = float(bars.iloc[k]["open"])
    exit_close = float(bars.iloc[k + HORIZON_BARS - 1]["close"])
    if not (math.isfinite(entry_open) and math.isfinite(exit_close)) or entry_open <= 0 or exit_close <= 0:
        return None
    return exit_close / entry_open - 1.0


def excess_labels(
    returns: Mapping[str, float], reference: Sequence[str], min_reference: int = MIN_REFERENCE
) -> tuple[dict[str, int], float] | None:
    """The label of design section 4.1 for one decision day, for every stock in `returns` (reference or not).

    Excess e = r - median r of the reference group. One cut-off C = the 70th percentile of e over the reference
    group only (linear interpolation). Label = 1 if e >= C, else 0, for every stock alike, so an extra training
    stock is labelled by the same rule against a fixed distribution and never moves C. A value at or tied with C
    is 1. A stock without a finite return gets no label. Returns None (no labels that day) with fewer than
    `min_reference` reference stocks that have a valid return.
    """
    valid = {s: float(r) for s, r in returns.items() if r is not None and math.isfinite(r)}
    ref_returns = [valid[s] for s in reference if s in valid]
    if len(ref_returns) < min_reference:
        return None
    median = float(np.median(ref_returns))
    cut = float(np.percentile([r - median for r in ref_returns], (1 - TOP_SHARE) * 100, method="linear"))
    return {s: int(r - median >= cut - _TOL) for s, r in valid.items()}, cut


MIN_BARS = 220  # a stock is in the reference group only with this much history up to the decision day
MIN_TURNOVER_INR = 5e7  # Rs 5 crore: median close x volume over 20 sessions up to and including the day
TURNOVER_SESSIONS = 20
IST = "Asia/Kolkata"


def median_turnover(bars: pd.DataFrame, day: date, sessions: int = TURNOVER_SESSIONS) -> float | None:
    """Median of close x volume over the last `sessions` bars up to and including `day`; None with fewer."""
    upto = bars[bars["day"] <= day].tail(sessions)
    if len(upto) < sessions:
        return None
    return float((upto["close"] * upto["volume"]).median())


def reference_for_day(day: date, candidates: Sequence[str], bars: Mapping[str, pd.DataFrame]) -> list[str]:
    """The reference group of design section 4.1 for one decision day: the candidates (the 49) with enough
    history and enough turnover. A valid forward return is checked by `excess_labels`, which drops the rest."""
    out = []
    for s in candidates:
        df = bars.get(s)
        if df is None or int((df["day"] <= day).sum()) < MIN_BARS:
            continue
        t = median_turnover(df, day)
        if t is not None and t >= MIN_TURNOVER_INR:
            out.append(s)
    return out


def label_frame(
    dataset: pd.DataFrame, bars: Mapping[str, pd.DataFrame], candidates: Sequence[str]
) -> tuple[pd.DataFrame, dict]:
    """Replace a training frame's target with the section 4.1 label. `dataset` has `symbol` and a tz-aware `ts`
    (the decision bar); the decision day is the IST date of the stamp. Rows without a forward return, and every
    row on a day without enough reference stocks, are dropped and counted. Returns the labelled frame (with a
    `day` column) and a report: counts, and the share of 1s among reference and extra stocks per year."""
    work = dataset.assign(day=pd.to_datetime(dataset["ts"], utc=True).dt.tz_convert(IST).dt.date)
    rets: dict[tuple[str, date], float | None] = {}
    for s, d in set(zip(work["symbol"], work["day"], strict=True)):
        df = bars.get(s)
        rets[(s, d)] = forward_return(df, d) if df is not None else None
    work["_r"] = [rets[(s, d)] for s, d in zip(work["symbol"], work["day"], strict=True)]
    no_return = int(work["_r"].isna().sum())
    labelled, days_ok, days_bad = [], set(), set()
    for d, grp in work.dropna(subset=["_r"]).groupby("day"):
        got = excess_labels(
            dict(zip(grp["symbol"], grp["_r"], strict=True)), reference_for_day(d, candidates, bars)
        )
        if got is None:
            days_bad.add(d)
            continue
        days_ok.add(d)
        labels, _cut = got
        labelled.append(grp.assign(target=[labels[s] for s in grp["symbol"]]))
    out = pd.concat(labelled).drop(columns=["_r"]) if labelled else work.iloc[0:0].drop(columns=["_r"])
    share: dict[str, dict[str, float]] = {}
    if len(out):
        cand = set(candidates)
        tagged = out.assign(year=[d.year for d in out["day"]], is_ref=[s in cand for s in out["symbol"]])
        for (year, is_ref), grp in tagged.groupby(["year", "is_ref"]):
            share.setdefault(str(year), {})["reference" if is_ref else "extra"] = float(grp["target"].mean())
    return out, {
        "rows_in": len(work),
        "rows_without_return": no_return,
        "days_labelled": len(days_ok),
        "days_without_labels": len(days_bad),
        "share_of_ones_by_year": share,
    }


# ---------------------------------------------------------------- the data-quality gate (design section 4.2)

GAP_LINE = 0.20  # an overnight move beyond this is flagged for review, never removed on its own
MAX_MISSING_SESSIONS = 10  # more missing sessions than this in a calendar year leaves that stock-year out
AFTER_ERROR_SESSIONS = 252  # rows after a verified error whose inputs still use the bad prices
FLAG_CLASSES = ("real_gap", "verified_error", "unresolved")


@dataclass(frozen=True, slots=True)
class OvernightFlag:
    day: date
    move: float  # open / previous close - 1


def bad_bar_days(bars: pd.DataFrame) -> set[date]:
    """Days with high below low, a close that is not positive, or zero volume."""
    bad = (bars["high"] < bars["low"]) | (bars["close"] <= 0) | (bars["volume"] <= 0)
    return {d for d, b in zip(bars["day"], bad, strict=True) if b}


def overnight_flags(bars: pd.DataFrame, line: float = GAP_LINE) -> list[OvernightFlag]:
    """Overnight moves (open against the previous close) larger than `line`. A flag is a question, not a verdict."""
    prev = bars["close"].shift(1)
    move = bars["open"] / prev - 1.0
    return [
        OvernightFlag(d, float(m))
        for d, m in zip(bars["day"], move, strict=True)
        if pd.notna(m) and abs(m) > line
    ]


def unclassified(
    symbol: str, flags: Sequence[OvernightFlag], record: Mapping[tuple[str, date], str]
) -> list[tuple[str, date]]:
    """Flags with no written classification. A run must refuse while this list is not empty."""
    for key, value in record.items():
        if value not in FLAG_CLASSES:
            raise ValueError(f"{key}: {value!r} is not one of {FLAG_CLASSES}")
    return [(symbol, f.day) for f in flags if (symbol, f.day) not in record]


def _spans(days: list[date], index: int, after: int) -> set[date]:
    """Decision days whose 15-bar window contains bar `index` (the 15 before it), the bar itself, and `after - 1`
    further sessions."""
    lo, hi = max(0, index - HORIZON_BARS), min(len(days), index + after)
    return set(days[lo:hi])


def excluded_decision_days(
    bars: pd.DataFrame, record: Mapping[tuple[str, date], str], symbol: str = ""
) -> dict[str, set[date]]:
    """Decision days to leave out of training, by reason. A real gap removes nothing; a verified error removes the
    labels spanning it and the next 252 sessions; an unresolved anomaly has the same span but is only used by the
    sensitivity run (`apply_gate(drop_unresolved=True)`)."""
    days = list(bars["day"])
    pos = {d: i for i, d in enumerate(days)}
    out: dict[str, set[date]] = {"bad_bar": set(), "verified_error": set(), "unresolved": set()}
    for d in bad_bar_days(bars):
        out["bad_bar"] |= _spans(days, pos[d], 1)
    for f in overnight_flags(bars):
        kind = record.get((symbol, f.day))
        if kind in ("verified_error", "unresolved"):
            out[kind] |= _spans(days, pos[f.day], AFTER_ERROR_SESSIONS)
    return out


def sparse_years(
    bars: pd.DataFrame, calendar: Sequence[date], max_missing: int = MAX_MISSING_SESSIONS
) -> set[int]:
    """Calendar years in which the stock lacks more than `max_missing` of the market's sessions, counted only
    between its first and last bar (sessions before it listed are not missing)."""
    if bars.empty:
        return set()
    first, last = bars["day"].iloc[0], bars["day"].iloc[-1]
    have = set(bars["day"])
    missing: dict[int, int] = {}
    for d in calendar:
        if first <= d <= last and d not in have:
            missing[d.year] = missing.get(d.year, 0) + 1
    return {y for y, n in missing.items() if n > max_missing}


def apply_gate(
    frame: pd.DataFrame,
    bars: Mapping[str, pd.DataFrame],
    record: Mapping[tuple[str, date], str],
    *,
    drop_unresolved: bool = False,
    calendar: Sequence[date] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Filter a frame of (symbol, day) rows by the gate. Each removed row is counted once, under the first reason
    that applies (bad bar, verified error, unresolved, sparse year). Genuine overnight gaps are always kept.
    `drop_unresolved=True` is the sensitivity run; the main result keeps unresolved anomalies."""
    cal = sorted({d for df in bars.values() for d in df["day"]}) if calendar is None else list(calendar)
    reasons = {"bad_bar": 0, "verified_error": 0, "unresolved": 0, "sparse_year": 0}
    keep = []
    stock_years: list[tuple[str, int]] = []
    flags_seen = {"real_gap_kept": 0, "unresolved_kept": 0}
    for sym, grp in frame.groupby("symbol", sort=False):
        df = bars[sym]
        ex = excluded_decision_days(df, record, sym)
        sp = sparse_years(df, cal)
        stock_years += [(sym, y) for y in sorted(sp)]
        for f in overnight_flags(df):
            kind = record.get((sym, f.day))
            if kind == "real_gap":
                flags_seen["real_gap_kept"] += 1
            elif kind == "unresolved" and not drop_unresolved:
                flags_seen["unresolved_kept"] += 1
        for idx, d in zip(grp.index, grp["day"], strict=True):
            if d in ex["bad_bar"]:
                reasons["bad_bar"] += 1
            elif d in ex["verified_error"]:
                reasons["verified_error"] += 1
            elif drop_unresolved and d in ex["unresolved"]:
                reasons["unresolved"] += 1
            elif d.year in sp:
                reasons["sparse_year"] += 1
            else:
                keep.append(idx)
    out = frame.loc[keep]
    return out, {
        "rows_in": len(frame),
        "rows_out": len(out),
        "by_reason": {**reasons, **flags_seen},
        "stock_years_left_out": stock_years,
        "unresolved_dropped": drop_unresolved,
    }


# ---------------------------------------------------------------- fold training (design sections 4 and 6.3)

ALGORITHM = "lightgbm"  # train_model's default, as Phase B and wf-protocol-v1
LABEL_KIND = "excess_top30"
EMBARGO_DAYS = HORIZON_BARS


@dataclass(frozen=True, slots=True)
class FoldFit:
    estimator: object
    scaler: object
    metrics: dict
    train_df: pd.DataFrame
    test_df: pd.DataFrame


def _ist_date(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True).dt.tz_convert(IST).dt.date


def chronology_violations(train_df: pd.DataFrame, cutoff: date, first_test_day: date) -> list[str]:
    """Problems that would make a fold look ahead (design rev 3, Stage 2): empty means chronological."""
    problems: list[str] = []
    if train_df.empty:
        return problems
    ends = _ist_date(train_df["label_end_ts"])
    days = _ist_date(train_df["ts"])
    if (ends > cutoff).any():
        problems.append(
            f"{int((ends > cutoff).sum())} training rows have a label ends after the cutoff {cutoff}"
        )
    if (days >= first_test_day).any():
        problems.append(
            f"{int((days >= first_test_day).sum())} training rows are dated on or after the first test day {first_test_day}"
        )
    return problems


def fit_fold(frame: pd.DataFrame, test_size: float | None = None) -> FoldFit:
    """Fit exactly as `train_model` does: chronological hold-back at the code default (0.2), embargo and
    `label_end_ts` purge, LightGBM defaults, no calibration. `frame` carries the features, `target`, `ts`,
    `label_end_ts`."""
    from swing_trade_ml.core.config import Settings
    from swing_trade_ml.ml.dataset import chronological_split
    from swing_trade_ml.ml.train import fit_and_score

    test_size = Settings.model_fields["ML_TRAIN_TEST_SPLIT"].default if test_size is None else test_size
    train_df, test_df = chronological_split(frame, test_size, embargo_days=EMBARGO_DAYS)
    if test_df.empty or train_df.empty or train_df["target"].nunique() < 2:
        raise ValueError("Not enough history for the lab fold model (both classes are needed in training).")
    estimator, scaler, metrics = fit_and_score(train_df, test_df, ALGORITHM, None, False)
    metrics["embargo_days"] = EMBARGO_DAYS
    metrics["label"] = (
        f"excess: top {TOP_SHARE:.0%} of 15-day return over the reference median (selection lab)"
    )
    return FoldFit(estimator, scaler, metrics, train_df, test_df)


def train_lab_model(
    db,
    *,
    name: str,
    cutoff: date,
    symbols: Sequence[str],
    candidates: Sequence[str],
    bars: Mapping[str, pd.DataFrame],
    record: Mapping[tuple[str, date], str] | None = None,
    drop_unresolved: bool = False,
):
    """Train one lab fold model on `symbols` (always an explicit list: never today's watchlist), label it with
    section 4.1 against `candidates` (the 49), apply the section 4.2 gate, and register it TRAINED, never
    activated. Rows come from `ml.dataset.build_training_dataset`, which keeps only rows whose label had
    resolved by `cutoff`."""
    from datetime import UTC, datetime

    from swing_trade_ml.core.enums import ModelStatus
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.ml import dataset as ds_mod
    from swing_trade_ml.ml import registry
    from swing_trade_ml.ml.features import FEATURE_COLUMNS
    from swing_trade_ml.ml.train import _feature_importance

    if not symbols:
        raise ValueError("The lab needs an explicit symbol list; it never trains on today's watchlist.")
    dataset = ds_mod.build_training_dataset(
        db,
        symbols=list(symbols),
        horizon_days=HORIZON_BARS,
        target_return=0.08,
        stop_return=0.04,
        cutoff=cutoff,
    )
    if dataset.empty:
        raise ValueError("No training data for the lab fold model.")
    labelled, label_report = label_frame(dataset, bars, candidates)
    gated, gate_report = apply_gate(labelled, bars, record or {}, drop_unresolved=drop_unresolved)
    problems = chronology_violations(gated, cutoff, cutoff + timedelta(days=1))
    if problems:
        raise ValueError("The fold is not chronological: " + "; ".join(problems))
    fit = fit_fold(gated)
    fit.metrics["asof_cutoff"] = cutoff.isoformat()
    fit.metrics["label_report"] = label_report
    fit.metrics["gate_report"] = {k: v for k, v in gate_report.items() if k != "stock_years_left_out"}
    version = registry.next_version(db, name)
    path = registry.save_artifact(
        name,
        version,
        {
            "estimator": fit.estimator,
            "scaler": fit.scaler,
            "feature_names": FEATURE_COLUMNS,
            "algorithm": ALGORITHM,
            "horizon_days": HORIZON_BARS,
            "target_return": None,
            "stop_return": None,
            "label_kind": LABEL_KIND,
            "calibrated": False,
        },
    )
    model = MLModel(
        name=name,
        version=version,
        algorithm=ALGORITHM,
        status=ModelStatus.TRAINED,
        artifact_path=path,
        feature_names=FEATURE_COLUMNS,
        hyperparameters={},
        training_symbols=sorted(gated["symbol"].unique().tolist()),
        train_start=pd.Timestamp(fit.train_df["ts"].min()).to_pydatetime(),
        train_end=pd.Timestamp(fit.train_df["ts"].max()).to_pydatetime(),
        n_samples=len(gated),
        prediction_horizon_days=HORIZON_BARS,
        target_return_pct=None,
        stop_return_pct=None,
        label_kind=LABEL_KIND,
        accuracy=fit.metrics["accuracy"],
        precision=fit.metrics["precision"],
        recall=fit.metrics["recall"],
        f1_score=fit.metrics["f1"],
        roc_auc=fit.metrics["roc_auc"],
        metrics=fit.metrics,
        feature_importance=_feature_importance(fit.estimator),
        trained_at=datetime.now(UTC),
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


# ---------------------------------------------------------------- the ranking verdict (design sections 6.1 and 6.3)

BONFERRONI_Q = 0.05 / 4  # familywise 5% over the four model candidates: the 1.25th percentile
BLOCK_DAYS = 15  # trades last up to 15 days, so days closer than this are not independent
DRAWS = 2000
SEED = 7
MIN_STOCKS = 10  # a day with fewer scored stocks is left out of every ranking measure
NOT_WORSE_MARGIN = 0.005  # S2r against S2: the paired IC difference must stay above -0.005
MIN_FOLD_DAYS = 10
MIN_FOLD_IDEAS = 20
MIN_ELIGIBLE_FOLDS = 12
FOLDS_SHARE = 0.60


def daily_ic(
    scores: Mapping[str, Mapping[date, float]],
    returns: Mapping[tuple[str, date], float | None],
    min_stocks: int = MIN_STOCKS,
) -> dict[date, float]:
    """Mean-rank (Spearman) correlation of score and 15-day return across the stocks of each day (R1's IC(d)).
    A day with fewer than `min_stocks` scored stocks that have a valid return, or where every score or every
    return is equal, is left out."""
    by_day: dict[date, list[tuple[float, float]]] = {}
    for sym, per_day in scores.items():
        for d, sc in per_day.items():
            r = returns.get((sym, d))
            if r is not None and math.isfinite(r) and math.isfinite(sc):
                by_day.setdefault(d, []).append((sc, r))
    out: dict[date, float] = {}
    for d, pairs in by_day.items():
        if len(pairs) < min_stocks:
            continue
        s, r = pd.Series([p[0] for p in pairs]), pd.Series([p[1] for p in pairs])
        if s.nunique() < 2 or r.nunique() < 2:
            continue
        out[d] = float(s.rank().corr(r.rank()))
    return out


def block_quantile(
    values: Sequence[float], q: float, block: int = BLOCK_DAYS, draws: int = DRAWS, seed: int = SEED
) -> float | None:
    """The q-quantile of the mean of `values` (in day order) over moving-block resamples: runs of `block`
    consecutive days, so overlapping 15-day trades are not treated as independent. None with fewer than two
    blocks of days (no honest bound)."""
    n = len(values)
    if n < max(5, 2 * block):
        return None
    rng = random.Random(seed)
    per_draw = -(-n // block)
    means = []
    for _ in range(draws):
        picked: list[float] = []
        for _ in range(per_draw):
            s = rng.randrange(n - block + 1)
            picked.extend(values[s : s + block])
        means.append(sum(picked) / len(picked))
    means.sort()
    return means[int(q * draws)]


def r1(ic: Mapping[date, float]) -> dict:
    """R1: the mean daily IC is above zero and so is its 1.25th-percentile block-bootstrap lower bound."""
    ordered = [ic[d] for d in sorted(ic)]
    mean = sum(ordered) / len(ordered) if ordered else None
    low = block_quantile(ordered, BONFERRONI_Q)
    return {
        "mean_ic": mean,
        "lower_bound": low,
        "days": len(ordered),
        "passes": bool(mean is not None and mean > 0 and low is not None and low > 0),
    }


def top_k(scores: Mapping[str, Mapping[date, float]], day: date, k: int = 5) -> list[str]:
    """The k highest scores on `day`; exact ties are broken by symbol, alphabetically."""
    have = [(s, per[day]) for s, per in scores.items() if day in per and math.isfinite(per[day])]
    return [s for s, _ in sorted(have, key=lambda x: (-x[1], x[0]))[:k]]


def top5_measures(
    scores: Mapping[str, Mapping[date, float]],
    returns: Mapping[tuple[str, date], float | None],
    k: int = 5,
    min_stocks: int = MIN_STOCKS,
) -> dict:
    """The top-5 measures of section 6.1 over the days with at least `min_stocks` scored stocks: mean excess
    (top-5 return minus the day's median), hit share (share of the top 5 whose return is in the top 30% of the
    day) and the spread (top 20% minus bottom 20% by score). `per_day_excess` lets callers split by fold."""
    excess, hits, spread, per_day, vs_mean = [], [], [], {}, []
    days = sorted({d for per in scores.values() for d in per})
    for d in days:
        u = [(s, scores[s][d], returns.get((s, d))) for s in scores if d in scores[s]]
        u = [(s, sc, r) for s, sc, r in u if r is not None and math.isfinite(r) and math.isfinite(sc)]
        if len(u) < min_stocks:
            continue
        ranked = sorted(u, key=lambda x: (-x[1], x[0]))
        rs = [x[2] for x in u]
        top = ranked[:k]
        e = sum(x[2] for x in top) / len(top) - float(np.median(rs))
        cut = float(np.percentile(rs, 70, method="linear"))
        excess.append(e)
        vs_mean.append(sum(x[2] for x in top) / len(top) - sum(rs) / len(rs))
        per_day[d] = e
        hits.append(sum(x[2] >= cut for x in top) / len(top))
        n20 = max(1, round(0.2 * len(ranked)))
        spread.append(sum(x[2] for x in ranked[:n20]) / n20 - sum(x[2] for x in ranked[-n20:]) / n20)

    def mean(v):
        return sum(v) / len(v) if v else None

    return {
        "days": len(excess),
        "excess": mean(excess),
        "excess_vs_mean": mean(vs_mean),
        "hit_share": mean(hits),
        "spread": mean(spread),
        "per_day_excess": per_day,
    }


def r2(excess: float | None, momentum_excess: float | None) -> dict:
    """R2: the top-5 excess is above zero and above momentum 5's on the same statistic."""
    ok = excess is not None and excess > 0 and momentum_excess is not None and excess > momentum_excess
    return {"excess": excess, "momentum_excess": momentum_excess, "passes": bool(ok)}


def r3(folds: Sequence[Mapping]) -> dict:
    """R3: IC above zero in at least 60% of eligible folds (a fold is eligible with 10 days and 20 finished
    ideas); fewer than 12 eligible folds is insufficient, not a pass."""
    eligible = [f for f in folds if f["days"] >= MIN_FOLD_DAYS and f["ideas"] >= MIN_FOLD_IDEAS]
    positive = sum(1 for f in eligible if f["mean_ic"] is not None and f["mean_ic"] > 0)
    enough = len(eligible) >= MIN_ELIGIBLE_FOLDS
    share = positive / len(eligible) if eligible else 0.0
    return {
        "eligible": len(eligible),
        "positive": positive,
        "share": share,
        "state": "ok" if enough else "insufficient",
        "passes": bool(enough and share >= FOLDS_SHARE),
    }


def r4(ic_a: Mapping[date, float], ic_b: Mapping[date, float], mode: str) -> dict:
    """R4: the paired daily IC difference (a minus b, on days both scored) has a 1.25th-percentile lower bound
    above zero ("better") or above -0.005 ("not_worse", for S2r against S2)."""
    if mode not in ("better", "not_worse"):
        raise ValueError("mode must be 'better' or 'not_worse'")
    common = sorted(set(ic_a) & set(ic_b))
    diff = [ic_a[d] - ic_b[d] for d in common]
    low = block_quantile(diff, BONFERRONI_Q)
    floor = 0.0 if mode == "better" else -NOT_WORSE_MARGIN
    return {
        "mode": mode,
        "days": len(common),
        "mean_difference": sum(diff) / len(diff) if diff else None,
        "lower_bound": low,
        "passes": bool(low is not None and low > floor),
    }


# ---------------------------------------------------------------- the ranking evaluation over folds

RISING_OVER = 0.03  # a window where the average stock gained more than this is "rising" (as walk_forward)
FALLING_UNDER = -0.03
MOMENTUM_BARS = 20  # the "strongest risers" rule looks back this many trading days
TEST_DAYS = 28
MONEY_NOT_EVALUATED = (
    "not evaluated: owner decision 2026-11-02, focus on the chart score by market condition. "
    "No profit, cost, capital or account figure is produced or implied."
)
TWO_QUESTIONS = (
    "Ranking and trading are different questions. Ranking asks whether a higher score picks stocks that do better "
    "than the other stocks that day (relative). Trading asks whether the +8% / -4% trade made money after costs. "
    "This result answers only the ranking question and is never a profit forecast."
)


@dataclass(frozen=True, slots=True)
class Fold:
    cutoff: date  # last day whose outcome the model may learn from
    start: date  # first test day
    end: date  # last test day


def make_folds(first_start: date, last_end: date, test_days: int = TEST_DAYS) -> list[Fold]:
    """Back-to-back test windows of `test_days` calendar days (the same windows wf-protocol-v1 uses). A window
    that would run past `last_end` is cut short; one under a week is dropped."""
    folds: list[Fold] = []
    start = first_start
    while start <= last_end:
        end = min(start + timedelta(days=test_days - 1), last_end)
        if (end - start).days >= 6:
            folds.append(Fold(cutoff=start - timedelta(days=1), start=start, end=end))
        start += timedelta(days=test_days)
    return folds


def market_label(bars: Mapping[str, pd.DataFrame], start: date, end: date) -> str:
    """Describe the window afterwards: how did the average stock move from its first to its last bar?
    (The same labelling as `walk_forward.classify_regime`.) Reporting only; it never picks anything."""
    moves = []
    for df in bars.values():
        w = df[(df["day"] >= start) & (df["day"] <= end)]
        if len(w) >= 2 and float(w.iloc[0]["close"]) > 0:
            moves.append(float(w.iloc[-1]["close"]) / float(w.iloc[0]["close"]) - 1.0)
    if not moves:
        return "unknown"
    avg = sum(moves) / len(moves)
    return "rising" if avg > RISING_OVER else "falling" if avg < FALLING_UNDER else "sideways"


def momentum_scores(bars: Mapping[str, pd.DataFrame], days: Sequence[date]) -> dict[str, dict[date, float]]:
    """Trailing 20-bar gain, known at the close of each day (the comparison for R2)."""
    out: dict[str, dict[date, float]] = {}
    wanted = set(days)
    for sym, df in bars.items():
        closes = [float(c) for c in df["close"]]
        bar_days = list(df["day"])
        per: dict[date, float] = {}
        for i, d in enumerate(bar_days):
            if d in wanted and i >= MOMENTUM_BARS and closes[i - MOMENTUM_BARS] > 0:
                per[d] = closes[i] / closes[i - MOMENTUM_BARS] - 1.0
        out[sym] = per
    return out


MIN_GROUP_STOCKS = 30  # a scored group smaller than this is a limited experiment
LIMITED_LABEL = "NO WARNING (diagnostic, limited sample)"
FULL_LABEL = "NO WARNING (diagnostic)"
BENCHMARK = (
    "Cap-group benchmark: a group's best-5 excess is measured over the day's median stock of the SAME group and "
    "over the average of that group's own eligible stocks, never over a different size group or an index."
)


def sample_warning(n_stocks: int) -> str | None:
    """The plain warning for a scored group under MIN_GROUP_STOCKS stocks; None for a large enough group."""
    if n_stocks >= MIN_GROUP_STOCKS:
        return None
    return f"Limited experiment: {n_stocks} stocks. Wide uncertainty. Not a basis for trading approval on its own."


def mid_group_from(
    model_training_symbols: Sequence[str], reject_set: Sequence[str], used_49: Sequence[str]
) -> list[str]:
    """The mid-cap group: the training stocks of the app's mid-cap model, minus the held-back set. None may be in
    the 49 (the large group): that would mean the two groups overlap, and the run is refused."""
    held, used = set(reject_set), set(used_49)
    group = sorted({s for s in model_training_symbols if s not in held})
    overlap = sorted(set(group) & used)
    if overlap:
        raise ValueError(f"The mid-cap group overlaps the 49: {', '.join(overlap)}")
    return group


def assert_no_held_back(reject_set: Sequence[str], **lists: Sequence[str]) -> None:
    """Hard rule: no held-back stock may be in any list the lab loads, trains on or scores."""
    held = set(reject_set)
    for name, symbols in lists.items():
        bad = sorted(set(symbols) & held)
        if bad:
            raise ValueError(
                f"Held-back stocks found in {name}: {', '.join(bad[:5])} ({len(bad)}). They are never used."
            )


def _group_result(
    members: Sequence[str],
    scores_all: Mapping[str, Mapping[date, float]],
    rets_all: Mapping[tuple[str, date], float | None],
) -> dict:
    sub = {s: scores_all[s] for s in members if s in scores_all}
    ic = daily_ic(sub, rets_all)
    top = top5_measures(sub, rets_all)
    r = r1(ic)
    return {
        "stocks_listed": len(members),
        "stocks_scored": sum(1 for per in sub.values() if per),
        "days": r["days"],
        "mean_ic": r["mean_ic"],
        "lower_bound": r["lower_bound"],
        "top5_excess_over_median": top["excess"],
        "top5_excess_over_group_average": top["excess_vs_mean"],
        "hit_share": top["hit_share"],
        "top5_days": top["days"],
    }


def evaluate_ranking(
    bars: Mapping[str, pd.DataFrame],
    folds: Sequence[Fold],
    model_scores: Callable[[Fold], dict[str, dict[date, float]]],
    candidates: Sequence[str],
    *,
    comparison_ic: Mapping[date, float] | None = None,
    r4_mode: str | None = None,
    groups: Mapping[str, Sequence[str]] | None = None,
) -> dict:
    """Ranking verdict (R1 to R4) of one candidate over expanding walk-forward folds, scored on the `candidates`
    (the 49) that have at least 220 bars and a valid 15-day return on the decision day. `model_scores(fold)`
    returns {symbol: {day: score}} from a model trained only on data known by the fold's cutoff. The money verdict
    is deliberately not evaluated (owner, 2026-11-02): the result says so and cannot qualify a winner."""
    scored = [s for s in candidates if s in bars]
    ic_all: dict[date, float] = {}
    scores_all: dict[str, dict[date, float]] = {s: {} for s in scored}
    rets_all: dict[tuple[str, date], float | None] = {}
    fold_rows: list[dict] = []
    cond_ic: dict[str, dict[date, float]] = {}
    cond_scores: dict[str, dict[str, dict[date, float]]] = {}
    max_scored = 0
    for fold in folds:
        days = sorted({d for s in scored for d in bars[s]["day"] if fold.start <= d <= fold.end})
        if not days:
            continue
        raw = model_scores(fold)
        scores: dict[str, dict[date, float]] = {}
        returns: dict[tuple[str, date], float | None] = {}
        for s in scored:
            df = bars[s]
            have = df["day"]
            per = {}
            for d, sc in raw.get(s, {}).items():
                if fold.start <= d <= fold.end and int((have <= d).sum()) >= MIN_BARS:
                    per[d] = sc
                    returns[(s, d)] = forward_return(df, d)
            scores[s] = per
        ic = daily_ic(scores, returns)
        top = top5_measures(scores, returns)
        label = market_label(bars, fold.start, fold.end)
        for s, per in scores.items():
            scores_all[s].update(per)
        rets_all.update(returns)
        ic_all.update(ic)
        cond_ic.setdefault(label, {}).update(ic)
        for s, per in scores.items():
            cond_scores.setdefault(label, {}).setdefault(s, {}).update(per)
        max_scored = max([max_scored, *(sum(1 for s in scores if d in scores[s]) for d in ic)])
        fold_rows.append(
            {
                "cutoff": fold.cutoff.isoformat(),
                "start": fold.start.isoformat(),
                "end": fold.end.isoformat(),
                "regime": label,
                "days": len(ic),
                "ideas": top["days"] * 5,
                "mean_ic": (sum(ic.values()) / len(ic)) if ic else None,
                "top5_excess": top["excess"],
            }
        )
    all_days = sorted({d for per in scores_all.values() for d in per})
    top_all = top5_measures(scores_all, rets_all)
    mom_all = top5_measures(momentum_scores({s: bars[s] for s in scored}, all_days), rets_all)
    r1_res, r2_res, r3_res = r1(ic_all), r2(top_all["excess"], mom_all["excess"]), r3(fold_rows)
    out: dict = {
        "protocol": "sl-protocol-v1.1 (ranking only)",
        "folds": fold_rows,
        "r1": r1_res,
        "r2": r2_res,
        "r3": r3_res,
        "top5": {k: v for k, v in top_all.items() if k != "per_day_excess"},
        "momentum5": {k: v for k, v in mom_all.items() if k != "per_day_excess"},
        "by_market_condition": {
            label: {
                "days": len(ic),
                "mean_ic": sum(ic.values()) / len(ic),
                "top5_excess": top5_measures(cond_scores[label], rets_all)["excess"],
            }
            for label, ic in cond_ic.items()
            if ic
        },
        "benchmark": BENCHMARK,
        "by_cap_group": {
            name: _group_result(members, scores_all, rets_all) for name, members in (groups or {}).items()
        },
        "stocks_scored_max": max_scored,
        "ic_by_day": ic_all,
        "money": MONEY_NOT_EVALUATED,
        "qualifies_for_winner": False,
        "statement": TWO_QUESTIONS,
    }
    warning = sample_warning(len(scored))
    out["label"] = FULL_LABEL if warning is None else LIMITED_LABEL
    if warning:
        out["sample_warning"] = warning
    parts = [r1_res["passes"], r2_res["passes"], r3_res["passes"]]
    if comparison_ic is not None and r4_mode is not None:
        out["r4"] = r4(ic_all, comparison_ic, r4_mode)
        parts.append(out["r4"]["passes"])
    insufficient = r1_res["lower_bound"] is None or r3_res["state"] == "insufficient"
    out["ranking_verdict"] = "pass" if all(parts) else ("insufficient" if insufficient else "fail")
    return out
