"""Does high delivery predict +8% before -4% within 15 days? Spec rule vs stricter ones."""
import numpy as np, pandas as pd
from sqlalchemy import select
from swing_trade_ml.db.models.feeds import DailyDelivery
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml.dataset import load_candles

rules = {"spec: >avg 3 of 5": (1.0, 3), ">avg 4 of 5": (1.0, 4), ">=1.2x avg 3 of 5": (1.2, 3), ">=1.3x avg 4 of 5": (1.3, 4)}
out = {k: [] for k in rules}; base = []
with session_scope() as db:
    for inst in db.execute(select(Instrument).where(Instrument.is_watchlisted.is_(True))).scalars():
        c = load_candles(db, inst.id, "day")
        if len(c) < 300: continue
        c["day"] = pd.to_datetime(c.ts, utc=True).dt.tz_convert("Asia/Kolkata").dt.date
        d = pd.DataFrame(db.execute(select(DailyDelivery.trade_date, DailyDelivery.delivery_pct).where(
            DailyDelivery.symbol == inst.tradingsymbol, DailyDelivery.series == "EQ")).all(), columns=["day", "pct"]).dropna()
        m = c.merge(d, on="day", how="inner").reset_index(drop=True)
        if len(m) < 100: continue
        avg = m.pct.shift(1).rolling(20).mean()
        ratio = m.pct / avg
        hi, lo, cl = m.high.to_numpy(float), m.low.to_numpy(float), m.close.to_numpy(float)
        for i in range(25, len(m) - 15):
            o = None
            for j in range(i + 1, i + 16):
                if lo[j] <= cl[i] * 0.96: o = 0; break
                if hi[j] >= cl[i] * 1.08: o = 1; break
            o = 0 if o is None else o
            base.append(o)
            r5 = ratio.iloc[i - 4 : i + 1].to_numpy()
            for k, (mult, need) in rules.items():
                if np.sum(r5 > mult) >= need: out[k].append(o)
print(f"any day            n={len(base):>6}  hit {np.mean(base):.1%}")
for k, v in out.items():
    print(f"{k:<19} n={len(v):>6} ({len(v)/len(base):.0%} of days)  hit {np.mean(v):.1%}")
