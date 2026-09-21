"""Point-in-time replay of the real ML swing strategy.

For each of 5 expanding walk-forward windows: train a model ONLY on data that ended
before the window (labels purged), then run the production strategy code (ml_swing
evaluate: confidence threshold, bear-market boost, liquidity/volatility/falling-knife
filters, +8%/-4% levels, exit-on-weak-confidence) through the production backtester
(account-size limits, sizing, costs, half-out at first target, time stop, drawdown
brake) on Rs 10 lakh.

Only the model and the (expensive) feature computation are swapped: features are
computed once per stock over the full history (every feature is causal) and looked up
per bar, instead of being rebuilt on every replay day. Everything else is production.

Benchmarks over the same windows: the SMA-crossover strategy through the same
backtester, and simply holding the NIFTY index.

Research only; writes nothing to the database.
"""
import json
import sys
import types
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml import dataset as ds
from swing_trade_ml.ml import train as tr
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features, build_label
from swing_trade_ml.ml.market_context import (
    load_index_candles, load_market_breadth, load_sector_candles, load_vix_candles,
)
from swing_trade_ml.ml.sector_map import get_sector_index
from swing_trade_ml.services import backtest as bt
from swing_trade_ml.strategies import ml_swing as msw

CAPITAL = 1_000_000.0
TIERS = {"large": None, "mid": "ml_swing_midcap", "small": "ml_swing_smallcap"}
STRESS_SLIPPAGE_BPS = 35.0  # ~0.3% worse than the base 5 bps, standing in for next-open gaps

FAKE_MODEL = types.SimpleNamespace(
    name="replay", version="pit", label_kind="barrier", prediction_horizon_days=15,
    target_return_pct=0.08, stop_return_pct=0.04,
)
STATE = {"symbol": None, "cache": {}, "bundle": None, "memo": {}}


def _patch_strategy():
    msw.get_active_model = lambda db, name=None: FAKE_MODEL
    msw._get_bundle = lambda model: STATE["bundle"]
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles", "load_market_breadth"):
        setattr(msw, loader, lambda *a, **k: None)
    msw.get_sector_index = lambda symbol: None

    def lookup(d, index_df, sector_df, vix_df, breadth_df):
        return STATE["cache"][STATE["symbol"]].loc[: d["ts"].max()]

    msw.build_features = lookup
    original = msw.MLSwingStrategy.evaluate

    def evaluate(self, df, instrument, db):
        key = (instrument.tradingsymbol, df["ts"].iloc[-1])
        if key in STATE["memo"]:
            return STATE["memo"][key]
        STATE["symbol"] = instrument.tradingsymbol
        decision = original(self, df, instrument, db)
        STATE["memo"][key] = decision
        return decision

    msw.MLSwingStrategy.evaluate = evaluate


def prepare(db, symbols):
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    stmt = (stmt.where(Instrument.tradingsymbol.in_([s.upper() for s in symbols]))
            if symbols else stmt.where(Instrument.is_watchlisted.is_(True)))
    instruments = list(db.execute(stmt).scalars().all())
    index_df = load_index_candles(db, "day")
    vix_df = load_vix_candles(db, "day")
    breadth_df = load_market_breadth(db, "day")
    cache, frames = {}, []
    for inst in instruments:
        raw = ds.load_candles(db, inst.id, "day")
        if len(raw) < 300:
            continue
        sector_df = load_sector_candles(db, get_sector_index(inst.tradingsymbol), "day")
        feat = build_features(raw, index_df, sector_df, vix_df, breadth_df).reset_index(drop=True)
        cache[inst.tradingsymbol] = feat.set_index("ts", drop=False)
        lab = build_label(feat, 15, 0.08, 0.04).dropna(subset=[*FEATURE_COLUMNS, "target"])
        lab["symbol"] = inst.tradingsymbol
        frames.append(lab[[*FEATURE_COLUMNS, "target", "label_end_ts", "symbol", "ts"]])
    data = pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)
    return sorted(cache), cache, data, index_df


def windows(data, n_folds=5):
    dates = data["ts"].drop_duplicates().sort_values().to_numpy()
    blocks = np.array_split(np.arange(len(dates)), n_folds + 1)
    for k in range(1, n_folds + 1):
        yield k, pd.Timestamp(dates[blocks[k][0]]), pd.Timestamp(dates[blocks[k][-1]])


