"""Fixed +8%/-4% barrier vs volatility-scaled barriers.

Question: if each stock's stop and target are set from its own volatility (ATR),
does the model pick trades that earn more per unit of risk after costs?

Everything else is held equal: same features, same 5 expanding walk-forward folds
purged by label window, same LightGBM recipe, same 2:1 payoff shape, same 15-bar
horizon. Research only; writes nothing to the database.

Comparison metric: expectancy in R (profit divided by the distance to the stop)
after estimated round-trip costs, for the model's top 5% of scores in each test
fold. R is comparable across variants because sizing in this app is risk-based
(1% of the account risked per trade), so one R is the same rupee risk everywhere.
"""
import json
import sys

import numpy as np
import pandas as pd
from sqlalchemy import select

from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml import dataset as ds
from swing_trade_ml.ml import train as tr
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles, load_market_breadth, load_sector_candles, load_vix_candles,
)
from swing_trade_ml.ml.sector_map import get_sector_index
from swing_trade_ml.db.models.market import Instrument

HORIZON = 15
TOP_FRACTION = 0.05
# Round trip: buy taxes 11.9bps + sell 10.4bps + 5bps slippage each way + ~3bps flat depository fee.
ROUND_TRIP_COST = (11.9 + 10.4 + 10.0 + 3.0) / 10_000

TIERS = {"large": None, "mid": "ml_swing_midcap", "small": "ml_swing_smallcap"}

VARIANTS = {
    "fixed_8_4": lambda atr: (np.full_like(atr, 0.04), np.full_like(atr, 0.08)),
    "atr_2x":    lambda atr: (lambda s: (s, 2 * s))(np.clip(2.0 * atr, 0.02, 0.08)),
    "atr_1.5x":  lambda atr: (lambda s: (s, 2 * s))(np.clip(1.5 * atr, 0.015, 0.06)),
}


def barrier_outcomes(df, stop_pct, target_pct):
    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    n = len(df)
    upper, lower = close * (1 + target_pct), close * (1 - stop_pct)
    never = HORIZON + 1
    hit_t = np.full(n, never, dtype="int32")
    hit_s = np.full(n, never, dtype="int32")
    for off in range(1, HORIZON + 1):
        fh = np.full(n, np.nan); fl = np.full(n, np.nan)
        fh[: n - off] = high[off:]; fl[: n - off] = low[off:]
        hit_t[(fh >= upper) & (hit_t == never)] = off
        hit_s[(fl <= lower) & (hit_s == never)] = off
    target = (hit_t < hit_s).astype(int)
    fut = np.full(n, np.nan); fut[: n - HORIZON] = close[HORIZON:]
    timeout_ret = fut / close - 1
    exit_ret = np.where(hit_t < hit_s, target_pct, np.where(hit_s <= hit_t, np.where(hit_s == never, timeout_ret, -stop_pct), 0))
    valid = np.arange(n) < n - HORIZON
    return target, exit_ret, valid


def build_tier(name, strategy_name):
    with session_scope() as db:
        symbols = None
        if strategy_name:
            symbols = db.execute(select(Strategy.symbols).where(Strategy.name == strategy_name)).scalar_one()
        stmt = select(Instrument).where(Instrument.is_active.is_(True))
        if symbols:
            stmt = stmt.where(Instrument.tradingsymbol.in_([s.upper() for s in symbols]))
        else:
            stmt = stmt.where(Instrument.is_watchlisted.is_(True))
        instruments = list(db.execute(stmt).scalars().all())
        index_df = load_index_candles(db, "day"); vix_df = load_vix_candles(db, "day")
        breadth_df = load_market_breadth(db, "day")
        frames = {v: [] for v in VARIANTS}
        for inst in instruments:
            raw = ds.load_candles(db, inst.id, "day")
            if len(raw) < 300:
                continue
            sector_df = load_sector_candles(db, get_sector_index(inst.tradingsymbol), "day")
            feat = build_features(raw, index_df, sector_df, vix_df, breadth_df).reset_index(drop=True)
            atr = feat["atr_14_pct"].to_numpy(float)
            for v, fn in VARIANTS.items():
                stop_pct, target_pct = fn(np.nan_to_num(atr, nan=0.03))
                target, exit_ret, valid = barrier_outcomes(feat, stop_pct, target_pct)
                f = feat.copy()
                f["target"], f["exit_ret"], f["stop_pct"] = target, exit_ret, stop_pct
                f["label_end_ts"] = f["ts"].shift(-HORIZON)
                f["symbol"] = inst.tradingsymbol
                f = f[valid].dropna(subset=[*FEATURE_COLUMNS, "exit_ret", "label_end_ts"])
                frames[v].append(f[[*FEATURE_COLUMNS, "target", "exit_ret", "stop_pct", "label_end_ts", "symbol", "ts"]])
    out = {v: pd.concat(fr, ignore_index=True).sort_values("ts").reset_index(drop=True) for v, fr in frames.items()}
    print(f"[{name}] symbols {out['fixed_8_4']['symbol'].nunique()}, rows {len(out['fixed_8_4']):,}", flush=True)
    return out


