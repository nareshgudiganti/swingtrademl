# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import psycopg
from zoneinfo import ZoneInfo
IST=ZoneInfo("Asia/Kolkata")
c=psycopg.connect("host=localhost port=5433 dbname=swing_trade_ml user=swingtrade password=<LOCAL_PG_PASSWORD>",connect_timeout=15)
cur=c.cursor()
for sym,d in [("ITC","2025-01-06"),("HINDUNILVR","2025-12-05"),("RELIANCE","2023-07-20")]:
    cur.execute("""select ts,open,high,low,close,volume from candles c join instruments i on i.id=c.instrument_id
      where i.tradingsymbol=%s and i.segment ilike '%%NSE%%' and interval='day' and ts between %s::date - 9 and %s::date + 6 order by ts""",(sym,d,d))
    print(sym,d)
    for r in cur.fetchall(): print(r[0].astimezone(IST).date(),*[float(x) for x in r[1:5]],r[5])
