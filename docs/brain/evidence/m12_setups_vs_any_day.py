"""Honest check: after each setup, how often did +8% come before -4% within 15 days?"""
from collections import defaultdict
import numpy as np, pandas as pd
from sqlalchemy import select
from swing_trade_ml.brain.modules.m12_stock.setups import find_setups
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml.dataset import load_candles

def outcome(b, i):
    entry = b.close[i]; hi, lo = entry * 1.08, entry * 0.96
    for j in range(i + 1, min(i + 16, len(b))):
        if b.low[j] <= lo: return 0          # stop first (conservative if both same day)
        if b.high[j] >= hi: return 1
    return 0 if i + 15 < len(b) else None

res = defaultdict(list); years = defaultdict(lambda: defaultdict(list))
with session_scope() as db:
    syms = db.execute(select(Instrument).where(Instrument.is_watchlisted.is_(True))).scalars().all()
    for inst in syms:
        c = load_candles(db, inst.id, "day")
        if len(c) < 300: continue
        c = c.reset_index(drop=True)
        b = c[["open", "high", "low", "close", "volume"]].astype(float)
        for i in range(260, len(b) - 15, 1):
            o = outcome(b, i)
            if o is None: continue
            res["any day"].append(o)
            yr = pd.Timestamp(c.ts[i]).year
            for s in find_setups(b.iloc[i - 259 : i + 1].reset_index(drop=True)):
                res[s.label].append(o); years[s.label][yr].append(o)
            years["any day"][yr].append(o)
for k, v in res.items():
    print(f"{k:<22} n={len(v):>6}  hit +8% before -4%: {np.mean(v):.1%}")
print()
for k in years:
    print(k, {y: f"{np.mean(v):.0%} ({len(v)})" for y, v in sorted(years[k].items())})
