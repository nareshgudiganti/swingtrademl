# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import psycopg, json, math, pandas as pd, numpy as np
from zoneinfo import ZoneInfo
IST=ZoneInfo("Asia/Kolkata")
OUT=r"C:\Users\nares\AppData\Local\Temp\claude\d--machine-learning-swing-trade-bot\7760ad1c-0af2-4782-9c69-ebf2dca1d1d5\scratchpad\corp_actions"
ev=json.load(open(r"D:\machine learning\swing-trade-bot\docs\brain\evidence\stock_split\stock_split_ev15.json"))
u49=set(ev['used_49']); print(len(u49), [k for k in ev if k not in('used_49',)][:12])
c=psycopg.connect("host=localhost port=5433 dbname=swing_trade_ml user=swingtrade password=<LOCAL_PG_PASSWORD>",connect_timeout=15)
df=pd.read_sql("""select i.tradingsymbol sym,i.is_watchlisted wl,i.is_active act,i.segment,i.instrument_type it,c.ts,c.open,c.high,c.low,c.close,c.volume
 from candles c join instruments i on i.id=c.instrument_id where c.interval='day' and i.segment='NSE' and i.instrument_type='EQ' order by 1,c.ts""",c)
df['day']=pd.to_datetime(df.ts,utc=True).dt.tz_convert(IST).dt.date
print(df.sym.nunique(), len(df))
print('dups',df.duplicated(['sym','day']).sum())
df.to_pickle(OUT+r"\bars.pkl")
pop=set(df.sym)
print('in 49 present',len(u49&pop), 'missing',u49-pop)
rows=[]
ratios={'1/2':.5,'1/3':1/3,'1/4':.25,'1/5':.2,'1/10':.1,'2/3':2/3,'3/4':.75,'4/5':.8,'5/6':5/6,'9/10':.9,'2':2,'3':3,'4':4,'5':5,'10':10}
for s,g in df.groupby('sym'):
    g=g.sort_values('day').reset_index(drop=True)
    g['r']=g.close/g.close.shift(1)
    g['ov']=g.open/g.close.shift(1)
    g['vr']=(g.volume+1)/(g.volume.shift(1)+1)
    # 20-day median volume
    g['vmed']=g.volume.shift(1).rolling(20,min_periods=5).median()
    g['vx']=g.volume/g.vmed
    for i in range(1,len(g)):
        r=g.r[i]
        if not np.isfinite(r):continue
        gap=(g.day[i]-g.day[i-1]).days
        big=abs(r-1)>=0.15
        # signature
        sig=None
        for k,v in ratios.items():
            if abs(r/v-1)<0.06 and abs(r-1)>0.12: sig=k;break
        if big or sig:
            rows.append(dict(sym=s,day=g.day[i],prev=g.day[i-1],gapdays=gap,prev_close=g.close[i-1],open=g.open[i],close=g.close[i],ret=r-1,ov=g.ov[i]-1,vol=g.volume[i],vx=g.vx[i],vr=g.vr[i],sig=sig,in49=s in u49,
              close_next=g.close[i+1] if i+1<len(g) else np.nan, close_p5=g.close[min(i+4,len(g)-1)]))
E=pd.DataFrame(rows); E.to_csv(OUT+r"\raw_flags.csv",index=False)
print(len(E), E.sym.nunique(), E.in49.sum(), E[E.in49].sym.nunique())
print((E.ret.abs()>=.2).sum(), (E.sig.notna()).sum())
pd.set_option('display.width',250,'display.max_rows',500,'display.max_columns',30)
print(E[E.ret.abs()>=.15][['sym','day','prev_close','close','ret','ov','vx','sig','in49']].round(3).to_string())
