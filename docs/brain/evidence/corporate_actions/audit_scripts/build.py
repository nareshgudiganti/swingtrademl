# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import pandas as pd, numpy as np, datetime as dt, json
P = r"C:\Users\nares\AppData\Local\Temp\claude\d--machine-learning-swing-trade-bot\7760ad1c-0af2-4782-9c69-ebf2dca1d1d5\scratchpad\corp_actions"
d = pd.read_pickle(P + r"\bars.pkl").sort_values(['sym', 'day']).reset_index(drop=True)
u49 = set(json.load(open(r"D:\machine learning\swing-trade-bot\docs\brain\evidence\stock_split\stock_split_ev15.json"))['used_49'])
raw = pd.read_csv(P + r"\raw_flags.csv", parse_dates=['day'])
raw['day'] = raw.day.dt.date
D = dt.date.fromisoformat
U = lambda *a: " ; ".join(a)
BS = "https://www.business-standard.com/"
V = {
    ('ABFRL', '2025-05-22'): ('demerger (Madura -> Aditya Birla Lifestyle Brands)', '1:1', 'VERIFIED', U(BS + 'amp/markets/news/why-did-abfrl-share-price-crashed-67-to-88-from-269-in-trade-today-125052200495_1.html', 'https://www.angelone.in/news/share-market/aditya-birla-fashion-retail-share-price-in-focus-ahead-of-may-22-demerger-record-date')),
    ('SANOFI', '2024-06-13'): ('demerger (consumer healthcare)', '1:1', 'VERIFIED', BS + 'markets/news/sanofi-india-turns-ex-date-for-healthcare-biz-demerger-hits-5-upper-limit-124061300425_1.html'),
    ('VEDL', '2026-04-30'): ('demerger (4 companies)', '1 VEDL : 1 each of 4 new cos', 'VERIFIED', U('https://www.businesstoday.in/amp/markets/stocks/story/vedanta-demerger-why-this-stock-is-showing-up-to-63-fall-in-your-trading-apps-today-528146-2026-04-30', 'https://www.kotakneo.com/bulletins/corporate-action-update-vedanta-limited-demerger/')),
    ('ALLCARGO', '2025-11-12'): ('demerger (international supply chain -> Allcargo Global)', '1:1', 'VERIFIED (event, ex-date); price factor not found', U('https://www.motilaloswal.com/news/stocks/109150', 'https://www.itln.in/latest-news/allcargo-logistics-completes-demerger-of-international-business-1356984')),
    ('ALLCARGO', '2023-04-18'): ('demerger (TransIndia Realty)', '1:1', 'PARTIALLY (ex-date 18 Apr 2023 from secondary aggregator snippet)', 'https://www.pocketful.in/stocks/allcargo-logistics-ltd/corporate-actions/merger-demerger'),
    ('TRIVENI', '2026-07-22'): ('demerger (power transmission -> TPTL)', '1 TPTL : 3 TRIVENI', 'VERIFIED', U('https://www.businesstoday.in/markets/stocks/story/from-rs-33-to-rs-471-why-this-smallcap-multibagger-stock-is-showing-38-fall-in-some-apps-544369-2026-07-22', 'https://www.angelone.in/news/stocks/triveni-engineering-shareholders-to-receive-tptl-shares-record')),
    ('NMDC', '2022-10-27'): ('demerger (NMDC Steel)', '1:1', 'VERIFIED', U(BS + 'amp/article/markets/nmdc-trades-ex-date-for-demerger-stock-surges-14-amid-heavy-volumes-122102700302_1.html', 'https://www.indiainfoline.com/news/markets/nmdc-soars-ex-demerger')),
    ('SIEMENS', '2025-04-07'): ('demerger (Siemens Energy India)', '1:1', 'VERIFIED', BS + 'amp/markets/capital-market-news/siemens-soars-on-ex-date-for-demerger-125040700442_1.html'),
    ('TMPV', '2025-10-14'): ('demerger (Tata Motors CV -> TMLCV)', '1:1', 'PARTIALLY (record date 14 Oct verified; sources conflict 13 vs 14 Oct for ex-date)', 'https://www.theweek.in/news/biz-tech/2025/10/13/tata-motors-demerger-special-pre-open-session-stock-split-record-date-and-share-price-explained.html'),
    ('ITC', '2025-01-06'): ('demerger (ITC Hotels)', '1 ITC Hotels : 10 ITC', 'VERIFIED', U(BS + 'amp/markets/news/itc-down-1-ahead-of-ex-date-for-hotel-business-on-monday-january-6-125010300337_1.html', 'https://www.itcportal.com/investor/pdf/share-entitlement-ratio-report.pdf')),
    ('HINDUNILVR', '2025-12-05'): ('demerger (Kwality Walls ice cream)', '1:1', 'VERIFIED (dates/ratio); adjusted price not found', U(BS + 'markets/news/hul-share-price-nse-bse-kwality-walls-ice-cream-business-demerger-record-date-125120500267_1.html', 'https://www.hul.co.in/files/newspaper-publication-regarding-intimation-of-record-date-21-11-2025.pdf')),
    ('RELIANCE', '2023-07-20'): ('demerger (Jio Financial Services)', '1:1', 'VERIFIED', U(BS + 'amp/markets/news/all-eyes-on-jio-fin-price-discovery-special-session-by-bourses-on-thursday-123071900788_1.html', 'https://www.voicendata.com/jio-financial-shares-from-the-reliance-demerger-worth-rs-261-85-each')),
    ('BAJAJELEC', '2023-09-14'): ('demerger (resulting company name not found)', 'not found', 'PARTIALLY (BSE filing: record date 14 Sep 2023, NCLT 8 Jun 2023; ex-date and ratio not found)', 'https://www.bseindia.com/xml-data/corpfiling/AttachHis/301406b4-1161-448f-9336-fb9dfb0602c0.pdf (returned by search, not opened)'),
    ('SCI', '2023-03-31'): ('demerger (SCI Land & Assets)', '1:1', 'PARTIALLY (record date 31 Mar 2023, effective 14 Mar 2023; ex-date not confirmed)', BS + 'amp/article/markets/shipping-corporation-fixes-march-31-as-record-date-for-demerger-stk-up-4-123032000699_1.html'),
    ('PAYTM', '2024-02-02'): ('GENUINE MOVE (RBI order, lower circuit)', '-', 'GENUINE MOVE (prior signed doc; not re-searched)', 'docs/brain/evidence/sl_v1/gap_classification.md'),
    ('IIFL', '2024-03-05'): ('GENUINE MOVE (RBI gold-loan ban, 20% lower circuit)', '-', 'GENUINE MOVE', 'https://www.businesstoday.in/amp/markets/company-stock/story/iifl-finance-shares-crack-20-after-rbi-order-development-a-major-negative-setback-says-motilal-oswal-420093-2024-03-05'),
    ('IIFL', '2024-03-06'): ('GENUINE MOVE (2nd lower circuit)', '-', 'GENUINE MOVE', 'https://www.businesstoday.in/markets/company-stock/story/iifl-finance-shares-down-37-in-3-days-stock-price-targets-more-420346-2024-03-06'),
    ('INDUSINDBK', '2025-03-11'): ('GENUINE MOVE (derivatives accounting discrepancy)', '-', 'GENUINE MOVE', BS + 'amp/markets/news/indusind-tanks-20-at-lowest-level-since-nov-2020-on-account-discrepancies-125031100200_1.html'),
    ('IEX', '2025-07-24'): ('GENUINE MOVE (CERC market coupling order)', '-', 'GENUINE MOVE', 'https://businesstoday.in/markets/stocks/story/iex-shares-136-lakh-retail-investors-lose-rs-1450-crore-as-stock-crashes-28-486107-2025-07-24'),
    ('OFSS', '2024-01-18'): ('GENUINE MOVE (Q3 results)', '-', 'GENUINE MOVE (size differs by source)', BS + 'amp/markets/news/oracle-financial-hits-record-high-zooms-15-on-strong-q3-results-124011800116_1.html'),
    ('ADANIENT', '2023-02-01'): ('GENUINE MOVE (Hindenburg / FPO withdrawn)', '-', 'GENUINE MOVE', BS + 'amp/article/markets/adani-enterprises-joins-emaar-motherson-in-cancelling-share-sale-123020201152_1.html'),
    ('ADANIENT', '2023-02-02'): ('GENUINE MOVE (Hindenburg aftermath)', '-', 'GENUINE MOVE', BS + 'amp/article/markets/adani-group-shares-extend-fall-adani-enterprises-tanks-35-in-2-days-123020200265_1.html'),
}
for s in ['ADANIENT', 'ADANIPORTS', 'ADANIGREEN', 'ADANIENSOL', 'ADANIPOWER']:
    for dd in ['2023-01-27', '2023-01-30', '2023-01-31', '2023-02-02', '2023-02-03', '2023-02-06', '2023-02-08']:
        V.setdefault((s, dd), ('GENUINE MOVE (Adani group / Hindenburg period)', '-', 'GENUINE MOVE (group-level news; per-day cause not individually checked)', BS + 'amp/article/markets/adani-group-shares-extend-fall-adani-enterprises-tanks-35-in-2-days-123020200265_1.html'))
