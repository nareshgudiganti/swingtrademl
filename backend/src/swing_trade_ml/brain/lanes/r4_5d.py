# backend/src/swing_trade_ml/brain/lanes/r4_5d.py
# ruff: noqa: E501, N812 (short R / V import aliases and long rule sentences, as in the h05 lane)
"""R4 research envelope, #219: 5D large-cap candidates judged out-of-sample after costs. Pure: no database.

Owner-approved envelope (2026-11-25 00:57 IST, sign-off record of the 5D paper trial protocol v1): local data only,
5D only, today's 53 inputs with the corrected `obv_slope` as its own feature-set version, LightGBM and logistic
regression, momentum as the comparison, every candidate fingerprinted before training. NOTHING here registers,
activates or deploys a model; nothing writes to a database.

Reused as they are: the h05 trade rule, charges, ranking, repeat rule and block bootstrap (`h05_rules`), the h05
verdict words and reading (`h05_verdict`), the 5D rule of `core/research_config` hz-rules-v1, and the model card
helpers (`ml/model_card`). `ml/features.py` is frozen and only imported.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import Any

import numpy as np
import pandas as pd

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes import h05_verdict as V
from swing_trade_ml.core import research_config
from swing_trade_ml.ml.features import build_features, on_balance_volume

EXPERIMENT = "r4-219-5d-largecap-v1"

# ------------------------------------------------------------------ the 5D rule (hz-rules-v1) and the signed spec

RULE_VERSION = research_config.HZ_RULES_V1.version
_RULE = research_config.rule_for(5, RULE_VERSION)
HORIZON = _RULE.max_sessions  # 5 sessions
LABEL_TARGET = 0.02  # H-2b: session-5 close >= signal close x 1.02 (the model target)
EMBARGO = 5  # sessions between the last training label's end and the first test signal
RUN_LENGTH = 60  # H-11: 60 consecutive signal sessions per run
TOP_K = P.TOP_K
MIN_SCORED = P.RUN_VALUES["min_evidence_per_group"]["min_eligible_per_day"]  # counts SCORED stocks (spec 6)
MIN_BARS = P.MIN_BARS
MOMENTUM_LOOKBACK = 20
MOMENTUM_GAP = 0.20
GROUP = "large"  # 10 bps slippage per side; ~44 bps round trip with taxes and the depository charge

# Out-of-sample windows (pre-registered). W_FULL: walk-forward for the trained candidates from the first session on or
# after this date. W_M2: model 2's own held-out period, from the session after its last training row + purge + embargo.
W_FULL_START = date(2024, 1, 1)
MODEL2_LAST_TRAIN_DAY = date(2025, 10, 10)  # registry train_end 2025-10-09 18:30 UTC = 2025-10-10 IST

# ------------------------------------------------------------------ universe: the frozen 52 (selection-biased)

# Local dev DB, strategy 1 (`ml_swing_main`, model `swing_classifier`) symbols; none is in the mid or small lists.
UNIVERSE: tuple[str, ...] = (
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE",
    "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY", "EICHERMOT", "GRASIM",
    "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "LTM", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATASTEEL", "TCS", "TECHM", "TITAN",
    "TMCV", "TMPV", "ULTRACEMCO", "UPL", "WIPRO",
)  # fmt: skip
EVIDENCE_LABEL = "selection-biased exploratory evidence"

# ------------------------------------------------------------------ feature set version

FEATURE_SET_VERSION = "r4-fs53-obvvol-v1"
# Today's 53 inputs, pinned here so a later change to ml/features.py cannot silently change this version.
FEATURE_NAMES: tuple[str, ...] = (
    "sma_10_ratio", "sma_20_ratio", "sma_50_ratio", "sma_200_ratio", "ema_12_ratio", "ema_26_ratio",
    "sma_10_50_cross", "sma_50_200_cross", "rsi_14", "macd", "macd_signal", "macd_hist", "stoch_k", "stoch_d",
    "williams_r", "roc_10", "roc_20", "atr_14_pct", "bb_position", "bb_width", "volatility_20", "volume_ratio_20",
    "obv_slope", "mfi_14", "return_1d", "return_5d", "return_10d", "return_20d", "high_20_dist", "low_20_dist",
    "high_52w_dist", "gap_pct", "body_pct", "upper_wick_pct", "lower_wick_pct", "days_since_52w_high",
    "days_since_52w_low", "streak", "adx_14", "trend_strength", "volatility_percentile_rank", "cmf_20",
    "relative_strength_5d", "relative_strength_20d", "nifty_volatility_20", "nifty_trend_regime",
    "sector_relative_strength_5d", "sector_relative_strength_20d", "sector_trend_regime", "vix_change_5d",
    "vix_percentile_rank", "breadth_pct_above_sma50", "breadth_advance_pct",
)  # fmt: skip
OBV_FORMULA = "obv.diff(10) / volume.rolling(20).mean() (0 -> NaN): 10-day OBV change over the 20-day mean daily VOLUME; window-independent"


def corrected_obv_slope(close: pd.Series, volume: pd.Series) -> pd.Series:
    """The corrected obv_slope (#272): denominator = typical daily volume, so it does not depend on how much history
    was loaded. The models 2/16/17 were trained on the old OBV-level denominator; this is a separate version."""
    obv = on_balance_volume(close, volume)
    return obv.diff(10) / volume.rolling(20).mean().replace(0, np.nan)


def research_features(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    breadth_df: pd.DataFrame,
) -> pd.DataFrame:
    """`build_features` (frozen, imported) with `obv_slope` recomputed by THIS version's formula, row for row."""
    out = build_features(df, index_df, sector_df, vix_df, breadth_df).copy()
    if len(out) != len(df):
        raise ValueError("feature rows and candles differ in length")
    obv = corrected_obv_slope(
        df["close"].astype(float).reset_index(drop=True), df["volume"].astype(float).reset_index(drop=True)
    )
    out["obv_slope"] = obv.replace([np.inf, -np.inf], np.nan).to_numpy()
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def feature_set_fingerprint() -> dict[str, str]:
    """Names, formula text and the recipe's output on the fixed model-card fixture (6 decimals), hashed together."""
    from swing_trade_ml.ml import model_card

    stock = model_card.synthetic_candles(0.0)
    frame = model_card.golden_fixture_frame().copy()
    frame["obv_slope"] = corrected_obv_slope(stock["close"], stock["volume"]).to_numpy()
    row = frame.iloc[-1]
    golden = {n: None if pd.isna(row[n]) else round(float(row[n]), 6) for n in FEATURE_NAMES}
    names_sha = _sha(json.dumps(list(FEATURE_NAMES)))
    golden_sha = _sha(json.dumps(golden, sort_keys=True))
    return {
        "version": FEATURE_SET_VERSION,
        "names_sha256": names_sha,
        "obv_formula": OBV_FORMULA,
        "golden_output_sha256": golden_sha,
        "fingerprint_sha256": _sha(FEATURE_SET_VERSION + names_sha + _sha(OBV_FORMULA) + golden_sha),
    }


# ------------------------------------------------------------------ candidates (at most 3 in this run)

CANDIDATES: dict[str, dict[str, Any]] = {
    "C1": {
        "kind": "served_model",
        "what": "model 2 as served: swing_classifier v2 weights, its own 37 inputs from today's builder (production obv_slope since 2026-10-06), no training",
        "model_id": 2,
        "model_name": "swing_classifier",
        "model_version": "v2",
        "artifact_sha256": P.EXPECTED_MODELS["large"]["sha256"],
    },
    "C2": {
        "kind": "trained",
        "algorithm": "lightgbm",
        "features": FEATURE_SET_VERSION,
        # Model 2's own settings (verified from its artifact), no tuning; determinism pinned.
        "params": {
            "n_estimators": 400, "learning_rate": 0.05, "max_depth": 6, "num_leaves": 31, "subsample": 0.8,
            "colsample_bytree": 0.8, "min_child_samples": 50, "reg_alpha": 0.1, "reg_lambda": 0.1,
            "class_weight": "balanced", "random_state": 42, "n_jobs": 4, "deterministic": True,
            "force_row_wise": True, "verbose": -1,
        },
        "scaler": "StandardScaler fitted on the training rows only",
    },
    "C3": {
        "kind": "trained",
        "algorithm": "logistic_regression",
        "features": FEATURE_SET_VERSION,
        "params": {"C": 1.0, "solver": "lbfgs", "max_iter": 2000, "class_weight": "balanced", "random_state": 42},
        "scaler": "StandardScaler fitted on the training rows only",
    },
}  # fmt: skip

COMMON: dict[str, Any] = {
    "experiment": EXPERIMENT,
    "universe": list(UNIVERSE),
    "universe_sha256": _sha("\n".join(UNIVERSE)),
    "evidence_label": EVIDENCE_LABEL,
    "rule_version": RULE_VERSION,
    "rule_sha256": research_config.HZ_RULES_V1.sha256,
    "label": "endpoint: close of market session 5 >= signal close x 1.02 (H-2b); session-5 candle missing -> no label",
    "trade": "h05_rules.simulate_trade, group large: entry session-1 open, +2% / -4% from the entry fill, stop first, both-levels candle = stop, gaps at the open, else session-5 close",
    "costs": {"charges": P.COSTS, "slippage_bps_per_side": P.SLIPPAGE_BPS[GROUP], "stress": P.STRESS, "notional_inr": P.NOTIONAL_INR},
    "eligibility": f"in the frozen 52, candle on the signal session, >= {MIN_BARS} bars, all 53 inputs of {FEATURE_SET_VERSION} finite (one common scored pool for every candidate and comparison)",
    "selection": f"top {TOP_K} by score, ties by symbol A-Z; repeat rule h05_rules.repeat_blocked, memory restarts each run",
    "matured_day": f">= {MIN_SCORED} scored stocks, >= 1 counted pick with a finished trade, pool with finished trades",
    "verdicts": "SELECTION (picks minus every scored stock, daily) with the endpoint-label veto, ECONOMIC (picks' own daily net); 90% block range, blocks 5, 2000 draws, seed 7; per run h05_verdict.run_decision + >20% unresolved counted picks -> INCONCLUSIVE",
    "combined": "per verdict: >= 2 runs PASS, no run FAIL, pooled range wholly above 0 -> PASS; pooled range wholly below 0 or >= 2 runs FAIL -> FAIL; else INCONCLUSIVE (needs >= 3 final runs)",
    "windows": {
        "W_M2 (primary, all candidates)": f"from the session after {MODEL2_LAST_TRAIN_DAY} + {HORIZON} + {EMBARGO} sessions; 3 full runs of {RUN_LENGTH}",
        "W_FULL (secondary, C2/C3 and comparisons)": f"from the first session on or after {W_FULL_START}; every full run of {RUN_LENGTH}",
        "retrain": f"C2/C3 refit at each run start on every labelled row whose signal index <= run start - {HORIZON} - {EMBARGO} - 1 (purge + embargo), expanding window",
        "leftover": "sessions after the last full run are reported, never judged",
    },
    "comparisons": "every scored stock (SELECTION baseline), momentum five (20-session close-to-close return, 21 closes, >20% unexplained overnight gap -> not ranked; corporate_actions table is empty locally), model 2 as served (C1), random five (200 draws, seed 7, pools sorted by symbol)",
    "feature_set": FEATURE_SET_VERSION,
}  # fmt: skip


def config_fingerprint(cid: str, candidate: Mapping[str, Any] | None = None) -> str:
    body = {"id": cid, "candidate": dict(candidate or CANDIDATES[cid]), "common": COMMON}
    return _sha(json.dumps(body, sort_keys=True, default=str))


def snapshot_sha256(frames: Mapping[str, pd.DataFrame]) -> str:
    """One hash over every input frame (names sorted; each frame's values and row order)."""
    h = hashlib.sha256()
    for name in sorted(frames):
        f = frames[name].reset_index(drop=True)
        h.update(name.encode("utf-8"))
        h.update(",".join(map(str, f.columns)).encode("utf-8"))
        h.update(pd.util.hash_pandas_object(f, index=False).to_numpy().tobytes())
    return h.hexdigest()


# ------------------------------------------------------------------ windows, purge and embargo


def signal_days(sessions: Sequence[date], start: date) -> list[date]:
    """Sessions on or after `start` whose session 5 exists (a matured outcome is possible)."""
    return [d for i, d in enumerate(sessions) if d >= start and i + HORIZON < len(sessions)]


def make_runs(days: Sequence[date], run_length: int = RUN_LENGTH) -> tuple[list[list[date]], list[date]]:
    full = len(days) // run_length
    runs = [list(days[k * run_length : (k + 1) * run_length]) for k in range(full)]
    return runs, list(days[full * run_length :])


def last_training_index(sessions: Sequence[date], run_start: date) -> int:
    """Largest signal-session index a training row may have: its label (session +5) ends before the embargo gap."""
    s = R.session_index(sessions, run_start)
    if s is None:
        raise ValueError(f"{run_start} is not a market session")
    return s - HORIZON - EMBARGO - 1


def window_start_after(sessions: Sequence[date], last_train_day: date) -> date:
    """First test signal session for a model whose last training row was `last_train_day` (same purge + embargo)."""
    i = R.session_index(sessions, last_train_day)
    if i is None:
        raise ValueError(f"{last_train_day} is not a market session")
    return sessions[i + HORIZON + EMBARGO + 1]


# ------------------------------------------------------------------ label, momentum, selection


def endpoint_label(closes: Mapping[date, float], sessions: Sequence[date], day: date) -> int | None:
    out = R.endpoint_outcome(dict(closes), sessions, day)
    return out.label if out.status == "evaluated" else None


def momentum_scores(
    bars: Mapping[str, Mapping[date, tuple[float, float, float, float]]], day: date, pool: Sequence[str]
) -> tuple[dict[str, float], dict[str, str]]:
    """20-session close-to-close return ending at the signal close, from the stock's own last 21 bars."""
    scores: dict[str, float] = {}
    excluded: dict[str, str] = {}
    for sym in sorted(pool):
        own = sorted(d for d in bars.get(sym, {}) if d <= day)
        if len(own) < MOMENTUM_LOOKBACK + 1 or own[-1] != day:
            excluded[sym] = "fewer_than_21_closes"
            continue
        window = own[-(MOMENTUM_LOOKBACK + 1) :]
        b = bars[sym]
        gaps = [abs(b[window[k]][0] / b[window[k - 1]][3] - 1) for k in range(1, len(window))]
        if any(g > MOMENTUM_GAP for g in gaps):
            excluded[sym] = "overnight_gap_over_20pct"
            continue
        scores[sym] = b[window[-1]][3] / b[window[0]][3] - 1
    return scores, excluded


def top_k(scores: Mapping[str, float], k: int = TOP_K) -> tuple[list[str], int]:
    return R.select_top(R.rank_group(list(scores.items())), k)


# ------------------------------------------------------------------ one run's daily series


@dataclass(frozen=True)
class Outcome:
    net: float | None  # None = UNRESOLVED (missing candle, too expensive, pending)
    net_stress: float | None
    label: int | None  # None = NOT EVALUATED
    flags: tuple[str, ...]


def evaluate_run(
    days: Sequence[date],
    sessions: Sequence[date],
    pools: Mapping[date, Sequence[str]],
    picks: Mapping[date, Sequence[str]],
    outcomes: Mapping[tuple[date, str], Outcome],
) -> dict[str, Any]:
    """Daily series for ONE run (one value per matured signal day). UNRESOLVED rows leave both sides."""
    blocked = R.repeat_blocked({d: list(picks[d]) for d in days if picks.get(d)}, sessions)
    keys = ("days", "picks_net", "pool_net", "trade_edge", "picks_net_stress", "label_days", "label_edge")
    out: dict[str, Any] = {k: [] for k in keys}
    counted = unresolved = n_blocked = short = flagged = 0
    random_pools: list[list[float]] = []
    for d in days:
        chosen = list(picks.get(d, ()))
        if len(chosen) < TOP_K:
            short += 1
        pool = list(pools.get(d, ()))
        mine = [s for s in chosen if (d, s) not in blocked]
        n_blocked += len(chosen) - len(mine)
        counted += len(mine)
        unresolved += sum(outcomes[(d, s)].net is None for s in mine)
        flagged += sum(bool(outcomes[(d, s)].flags) and outcomes[(d, s)].net is not None for s in mine)
        if len(pool) < MIN_SCORED:
            continue
        p_net = [outcomes[(d, s)].net for s in mine if outcomes[(d, s)].net is not None]
        b_rows = [outcomes[(d, s)] for s in sorted(pool) if outcomes[(d, s)].net is not None]
        if not p_net or not b_rows:
            continue
        p_mean, b_mean = fmean(p_net), fmean(o.net for o in b_rows)
        out["days"].append(d)
        out["picks_net"].append(p_mean)
        out["pool_net"].append(b_mean)
        out["trade_edge"].append(p_mean - b_mean)
        out["picks_net_stress"].append(
            fmean(outcomes[(d, s)].net_stress for s in mine if outcomes[(d, s)].net is not None)
        )
        random_pools.append([o.net for o in b_rows])
        p_lab = [outcomes[(d, s)].label for s in mine if outcomes[(d, s)].label is not None]
        b_lab = [outcomes[(d, s)].label for s in pool if outcomes[(d, s)].label is not None]
        if p_lab and b_lab:
            out["label_days"].append(d)
            out["label_edge"].append(fmean(p_lab) - fmean(b_lab))
    out.update(
        matured_days=len(out["days"]),
        counted_picks=counted,
        unresolved_counted=unresolved,
        flagged_counted=flagged,
        blocked_repeats=n_blocked,
        shortfall_day_share=short / len(days) if days else 0.0,
        random_pools=random_pools,
    )
    return out


def unresolved_override(res: Mapping[str, Any]) -> str | None:
    n = res["counted_picks"]
    return "more than 20% of counted picks UNRESOLVED" if n and res["unresolved_counted"] / n > 0.20 else None


def run_verdict(res: Mapping[str, Any]) -> dict[str, Any]:
    decision = V.run_decision(
        res["trade_edge"], res["label_edge"], res["picks_net"], res["shortfall_day_share"]
    )
    why = unresolved_override(res)
    if why:
        waiting = {"verdict": V.INCONCLUSIVE, "range": None}
        decision = {**decision, "selection": waiting, "economic": waiting, "why": why}
    n = res["counted_picks"]
    decision["unresolved_warning"] = bool(n and res["unresolved_counted"] / n > 0.10)
    return decision


def combine_runs(words: Sequence[str], pooled: Sequence[float]) -> dict[str, Any]:
    """The H-11b rule for one verdict type over N >= 3 final runs (the signed rule, written for 3)."""
    if len(words) < 3:
        return {"verdict": V.INCONCLUSIVE, "why": f"{len(words)} final runs; 3 needed"}
    passing, failing = sum(w == V.PASS for w in words), sum(w == V.FAIL for w in words)
    rng = V._range(pooled)
    word = V._word(rng)
    if word == V.FAIL or failing >= 2:
        verdict = V.FAIL
    elif passing >= 2 and failing == 0 and word == V.PASS:
        verdict = V.PASS
    else:
        verdict = V.INCONCLUSIVE
    return {
        "verdict": verdict,
        "runs_passing": passing,
        "runs_failing": failing,
        "pooled_range": rng,
        "why": None,
    }


def paired_difference(a: Mapping[date, float], b: Mapping[date, float]) -> list[float]:
    """a - b on the days both have a value, in day order (for 'picks vs momentum five' and 'vs model 2')."""
    return [a[d] - b[d] for d in sorted(set(a) & set(b))]


def block_range(values: Sequence[float]) -> tuple[float, float] | None:
    return V._range(values)


def safe_mean(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    return fmean(vals) if vals else None


# ------------------------------------------------------------------ fitting


def fit_candidate(cid: str, x: np.ndarray, y: np.ndarray, candidate: Mapping[str, Any] | None = None):
    from sklearn.preprocessing import StandardScaler

    cfg = dict(candidate or CANDIDATES[cid])
    scaler = StandardScaler().fit(x)
    xs = scaler.transform(x)
    if cfg["algorithm"] == "lightgbm":
        from lightgbm import LGBMClassifier

        est = LGBMClassifier(**cfg["params"])
    elif cfg["algorithm"] == "logistic_regression":
        from sklearn.linear_model import LogisticRegression

        est = LogisticRegression(**cfg["params"])
    else:
        raise ValueError(f"unknown algorithm {cfg['algorithm']!r}")
    est.fit(xs, y)
    return scaler, est


def predict(scaler, estimator, x: np.ndarray) -> np.ndarray:
    return estimator.predict_proba(scaler.transform(np.asarray(x, dtype=np.float64)))[:, 1]
