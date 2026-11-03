# Price change detector (report only)

**What it does.** Kite sometimes restates old prices after a split, bonus or demerger. Our
daily top-up only refetches the last two days, so older stored bars stay on the old scale
and a fake price step appears on the ex-date. This tool finds those cases and tells you.
**It never changes data, never writes to the candle tables and never queues a refetch.**

**Code:** `backend/src/swing_trade_ml/services/price_change_detector.py`
**Tests:** `backend/tests/test_price_change_detector.py` (pure, no database, no network)

## Checks
1. Overlap check: last ~10 trading days, all stocks, every run.
2. Older-date check: each run, a rotating slice of stocks (by hash of symbol and date) is
   compared over the last ~260 trading days. Every stock gets a full-year check once per
   20 weekday runs (about a month; a market holiday can delay a stock a few days).
3. Restatement: any close differing by more than 0.5% (configurable). Classified as
   uniform scale (factor and the date it changes), scattered, or missing/extra dates.
4. Passive signatures on stored prices only: move of 7%+ with volume under 3x the 20-day
   median; split-like price ratios (1/2, 1/3, 1/4, 1/5, 1/10, 2/3, 3/4 and reverses) with an
   opposite volume step; and moves of 20%+ ("large move, needs a single-announcement lookup").
   Days already corrected or verified can be excluded.

## Run it offline (no Kite)
Prepare two files: stored bars and freshly fetched bars, JSON `{"SYMBOL": [{"date","open","high","low","close","volume"}, ...]}`
or CSV with columns `symbol,date,open,high,low,close,volume`.

    cd "D:\machine learning\detector-wt"
    set PYTHONPATH=backend\src
    backend\.venv\Scripts\python.exe -m swing_trade_ml.services.price_change_detector --offline stored.json fetched.json
    (optional) --exclude RELIANCE:2023-07-20  --threshold 0.01  --log backend/data/price_change.jsonl

## Online mode
`run_online(...)` / `run_detection_job(...)` take an injected `fetch_fresh(symbol, from, to)`.
The one-line injection point is a function that calls `kite_broker.get_historical_data(...)`.
That is deliberately not implemented here: Kite logins go to prod only. The job is **not**
registered in `workers/scheduler.py`; scheduling and deploy need owner approval.

## What to do with a finding
Look up the single exchange announcement; do not bulk-scrape NSE. Whether to refetch a
symbol is the owner's decision.
