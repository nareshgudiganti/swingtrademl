"""Does adding delivery-% features improve walk-forward results?

Same rows, same folds, same algorithm; only the feature list differs.
Research only: nothing here writes to the database or touches a model.
"""
import json
import sys
import numpy as np
import pandas as pd
from sqlalchemy import select, text

from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml import dataset as ds
from swing_trade_ml.ml import train as tr
from swing_trade_ml.ml.features import FEATURE_COLUMNS

DELIVERY_FEATURES = [
    "deliv_pct_ratio_20",   # today's delivery % against this stock's own 20-day norm
    "deliv_pct_5d_vs_60d",  # last week's delivery % against its own 60-day norm
    "deliv_qty_ratio_20",   # delivered shares against this stock's own 20-day norm
    "deliv_pct_up_days_5d", # delivery % on up days minus on down days, last 5 days
]

TIERS = {
    "large": None,                 # production watchlist
    "mid": "ml_swing_midcap",
    "small": "ml_swing_smallcap",
}


def delivery_frame(db, symbols):
    rows = db.execute(
        text(
            "select symbol, trade_date, delivery_pct, delivery_qty, close_price from daily_delivery "
            "where series = 'EQ' and symbol = any(:syms) order by symbol, trade_date"
        ),
        {"syms": list(symbols)},
    ).all()
    df = pd.DataFrame(rows, columns=["symbol", "date", "pct", "qty", "close"])
    out = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("date").copy()
        g["ret"] = g["close"].pct_change()
        g["deliv_pct_ratio_20"] = g["pct"] / g["pct"].rolling(20, min_periods=15).mean()
        g["deliv_pct_5d_vs_60d"] = g["pct"].rolling(5, min_periods=4).mean() / g["pct"].rolling(60, min_periods=40).mean()
        g["deliv_qty_ratio_20"] = g["qty"] / g["qty"].rolling(20, min_periods=15).mean()
        up = g["pct"].where(g["ret"] > 0)
        down = g["pct"].where(g["ret"] < 0)
        g["deliv_pct_up_days_5d"] = up.rolling(5, min_periods=1).mean() - down.rolling(5, min_periods=1).mean()
        out.append(g[["symbol", "date", *DELIVERY_FEATURES]])
    return pd.concat(out, ignore_index=True)


def run_tier(name, strategy_name):
    with session_scope() as db:
        symbols = None
        if strategy_name:
            symbols = db.execute(select(Strategy.symbols).where(Strategy.name == strategy_name)).scalar_one()
        data = ds.build_training_dataset(db, symbols=symbols)
        syms = data["symbol"].unique()
        deliv = delivery_frame(db, syms)

    # Candle bars are stamped 00:00 IST; align to NSE's trading date the same way.
    data["date"] = pd.to_datetime(data["ts"]).dt.tz_convert("Asia/Kolkata").dt.date
    merged = data.merge(deliv, on=["symbol", "date"], how="left")
    have = merged.dropna(subset=DELIVERY_FEATURES)
    print(f"[{name}] rows {len(data):,} -> with delivery features {len(have):,} "
          f"({have['date'].min()} .. {have['date'].max()})", flush=True)
    have = have.sort_values("ts").reset_index(drop=True)

    results = {}
    for variant, cols in (("baseline", FEATURE_COLUMNS), ("with_delivery", FEATURE_COLUMNS + DELIVERY_FEATURES)):
        tr.FEATURE_COLUMNS = cols
        folds = tr.walk_forward(have, n_folds=5, embargo_days=15, algorithm="lightgbm")
        results[variant] = [
            (f["metrics"]["roc_auc"], f["metrics"]["precision_at_threshold"], f["metrics"]["confident_signal_count"])
            for f in folds if not f.get("skipped")
        ]
        aucs = [r[0] for r in results[variant]]
        print(f"[{name}] {variant:14s} AUC per fold {[round(a,3) for a in aucs]}  mean {np.mean(aucs):.4f}", flush=True)
    tr.FEATURE_COLUMNS = FEATURE_COLUMNS
    return results


if __name__ == "__main__":
    summary = {}
    for name, strat in TIERS.items():
        summary[name] = run_tier(name, strat)
    print("\n==== SUMMARY (paired by fold) ====")
    diffs, prec = [], []
    for name, r in summary.items():
        for (b, w) in zip(r["baseline"], r["with_delivery"]):
            diffs.append(w[0] - b[0]); prec.append(w[1] - b[1])
        print(name, "mean AUC  baseline %.4f  with delivery %.4f" % (
            np.mean([x[0] for x in r["baseline"]]), np.mean([x[0] for x in r["with_delivery"]])),
            "| precision@thr baseline %.3f with %.3f" % (
            np.mean([x[1] for x in r["baseline"]]), np.mean([x[1] for x in r["with_delivery"]])))
    diffs = np.array(diffs); prec = np.array(prec)
    print(f"\nAUC change per fold: mean {diffs.mean():+.4f}, improved in {(diffs>0).sum()}/{len(diffs)} folds, "
          f"std {diffs.std():.4f}")
    print(f"Precision-at-threshold change: mean {prec.mean():+.4f}, improved in {(prec>0).sum()}/{len(prec)} folds")
    json.dump({k: v for k, v in summary.items()}, open(sys.argv[1] if len(sys.argv) > 1 else "ablation.json", "w"))
