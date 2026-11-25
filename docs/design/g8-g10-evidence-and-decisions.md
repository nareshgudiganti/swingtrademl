# G8 / G9 / G10 candle freshness: evidence, corrections and decisions

Status: DESIGN ONLY. No code, migration, engine change, merge, deploy, database read or production query. Written 2026-11-25 (IST)
against `origin/main` `36bb2830`. This extends `docs/design/g8-g10-candle-freshness-design.md` (commit `06ab219a`, written against
`13b9c31b`); read that first. Paths are under `backend/src/swing_trade_ml/` unless stated. Candle times are stamped IST midnight
(18:30 UTC the previous day); every date means `.astimezone(IST).date()`.

## 1. Current behaviour: citations re-checked on main

Every file:line in section 1 of the earlier design was checked against `origin/main` `36bb2830`. Most are unchanged. Corrections:

| Earlier citation | Now | Note |
|---|---|---|
| `workers/scheduler.py:127-129` (15:40 "settled" comment) | `:130-131` | Jobs themselves unchanged: `daily_ingest` `:132-136` (15:40), `predict_watchlist` `:138-142` (15:42), `signal_scan` `:144-153` (SIGNAL_SCAN_CRON_HOUR/MINUTE) |
| `workers/jobs.py:512` ("out of services/engine.py" comment) | `:513` | `job_signal_scan` `:500`, `run_all_active` call `:510`: unchanged |
| `services/ingestion.py:412` (ON CONFLICT DO UPDATE) | `:413` | `_upsert_candles` `:344`, `CandleCorrection(` `:394`, `CandleArrival` insert `:426`, snapshot invalidation `:433`: unchanged |
| `brain/modules/m01_quality/quality.py:125-144` (market-wide rule) | `:119-150` (`summarise`; the 20% share test is `:140`) | `INGEST_DONE` `:23`, `MAX_STALE_SHARE` `:29`, `expected_bar_day` `:42`, `behind` test `:71-74`, `fresh=` `:113`: unchanged |
| `core/market_session.py:187-193` (docstring) | `:187-194` | `expected_latest_trading_day` `:186`: unchanged |
| `docs/verification/246-data-freshness.md` cites `system.py:45` | `api/v1/endpoints/system.py:75` | The earlier design already used :75, which is right |

Confirmed unchanged: `services/engine.py:136` (`load_candles(... limit=min_bars+50)`), `:140` (`impl.evaluate`), `ml/dataset.py:42` (order and limit
at `:49,56-57`, no date bound), `brain/modules/m01_quality/module.py:44`, `brain/constitution.py:59` and `:84`,
`core/market_session.py:60,64,76,83,198`, `core/holidays.py:18`, `services/beginner_views.py:379` (calls
`expected_latest_trading_day` at noon, so it is also "previous trading day"), `db/models/market.py:116` (`CandleCorrection`) and `:138` (`CandleArrival`),
ingest log names at `workers/jobs.py:408,410` (`job.ingest.done`, `job.ingest.index_done`).

New fact worth stating: `ingestion.py:378` takes one `now = datetime.now(UTC)` for the whole batch of one instrument, and that `now` is what is
stored as `received_at` (`:426-432`, insert with DO NOTHING). So `received_at` is our clock at the moment we wrote the batch, not a provider time.

The contradiction c7 is still real in code: M01 expects TODAY's bar from 15:40 on a trading day (`quality.py:42-48`); the status page and beginner
view expect the PREVIOUS trading day all day (`market_session.py:186-194`).

## 2. G9 evidence status

Searched `origin/main` (backend/src, backend/tests, backend/scripts, backend/alembic, docs) for "published", "publish", "ingested_at",
"candle_arrivals", "CandleArrival", "arrival". Result:

