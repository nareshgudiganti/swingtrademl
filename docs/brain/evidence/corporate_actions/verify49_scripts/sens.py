# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import psycopg, pandas as pd, json, bisect
from datetime import date, timedelta
from zoneinfo import ZoneInfo
IST=ZoneInfo("Asia/Kolkata")
import swing_trade_ml.brain.service
from swing_trade_ml.brain import five_day as fd
c=psycopg.connect("host=localhost port=5433 dbname=swing_trade_ml user=swingtrade password=<LOCAL_PG_PASSWORD>",connect_timeout=15)
cur=c.cursor()
cur.execute("""select i.tradingsymbol,c.ts,c.open,c.high,c.low,c.close,c.volume from candles c join instruments i on i.id=c.instrument_id
 where i.is_watchlisted and c.interval='day' order by 1,2""")
from collections import defaultdict
g=defaultdict(list)
for s,ts,o,h,l,cl,v in cur.fetchall(): g[s].append(dict(day=ts.astimezone(IST).date(),open=float(o),high=float(h),low=float(l),close=float(cl),volume=float(v or 0)))
bars={s:pd.DataFrame(r) for s,r in g.items()}
print(len(bars),"stocks")
cal=fd.trading_calendar(bars)
EV={"RELIANCE":date(2023,7,20),"ITC":date(2025,1,6),"HINDUNILVR":date(2025,12,5)}
WIN={"fd_v1/wf_v1 2023-07-01..2025-01-31":(date(2023,7,1),date(2025,1,31)),
 "horizon_grid A 2025-02-03..2025-06-30":(date(2025,2,3),date(2025,6,30)),
 "horizon_grid B 2025-08-01..2025-12-31":(date(2025,8,1),date(2025,12,31)),
 "horizon_grid C 2026-05-01..2026-08-14":(date(2026,5,1),date(2026,8,14)),
 "walk_forward/portfolio_replay 2025-10-01..2026-08-15":(date(2025,10,1),date(2026,8,15)),
 "scoreboard s1 2025-02-01..2026-08-15":(date(2025,2,1),date(2026,8,15)),
 "scoreboard s2 2026-07-13..2026-09-08(data end)":(date(2026,7,13),date(2026,9,8))}
out=[]
for wn,(a,b) in WIN.items():
    days=[d for d in cal if a<=d<=b]
    for variant in ("hold","day5"):
        outs,exits=fd.outcomes_prod(bars,days,cal,{},variant=variant)
        # affected sets per stock
        aff_path=set();aff_lab=set();aff_feat=set()
        for s,ev in EV.items():
            bd=list(bars[s]["day"]); ei=bd.index(ev)
            for (ss,d),o in outs.items():
                if ss!=s: continue
                k=bisect.bisect_right(bd,d)  # entry bar
                xi=bd.index(o.exit_day) if o.exit_day else len(bd)
                di=bd.index(d)
                if di<ei<=xi: aff_path.add((s,d))     # trade opened before ex-date and still open at/over it
                if ei-5<=di<ei: aff_lab.add((s,d))
                if ei<=di<ei+252: aff_feat.add((s,d))
        allv=[o.net_return for o in outs.values() ]
        def mean_excl(excl):
            v=[o.net_return for k,o in outs.items() if k not in excl and o.status!="open"]
            return (sum(v)/len(v) if v else None,len(v))
        base=mean_excl(set())
        rows=dict(window=wn,variant=variant,finished=base[1],base=round(base[0]*100,4) if base[0] is not None else None)
        for nm,ex in [("excl_path",aff_path),("excl_path+label5",aff_path|aff_lab),("excl_path+label5+feat252",aff_path|aff_lab|aff_feat)]:
            m,n=mean_excl(ex); rows[nm]=(round(m*100,4) if m is not None else None,n,len(ex & set(outs)))
        out.append(rows); print(rows,flush=True)
json.dump(out,open(r"C:/Users/nares/AppData/Local/Temp/claude/d--machine-learning-swing-trade-bot/7760ad1c-0af2-4782-9c69-ebf2dca1d1d5/scratchpad/corp_actions/verify49/sens.json",'w'),indent=1,default=str)
