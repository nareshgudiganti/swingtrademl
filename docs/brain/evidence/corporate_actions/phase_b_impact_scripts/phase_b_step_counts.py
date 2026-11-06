"""Counts-only structural analysis of Phase B price-step exposure. Reads bar DATES only. No prices, no returns, no scores."""
import csv, json, sys, os
from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo
import psycopg
IST = ZoneInfo("Asia/Kolkata")
ROOT = "D:/machine learning/anomaly-impact-wt/"
split = json.load(open(ROOT + "docs/brain/evidence/stock_split/stock_split_ev15.json"))
U49, EXTRA, REJECT = list(split["used_49"]), list(split["extra_training_set"]), list(split["reject_set"])
DEV_START, DEV_END, H = date(2025, 2, 1), date(2026, 8, 15), 15
# folds exactly as walk_forward.make_folds
folds, s = [], DEV_START
while s <= DEV_END:
    e = min(s + timedelta(days=27), DEV_END)
    if (e - s).days >= 6:
        folds.append((s - timedelta(days=1), s, e))
    s += timedelta(days=28)
assert len(folds) == 20, len(folds)
events = []
for r in csv.DictReader(open(ROOT + "docs/brain/evidence/corporate_actions/events.csv", encoding="utf-8")):
    if r["mechanical_step"].strip().lower() == "true":
        events.append((r["stock"], date.fromisoformat(r["date"]), r["event_type"], r["move_pct"]))
need = sorted(set(U49) | set(EXTRA) | {e[0] for e in events})
bars = {}
with psycopg.connect(os.environ["PHASE_B_IMPACT_LOCAL_DSN"], connect_timeout=5) as c:
    c.read_only = True
    cur = c.cursor()
    cur.execute("select i.tradingsymbol, c.ts from candles c join instruments i on i.id=c.instrument_id where c.interval='day' and i.tradingsymbol = any(%s) order by 1,2", (need,))
    for sym, ts in cur.fetchall():
        bars.setdefault(sym, []).append(ts.astimezone(IST).date())
missing = [x for x in need if x not in bars]
print("symbols needed", len(need), "missing in local DB:", missing)
days49 = sorted({d for s_ in U49 if s_ in bars for d in bars[s_] if DEV_START <= d <= DEV_END})
print("dev trading days (union of the 49):", len(days49), days49[0], days49[-1])
# scored stock-days: (sym, day) with a bar and an entry bar after it
scored = 0
for s_ in U49:
    L = bars.get(s_, [])
    sd = set(L)
    for d in days49:
        if d in sd and L.index(d) + 1 < len(L):
            scored += 1
print("scored stock-days in dev window (49 stocks):", scored, " avg stocks/day:", round(scored / len(days49), 2))
LOOK = (20, 50, 200, 252)
def where(sym):
    return "49" if sym in U49 else "extra128" if sym in EXTRA else "reject" if sym in REJECT else "other"
rows = []
for sym, s_date, etype, mv in events:
    L = bars.get(sym)
    if not L or s_date not in L:
        rows.append((sym, s_date, where(sym), "NO BARS/DATE LOCALLY")); continue
    idx = L.index(s_date)
    strad = [L[i] for i in range(idx - H, idx - 1) if i >= 0]            # decision days whose 15-bar path has pre- and post-step bars (14)
    aud = [L[i] for i in range(idx - H, idx) if i >= 0]                  # audit-style (15 rows)
    lab_dev = [d for d in strad if DEV_START <= d <= DEV_END]
    feat = {}
    for lk in LOOK:
        fd = [L[j] for j in range(idx, min(idx + lk - 1, len(L)))]       # decision days j>=ex whose lookback still spans the pre-step bar
        feat[lk] = (len(fd), len([d for d in fd if DEV_START <= d <= DEV_END]))
    in_test_fold = [k + 1 for k, (c_, a, b) in enumerate(folds) if a <= s_date <= b]
    step_in_train = [k + 1 for k, (c_, a, b) in enumerate(folds) if s_date <= c_]
    lab_touch_test = sorted({k + 1 for k, (c_, a, b) in enumerate(folds) for d in lab_dev if a <= d <= b})
    feat_touch_test = {lk: sorted({k + 1 for k, (c_, a, b) in enumerate(folds) for j in range(idx, min(idx + lk - 1, len(L))) if a <= L[j] <= b}) for lk in LOOK}
    rows.append((sym, s_date, where(sym), etype, mv, len(strad), len(aud), len(lab_dev), feat, in_test_fold, step_in_train, lab_touch_test, feat_touch_test))
out = {"events": []}
for r in rows:
    print("\n==", r[0], r[1], r[2])
    if len(r) == 4:
        print("  ", r[3]); continue
    sym, s_date, w, etype, mv, nst, naud, nlab_dev, feat, itf, sit, ltt, ftt = r
    print(f"  {etype} move {mv}%")
    print(f"  label-straddling decision days: {nst} (audit-style {naud}); inside dev window: {nlab_dev}; test folds touched by labels: {ltt}")
    for lk in LOOK:
        print(f"  feature lookback {lk}: decision days touched {feat[lk][0]} (inside dev window {feat[lk][1]}); test folds touched: {ftt[lk][:1]}..{ftt[lk][-1:]} (n={len(ftt[lk])})")
    print(f"  step falls in test window of fold(s): {itf}; step inside TRAINING window of folds: {len(sit)} of 20 ({sit[:1]}..{sit[-1:]})" if sit else f"  step falls in test window of fold(s): {itf}; step NOT inside training window of any fold")
    out["events"].append({"stock": sym, "date": str(s_date), "set": w, "label_straddle_days": nst, "label_days_in_dev": nlab_dev,
                          "feat_days_touched": {str(k): v[0] for k, v in feat.items()}, "feat_days_in_dev": {str(k): v[1] for k, v in feat.items()},
                          "test_folds_label": ltt, "folds_with_step_in_training": len(sit)})
# training-row shares per fold (approx: decision days with >=251 bars of history and a finished 15-bar label by the cutoff)
def train_rows(symbols, cutoff):
    n = 0
    for s_ in symbols:
        L = [d for d in bars.get(s_, []) if d <= cutoff]
        n += max(0, len(L) - H - 251)
    return n
print("\n== BAJAJELEC share of B2 training rows")
for sym in ("BAJAJELEC",):
    if sym in bars:
        L = bars[sym]; idx = L.index(date(2023, 9, 14))
        for k in (0, 9, 19):
            c_ = folds[k][0]
            tot = train_rows(sorted(set(U49) | set(EXTRA)), c_)
            lab = len([1 for i in range(idx - H, idx - 1) if L[i + H - 1 if i + H - 1 < len(L) else -1] <= c_])
            ft = len([1 for j in range(idx, min(idx + 251, len(L))) if L[j] <= c_])
            print(f"  fold {k+1} cutoff {c_}: B2 training rows ~{tot}; BAJAJELEC label-straddle rows {lab} ({lab/tot*100:.4f}%), feature rows touched {ft} ({ft/tot*100:.4f}%)")
print("\n== all mechanical events: membership summary")
for sym, s_date, etype, mv in events:
    print(f"  {sym:12s} {s_date} {where(sym):9s} move {mv:>7s}%  {etype[:48]}")
out["dev_days"] = len(days49); out["scored_stock_days"] = scored
json.dump(out, open(sys.argv[1], "w"), indent=1)
