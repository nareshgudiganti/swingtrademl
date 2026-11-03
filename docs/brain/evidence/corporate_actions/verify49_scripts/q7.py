# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import psycopg
c=psycopg.connect("host=localhost port=5433 dbname=swing_trade_ml user=swingtrade password=<LOCAL_PG_PASSWORD>",connect_timeout=15)
cur=c.cursor()
print("local positions date range")
cur.execute("select min(entry_at),max(coalesce(exit_at,entry_at)),count(*) from positions");print(cur.fetchone())
cur.execute("select min(opened_on),max(day),count(*) from brain_track");print(cur.fetchone())
cur.execute("select min(generated_at),max(generated_at) from signals");print(cur.fetchone())
for sym,d in [("ITC","2025-01-06"),("HINDUNILVR","2025-12-05"),("RELIANCE","2023-07-20")]:
    cur.execute("""select p.id,p.mode,p.status,p.entry_at,p.exit_at from positions p join instruments i on i.id=p.instrument_id where i.tradingsymbol=%s and p.entry_at<=%s::date+1 and coalesce(p.exit_at,now())>=%s::date""",(sym,d,d));print(sym,"positions across",cur.fetchall())
    cur.execute("select count(*) from brain_track where symbol=%s and opened_on<=%s and (day>=%s)",(sym,d,d));print(" brain_track",cur.fetchone())
    cur.execute("""select count(*) from signals s join instruments i on i.id=s.instrument_id where i.tradingsymbol=%s and s.generated_at between %s::date-8 and %s::date""",(sym,d,d));print(" signals in 8d before",cur.fetchone())
