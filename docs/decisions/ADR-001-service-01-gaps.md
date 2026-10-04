# ADR-001: Service 1 gap components, and what stays in the Brain

- **Date**: 2026-10-04
- **Status**: Proposed. Analysis accepted as the basis for planning. The owner has not yet
  approved the build list. Nothing is implemented.

## Context

The owner's brief asked to strengthen "Service 1 — Market Data & Input Processing" with 13
**[NEW GAP]** capabilities. The goal is data that is trustworthy, point-in-time correct,
replayable and ready for the TradeMind Brain. The brief forbids redesign, duplication and
infrastructure added for its own sake.

Checking the brief against the code showed:

- There is no separate Service 1. It is v1 ingestion (`services/ingestion.py`,
  `services/market_feeds.py`), the brain's `DatedReader`, M01 quality and M02 feature snapshots.
- Several gaps are **real defects that already affect replays and evidence**, not just missing
  features:
  - The replay universe uses today's watchlist (hindsight bias).
  - Candle upserts overwrite corrections, so the original value is lost.
  - Prices are not adjusted for corporate actions. M01 only excuses the jump.
  - The holiday calendar ends in 2026.
- Other gaps would be premature at the current scale (~50 NSE stocks, daily bars, one price
  source, ₹1–5L capital).

## Decision

1. **Add the gap capabilities as small modules and tables inside the existing backend.** No new
   service, no Kafka, Airflow or S3. Reuse Postgres/TimescaleDB, Redis, APScheduler, the
   `FeedSource` connector contract and `DatedReader`.
2. **Why each new component exists**:
   - *Point-in-time + correction log (1, 13)*: so a replay of a past day sees what was known that
     day, and decisions can be reproduced.
   - *Corporate action layer (3)*: so indicators and replays don't read fake crashes from splits
     and bonuses. It sits **beside** raw candles because v1's models were trained on raw stored
     prices and v1 must not change.
   - *Universe / eligibility (4)*: one point-in-time eligible list, replacing checks scattered
     across M01, M07 and `avoid.py`, and fixing the hindsight bug.
   - *Trading calendar (11)*: freshness depends on it, and it stops working on 1 Jan 2027.
   - *Readiness contract (10) and quality breakdown (9)*: so the Brain knows which inputs are
     actually present, not just one score.
   - *Run manifest for lineage and versioning (5, 8)*: answers "where did this value come from"
     and "which versions produced this decision" at about 10% of the cost of a lineage store.
   - *Security master lite (2)*: so a renamed stock keeps its history (ISIN + symbol history).
   - *Same live/backfill path (7)*: already true. The one live/batch feature skew gets fixed.
3. **Deferred**: source reconciliation (6) waits until there's a second source. Microstructure (12)
   waits until size or small caps make spread matter.

## What remains in the TradeMind Brain (not moved into Service 1)

Service 1 only answers: what instrument is this, where did the data come from, when did it happen
and when was it known, is it fresh and trustworthy, was there a corporate action, is the stock
eligible, is all required data ready, and can we reproduce and trace it.

These stay in the Brain modules:

- Perception of state and market mode: M02, M03, M10, M04 situations.
- Signals and scoring: v1 models, M12 setups, M06 calibrated meta-model.
- Opportunity selection, ranking, candidate competition: M08 decision engine with pluggable rules.
- Sector and news context: M11, M13.
- Risk and capital allocation: M07 risk gate (mandatory), M14 portfolio.
- Memory, tracking, learning: M05, M15, M09.
- Trading stages: M18 (shadow → approval → auto).
- The constitution's caution rule: bad or stale data never makes a decision more aggressive.

Eligibility (gap 4) filters **who may be considered**. It never ranks or chooses.

## Consequences

- Replays and evidence (M06, M09) must be re-run after gaps 3, 4 and 13.
- This work competes with M18 for time. The split-contamination check decides whether gap 3 goes
  first.
- An alembic merge will be needed when the brain, plans and any Service 1 migrations meet.
