"""Evidence for M05: does recalling similar past cases predict the next outcome?

Walk-forward by month: every case in month M is scored using only cases whose
outcome was known before M began (the same key widening as recall.py). Then
compare the recalled hit rate with what happened. Run with the check DB env
vars and PYTHONPATH=src. Universe: today's watch list (survivor-biased)."""
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score
from sqlalchemy import select

from swing_trade_ml.brain.modules.m04_situations.rules import label_days
from swing_trade_ml.brain.modules.m05_memory.cases import build_cases
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml.dataset import load_candles

import sys

RICH = "--rich" in sys.argv  # add distance from the 1-year high to the key
LEVELS = [["market", "stock", "trend", "vol"], ["market", "stock", "trend"], ["stock", "trend"], ["stock"]]
if RICH:
    LEVELS = [["market", "dd52", "trend", "vol"], ["market", "dd52", "trend"], ["dd52", "trend"], ["dd52"]]


def bars_of(db, inst):
    c = load_candles(db, inst.id, "day")
    c["day"] = pd.to_datetime(c.ts, utc=True).dt.tz_convert("Asia/Kolkata").dt.date
    return c[["day", "open", "high", "low", "close", "volume"]].astype({"close": float, "high": float, "low": float})


with session_scope() as db:
    def inst(sym):
        return db.execute(select(Instrument).where(Instrument.tradingsymbol == sym)).scalars().first()
    n, v = bars_of(db, inst(settings.BENCHMARK_INDEX_SYMBOL)), bars_of(db, inst("INDIA VIX"))
    labels = label_days(pd.Series(n.close.values, index=n.day), pd.Series(v.close.values, index=v.day))["label"]
    parts = []
    for i in db.execute(select(Instrument).where(Instrument.is_watchlisted.is_(True))).scalars():
        b = bars_of(db, i)
        if len(b) >= 260:
            cs = build_cases(i.tradingsymbol, b, labels)
            dd = (b.close / b.close.rolling(250, min_periods=1).max() - 1).set_axis(b.day)
            cs["dd52"] = pd.cut(cs.day.map(dd), [-1, -0.30, -0.15, -0.05, 0.01], labels=["<-30%", "-30..-15%", "-15..-5%", "near high"]).astype(str)
            parts.append(cs)
cases = pd.concat(parts, ignore_index=True)
cases["hit"] = (cases.outcome == "target").astype(int)
cases["month"] = pd.to_datetime(cases.day).dt.to_period("M")
print(f"{len(cases)} cases, {cases.symbol.nunique()} stocks, {cases.day.min()} to {cases.day.max()}, base hit {cases.hit.mean():.1%}")

rows = []
for month in sorted(cases.month.unique())[6:]:
    start = month.to_timestamp().date()
    hist = cases[cases.outcome_day < start]
    test = cases[cases.month == month].copy()
    if len(hist) < 1000:
        continue
    test["pred"], test["pred_ev"], test["level"] = np.nan, np.nan, -1
    for lvl, keys in enumerate(LEVELS):
        g = hist.groupby(keys).agg(n=("hit", "size"), p=("hit", "mean"), ev=("exit_return", "mean")).reset_index()
        g = g[g.n >= 30]
        m = test[test.level == -1].reset_index().merge(g, on=keys, how="inner").set_index("index")
        test.loc[m.index, ["pred", "pred_ev", "level"]] = m[["p", "ev"]].assign(level=lvl).values
    test["base"] = hist.hit.mean()
    rows.append(test.dropna(subset=["pred"]))
r = pd.concat(rows)
y, p = r.hit.to_numpy(), r.pred.to_numpy()
print(f"scored {len(r)} cases over {r.month.nunique()} unseen months; key level used: {r.level.value_counts().sort_index().to_dict()}")
print(f"AUC {roc_auc_score(y, p):.3f}   Brier memory {brier_score_loss(y, p):.4f} vs base rate {brier_score_loss(y, r.base):.4f}")
top = p >= np.quantile(p, 0.9)
print(f"top 10% by recalled chance: hit {y[top].mean():.1%} (all {y.mean():.1%})")
for lo, hi in [(0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, 1.01)]:
    m = (p >= lo) & (p < hi)
    if m.any():
        print(f"  recalled {lo:.0%}-{min(hi,1):.0%}: n={m.sum():>5}  said {p[m].mean():.1%}  happened {y[m].mean():.1%}")
pos = r.pred_ev > 0
print(f"recalled average result > 0: n={pos.sum()} ({pos.mean():.0%})  real average exit {r.exit_return[pos].mean()/0.04:+.2f} R"
      f"  vs others {r.exit_return[~pos].mean()/0.04:+.2f} R")
