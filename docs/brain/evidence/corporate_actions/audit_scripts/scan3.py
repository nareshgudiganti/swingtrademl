# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths are relative to this script; set SWING_LOCAL_DB_URL (local Postgres connection string) and optionally SWING_EVIDENCE_WORK.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import os, pathlib
_HERE = pathlib.Path(__file__).resolve().parent
EVID = _HERE.parent  # the corporate_actions evidence folder (events.csv lives here)
SPLIT_JSON = EVID.parent / "stock_split" / "stock_split_ev15.json"
WORK = pathlib.Path(os.environ.get("SWING_EVIDENCE_WORK", EVID / "work"))  # intermediates/outputs; override with SWING_EVIDENCE_WORK
WORK.mkdir(parents=True, exist_ok=True)
def _dsn():
    v = os.environ.get("SWING_LOCAL_DB_URL")
    if not v:
        raise SystemExit("Set SWING_LOCAL_DB_URL, e.g. postgresql://swingtrade:<LOCAL_PG_PASSWORD>@localhost:5433/swing_trade_ml (local Docker Postgres)")
    return v
import pandas as pd, numpy as np, datetime as dt
pd.set_option('display.width',250,'display.max_rows',500)
d=pd.read_pickle(str(WORK / "bars.pkl")).sort_values(['sym','day']).reset_index(drop=True)
d['r']=d.groupby('sym').close.pct_change()
d['ov']=d.open/d.groupby('sym').close.shift(1)-1
d['vmed']=d.groupby('sym').volume.transform(lambda s:s.shift(1).rolling(20,min_periods=5).median())
d['vx']=d.volume/d.vmed
mk=d.groupby('day').r.median(); d['ex']=d.r-d.day.map(mk)
d['exov']=d.ov-d.day.map(d.groupby('day').ov.median())
m=d[(d.ex.abs()>=.07)&(d.exov.abs()>=.05)&(d.vx<2.5)]
print(len(m)); print(m[['sym','day','r','ov','vx']].round(3).to_string())
cal=sorted(d.day.unique()); print('calendar days',len(cal))
miss=[]
for s,g in d.groupby('sym'):
    days=set(g.day); lo,hi=min(days),max(days)
    mm=len([x for x in cal if lo<=x<=hi])-len(days)
    if mm>0: miss.append((s,mm,lo))
print('missing-day stocks',len(miss),sorted(miss,key=lambda x:-x[1])[:12])
g=d[d.sym=='NMDC'].reset_index(drop=True)
i=g.index[g.day==dt.date(2022,10,27)][0];print(g.iloc[i-4:i+4][['day','open','close','volume']])
