# Strategies Tab — Design Spec

Status: approved by user, ready for implementation planning
Date: 2026-09-14

## 1. Problem

The bot already runs multiple parallel strategies (large/mid/small-cap ML
swing variants, plus `sma_crossover`, `long_term_value`, and the advisory
`real_trading` strategy for manually-imported holdings — see
`strategies/base.py`'s `STRATEGY_REGISTRY` and the `Strategy` table). Every
`Trade` row already carries `strategy_id` and `is_win`, so per-strategy
win-rate is fully derivable — but nothing computes or shows it.

The only place to see or change strategies today is `/strategies`, a hidden
admin CRUD page (not in nav) built for configuration, not for a non-expert
user ([[feedback_jargon_free_ui]]) deciding which approach is working. The
user wants: which strategies exist, in plain English, how many stocks each
covers, its success rate so far, a recommendation on which is doing best, and
an easy way to switch — so that after a few months of paper trading they can
pick a winner. They also flagged Reports as too chart-heavy for what it needs
to convey.

## 2. Goal

A user-facing **Strategies** tab, promoted to the main nav, showing the
cap-tier strategies (large/mid/small) as plain-English cards: what it is,
tier, how many stocks it's watching, current win rate (with sample size),
and a "Recommended" badge on whichever is performing best once there's
enough data. Activate/deactivate remains the switch mechanism — already
matches the user's confirmed model ("only new trades use the new strategy;
open positions keep running under whatever strategy opened them"). Strategy
attribution becomes visible on Holdings and Portfolio, and Reports gains a
by-strategy breakdown while dropping its bar chart.

## 3. Non-goals (YAGNI)

- No changes to the ML model, feature engineering, or prediction logic —
  explicitly preserved as-is ([[project_ml_accuracy_roadmap]] work continues
  separately).
- No schema change to `Strategy` or `Trade` — all data needed already
  exists on those tables.
- No auto-switching. The recommendation is informational; the user still
  flips the activate/deactivate toggle themselves.
- No mutual exclusivity between strategies — the existing multi-active
  architecture (all three cap tiers can run simultaneously with separate
  capital allocations) is unchanged.
- No LLM-generated recommendation text — deterministic rule based on
  win rate / profit factor / sample size.
- No new charting library, no PDF/export. Reports moves toward tiles and
  tables, not away from them toward something heavier.
- `sma_crossover`, `long_term_value`, and `real_trading` are not redesigned
  into cards — they stay reachable via a collapsed "Advanced strategies"
  section reusing the existing admin table, not deleted.

## 4. Data model

No new tables or columns. Existing fields used:

- `Strategy`: `id`, `name`, `strategy_type`, `params` (has `model_name` for
  ml_swing variants), `is_active`, `mode`, `symbols` (JSON list; empty means
  "whole watchlist" per `engine._eligible_instruments()`), `capital_allocation`.
- `Trade`: `strategy_id`, `is_win`, `net_pnl`, `return_pct`, `holding_days`,
  `exit_reason`, `created_at`/exit timestamp for windowing.
- `Position`: `strategy_id`, for the "currently open, this strategy" count
  and for attributing rows in Holdings/Portfolio tables.

## 5. Backend changes

### 5a. Shared cap-tier helper (cleanup, in scope)

`_cap_tier()` is currently duplicated twice in `api/v1/endpoints/signals.py`.
Extract it once to a shared location (e.g. `strategies/tier.py`) and import
it from `signals.py` and the new endpoint below, so the mapping from
`params.model_name` → large/mid/small stays in one place.

### 5b. New endpoint: `GET /strategies/performance`

Returns, for every `Strategy` row, performance over three windows
(`last_30d`, `last_90d`, `all_time`):

```
{
  "strategies": [
    {
      "id": ..., "name": ..., "strategy_type": "ml_swing",
      "cap_tier": "midcap", "is_active": true,
      "universe_size": 18,                 # len(symbols) or watchlist count if empty
      "open_positions": 3,
      "windows": {
        "last_30d":  { "trades": 4,  "win_rate": 0.75, "profit_factor": 2.1, "net_pnl": 4200.0 },
        "last_90d":  { "trades": 11, "win_rate": 0.64, "profit_factor": 1.8, "net_pnl": 9100.0 },
        "all_time":  { "trades": 23, "win_rate": 0.61, "profit_factor": 1.6, "net_pnl": 15200.0 }
      }
    }
  ],
  "recommended_strategy_id": 4,   # or null
  "recommendation_reason": "Best win rate (64%) over the last 90 days among strategies with enough closed trades"
}
```

Stats reuse the aggregation already in `services/portfolio.py::performance_stats()`
(win_rate, profit_factor, net P&L), refactored to accept an optional
`strategy_id` and `since` filter rather than only filtering by broker mode.

**Recommendation rule:** among currently **active** cap-tier strategies
(`strategy_type == "ml_swing"` with a cap-tier `model_name`) with
`all_time.trades >= 10` closed trades, pick the highest `last_90d.win_rate`
(falling back to `all_time.win_rate` if a strategy has fewer than 3 closed
trades in the last 90 days); tie-break by `profit_factor`, then `net_pnl`.
If no strategy has 10+ trades yet, `recommended_strategy_id` is `null` and
`recommendation_reason` explains how many more trades are needed on the
closest strategy.

### 5c. Extend existing responses with strategy attribution

Add `strategy_name` and `cap_tier` (nullable, via the shared helper) to:

- `GET /portfolio/positions/detailed` — so Holdings/Portfolio can show which
  strategy picked each position.
- `GET /portfolio/trades` — so Reports can group the existing trade log by
  strategy without a second endpoint.

Both endpoints already join `Position`/`Trade` to `Strategy` via
`strategy_id`; this is an additive field on the existing serializer, not a
new query pattern.

## 6. Frontend changes

### 6a. `Strategies.tsx` — redesigned, promoted to nav

Add "Strategies" to `NAV` in `App.tsx`.

Primary section: one card per cap-tier `ml_swing` strategy (main/midcap/
smallcap), each showing:

- Friendly name + tier badge (reuse/extend `lib/tiers.ts`, which already
  maps strategy name → tier; add a plain-English one-line description per
  tier, e.g. "Bigger, steadier companies. Fewer trades, lower risk." /
  "Mid-sized companies. Balanced risk and reward." / "Smaller, more
  volatile companies. Higher risk, higher potential reward.")
- "Watching N stocks" (`universe_size`)
- Win rate for last 90 days, with sample size shown plainly ("7 of 11 trades
  won in the last 90 days") or "Not enough closed trades yet" below the
  10-trade threshold
- Risk badge (existing `strategyRisk.ts` heuristic, unchanged)
- Active/Inactive toggle (existing activate/deactivate endpoints, unchanged
  behavior — only affects future scans)
- "Recommended" ribbon on the card matching `recommended_strategy_id`, with
  the `recommendation_reason` as hover/tap detail per [[feedback_jargon_free_ui]]
  ("detail on tap")

Secondary, collapsed by default: "Advanced strategies" — the existing admin
table (sma_crossover, long_term_value, real_trading, run-scan-now, param
editing) unchanged, just moved under a `<details>`/expandable section
instead of being the whole page.

### 6b. `Dashboard.tsx` tier-comparison widget

Extend the existing per-cap-tier comparison block to pull from
`/strategies/performance` and show win rate + the recommendation badge
alongside what it already shows, instead of building a second data source.

### 6c. Holdings / Portfolio (`Holdings.tsx`, `Positions.tsx`, shared `PositionsTable`)

Add a "Strategy" column (name + tier chip) to `PositionsTable`, sourced from
the new `strategy_name`/`cap_tier` fields on `positions/detailed`. One
component change covers both pages since they share the table.

### 6d. `Reports.tsx` — lighter, strategy-aware

- Remove the Recharts `BarChart` (and the now-unused `recharts` import from
  this file — leave the dependency itself alone unless nothing else in the
  app uses it).
- Keep the stat tiles (total realized P&L, win rate, broker charges,
  best/worst period) and the existing period summary + trade log tables —
  these are the "proper details instead of heavy charts" the user asked for.
- Add a new "By Strategy" table: strategy name, tier, trades, win rate, net
  P&L — grouped client-side from the trade log, which now carries
  `strategy_name`/`cap_tier` per row (§5c), no new endpoint needed.

## 7. Testing

- Backend: unit test for the refactored performance aggregation (windowing,
  `strategy_id` filter, profit factor/win rate math) with fixture trades
  covering under-threshold and over-threshold sample sizes.
- API test for `GET /strategies/performance`, including the recommendation
  rule (tie-break order, null case below 10 trades).
- API test confirming `strategy_name`/`cap_tier` appear on
  `positions/detailed` and `trades` responses.
- No new frontend test infra; match existing page conventions. Manually
  verify in-browser (dev server) that the Strategies tab renders for a
  fresh-install low-data state (recommendation null) and a populated state.

## 8. Open items deferred to implementation planning

- Exact threshold tuning (10 trades, 3-trade fallback window) can move if
  it proves too strict/loose once real data is seen — implementation should
  keep these as named constants, not magic numbers.
- Whether `real_trading` (advisory, personal holdings) should ever appear in
  the recommendation pool — spec says no (it's not a cap-tier strategy
  competing for the same capital), confirm this reads correctly once the
  card UI is in front of the user.
