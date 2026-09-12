# Signal Track Record — Design Spec

Status: approved by user, ready for implementation planning
Date: 2026-09-12
Amended: 2026-09-12 — renamed to "Scan Results" and moved to its own top-level
tab (see §9a) after a separate request for a unified scan-results view turned
out to be this same feature; building both would have duplicated the backend.

## 1. Problem

The bot has been paper-trading for months with no fixed date to go live
([[project_live_trading_transition]]). The open question isn't "does the UI
look good" — it's "is the model actually good enough to trust with real
money." There is currently no single view that answers that honestly:

- `Prediction` rows are scored (`was_correct`, `actual_return` via
  `evaluate_pending_predictions` in `ml/predict.py`) but that's raw model
  direction-calling, not "would a real trade using this signal's stop/target
  have worked."
- `Trade` rows (`is_win`, `net_pnl`, `return_pct`) are fully scored but only
  exist for positions that were actually opened and closed — advisory-only
  signals, rejected signals, and signals nobody acted on are invisible. A
  view built only from `Trade` inherits the same survivorship bias every
  commercial tip site in the reference screenshots has (StockGuru-style
  "+48%" badges with no losers shown).

This was scoped from four reference screenshots (Moneyworks4me-style daily
buy/sell table, a Caplin Point plain-English stock page, a StockGuru.in
signal-with-age scoreboard, an INDmoney screener). Of the four patterns, this
spec covers only the **signal-with-age scoreboard** pattern — chosen first
because it's the one that serves the standing accuracy priority
([[project_ml_accuracy_roadmap]]) rather than being pure UI polish. The other
three patterns are out of scope for this spec and may become separate specs
later.

## 2. Goal

Every `Signal` ever issued with an actionable stop/target — whether or not it
was executed, paper or real — gets scored against what actually happened to
the price afterward, and is shown in one list, wins and losses together, with
its age. This is the evidence the manual-approval trial phase needs to decide
when (or whether) to lift to full auto-execution.

## 3. Non-goals (YAGNI, may follow in separate specs)

- No public/shareable page or marketing-style scoreboard.
- No cross-strategy leaderboard or model-vs-model comparison view.
- No confidence-calibration chart (reliability diagram) — a candidate for
  the ML accuracy roadmap, not this feature.
- No changes to the daily action table, the plain-English stock page, or
  watchlist discovery (screenshots 1, 2, 4) — separate specs.

## 4. Scope

Applies to any `Signal` row with both `stop_loss` and `take_profit` set.
Today that's every `BUY` signal from `ml_swing` and `sma_crossover`
(confirmed both strategies set these — see `strategies/ml_swing.py:186-192`
and `strategies/sma_crossover.py:119-134`). Signals without a target (`HOLD`,
filtered-out/rejected `BUY` attempts) are not scored — there is nothing to
hit or miss.

## 5. Data model

Three new columns on `Signal` (`db/models/trading.py`):

| Column | Type | Meaning |
|---|---|---|
| `horizon_days` | `int` | Copied at generation time from the active model's `prediction_horizon_days` (ML strategies) or a per-strategy default (non-ML strategies, e.g. `sma_crossover`). Stored on the signal itself — not looked up from the model later — so scoring stays correct even after the active model changes. |
| `outcome` | `str \| None` | One of `TARGET_HIT`, `STOP_LOSS_HIT`, `EXPIRED_NO_HIT`. `None` while still open. |
| `outcome_pct` | `float \| None` | Realized return from `price` to the outcome price. |
| `outcome_at` | `datetime \| None` | When the outcome was determined. |

No new table. This mirrors the existing `Prediction.was_correct` /
`actual_return` / `evaluated_at` pattern already in the codebase, applied to
`Signal` instead.

Alembic migration adds the three nullable columns; no backfill of historical
signals required at migration time (the scoring job picks them up on its
next run, same as `evaluate_pending_predictions` does for `Prediction`).

## 6. Scoring logic

New function in `ml/predict.py`, next to `evaluate_pending_predictions`,
same shape and error-handling conventions:

```
def evaluate_pending_signals(db: Session, interval: str = "day") -> int
```

For each `Signal` where `outcome IS NULL` and both `stop_loss` and
`take_profit` are set:

1. Walk daily candles from `generated_at + 1 day` forward, in order.
2. On each candle, check **high/low, not close** — a stop or target order
   triggers intraday; scoring against closes only would misrepresent what a
   real order does. If `low <= stop_loss`, outcome is `STOP_LOSS_HIT` as of
   that candle. Else if `high >= take_profit`, outcome is `TARGET_HIT`. If a
   single candle's range crosses both, `STOP_LOSS_HIT` wins (conservative:
   assume the worse fill on an ambiguous day).