| Item | Where | What it records |
|---|---|---|
| `candle_arrivals` table | migration `alembic/versions/20261013_1800_candle_arrivals.py`; model `db/models/market.py:138-151` | Columns: `instrument_id` (FK, cascade), `interval` (text), `ts` (timestamptz, the bar time), `received_at` (timestamptz). Primary key `(instrument_id, interval, ts)` (`pk_candle_arrivals`), index `ix_candle_arrivals_received_at`. |
| Writer | `services/ingestion.py:425-432` | First `received_at` per bar, never updated (DO NOTHING). Bars stored before 2026-10-13 have no row. |
| `candle_corrections` | `db/models/market.py:116-135` | `old_*` and `new_*` OHLCV and `corrected_at` (our clock). |
| Tests | `tests/test_candle_arrivals.py`, `tests/test_verify_246_data_freshness.py:106-139` | They prove "first arrival is kept" and "a late bar is stamped with the arrival date". |
| Readers | none | `test_verify_246_data_freshness.py:265-268` asserts nothing outside the writer reads these tables. |
| Docs | `docs/architecture/architecture-gaps.md:17`, `service-01-market-data.md:91`, `docs/LEGACY-INVENTORY.md:219,422` (story S11), `docs/verification/246-data-freshness.md` | Say `ingested_at`/`known_at` is a gap; S11 plans a reader. |
| Log/export tooling | `backend/scripts/` | None for arrivals. `audit_session_days.py` only checks dates against the holiday list (no database, no network). `backend/scripts/groww_probe.py` is untracked in the main checkout and not on main. |

Not found anywhere: `ingested_at`, `published_at` or any provider-side publication time for candles. (The only "published" hits are unrelated: model files,
the capital ladder, billing text, side-feed comments such as `market_feeds.py:9` and `m01_quality/module.py:23`.)

Answer to "provider publish time or only our arrival time": **only our arrival time.** `received_at` is an UPPER BOUND on when the provider made the bar
available, and it cannot be earlier than our first fetch. The daily ingest first runs at 15:40 IST, so a same-day `received_at` around 15:40 means
"it was available by then"; it cannot show it was available earlier. A next-day `received_at` is ambiguous: the provider was late, or our ingest failed or
skipped that day. The only text claim that Zerodha does not publish the day's candle the same day is the docstring at `core/market_session.py:187-194`; no
timestamped proof is in the repo. Status: **EVIDENCE MISSING for provider publish time; ARRIVAL evidence exists in production only and was not read.**

### Exact export request for the owner (read-only, no credentials in the text)

Run against the production Postgres by the owner, in a read-only session. Replace the ten symbols; keep NIFTY (check its exact `tradingsymbol` with query 0).

```sql
-- 0. Find the exact symbol text for the index and check the symbols exist (10 rows expected).
SELECT id, tradingsymbol, exchange
FROM instruments
WHERE tradingsymbol IN ('NIFTY 50','RELIANCE','TCS','INFY','HDFCBANK','ICICIBANK','SBIN','ITC','LT','KEI')
ORDER BY tradingsymbol;

-- 1. One row per (symbol, session) for the last 20 sessions that exist in the candles table for the first symbol listed.
WITH sessions AS (
  SELECT DISTINCT (c.ts AT TIME ZONE 'Asia/Kolkata')::date AS session_date
  FROM candles c
  JOIN instruments i ON i.id = c.instrument_id
  WHERE i.tradingsymbol = 'RELIANCE' AND c.interval = 'day'
  ORDER BY session_date DESC
  LIMIT 20
)
SELECT
  i.tradingsymbol,
  (ca.ts AT TIME ZONE 'Asia/Kolkata')::date                      AS session_date_ist,
  to_char(ca.received_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS') AS received_at_ist,
  ((ca.received_at AT TIME ZONE 'Asia/Kolkata')::date
     - (ca.ts AT TIME ZONE 'Asia/Kolkata')::date)                AS days_after_session,
  EXISTS (SELECT 1 FROM candle_corrections cc
          WHERE cc.instrument_id = ca.instrument_id AND cc.interval = ca.interval AND cc.ts = ca.ts) AS was_corrected,
  (SELECT to_char(min(cc.corrected_at) AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS')
     FROM candle_corrections cc
    WHERE cc.instrument_id = ca.instrument_id AND cc.interval = ca.interval AND cc.ts = ca.ts) AS first_corrected_at_ist
FROM candle_arrivals ca
JOIN instruments i ON i.id = ca.instrument_id
JOIN sessions s ON s.session_date = (ca.ts AT TIME ZONE 'Asia/Kolkata')::date
WHERE ca.interval = 'day'
  AND i.tradingsymbol IN ('NIFTY 50','RELIANCE','TCS','INFY','HDFCBANK','ICICIBANK','SBIN','ITC','LT','KEI')
ORDER BY i.tradingsymbol, session_date_ist;
```

