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
d=pd.read_pickle(str(WORK / "bars.pkl"))
rows=[]
for s,g in d.groupby('sym'):
    g=g.sort_values('day').reset_index(drop=True)
    g['r']=g.close/g.close.shift(1)-1
    g['vmed']=g.volume.shift(1).rolling(20,min_periods=5).median()
    g['vx']=g.volume/g.vmed
    g['gap']=g.day.diff().dt.days if False else pd.Series([None]+[(g.day[i]-g.day[i-1]).days for i in range(1,len(g))])
    m=g[(g.r.abs()>=.07)&(g.r.abs()<.15)&(g.vx<2.0)]
    for _,x in m.iterrows(): rows.append((s,x.day,round(x.r,3),round(x.vx,2),x.close))
print(len(rows))
for r in rows:print(r)
# halts: long gaps in calendar vs market
cal=sorted(d.day.unique()); print('calendar days',len(cal))
cnt=d.groupby('sym').day.nunique(); print(cnt.describe())
# stocks missing days relative to own span
miss=[]
for s,g in d.groupby('sym'):
    days=set(g.day); lo,hi=min(days),max(days)
    exp=[x for x in cal if lo<=x<=hi]
    m=len(exp)-len(days)
    if m>0: miss.append((s,m))
print('missing-day stocks',len(miss),sorted(miss,key=lambda x:-x[1])[:15])
g=d[d.sym=='NMDC'].sort_values('day').reset_index(drop=True)
i=g.index[g.day==dt.date(2022,10,27)][0];print(g.iloc[i-4:i+4][['day','open','close','volume']])
