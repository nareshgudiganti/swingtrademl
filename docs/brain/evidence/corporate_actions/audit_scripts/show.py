# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import pandas as pd
pd.set_option('display.width',250,'display.max_rows',500)
E=pd.read_csv(r"C:\Users\nares\AppData\Local\Temp\claude\d--machine-learning-swing-trade-bot\7760ad1c-0af2-4782-9c69-ebf2dca1d1d5\scratchpad\corp_actions\raw_flags.csv")
b=E[E.ret.abs()>=.15]
print(b.iloc[170:][['sym','day','prev_close','close','ret','ov','vx','sig','in49']].round(3).to_string())
print("--- sig only (<15%), by sym:")
s=E[(E.ret.abs()<.15)]
print(s.groupby('sym').size().describe())