PSU = ['NTPC', 'ONGC', 'PFC', 'RECLTD', 'BHEL', 'HUDCO', 'IRCON', 'SAIL', 'NATIONALUM', 'GAIL', 'HINDPETRO', 'HINDCOPPER', 'CONCOR', 'J&KBANK', 'LICHSGFIN', 'PNB', 'UNIONBANK', 'TITAGARH', 'RAILTEL', 'IRCTC', 'IDEA', 'HDFCAMC', 'INDUSTOWER', 'SCI', 'NIACL', 'ADANIPORTS', 'ABFRL', 'AMBUJACEM', 'ADANIENSOL', 'ADANIENT', 'ADANIGREEN', 'ADANIPOWER', 'IREDA', 'NHPC', 'RITES', 'SJVN', 'POONAWALLA', 'GRANULES', 'PAYTM', 'GAIL', 'CUB']
for s in PSU:
    V.setdefault((s, '2024-06-04'), ('GENUINE MOVE (election-result day market crash; PSU index -14..16%)', '-', 'GENUINE MOVE (market-level news verified; per-stock cause not individually checked)', U('https://www.angelone.in/news/share-market/10-psu-stocks-with-the-highest-decline-on-election-result-day', BS + 'amp/markets/news/sensex-plunges-over-4-000-points-intraday-check-factors-behind-the-fall-124060400591_1.html')))
