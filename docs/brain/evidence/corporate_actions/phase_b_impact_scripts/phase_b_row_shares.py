"""Counts only: share of training rows and of scored stock-days touched by each step. Dates only; no prices."""
import json, csv, os
from datetime import date, timedelta
from zoneinfo import ZoneInfo
import psycopg
IST = ZoneInfo("Asia/Kolkata")
R = "D:/machine learning/anomaly-impact-wt/"
sp = json.load(open(R + "docs/brain/evidence/stock_split/stock_split_ev15.json"))
U49, EXTRA, REJ = sp["used_49"], sp["extra_training_set"], sp["reject_set"]
DS, DE, H = date(2025,2,1), date(2026,8,15), 15
folds=[]; s=DS
while s<=DE:
    e=min(s+timedelta(days=27),DE)
    if (e-s).days>=6: folds.append((s-timedelta(days=1),s,e))
    s+=timedelta(days=28)
syms = sorted(set(U49)|set(EXTRA)|set(REJ))
bars={}
with psycopg.connect(os.environ["PHASE_B_IMPACT_LOCAL_DSN"]) as c:
    c.read_only=True; cur=c.cursor()
    cur.execute("select i.tradingsymbol,c.ts from candles c join instruments i on i.id=c.instrument_id where c.interval='day' and i.tradingsymbol=any(%s) order by 1,2",(syms,))
    for a,t in cur.fetchall(): bars.setdefault(a,[]).append(t.astimezone(IST).date())
print("reject stocks with bars:", sum(1 for x in REJ if x in bars), "of", len(REJ))
days49 = sorted({d for x in U49 for d in bars[x] if DS<=d<=DE})
def rows_tr(symset, cutoff):  # usable training decision rows: >=251 bars history, label finished by cutoff
    return sum(max(0,len([d for d in bars[x] if d<=cutoff])-H-251) for x in symset if x in bars)
ev = {"RELIANCE":date(2023,7,20),"ITC":date(2025,1,6),"HINDUNILVR":date(2025,12,5),"BAJAJELEC":date(2023,9,14),"SANOFI":date(2024,6,13),"ABFRL":date(2025,5,22),"VEDL":date(2026,4,30)}
def touched(sym,s_date,cutoff):
    L=bars[sym]; i=L.index(s_date)
    lab=len([1 for k in range(max(0,i-H),i-1) if k+H-1<len(L) and L[k+H-1]<=cutoff])
    ft=len([1 for j in range(i,min(i+251,len(L))) if L[j]<=cutoff])
    return lab,ft
print("\nTraining-row shares (rows touched by the step in label or in a 252-bar feature lookback)")
for name,symset in (("B1/B3 training = the 49",U49),("B2 training = 49 + 128",sorted(set(U49)|set(EXTRA)))):
    print("==",name)
    for k in (0,9,19):
        c_=folds[k][0]; tot=rows_tr(symset,c_)
        parts=[]; allf=0
        for sym,sd in ev.items():
            if sym in symset and sd<=c_:
                lab,ft=touched(sym,sd,c_); parts.append(f"{sym} {lab}+{ft}"); allf+=ft
        print(f"  fold {k+1:2d} cutoff {c_}: ~{tot} rows; touched (label+feature) {'; '.join(parts)}; feature rows touched total {allf} = {allf/tot*100:.2f}%")
# scored stock-days touched, dev window, 49 stocks
print("\nScored stock-days (49) touched, dev window; total", sum(1 for x in U49 for d in days49 if d in set(bars[x]) and bars[x].index(d)+1<len(bars[x])))
tot49=sum(1 for x in U49 for d in days49 if d in set(bars[x]) and bars[x].index(d)+1<len(bars[x]))
for sym in ("ITC","HINDUNILVR","RELIANCE"):
    L=bars[sym]; i=L.index(ev[sym])
    lab=[L[k] for k in range(i-H,i-1) if DS<=L[k]<=DE]
    f252=[L[j] for j in range(i,min(i+251,len(L))) if DS<=L[j]<=DE]
    f50=[L[j] for j in range(i,min(i+49,len(L))) if DS<=L[j]<=DE]
    print(f"  {sym}: label {len(lab)} ({len(lab)/tot49*100:.3f}%), feature-50 {len(f50)} ({len(f50)/tot49*100:.2f}%), feature-252 {len(f252)} ({len(f252)/tot49*100:.2f}%)")
# reject set scored stock-days and the 4 in-window reject steps
rej_in=[x for x in REJ if x in bars]
totrej=sum(1 for x in rej_in for d in days49 if d in set(bars[x]) and bars[x].index(d)+1<len(bars[x]))
print("\nReject set scored stock-days (dev window):",totrej,"over",len(rej_in),"stocks")
rev={"SIEMENS":date(2025,4,7),"TMPV":date(2025,10,14),"ALLCARGO":date(2025,11,12),"TRIVENI":date(2026,7,22)}
lab_tot=0
for sym,sd in rev.items():
    L=bars[sym]; i=L.index(sd); lab=[L[k] for k in range(i-H,i-1) if DS<=L[k]<=DE]; lab_tot+=len(lab)
    print(f"  {sym} {sd}: {len(lab)} label-straddle stock-days")
print(f"  total {lab_tot} = {lab_tot/totrej*100:.3f}% of reject-set stock-days; max share of mean per-trade shift if each is wrongly a -4% stop vs 0 = {lab_tot*0.04/totrej*100:.4f} pp; vs 12 pp flip = {lab_tot*0.12/totrej*100:.4f} pp")