def folds_for(data, n_folds=5):
    dates = data["ts"].drop_duplicates().sort_values().to_numpy()
    blocks = np.array_split(np.arange(len(dates)), n_folds + 1)
    for k in range(1, n_folds + 1):
        b = blocks[k]
        t0, t1 = dates[b[0]], dates[b[-1]]
        test = data[(data["ts"] >= t0) & (data["ts"] <= t1)]
        train = data[(data["ts"] < t0) & (data["label_end_ts"] < t0)]
        yield k, train, test


def evaluate(name, variant, data):
    rows = []
    for k, train, test in folds_for(data):
        if train["target"].nunique() < 2 or test["target"].nunique() < 2:
            continue
        est, scaler, m = tr.fit_and_score(train, test, "lightgbm")
        proba = est.predict_proba(scaler.transform(test[FEATURE_COLUMNS].to_numpy(float)))[:, 1]
        test = test.assign(p=proba)
        top = test.nlargest(max(int(len(test) * TOP_FRACTION), 1), "p")
        for label, part in (("model_top5", top), ("all_rows", test)):
            r = (part["exit_ret"] - ROUND_TRIP_COST) / part["stop_pct"]
            rows.append(dict(tier=name, variant=variant, fold=k, sel=label, n=len(part),
                             win=float((part["exit_ret"] > 0).mean()), mean_R=float(r.mean()),
                             stop_pct=float(part["stop_pct"].mean()), auc=m["roc_auc"]))
    return rows


if __name__ == "__main__":
    results = []
    for name, strat in TIERS.items():
        data = build_tier(name, strat)
        for v, d in data.items():
            rows = evaluate(name, v, d)
            results += rows
            top = [r for r in rows if r["sel"] == "model_top5"]
            base = [r for r in rows if r["sel"] == "all_rows"]
            print(f"[{name}] {v:10s} model top5%: R/trade {np.mean([r['mean_R'] for r in top]):+.3f}  "
                  f"win {np.mean([r['win'] for r in top]):.2f}  folds>0 {sum(r['mean_R']>0 for r in top)}/{len(top)}"
                  f"  | all rows R {np.mean([r['mean_R'] for r in base]):+.3f}  | avg stop {np.mean([r['stop_pct'] for r in top]):.3f}"
                  f"  | AUC {np.mean([r['auc'] for r in top]):.3f}", flush=True)
    df = pd.DataFrame(results)
    print("\n==== SUMMARY: expectancy in R per trade, after costs, model's top 5% ====")
    piv = df[df.sel == "model_top5"].groupby(["tier", "variant"])["mean_R"].mean().unstack()
    print(piv.round(3).to_string())
    print("\nfolds with positive expectancy (of 5):")
    print(df[df.sel == "model_top5"].assign(pos=lambda d: d.mean_R > 0).groupby(["tier", "variant"])["pos"].sum().unstack().to_string())
    print("\nunfiltered (all rows) R for reference:")
    print(df[df.sel == "all_rows"].groupby(["tier", "variant"])["mean_R"].mean().unstack().round(3).to_string())
    df.to_csv(sys.argv[1] if len(sys.argv) > 1 else "vol_label.csv", index=False)
