# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import psycopg
c=psycopg.connect("host=localhost port=5433 dbname=swing_trade_ml user=swingtrade password=<LOCAL_PG_PASSWORD>",connect_timeout=15)
cur=c.cursor()
cur.execute("select count(*),min(received_at),max(received_at) from candle_arrivals");print(cur.fetchone())
cur.execute("select date_trunc('day',received_at at time zone 'Asia/Kolkata')::date d,count(*) from candle_arrivals group by 1 order by 1 limit 12");print(cur.fetchall())
cur.execute("select count(*) from candles c where not exists(select 1 from candle_arrivals a where a.instrument_id=c.instrument_id and a.ts=c.ts)");print('bars w/o arrival',cur.fetchone())
cur.execute("select i.tradingsymbol,min(c.ts),max(c.ts),count(*) from candles c join instruments i on i.id=c.instrument_id where i.tradingsymbol in ('NESTLEIND','BAJFINANCE','NMDC','TAALTECH','TRIVENI') group by 1");print(cur.fetchall())
cur.execute("select tradingsymbol from instruments where tradingsymbol in ('TAALTECH','BLSE','BUILDPRO','MOLDTECH','JSWDULUX','AZADIND','BANSALWIRE','OLAELEC','NATCOPHARM','KMSUGAR')");print(cur.fetchall())