extra = [('ITC', '2025-01-06'), ('HINDUNILVR', '2025-12-05'), ('RELIANCE', '2023-07-20'), ('TMPV', '2025-10-14')]
g = {s: x.reset_index(drop=True) for s, x in d.groupby('sym')}


def row(s, day):
    x = g[s]
    i = x.index[x.day == day][0]
    return dict(sym=s, day=day, prev_close=x.close[i - 1], open=x.open[i], close=x.close[i], ret=x.close[i] / x.close[i - 1] - 1,
                ov=x.open[i] / x.close[i - 1] - 1, vol=x.volume[i], vx=x.volume[i] / x.volume[max(0, i - 20):i].median(), sig=None, in49=s in u49, i=i)


have = {(r.sym, str(r.day)) for r in raw.itertuples()}
rows = []
for r in raw.itertuples():
    x = g[r.sym]
    i = x.index[x.day == r.day][0]
    rows.append(dict(sym=r.sym, day=r.day, prev_close=r.prev_close, open=r.open, close=r.close, ret=r.ret, ov=r.ov, vol=r.vol, vx=r.vx, sig=r.sig, in49=r.in49, i=i))
for s, day in extra:
    if (s, day) not in have:
        rows.append(row(s, D(day)))
E = pd.DataFrame(rows)
out = []
for r in E.itertuples():
    k = (r.sym, str(r.day))
    if k in V:
        t, ratio, st, url = V[k]
    elif abs(r.ret) >= .15 and r.vx >= 3:
        t, ratio, st, url = ('unknown (INFERRED market move: volume >=3x 20d median, no mechanical signature)', '-', 'UNVERIFIED', '')
    elif abs(r.ret) >= .15:
        t, ratio, st, url = ('unknown (INFERRED possible mechanical or circuit move: low volume reaction)', '-', 'UNVERIFIED', '')
    else:
        t, ratio, st, url = ('ratio-signature only (<15% move); no event found', '-', 'UNVERIFIED (no evidence of corporate action)', '')
    out.append(dict(stock=r.sym, date=r.day, move_pct=round(r.ret * 100, 1), open_gap_pct=round(r.ov * 100, 1),
                    vol_vs_20d_median=round(r.vx, 2) if pd.notna(r.vx) else None, ratio_signature=r.sig, event_type=t, ratio=ratio,
                    status=st, source_url=url, in_49='yes' if r.in49 else 'no', mechanical_step=t.startswith('demerger'), bar_index=r.i))