Also send (from the worker logs, with their IST timestamps) the lines `job.ingest.done` and `job.ingest.index_done` for the same 20 sessions. A
session with no row in query 1 means either the bar predates 2026-10-13 or it was never stored; say which if known.

How to read it: `days_after_session = 0` and a time near 15:40 for most symbols and most sessions means the same-day bar was available when we first asked.
`days_after_session = 1` for most sessions means the previous-trading-day rule (status page) is right. Mixed results mean neither fixed rule is safe.
Neither result shows the exact publication minute; that needs the probe in question 2 below.

## 3. G8 gate placement: scan job or engine

The gate rules are in section 2 of the earlier design and are unchanged (present, valid, not stale in trading days, calendar sound, market-wide, ingest
outcome). This section only compares where it runs.

| | A. In `workers/jobs.py` `job_signal_scan` (before `run_all_active`, `:510`) | B. In `services/engine.py` (before `impl.evaluate`, `:140`) | C. Brain only (today) |
|---|---|---|---|
| Frozen? | No. `workers/jobs.py` is not in `trial_freeze.json`. | Yes. `services/engine.py` is frozen; needs `scripts/approve_trial_change.py`. | `m01_quality/*`, `constitution.py` are frozen; no change proposed. |
| What it can do | Skip the WHOLE scan, or the whole strategy run, when market-wide checks fail (benchmark stale, more than 20% stale, calendar missing, ingest failed). It cannot skip single instruments without touching the engine. | Skip a single stock whose last bar is not the expected session; the rest still run. | Already fails closed: unfresh data forces NO NEW TRADES and downgrades TRADE to WATCH (`constitution.py:59,84`). Does not cover the v1 scan. |
| Trial effect | Directly changes behaviour on stale days: no v1 signals where today there would be some. | Same, but per stock. | None. |
| Risk | Over-blocking on a single bad stock (all or nothing). | Edits a frozen file in the middle of the trial. | The v1 path stays exposed (gap d2). |
| Recommendation | Interim choice: market-wide check only, record-only per-stock list. | Only after the trial or with explicit owner approval. | Keep. |

Direction check: every block moves toward caution; nothing loosens. Exits, stops and open positions are never gated.

My recommendation: ship A in a "record only" mode first (write a warning line and an Admin message when the check would have blocked, but do not skip),
compare it with real days, then let the owner switch it to blocking. Nothing in A needs a migration if the record is a log line; an `ingest_runs` table
(section 4) is needed only for rule 6.

## 4. G10 validation rules and audit fields (TEXT ONLY, NEEDS OWNER APPROVAL, no migration file)

Rules (each produces an event; only "block" severity can stop a new signal):

| Rule | Detects | Severity | Basis |
|---|---|---|---|
| R1 duplicate unchanged | same `(instrument, interval, ts)` re-delivered with identical OHLCV | warn (counted, no row per repeat in `candle_corrections`) | `ingestion.py:394-413` compares values today |
| R2 late | first arrival after the expected publication for the session; record lateness in trading days and minutes | warn, block if the bar is the expected-day bar | needs G9 evidence for "expected publication" |
| R3 corrected | values differ from what we stored; classify price vs volume, size of change, and whether a signal for that session had already run | warn; block (void) if a signal already ran | extends `candle_corrections` |
| R4 missing session | a calendar trading day between first and last stored bar with no bar | block if the missing day is the expected day, else warn | `core/market_session.py:64` |
| R5 unexpected session | a bar on a weekend or listed holiday | warn (could be a special session; see question 8) | `core/holidays.py:18` has no special sessions |
| R6 invalid | OHLC not ordered, price <= 0, NaN, negative volume | block for new signals; keep the stored row | rule 2 of the earlier design |
| R7 bad timestamp | `ts` is not IST midnight | block | candle convention |
| R8 ingest failed or partial | the session's ingest run is not `complete` | block | needs the run record below |