def summarise(res):
    s = res.stats
    return {
        "return_pct": s["total_return_pct"], "trades": s["total_trades"], "win_rate": s["win_rate"],
        "profit_factor": s["profit_factor"] if np.isfinite(s["profit_factor"]) else None,
        "max_dd": s["max_drawdown_pct"], "avg_hold": s["avg_holding_days"],
        "avg_trade_pct": s["avg_return_pct"], "charges": s["total_charges"],
    }


def index_return(index_df, t0, t1):
    seg = index_df[(index_df["ts"] >= t0) & (index_df["ts"] <= t1)]
    return float(seg["close"].iloc[-1] / seg["close"].iloc[0] - 1)


def run_tier(name, strategy_name):
    _patch_strategy()
    with session_scope() as db:
        symbols = None
        if strategy_name:
            symbols = db.execute(select(Strategy.symbols).where(Strategy.name == strategy_name)).scalar_one()
        syms, cache, data, index_df = prepare(db, symbols)
        STATE["cache"] = cache
        print(f"[{name}] {len(syms)} symbols, {len(data):,} training rows", flush=True)
        out = []
        for k, t0, t1 in windows(data):
            train = data[(data["ts"] < t0) & (data["label_end_ts"] < t0)]
            test = data[(data["ts"] >= t0) & (data["ts"] <= t1)]
            est, scaler, m = tr.fit_and_score(train, test, "lightgbm")
            STATE["bundle"] = {"estimator": est, "scaler": scaler, "feature_names": FEATURE_COLUMNS}
            STATE["memo"] = {}
            start, end = t0.date(), t1.date()
            row = {"tier": name, "fold": k, "start": str(start), "end": str(end),
                   "auc": m["roc_auc"], "nifty_hold": index_return(index_df, t0, t1)}
            base_slip = settings.PAPER_SLIPPAGE_BPS
            try:
                row["ml"] = summarise(bt.run_backtest(db, "ml_swing", syms, start, end,
                                                      params={"model_name": "replay"}, starting_capital=CAPITAL))
                settings.PAPER_SLIPPAGE_BPS = STRESS_SLIPPAGE_BPS
                row["ml_stress"] = summarise(bt.run_backtest(db, "ml_swing", syms, start, end,
                                                             params={"model_name": "replay"}, starting_capital=CAPITAL))
            finally:
                settings.PAPER_SLIPPAGE_BPS = base_slip
            row["sma"] = summarise(bt.run_backtest(db, "sma_crossover", syms, start, end, starting_capital=CAPITAL))
            out.append(row)
            print(f"[{name}] fold {k} {start}..{end}  ML {row['ml']['return_pct']:+.1%} ({row['ml']['trades']} trades, "
                  f"DD {row['ml']['max_dd']:.1%})  stress {row['ml_stress']['return_pct']:+.1%}  "
                  f"SMA {row['sma']['return_pct']:+.1%}  NIFTY {row['nifty_hold']:+.1%}", flush=True)
        return out


if __name__ == "__main__":
    tiers = sys.argv[2].split(",") if len(sys.argv) > 2 else list(TIERS)
    results = []
    for t in tiers:
        results += run_tier(t, TIERS[t])
    json.dump(results, open(sys.argv[1], "w"), default=str)
    print("\n==== SUMMARY (5 walk-forward windows, Rs 10 lakh each) ====")
    df = pd.DataFrame(results)
    for t in tiers:
        d = df[df.tier == t]
        g = lambda key, f: [r[key][f] for r in d.to_dict("records")]
        print(f"\n{t}: windows {len(d)}")
        for label, key in (("ML strategy", "ml"), ("ML, worse fills", "ml_stress"), ("SMA benchmark", "sma")):
            rets = g(key, "return_pct")
            print(f"  {label:16s} mean window return {np.mean(rets):+.1%} | positive windows {sum(r>0 for r in rets)}/{len(rets)} | "
                  f"worst DD {max(g(key,'max_dd')):.1%} | trades {sum(g(key,'trades'))} | win rate {np.mean(g(key,'win_rate')):.0%}")
        print(f"  {'Hold NIFTY':16s} mean window return {np.mean(d['nifty_hold']):+.1%} | positive windows {(d['nifty_hold']>0).sum()}/{len(d)}")
