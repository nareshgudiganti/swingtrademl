# Service 1 — Market Data & Input Processing

Status as of 2026-10-04. Code references are to branch `brain/integration`
(worktree `.claude/worktrees/brain-int`), paths under `backend/src/swing_trade_ml/`.

> **Important.** "Service 1" is the first of 12 boxes in the TradeMind architecture picture
> ("Service 1: Market Data & Input Processing Service (v2.0)"). In the code it is **not a separate
> service**. It is a logical layer made of existing modules inside the one backend.
>
> The 13 **[NEW GAP]** components below were proposed on 2026-10-04 and analysed against the code.
> **None is implemented, and the owner has not yet approved which ones to build.** They are
> documented here as the target design, each marked with its status.

## 1. Current architecture (what exists today)

```
DATA SOURCES   Zerodha Kite (prices, instruments, quotes) · NSE public files/APIs
     ↓
CONNECTORS     Kite SDK client · NSE fetchers in services/market_feeds.py
     ↓
INGESTION      services/ingestion.py (APScheduler jobs: 15:40 daily ingest, backfill)
     ↓
VALIDATION     brain/modules/m01_quality (freshness, gaps, spikes, zero volume, impossible bars)
     ↓
NORMALIZATION  brain/modules/m02_perception (features + plain facts, e.g. adv_inr_20)
/ ENRICHMENT   v1 market_context loaders (index/sector history)
     ↓
STORAGE        Postgres/TimescaleDB: instruments, candles, quotes, daily_delivery,
               block_deals, institutional_flows, upcoming_events, trading_restrictions,
               feature_snapshots · Redis
     ↓
OUTPUT         brain/reader.py DatedReader → TradeMind Brain (M00–M18)
```

### Component responsibilities (existing)

| Component | File | Responsibility |
|---|---|---|
| Instrument sync | `services/ingestion.py` `sync_instruments` | Upserts Kite's instrument dump into `instruments` (key: Kite `instrument_token`). |
| Watchlist | `services/ingestion.py` `set_watchlist` | Marks `instruments.is_watchlisted` (~50 NSE stocks). |
| Candle ingest / backfill | `services/ingestion.py` | Daily bars into `candles`; live and backfill share the same save function. Upsert on `(instrument_id, interval, ts)` **overwrites** open/high/low/close/volume. |
| Quotes | `services/ingestion.py` | Last price per instrument in `quotes` (no bid/ask/depth). |
| Side feeds | `services/market_feeds.py` | NSE bhavcopy (delivery), bulk/block deals, FII/DII flows, upcoming events and corporate-action records, ASM/GSM surveillance list. |
| Feed connector contract | `brain/connectors.py` `FeedSource(name, latest(db, upto))` | Minimal contract: "what is the newest day you have, up to this moment?" Used for freshness. |
| Trading calendar | `core/holidays.py`; `m01_quality/quality.py` (`is_trading_day`, `expected_bar_day`, `trading_days_between`) | Hardcoded NSE holidays 2025–2026. Freshness counts trading days, not calendar days. |
| Data quality | `brain/modules/m01_quality/quality.py` | Score starts at 1, fixed penalties per problem → per-stock score + issues. Big moves on known split/bonus days are **excused** (`action_days`), not adjusted. |
| Feature snapshots | `brain/modules/m02_perception`, table `feature_snapshots` | What the brain saw per stock per day, unique on `(symbol, bar_date, feature_set_version)`. |
| DatedReader | `brain/reader.py` | The only brain read path. Every price query is bounded by `Candle.ts <= as_of`. Replays (`live=False`) get no model scores, holdings or account numbers. |
| Universe | `DatedReader.universe()` | Returns **today's** watchlisted + active instruments, even in a replay. |
| Run record | table `brain_runs` (+ `context` JSONB), `brain_decisions` | Run id, as_of, model version, per-stock decisions. |

### Existing contracts

- **Connector**: `FeedSource(name: str, latest: Callable[[Session, date], date | None])`.
- **Reader**: `DatedReader(db, as_of: datetime, live: bool)`; methods include `universe()`,
  `instrument_id(symbol)`, daily-bar loaders cut at `as_of`, `refresh_context_if_stale()`.