O = pd.DataFrame(out).sort_values(['mechanical_step', 'in_49', 'date'], ascending=[False, False, True])
O.drop(columns=['bar_index']).to_csv(P + r"\events.csv", index=False)
print('rows', len(O), 'stocks', O.stock.nunique(), 'in49 rows', (O.in_49 == 'yes').sum(), 'in49 stocks', O[O.in_49 == 'yes'].stock.nunique())
print(O.status.str.split(' ').str[0].value_counts().to_dict())
print('>=15%:', (O.move_pct.abs() >= 15).sum(), '>=20%:', (O.move_pct.abs() >= 20).sum())
big = O[O.move_pct.abs() >= 20]
print('>=20 status:', big.status.str.split(' ').str[0].value_counts().to_dict())
print(big[big.status == 'UNVERIFIED'][['stock', 'date', 'move_pct', 'vol_vs_20d_median']].to_string())
M = O[O.mechanical_step & O.status.str.startswith(('VERIFIED', 'PARTIALLY'))].copy()
NB = {s: len(x) for s, x in g.items()}
res = []
W = [5, 10, 20, 50, 200, 252]
H = [5, 10, 15]
for r in M.itertuples():
    n = NB[r.stock]
    i = int(r.bar_index)
    rec = dict(stock=r.stock, date=r.date, move=r.move_pct, in49=r.in_49, n_bars=n, idx=i)
    for w in W:
        rec[f'feat{w}'] = min(i + w - 1, n - 1) - i + 1
    for h in H:
        rec[f'lab{h}'] = (i - max(i - h, 0)) if i >= 1 else 0
    res.append(rec)
R = pd.DataFrame(res)
R.to_csv(P + r"\impact_by_event.csv", index=False)
pd.set_option('display.width', 250)
print(R.to_string())
tot49 = d[d.sym.isin(u49)].shape[0]
tot = d.shape[0]
for name, sub, T in [('49', R[R.in49 == 'yes'], tot49), ('306', R, tot)]:
    print(name, 'events', len(sub), 'stocks', sub.stock.nunique(), 'bars', T)
    for c in [f'feat{w}' for w in W] + [f'lab{h}' for h in H]:
        print('  ', c, sub[c].sum(), f"{sub[c].sum() / T * 100:.2f}%")


def union(sub, fw=252, h=15):
    s = 0
    for st, gg in sub.groupby('stock'):
        mark = np.zeros(NB[st], bool)
        for r in gg.itertuples():
            i = int(r.idx)
            mark[i:min(i + fw, NB[st])] = True
            mark[max(0, i - h):i] = True
        s += mark.sum()
    return s


for name, sub, T in [('49', R[R.in49 == 'yes'], tot49), ('306', R, tot)]:
    u = union(sub)
    print(name, 'union rows 252feat+15lab', u, f"{u / T * 100:.2f}%", ' stocks', sub.stock.nunique())
print('universe stocks', d.sym.nunique(), 'bars', tot, tot49)
for s, day in [('NESTLEIND', '2024-01-05'), ('BAJFINANCE', '2025-06-16'), ('DRREDDY', '2024-10-28'), ('RELIANCE', '2024-10-28'), ('TATASTEEL', '2022-07-28')]:
    x = g[s]
    i = x.index[x.day == D(day)][0]
    print(s, day, 'close ret %.1f%%' % ((x.close[i] / x.close[i - 1] - 1) * 100), 'open gap %.1f%%' % ((x.open[i] / x.close[i - 1] - 1) * 100), 'vol x20d med %.2f' % (x.volume[i] / x.volume[i - 20:i].median()))