3. If no candle triggers either within `horizon_days` calendar days of
   `generated_at`, and that horizon has elapsed (candles exist past it),
   outcome is `EXPIRED_NO_HIT` with `outcome_pct` computed against the last
   candle's close at/after the horizon — reusing the existing
   `forward_return_at_horizon` helper for that final lookup.
4. Signals whose horizon hasn't elapsed yet and haven't hit either level are
   left unscored (still "open") — matching `evaluate_pending_predictions`'s
   existing not-yet-computable case.

## 7. Job wiring

`job_evaluate_signals()` added to `workers/jobs.py`, following the exact
pattern of the neighboring `job_evaluate_predictions`: own `session_scope()`,
swallow-and-report exceptions via `_report_error`, one-line log on success.
Registered in the scheduler (`workers/scheduler.py`) on the same daily cron
slot as the existing prediction-evaluation job (currently
`CronTrigger(day_of_week=WEEKDAYS, hour=16, minute=15, ...)` — see the
existing job list; exact slot confirmed during implementation).

## 8. API

New endpoint in `api/v1/endpoints/signals.py`, alongside the existing
`/top-picks` and `/buy-list`:

```
GET /api/v1/signals/track-record
```

Returns every signal that is scored (`outcome IS NOT NULL`) or still open
and eligible for scoring (has stop/target set), newest `generated_at` first.
Each row: symbol, signal type, `generated_at` (+ derived age in days),
entry `price`, `stop_loss`, `take_profit`, `confidence`, `outcome`,
`outcome_pct`, `outcome_at`, `mode` (paper/real). Where `was_executed=True`
and a `Trade` exists for the resulting position, join in that trade's
`net_pnl`, `return_pct`, and `holding_days` so a row can show both "what the
model called" and "what it actually made after real charges."

No pagination needed at current signal volumes (~20-30 watchlist names,
handful of signals/day); add if this becomes a problem.

## 9a. Frontend — superseded, see below

(Original v1 plan below is superseded by the amendment at the top of this
document — kept for history, not for implementation.)

~~Added as a new section on `Reports.tsx`~~

## 9. Frontend (amended)

Its own top-level nav tab, **"Scan Results"** (route `/scans`), not a
subsection of Reports — this is now also the answer to the separate ask for
a single place to browse every scan the bot has ever produced, so it earns
first-class nav placement (icon: reuse the `LayersIcon` pattern already in
`components/icons.tsx`, following the sidebar-fix work landing alongside
this). The existing `Search.tsx` page and its nav entry are removed — manual
lookup is no longer a separate flow; the popup detail below covers it.

Table columns, plain-English per [[feedback_jargon_free_ui]]:

| Column | Content |
|---|---|
| Stock | Symbol / name |
| Cap tier | Large / Mid / Small — reuse `_cap_tier()` from `signals.py`'s existing `/top-picks` |
| Called On | Date + "N days ago" |
| Entry / Stop / Target | ₹ values |
| Current price | Live price, same source `Position.current_price` mark-to-market already uses |
| Status | Chip: 🟢 Hit Target · 🔴 Hit Stop · ⚪ Open · ⚫ Expired, no hit |
| Result | outcome_pct, or trade's real return_pct when executed, whichever is more relevant to show first |

Clicking a row opens a popup (reuse the existing `Modal` component, same
pattern as `Finance.tsx`'s statement/loan modals) with full detail: the
signal's `reason` text, confidence, all recorded features, and — when
executed — the linked trade's real charges and net P&L.

## 9b. API (amended)

`GET /signals/track-record` (§8) additionally returns `cap_tier` (via the
existing `_cap_tier()` helper) and `current_price` (same live-price lookup
`portfolio.mark_to_market` already performs) per row, so the frontend needs
no second round-trip to assemble the table.

## 10. Testing

- Unit tests for `evaluate_pending_signals` covering: target hit before
  stop, stop hit before target, same-day double-touch (stop wins), no hit
  within horizon (expires), signal not yet at horizon (stays open, no
  outcome written).
- API test for `/signals/track-record` covering the executed-trade join.
- No frontend test infra assumed beyond whatever the existing Reports page
  already uses; match its pattern.

## 11. Open items deferred to implementation planning

- Exact cron slot for `job_evaluate_signals` (confirm no conflict with
  existing jobs at implementation time).
- Per-strategy default `horizon_days` for non-ML strategies like
  `sma_crossover` (needs a concrete number — implementation plan should
  pick one, e.g. matching `DEFAULT_TAKE_PROFIT_PCT`/`DEFAULT_STOP_LOSS_PCT`
  conventions already in `core/config.py`).
