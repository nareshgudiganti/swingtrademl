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
import psycopg
from zoneinfo import ZoneInfo
IST=ZoneInfo("Asia/Kolkata")
c=psycopg.connect(_dsn(),connect_timeout=15)
cur=c.cursor()
for sym,d in [("ITC","2025-01-06"),("HINDUNILVR","2025-12-05"),("RELIANCE","2023-07-20")]:
    cur.execute("""select ts,open,high,low,close,volume from candles c join instruments i on i.id=c.instrument_id
      where i.tradingsymbol=%s and i.segment ilike '%%NSE%%' and interval='day' and ts between %s::date - 9 and %s::date + 6 order by ts""",(sym,d,d))
    print(sym,d)
    for r in cur.fetchall(): print(r[0].astimezone(IST).date(),*[float(x) for x in r[1:5]],r[5])
