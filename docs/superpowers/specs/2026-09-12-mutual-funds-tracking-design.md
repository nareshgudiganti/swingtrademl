# Mutual Funds Tracking — Design Spec

Status: approved by user, ready for implementation planning
Date: 2026-09-12

## 1. Problem

Personal finance already tracks bank transactions, recurring bills, and
loans ([[project_real_vs_paper_tracking]] area of the app), but has no
concept of mutual fund holdings at all — no data model, no NAV history, no
returns calculation. The user holds/watches mutual funds and wants them
visible alongside the rest of their net worth.

## 2. Goal

Track mutual fund holdings (units, purchase NAV, purchase date) and show
current value, absolute/annualized returns, and basic risk (volatility,
drawdown) per holding and in aggregate — using free, official NAV data.
**Track and analyze only** — no fund recommendations or screening in this
round (explicitly deferred by the user).

## 3. Non-goals

- No fund recommendation/ranking engine.
- No SIP scheduling or transaction-level MF ledger (buy/sell history) beyond
  the current holding's cost basis — if the user wants lot-level tracking
  later, that's a follow-up.
- No brokerage/RTA integration (CAMS/KFintech) to auto-import holdings —
  manual entry only, matching how loans are entered today.

## 4. Data source

**AMFI's daily NAV disclosure** (`https://www.amfiindia.com/spages/NAVAll.txt`)
— the mutual fund industry body's own public, regulator-mandated NAV
publication. This is official data the fund industry itself publishes for
public consumption, not scraped from a third party's rendered page, so it
fits the "no scraping" boundary agreed for stock data.

- **Current + latest NAV, all schemes**: `NAVAll.txt`, refreshed daily after
  the AMCs report (typically available ~9-11pm IST for that trading day).
- **Historical NAV time series** (for returns/volatility calculation): AMFI
  also publishes historical NAV files per date; a sync job backfills each
  tracked scheme's history once, then appends daily.

No third-party wrapper API is used — pulling directly from AMFI avoids a
dependency on an unofficial intermediary's uptime/rate limits.

## 5. Data model

New tables, alongside the existing `FinanceLoan` pattern in
`db/models/finance.py`:

- **`MutualFund`** — scheme master: `scheme_code` (AMFI's own code, natural
  key), `name`, `amc_name`, `category` (equity/debt/hybrid/etc., parsed from
  AMFI's category field), `is_tracked` (bool — only tracked schemes get
  their history synced, not all ~10,000+ AMFI schemes).
- **`MutualFundNav`** — time series: `scheme_id`, `date`, `nav`. Natural key
  `(scheme_id, date)`, same reasoning as `Candle`'s natural key (§ in the
  existing `db/models/market.py` — no surrogate id needed, nothing
  foreign-keys to an individual NAV row).
- **`MutualFundHolding`** — user's position: `scheme_id`, `units`,
  `purchase_nav`, `purchase_date`, `notes`. One row per lot; multiple lots
  per scheme are allowed (average cost computed, not stored).

## 6. Service layer

New `services/finance/mutual_funds.py`, following the existing
`services/finance/loans.py` convention (pure functions, nothing persisted
except the sync job's own writes):

- `sync_nav_snapshot(db)` — daily job: download `NAVAll.txt`, upsert
  `MutualFund` rows for any new tracked scheme, append today's `MutualFundNav`
  row for every tracked scheme.
- `backfill_scheme_history(db, scheme_id, start_date)` — one-time historical
  pull when a scheme is newly tracked (added because the user just entered a
  holding in it).
- `holding_value(holding, latest_nav)` — current value, absolute return,
  annualized (XIRR-style since purchase date) return.
- `holding_risk(scheme_id, nav_history)` — trailing volatility (stdev of
  daily returns) and max drawdown over the available history — same
  statistical shape as `ml/features.py`'s `volatility_20`, reused
  conceptually, not by import (different domain, different table).

## 7. Job wiring

`job_sync_mutual_fund_navs()` in `workers/jobs.py`, same
`session_scope`/swallow-and-report pattern as every other job. Scheduled
once daily, after market close (mirrors the existing end-of-day jobs' cron
slots — exact time picked at implementation to avoid clashing with the
existing 15:40-16:15 IST job cluster).

## 8. API

New router, `api/v1/endpoints/mutual_funds.py`:

- `GET /mutual-funds/search?q=` — scheme lookup by name (for the add-holding
  form), searching the already-synced `MutualFund` table (AMFI's full
  scheme list is pulled and stored regardless of tracking state, so search
  works before a scheme is explicitly tracked; only `is_tracked` schemes get
  NAV history).
- `POST /mutual-funds/holdings` — add a holding (scheme + units + purchase
  NAV/date); marks the scheme `is_tracked=True` and triggers a one-time
  history backfill.
- `GET /mutual-funds/holdings` — list holdings with computed current value,
  returns, and risk stats joined in.
- `PATCH` / `DELETE /mutual-funds/holdings/{id}` — edit/remove a lot.
- `GET /mutual-funds/{scheme_id}/history` — NAV time series for charting.

## 9. Frontend

New tab on the existing `Finance.tsx` page (8th tab, alongside
statement/transactions/calculation/analysis/loans/monthly/daily) — this is
personal net-worth data, same home as loans, not a trading surface. Reuses
the page's existing `Modal` pattern for add/edit-holding forms and the
existing `Stat` component for the summary strip (total invested, current
value, overall return %).

Per-holding row: scheme name, category, units, current value, return % (color
banded pos/neg per the existing `--pos`/`--neg` CSS tokens), a small
sparkline of NAV history (reuse whatever charting approach the dashboard
already uses, if any — confirm at implementation time).

The existing `/net-worth` endpoint (`finance.py:267`) is extended to include
mutual fund holdings' current value in the aggregate net worth figure.

## 10. Testing

- Unit tests for `holding_value`/`holding_risk` against known NAV series
  with hand-computed expected returns.
- A fixture/sample `NAVAll.txt` snippet for `sync_nav_snapshot` — parsing
  correctness (AMFI's pipe-delimited format, blank-line category headers)
  matters more than live-network tests here.
- API test for the add-holding → history-backfill → holdings-list round
  trip.

## 11. Open items deferred to implementation planning

- Exact AMFI historical-NAV file format/endpoint for backfill (per-date
  files vs. a bulk historical export) — confirm at implementation time,
  AMFI's exact URL scheme for historical data has changed before.
- Sparkline/charting library choice, if the dashboard doesn't already have
  one in place.
