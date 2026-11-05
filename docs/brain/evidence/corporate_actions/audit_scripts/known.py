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
import pandas as pd, json, datetime as dt
pd.set_option('display.width',250,'display.max_rows',500)
d=pd.read_pickle(str(WORK / "bars.pkl"))
ev=json.load(open(str(SPLIT_JSON)))
print(sorted(ev['used_49']))
def ctx(s,day,n=3):
    g=d[d.sym==s].sort_values('day').reset_index(drop=True)
    if g.empty: print(s,'ABSENT');return
    i=g.index[g.day>=dt.date.fromisoformat(day)]
    if len(i)==0: print(s,'no data after');return
    i=i[0]; print(s,day); print(g.iloc[max(0,i-n):i+n+1][['day','open','high','low','close','volume']].to_string())
for s,day in [('NESTLEIND','2024-01-04'),('BAJFINANCE','2025-06-16'),('BAJAJFINSV','2025-09-26'),('DRREDDY','2025-11-26'),('TATASTEEL','2022-07-28'),('ITC','2025-01-06'),('RELIANCE','2024-10-28'),('HINDUNILVR','2025-12-05'),('TMPV','2025-10-14'),('TATAMOTORS','2025-10-14')]:
    ctx(s,day)
