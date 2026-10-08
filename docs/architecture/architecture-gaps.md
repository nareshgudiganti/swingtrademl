# Architecture gaps — Service 1 (Market Data & Input Processing)

Source: the owner's brief "TradeMind — Service 1 Architecture Gap Integration" and the Service 1
v2.0 diagram (2026-10-04). Analysed against the code the same day. Nothing below is a new
requirement. Each gap is one the brief lists.

**Status key**: Implemented · Partial (some of it already exists in code) · Pending (not built) ·
Deferred (recommended to postpone).
Owner approved **P0 build** on 2026-10-05 (see `docs/brain/ROADMAP.md`). P1/P2 items remain as listed below.

For the full product diagram (Market Intelligence, Opportunity Center, validation layer, UI routes,
brain steps, and consolidated gap register), see
[`TRADEMIND-SOLUTION-OVERVIEW.md`](TRADEMIND-SOLUTION-OVERVIEW.md).

| # | Gap | Status | What exists today | What is missing | Recommendation |
|---|---|---|---|---|---|
| 1 | Point-in-time / as-of control | Partial | `DatedReader` bounds prices; `candle_corrections.corrected_at` on overwrite | No `ingested_at` on `candles` rows yet; no `source_version` | Partial — lite via correction log |
| 2 | Security master / instrument identity | Partial | `instruments` keyed by Kite `instrument_token` + `tradingsymbol`. Brain looks up by symbol. Side-feed tables use plain symbols. | ISIN, symbol history (renames), active_from/to, BSE, company_id. Sector and cap tier are uncommitted v2 work. | Pending (lite: ISIN + symbol history; skip BSE/company_id) |
| 3 | Corporate action processing | Deferred | Corporate-action *records* loaded (`upcoming_events`). M01 excuses big moves on split/bonus days. B0 split-check clean 2026-10-05. | No price adjustment layer. Candle upsert overwrites; risk if contamination appears later. | **Deferred** unless `brain split-check` flags suspicious moves. |
| 4 | Universe / eligibility layer | Partial | `watchlist_snapshots` + replay via `brain_universe(as_of=)`; live unchanged | One consolidated eligibility step across M01/M07/avoid | **Priority.** Extend snapshots / eligibility rules |
| 5 | Data lineage / provenance | Partial | `brain_runs.context.data_manifest` (feature set, universe snapshot date, connectors) | Full trace to source rows | Partial — manifest lite |
| 6 | Source reconciliation | Pending | One price source (Kite). NSE bhavcopy is already downloaded for delivery data. | Precedence, conflict tolerance and status between sources | **Deferred.** Optional nightly Kite-close vs bhavcopy check feeding quality. |
| 7 | Backfill / replay pipeline | Partial (mostly done) | Same candle save path; `obv_slope` denominator fixed in `ml/features.py` | Re-train evidence after deploy | Partial — skew fix in code |
| 8 | Data versioning | Partial | Manifest carries `feature_set_version` + connector latest days | Full schema/version registry | Partial — manifest lite |
| 9 | Data quality breakdown | Partial | M01 named penalties → one score | Explicit components (freshness, completeness, plausibility, consistency, source confidence, CA integrity, cross-source agreement) | Pending. Don't fake source-confidence or cross-source scores while there's one source. |
| 10 | Data availability / readiness contract | Partial | M01 freshness; `/brain/health` connector status via `brain/connectors.py` | Per-stock price readiness + UI labels | Partial — market feeds on health |
| 11 | Trading calendar | Partial | `core/holidays.py` includes provisional **2027** (verify vs NSE circular). | Muhurat sessions, timing changes | Partial — 2027 list in code |
| 12 | Market microstructure / execution inputs | Partial | `adv_inr_20`; last price in `quotes` | Bid, ask, spread, depth | **Deferred** (not material for daily swing trades at ₹1–5L) |
| 13 | Late data / correction handling | Done | `candle_corrections` on upsert; `feature_snapshots` invalidated from corrected bar (lazy recompute on next nightly) | — | — |

## Implemented (lite)

As of 2026-10-05: **#4** (PIT watchlist snapshots), **#11** (2027 calendar provisional), **#13** (correction log + snapshot invalidation), **#5/#8** (run `data_manifest`), **#10** (connector status on brain health), **#7** (`obv_slope` fix). **#3** adjusted prices **deferred** (B0 clean). Phase 1 gate replay documented in `docs/brain/ROADMAP.md`.

## Diagram items recommended NOT to build

These are from the v2.0 diagram, not the 13 gaps. Listed so they aren't picked up by mistake:
Kafka/Redis streams raw-data queue, Airflow, S3/object storage, dead-letter queue service,
alternative data (social sentiment, satellite, Google Trends: owner decided "not planned"),
NewsAPI/FRED/Polygon/Alpha Vantage connectors, BSE feed, 1- and 5-minute data.

## Recommended build order (post P0, 2026-10-05)

0. **Done:** B0 split-check; P0 shipped (#4, #11, #13 correction log + snapshot invalidation, #1 lite, manifest, health feeds, #7).
1. **Next:** #9 quality breakdown; #2-lite; M06/M09 evidence doc.
2. **Deferred:** #3 adjusted layer (unless split-check regresses), #6, #12, BSE, full lineage graph.

Re-run M06 and M09 evidence after any change that affects replay prices or universe.
