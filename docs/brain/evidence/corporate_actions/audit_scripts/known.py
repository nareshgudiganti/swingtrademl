# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import pandas as pd, json, datetime as dt
pd.set_option('display.width',250,'display.max_rows',500)
d=pd.read_pickle(r"C:\Users\nares\AppData\Local\Temp\claude\d--machine-learning-swing-trade-bot\7760ad1c-0af2-4782-9c69-ebf2dca1d1d5\scratchpad\corp_actions\bars.pkl")
ev=json.load(open(r"D:\machine learning\swing-trade-bot\docs\brain\evidence\stock_split\stock_split_ev15.json"))
print(sorted(ev['used_49']))
def ctx(s,day,n=3):
    g=d[d.sym==s].sort_values('day').reset_index(drop=True)
    if g.empty: print(s,'ABSENT');return
    i=g.index[g.day>=dt.date.fromisoformat(day)]
    if len(i)==0: print(s,'no data after');return
    i=i[0]; print(s,day); print(g.iloc[max(0,i-n):i+n+1][['day','open','high','low','close','volume']].to_string())
for s,day in [('NESTLEIND','2024-01-04'),('BAJFINANCE','2025-06-16'),('BAJAJFINSV','2025-09-26'),('DRREDDY','2025-11-26'),('TATASTEEL','2022-07-28'),('ITC','2025-01-06'),('RELIANCE','2024-10-28'),('HINDUNILVR','2025-12-05'),('TMPV','2025-10-14'),('TATAMOTORS','2025-10-14')]:
    ctx(s,day)
