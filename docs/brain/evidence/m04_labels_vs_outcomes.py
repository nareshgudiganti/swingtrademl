"""Evidence for M04: under each market label, how often did a watch-list stock
reach +8% before -4% within 15 trading days, and how often did it hit -4% first?
Run with the check DB env vars and PYTHONPATH=src."""
from collections import defaultdict

import numpy as np
import pandas as pd
from sqlalchemy import select

from swing_trade_ml.brain.modules.m04_situations.novelty import novelty, state_vectors
from swing_trade_ml.brain.modules.m04_situations.rules import label_days
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml.dataset import load_candles


def dated(db, symbol):
    inst = db.execute(select(Instrument).where(Instrument.tradingsymbol == symbol)).scalars().first()
    c = load_candles(db, inst.id, "day")
    c["day"] = pd.to_datetime(c.ts, utc=True).dt.tz_convert("Asia/Kolkata").dt.date
    return c


with session_scope() as db:
    n = dated(db, settings.BENCHMARK_INDEX_SYMBOL)
    v = dated(db, "INDIA VIX")
    nifty = pd.Series(n.close.astype(float).values, index=n.day)
    vix = pd.Series(v.close.astype(float).values, index=v.day)
    labels = label_days(nifty, vix)["label"]
    vec = state_vectors(nifty, vix)
    unknown = {}
    for k in range(270, len(vec)):
        unknown[vec.index[k]] = novelty(vec.iloc[: k + 1]).is_unknown
    win, loss = defaultdict(list), defaultdict(list)
    for inst in db.execute(select(Instrument).where(Instrument.is_watchlisted.is_(True))).scalars():
        c = dated(db, inst.tradingsymbol)
        hi, lo, cl = c.high.to_numpy(float), c.low.to_numpy(float), c.close.to_numpy(float)
        for i in range(len(c) - 15):
            lab = labels.get(c.day[i])
            if lab is None or lab == "unlabelled":
                continue
            o = None
            for j in range(i + 1, i + 16):
                if lo[j] <= cl[i] * 0.96:
                    o = 0
                    break
                if hi[j] >= cl[i] * 1.08:
                    o = 1
                    break
            keys = [lab, "ALL"] + (["unknown"] if unknown.get(c.day[i]) else [])
            for key in keys:
                win[key].append(o == 1)
                loss[key].append(o == 0)
print("label distribution (days):", labels.value_counts().to_dict())
print("unknown days:", sum(unknown.values()), "of", len(unknown))
for k in sorted(win, key=lambda k: -len(win[k])):
    print(f"{k:<12} n={len(win[k]):>6}  +8% first {np.mean(win[k]):.1%}   -4% first {np.mean(loss[k]):.1%}")