- **Module**: `run(view) -> Contribution`; pure, no DB writes, no orders.
- **Safety rule**: bad or stale data can only make a decision more cautious (constitution: data not
  fresh → NO_NEW_TRADES; unchecked/stale → TRADE capped at WATCH).

## 2. Approved / proposed NEW GAP additions

No gap has been approved for build yet. The table shows the recommendation from the 2026-10-04
analysis, which is awaiting the owner's decision. Full detail: `architecture-gaps.md`.

| # | Component [NEW GAP] | Status | Recommended shape (fits the existing code) |
|---|---|---|---|
| 1 | Point-in-time / as-of control | Pending | Add a "known at / ingested at" time to stored records. DatedReader already blocks future prices. |
| 2 | Security master | Pending (lite) | Add ISIN and a symbol-history table to `instruments`. BSE and company_id deferred. |
| 3 | Corporate action engine | Pending (**priority**) | Separate adjusted-price layer next to raw `candles`, read only by the brain. v1 prices untouched. |
| 4 | Universe / eligibility | Pending (**priority**) | One module gathering existing checks (surveillance, liquidity, history, quality). Must be point-in-time. |
| 5 | Data lineage | Pending (lite) | A data manifest saved with each brain run, not a separate lineage store. |
| 6 | Source reconciliation | Deferred | Only one price source. At most a nightly Kite-close vs NSE bhavcopy check feeding quality. |
| 7 | Backfill / replay pipeline | Mostly exists | Same save path already. Open item: M02 `obv_slope` differs from batch feature code. |
| 8 | Data versioning | Pending (lite) | Part of the run manifest (#5). `feature_set_version` and model version already exist. |
| 9 | Data-quality breakdown | Pending | Re-label M01's penalties as named components. No fake source-confidence while there is one source. |
| 10 | Readiness contract | Pending | Per-stock "which inputs are ready" list. Also feeds the TradeMind "Not connected yet" labels. |
| 11 | Trading calendar | Pending (**priority**) | Extend beyond 2026; model special (Muhurat) sessions. |
| 12 | Market microstructure inputs | Deferred | `adv_inr_20` exists. Bid/ask/depth not needed at current size. |
| 13 | Late data / correction handling | Pending (**priority**) | Small change log on candle corrections instead of silent overwrite. |

## 3. Final data flow (target, once approved gaps are built)

```
DATA SOURCES (Kite, NSE)
   ↓
CONNECTORS (existing FeedSource contract, Kite client)
   ↓
INGESTION (live + backfill, same path)
   ↓
POINT-IN-TIME CONTROL            [NEW GAP 1]  known_at / ingested_at on records
   ↓
SECURITY MASTER                  [NEW GAP 2]  ISIN + symbol history
   ↓
VALIDATION + DATA QUALITY        (M01)        + breakdown [NEW GAP 9], calendar [NEW GAP 11]
   ↓
SOURCE RECONCILIATION            [NEW GAP 6]  deferred
   ↓
CORPORATE ACTION ENGINE          [NEW GAP 3]  raw → adjusted layer (raw untouched)
   ↓                                          corrections logged [NEW GAP 13]
NORMALIZATION + ENRICHMENT       (M02, market_context)
   ↓
UNIVERSE / ELIGIBILITY           [NEW GAP 4]  point-in-time eligible universe
   ↓
DATA AVAILABILITY / READINESS    [NEW GAP 10] per-stock ready list + overall quality
   ↓
CANONICAL STORAGE                (existing Postgres/TimescaleDB/Redis)
   ↓
DATA LINEAGE / VERSION MANIFEST  [NEW GAP 5, 8] saved with each brain_run
   ↓
DatedReader → TRADEMIND BRAIN
```

Order of the boxes follows the owner's brief. In code most new boxes are small functions or
tables used by existing steps, not separate pipeline stages.

## 4. Rules for any Service 1 change

1. Preserve every existing component; add only approved gaps.
2. No new infrastructure (no Kafka, Airflow, S3, dead-letter queue service).
3. Reuse the connector contract, `DatedReader` and the replay mechanism.
4. v1 tables keep their current meaning. New layers sit alongside.
5. No decision logic in Service 1.
6. Gaps 3, 4 and 13 change what replays see, so M06/M09 evidence must be re-run after them.
