# Architecture gaps — Service 1 (Market Data & Input Processing)

Source: the owner's brief "TradeMind — Service 1 Architecture Gap Integration" and the Service 1
v2.0 diagram (2026-10-04). Analysed against the code the same day. Nothing below is a new
requirement. Each gap is one the brief lists.

**Status key**: Implemented · Partial (some of it already exists in code) · Pending (not built) ·
Deferred (recommended to postpone).
Owner approval of a build list is **still outstanding**.

| # | Gap | Status | What exists today | What is missing | Recommendation |
|---|---|---|---|---|---|
| 1 | Point-in-time / as-of control | Partial | `DatedReader` bounds every price query by `Candle.ts <= as_of` | No `known_at` / `ingestion_time` / `source_version` on records. A replay can't tell what was known on a past day if data was later changed. | Pending, must-do with #13 |
| 2 | Security master / instrument identity | Partial | `instruments` keyed by Kite `instrument_token` + `tradingsymbol`. Brain looks up by symbol. Side-feed tables use plain symbols. | ISIN, symbol history (renames), active_from/to, BSE, company_id. Sector and cap tier are uncommitted v2 work. | Pending (lite: ISIN + symbol history; skip BSE/company_id) |
| 3 | Corporate action processing | Pending | Corporate-action *records* loaded (`upcoming_events`). M01 excuses big moves on split/bonus days. | No price adjustment. Candle upsert overwrites, so re-downloaded split-adjusted days could sit next to unadjusted old days and create fake crashes. | **Priority.** Separate adjusted layer, raw untouched. Run the read-only split-contamination check first. |
| 4 | Universe / eligibility layer | Partial (with bug) | Surveillance list (`trading_restrictions`), liquidity (`adv_inr_20`), history checks spread across M01, M07 and v1 `avoid.py` | One eligibility step. **Bug:** `DatedReader.universe()` returns today's watchlist even in replays (hindsight bias). | **Priority.** Point-in-time universe module. |
| 5 | Data lineage / provenance | Partial | `feature_snapshots.feature_set_version`, `brain_runs` id and context, model version recorded | Trace from a brain value back to its source records | Pending (lite: per-run data manifest, no lineage store) |
| 6 | Source reconciliation | Pending | One price source (Kite). NSE bhavcopy is already downloaded for delivery data. | Precedence, conflict tolerance and status between sources | **Deferred.** Optional nightly Kite-close vs bhavcopy check feeding quality. |
| 7 | Backfill / replay pipeline | Partial (mostly done) | Live and backfill use the same candle save function | M02 `obv_slope` differs from the batch feature code (live/batch skew) | Pending: fix the skew |
| 8 | Data versioning | Partial | `feature_set_version`, model version | data_schema / connector / normalization / corporate_action / calculation versions | Pending (lite: part of the #5 manifest) |
| 9 | Data quality breakdown | Partial | M01 named penalties → one score | Explicit components (freshness, completeness, plausibility, consistency, source confidence, CA integrity, cross-source agreement) | Pending. Don't fake source-confidence or cross-source scores while there's one source. |
| 10 | Data availability / readiness contract | Partial | M01 freshness. `connectors.py` lists side feeds. | Per-stock READY/PARTIAL list + `ready_for_brain` | Pending (cheap; also feeds TradeMind "Not connected yet" labels) |
| 11 | Trading calendar | Partial | `core/holidays.py` (2025–2026 only). Freshness already uses trading days. | 2027+ dates, special/Muhurat sessions, exchange timings | **Priority.** From 1 Jan 2027 holidays count as trading days, so data gets wrongly marked stale. |
| 12 | Market microstructure / execution inputs | Partial | `adv_inr_20`; last price in `quotes` | Bid, ask, spread, depth | **Deferred** (not material for daily swing trades at ₹1–5L) |
| 13 | Late data / correction handling | Pending | — | Candle upsert silently overwrites. No correction event and no recompute of affected features. | **Priority.** Small change log on corrections. |

## Implemented

None of the 13 gaps is implemented as of 2026-10-04.

## Diagram items recommended NOT to build

These are from the v2.0 diagram, not the 13 gaps. Listed so they aren't picked up by mistake:
Kafka/Redis streams raw-data queue, Airflow, S3/object storage, dead-letter queue service,
alternative data (social sentiment, satellite, Google Trends: owner decided "not planned"),
NewsAPI/FRED/Polygon/Alpha Vantage connectors, BSE feed, 1- and 5-minute data.

## Recommended build order (awaiting owner approval)

0. Read-only check: one-day moves > 30% on known split/bonus dates (needs local Postgres).
   This decides whether gap 3 goes ahead of M18 work.
1. Must-do (real defects): 3, 4, 11, 13 (with 1).
2. Next (cheap, high value): 5+8 run manifest, 10, 9, 2-lite, 7 skew fix.
3. Deferred: 6, 12, BSE, full lineage graph.

After 3, 4 and 13: re-run M06 and M09 evidence, because replays will see different data.