Proposed `candle_audit_events` fields (NEEDS OWNER APPROVAL): `id`, `instrument_id`, `interval`, `session_date` (IST date), `event_type`
(`late | corrected | duplicate_unchanged | missing_session | unexpected_session | invalid | bad_timestamp | ingest_failed`), `provider`,
`provider_published_at` (nullable; filled only if a provider ever gives it), `received_at`, `detected_at`, `ingest_run_id`, `old_values` and `new_values`
(json, nullable), `signal_run_affected` (bool), `severity` (`warn | block`), `note`.
Proposed `ingest_runs` (NEEDS OWNER APPROVAL): `id`, `started_at`, `finished_at`, `interval`, `symbols_requested`, `symbols_ok`, `symbols_failed`,
`bars_written`, `status` (`complete | partial | failed`). `candle_arrivals` and `candle_corrections` stay as they are. Old data is never deleted or
filtered; bars that fail a rule are kept and flagged. All new tables are additive; the migration is a separate approval.

## 5. Frozen-file check (`backend/tests/trial_freeze.json`, `files` has 98 entries)

I looked up each path in the keys of `trial_freeze.json` as it is on `origin/main`.

FROZEN (a change fails `tests/test_trial_freeze.py` until approved with `scripts/approve_trial_change.py`):
`services/engine.py`, `brain/modules/m01_quality/quality.py`, `brain/modules/m01_quality/module.py`, `brain/constitution.py`, `brain/reader.py`,
`brain/service.py`, `brain/contracts.py`, `strategies/ml_swing.py`, `strategies/base.py`, `ml/predict.py`.

NOT frozen: `workers/jobs.py`, `workers/scheduler.py`, `services/ingestion.py`, `core/market_session.py`, `core/holidays.py`, `db/models/market.py`,
`api/v1/endpoints/system.py`, `services/beginner_views.py`, `ml/dataset.py`, `services/feature_snapshots.py`, `services/execution.py`,
`services/score_history.py`, `services/identity/*`, `db/models/ml.py`, `services/horizon_nightly.py`, any new audit module.

Not frozen is not trial-safe: a gate in `workers/jobs.py`, a change to `INGEST_DONE`/`expected_bar_day`, or aligning M01 with the status page all change
which signals and trades happen. Record-only audit tables and the G9 probe do not change decisions (migration still needs approval).

## 6. Questions for the owner

1. Will you run the G9 export in section 2 (agents may not query production)? Which 10 symbols (the list in the SQL is a placeholder), and is the index instrument called `NIFTY 50`?
2. Approve a record-only probe job that asks the provider for the day's bar every few minutes after 15:30 IST for 10 sessions and logs the first time it appears? Only this gives the provider's publish time.
3. Until evidence exists, which is the interim truth for the day's bar: the previous trading day (status page) or today's bar after 15:40 (M01)? Recommendation: previous trading day, because it is the cautious one and has a code comment behind it.
4. Where may the gate live: `job_signal_scan` (not frozen, whole scan only) or the frozen engine? Recommendation: `job_signal_scan`, record-only first.
5. On a stale day, skip the whole v1 scan, or only the stale instruments? Per-stock needs the engine (frozen).
6. Approve the `candle_audit_events` and `ingest_runs` shapes (schema only; the migration is a later approval)?
7. A correction arrives after a signal ran: void the signal, or only warn? Recommendation: warn first; voiding changes outcomes.
8. Special sessions (Muhurat, weekend sessions) are not in `core/holidays.py`: who maintains them, and should a missing year fail closed (`calendar_warning`, `market_session.py:198`)?
9. After how many trading days may a missing bar be accepted as "provider will never publish" (halted stock) so the stock is excluded rather than blocking?
10. Should candle events (G10) appear beside each stock's score history in the identity ledger (#389 decision 9)?
