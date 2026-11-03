# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import psycopg
c=psycopg.connect("host=localhost port=5433 dbname=swing_trade_ml user=swingtrade password=<LOCAL_PG_PASSWORD>",connect_timeout=15)
cur=c.cursor()
cur.execute("select count(*) from instruments where is_watchlisted and segment ilike '%NSE%'");print(cur.fetchone())
cur.execute("select count(*) from instruments where is_watchlisted");print(cur.fetchone())
cur.execute("select tradingsymbol from instruments where is_watchlisted order by 1");print([r[0] for r in cur.fetchall()])
