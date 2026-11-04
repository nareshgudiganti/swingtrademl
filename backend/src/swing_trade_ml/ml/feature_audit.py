"""READ-ONLY audit helpers for the 53 existing inputs (ml/features.FEATURE_COLUMNS). Research only.

`ml/features.py` is imported and used, never edited. Nothing here touches the database (callers pass data in),
nothing here is imported by the app (the research tests enforce that for the sibling modules).

  * `pit_check`        point-in-time test: the features of day t built from data cut at t must equal the features of
                       day t built from the full history. If any input at t "knew" about a later bar, it differs.
  * `mutation_check`   the same idea the other way round: wreck every series after day T and confirm that every
                       input on or before T is unchanged.
  * `availability`     per input: first valid date, share and count of missing rows after warm-up.
  * `overlap`          how much the four sector inputs are explained by the existing inputs (pooled stock-days).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml.features import FEATURE_COLUMNS

RTOL, ATOL = 1e-7, 1e-9


def _cut_inputs(
    inputs: sr.ResearchInputs, sym: str, day: pd.Timestamp
) -> tuple[pd.DataFrame, sr.ResearchInputs]:
    raw = sr._cut(inputs.raw[sym].sort_values("ts"), day)
    cut = sr.ResearchInputs(
        raw={sym: raw},
        index_df=sr._cut(inputs.index_df, day),
        index_frames={k: sr._cut(v, day) for k, v in inputs.index_frames.items()},
        vix_df=sr._cut(inputs.vix_df, day),
        breadth_df=inputs.breadth_df[sr._ist_date(inputs.breadth_df["ts"]) <= day].reset_index(drop=True),
    )
    return raw, cut


def _same(a: float, b: float) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return bool(np.isclose(a, b, rtol=RTOL, atol=ATOL))


def pit_check(
    inputs: sr.ResearchInputs,
    sym: str,
    cut_days: Iterable[pd.Timestamp],
    columns: Sequence[str] = FEATURE_COLUMNS,
) -> dict[str, dict]:
    """For each cut day t (IST date) the stock traded on: features of t from data <= t versus from the full
    history. Returns {column: {"checked": n, "mismatches": n, "max_abs_diff": x, "example": date or None}}."""
    full_raw = inputs.raw[sym].sort_values("ts").reset_index(drop=True)
    full = sr._existing_features(full_raw, inputs, sym)
    full_day = sr._ist_date(full_raw["ts"])
    out = {c: {"checked": 0, "mismatches": 0, "max_abs_diff": 0.0, "example": None} for c in columns}
    for t in cut_days:
        t = pd.Timestamp(t).normalize()
        where = np.flatnonzero((full_day == t).to_numpy())
        if len(where) != 1:
            continue
        raw, cut = _cut_inputs(inputs, sym, t)
        part = sr._existing_features(raw, cut, sym).iloc[-1]
        ref = full.iloc[where[0]]
        for c in columns:
            a, b = part[c], ref[c]
            o = out[c]
            o["checked"] += 1
            if not _same(a, b):
                o["mismatches"] += 1
                o["example"] = o["example"] or t.date().isoformat()
                if not (pd.isna(a) or pd.isna(b)):
                    o["max_abs_diff"] = max(o["max_abs_diff"], abs(float(a) - float(b)))
    return out


def mutation_check(
    inputs: sr.ResearchInputs, sym: str, day: pd.Timestamp, *, factor_seed: int = 1
) -> dict[str, int]:
    """Multiply every price/volume/breadth value dated after `day` by random factors, then count, per column,
    the rows dated on or before `day` whose value changed. Expected: all zero."""
    day = pd.Timestamp(day).normalize()
    rr = np.random.default_rng(factor_seed)

    def wreck(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        late = (sr._ist_date(df["ts"]) > day).to_numpy()
        n = int(late.sum())
        for c in ("open", "high", "low", "close", "volume"):
            df.loc[late, c] = df.loc[late, c].to_numpy() * rr.uniform(0.5, 2.0, n)
        df.loc[late, "high"] = df.loc[late, ["open", "high", "close"]].max(axis=1)
        df.loc[late, "low"] = df.loc[late, ["open", "low", "close"]].min(axis=1)
        return df

    b = inputs.breadth_df.copy()
    late = (sr._ist_date(b["ts"]) > day).to_numpy()
    b.loc[late, ["breadth_pct_above_sma50", "breadth_advance_pct"]] = rr.uniform(0, 1, (int(late.sum()), 2))
    mutated = sr.ResearchInputs(
        raw={sym: wreck(inputs.raw[sym])},
        index_df=wreck(inputs.index_df),
        index_frames={k: wreck(v) for k, v in inputs.index_frames.items()},
        vix_df=wreck(inputs.vix_df),
        breadth_df=b,
    )
    a_raw = inputs.raw[sym].sort_values("ts").reset_index(drop=True)
    a = sr._existing_features(a_raw, inputs, sym)
    m = sr._existing_features(mutated.raw[sym].sort_values("ts").reset_index(drop=True), mutated, sym)
    upto = (sr._ist_date(a_raw["ts"]) <= day).to_numpy()
    bad = {}
    for c in FEATURE_COLUMNS:
        av, mv = a.loc[upto, c].to_numpy(), m.loc[upto, c].to_numpy()
        same = np.array([_same(x, y) for x, y in zip(av, mv, strict=True)])
        bad[c] = int((~same).sum())
    return bad


def availability(
    inputs: sr.ResearchInputs, symbols: Sequence[str], min_history: int = 252
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-input table, per-stock first-valid table). Rows counted are the stock's sessions after the warm-up
    (the same `min_history` skipped as the research matrix); the label tail is NOT removed (this is about inputs)."""
    first: dict[str, dict[str, pd.Timestamp | None]] = {}
    missing = dict.fromkeys(FEATURE_COLUMNS, 0)
    total = 0
    first_after_warmup: dict[str, list[pd.Timestamp]] = {c: [] for c in FEATURE_COLUMNS}
    nan_examples: dict[str, list[str]] = {c: [] for c in FEATURE_COLUMNS}
    for sym in symbols:
        raw = inputs.raw[sym].sort_values("ts").reset_index(drop=True)
        feat = sr._existing_features(raw, inputs, sym)
        day = sr._ist_date(raw["ts"])
        first[sym] = {}
        post = feat.iloc[min_history:]
        pday = day.iloc[min_history:]
        total += len(post)
        for c in FEATURE_COLUMNS:
            v = feat[c].notna().to_numpy()
            first[sym][c] = day[v].iloc[0] if v.any() else None
            pm = post[c].isna().to_numpy()
            missing[c] += int(pm.sum())
            ok = (~pm).nonzero()[0]
            if len(ok):
                first_after_warmup[c].append(pday.iloc[ok[0]])
            if pm.any() and len(nan_examples[c]) < 3:
                nan_examples[c].append(f"{sym}:{pday[pm].iloc[0].date()}")
    rows = []
    for c in FEATURE_COLUMNS:
        firsts = [v[c] for v in first.values() if v[c] is not None]
        rows.append(
            {
                "input": c,
                "first_valid_any_stock": min(firsts).date().isoformat() if firsts else None,
                "first_valid_all_stocks": max(firsts).date().isoformat()
                if len(firsts) == len(first)
                else None,
                "stocks_with_no_value": len(first) - len(firsts),
                "rows_after_warmup": total,
                "missing_rows": missing[c],
                "missing_share": missing[c] / total if total else None,
                "first_missing_examples": ";".join(nan_examples[c]),
            }
        )
    per_stock = pd.DataFrame(
        {
            s: {c: (v.date().isoformat() if v is not None else None) for c, v in d.items()}
            for s, d in first.items()
        }
    ).T
    return pd.DataFrame(rows), per_stock


