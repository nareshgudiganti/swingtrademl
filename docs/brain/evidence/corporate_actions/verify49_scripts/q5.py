# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import psycopg
c=psycopg.connect("host=localhost port=5433 dbname=swing_trade_ml user=swingtrade password=<LOCAL_PG_PASSWORD>",connect_timeout=15)
cur=c.cursor()
cur.execute("select table_name from information_schema.tables where table_schema='public' and (table_name ilike '%position%' or table_name ilike '%trade%' or table_name ilike '%idea%' or table_name ilike '%signal%' or table_name ilike '%order%' or table_name ilike '%brain%') order by 1");tabs=[r[0] for r in cur.fetchall()];print(tabs)
for t in tabs:
    cur.execute(f"select count(*) from {t}");print(t,cur.fetchone()[0])