def overlap(matrix: pd.DataFrame) -> dict:
    """Pooled stock-day overlap between the four sector inputs and the 53 existing inputs (eligible rows only).
    Pearson and Spearman against every existing input, the strongest partner of each new input, and the share of
    each new input's variance a linear model on (a) the five relative-strength / sector-regime inputs and (b) all 53
    existing inputs explains (R squared, in-sample, pooled; descriptive, not a forecast)."""
    new, old = list(sr.SECTOR_COLUMNS), list(sr.FEATURE_COLUMNS)
    pear = matrix[new + old].corr(method="pearson").loc[new, old]
    spear = matrix[new + old].rank().corr(method="pearson").loc[new, old]
    rel = [
        "sector_relative_strength_5d",
        "sector_relative_strength_20d",
        "sector_trend_regime",
        "relative_strength_5d",
        "relative_strength_20d",
    ]

    def r2(y: np.ndarray, cols: list[str]) -> float:
        X = matrix[cols].to_numpy("float64")
        X = np.c_[np.ones(len(X)), (X - X.mean(0)) / np.where(X.std(0) == 0, 1, X.std(0))]
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        res = y - X @ coef
        return float(1 - res.var() / y.var())

    out = {
        "rows": int(len(matrix)),
        "pearson": pear.round(4).to_dict("index"),
        "spearman": spear.round(4).to_dict("index"),
        "strongest_partner": {},
        "r2_on_sector_and_relative_inputs": {},
        "r2_on_all_53": {},
    }
    for n in new:
        s = pear.loc[n].abs().sort_values(ascending=False)
        out["strongest_partner"][n] = [(k, round(float(pear.loc[n, k]), 4)) for k in s.index[:3]]
        y = matrix[n].to_numpy("float64")
        out["r2_on_sector_and_relative_inputs"][n] = round(r2(y, rel), 4)
        out["r2_on_all_53"][n] = round(r2(y, old), 4)
    # (stock 20d return - NIFTY 20d return) - (stock 20d return - sector 20d return) = sector - NIFTY 20d return:
    # the new `sector_ret_20d_vs_nifty` should equal that difference of two EXISTING inputs.
    resid = (
        matrix["sector_ret_20d_vs_nifty"]
        - (matrix["relative_strength_20d"] - matrix["sector_relative_strength_20d"])
    ).abs()
    out["sector_ret_20d_vs_nifty_minus_existing_difference"] = {
        "max_abs": float(resid.max()),
        "mean_abs": float(resid.mean()),
        "rows_over_1e-9": int((resid > 1e-9).sum()),
    }
    return out
