# Long-Term Stock Picks — Design Spec

Status: approved by user, ready for implementation planning
Date: 2026-09-12

## 1. Problem

The user asked for "10X" long-term stock recommendations. No legitimate
model can promise a specific return multiple — this spec deliberately
reframes that ask into what a real system can honestly deliver: a small,
high-conviction, long-horizon (months to years) pick list, scored against
its own outcomes with the same honesty as the swing-trading
[[Signal Track Record]] (see the amended
`2026-09-12-signal-track-record-design.md`, now the "Scan Results" tab).

This is explicitly framed as serving the standing
[[project_ml_accuracy_roadmap]] — better features (fundamentals in
particular) — rather than being a separate product bolted on. Everything
here (Signal, Prediction, MLModel, the scoring job) is infrastructure this
codebase already has; long-term picks reuse it with a longer horizon and a
new feature set, rather than building a parallel system.

## 2. Goal

A second, independently-trained model — same architecture and pipeline as
the existing swing classifier — trained to predict multi-month/year moves
using fundamentals in addition to the existing price/volume/technical
features, surfaced as its own set of `BUY` signals with a long
`prediction_horizon_days`, scored honestly via the same outcome machinery
the Scan Results tab already provides.

## 3. Non-goals

- No promise or display of a target return multiple ("10X", "5X", etc.)
  anywhere in the UI — confidence and historical hit-rate only, same
  standard as every other signal in the app.
- No portfolio-construction/rebalancing logic for long-term holdings in this
  round — picks are advisory, the user still decides sizing manually
  (matches how `/top-picks` already works for swing signals).
- No auto-execution of long-term picks — advisory-only by default
  (`Signal.advisory_only=True`), consistent with the manual-approval trial
  phase the whole app is still in ([[project_live_trading_transition]]).

## 4. Fundamentals data — the real open dependency

The current feature set (`ml/features.py`) is entirely price/volume-derived.
Long-term investing quality depends heavily on fundamentals (P/E, ROE,
debt/equity, revenue/earnings growth, promoter holding trends) that no
existing pipeline in this codebase fetches.

**Decision:** paid vendor, budget not a constraint per
[[project_ml_accuracy_roadmap]]. **Exact vendor selection is a spike, not
locked in this spec** — pricing and API shape for Indian-market fundamentals
data change often enough that naming one here risks being wrong by
implementation time. Implementation planning should budget a short spike to
evaluate 2-3 candidates against these criteria before integrating:

- Coverage of NSE/BSE-listed companies specifically (not just US/global).
- Point-in-time fundamentals (the ratio as it was known at the time, not
  restated later) — using restated fundamentals in training silently leaks
  future information, the exact bug class `ml/features.py`'s own
  header warns about for price data.
- Reasonable historical depth (5+ years) to get enough training examples.
- A real API (REST/SDK), not a scrape target — same "no scraping" line
  already drawn for stock-picking data sources generally.

This dependency blocks the fundamentals-feature-engineering step below but
not the rest of the design (data model, strategy shape, scoring reuse) — all
of that can be built and tested against price/volume features alone, with
fundamentals features layered in once the vendor is chosen.

## 5. Model & features

- New model name, e.g. `long_term_value` (or `_midcap`/`_smallcap` variants
  following the existing cap-tier naming convention `signals.py`'s
  `_cap_tier()` already reads) registered through the existing `MLModel`/
  `train.py`/`registry.py` pipeline unchanged — this is a new named model,
  not a new pipeline.
- `prediction_horizon_days` set far longer than the swing model's default
  (e.g. 180-365 vs. the swing model's ~5-20) and `target_return_pct` set
  accordingly higher (a multi-month/year hold should target a materially
  larger move than a 2-week swing).
- New fundamentals features appended to a **separate feature list**, not
  merged into `FEATURE_COLUMNS` — the swing model must not silently start
  depending on slower-moving fundamentals data it was never validated
  against. A new `FUNDAMENTALS_FEATURE_COLUMNS` list in `ml/features.py` (or
  a new `ml/fundamentals.py` module, mirroring `ml/market_context.py`'s
  separation of concerns) covers: trailing P/E vs. sector median, ROE
  trend, debt/equity trend, revenue/earnings YoY growth, promoter holding
  change — exact set finalized once the vendor's actual fields are known.

## 6. Strategy

New strategy class `LongTermValueStrategy` in `strategies/`, following
`ml_swing.py`'s exact shape (same `BaseStrategy` interface, same
probability-threshold-then-filter structure) but:

- Reads the `long_term_value` model instead of `swing_classifier`.
- Stop/target derived from a wider band appropriate to the horizon (not
  ATR-based day-to-day noise — a percentage-of-price band matching
  `sma_crossover.py`'s simpler `stop_loss_pct`/`take_profit_pct` convention
  is more appropriate at this horizon than ATR, which is tuned for
  short-term noise).
- `advisory_only=True` by default, per §3.

Because it's a normal `Signal`-producing strategy, it automatically gets
scored by the Scan Results tab's outcome job (§6 of that spec) — no separate
scoring path needed, just a much longer horizon in the same
`evaluate_pending_signals` walk.

## 7. Data model

No new tables. Reuses `Signal`/`MLModel`/`Prediction` exactly as-is — the
long horizon and advisory-only flag are just field values, not new
structure. If fundamentals turn out to need their own historical storage
(likely, for point-in-time correctness), a new `Fundamental` table
(`instrument_id`, `as_of_date`, the ratio fields) is added at implementation
time, shaped like `MutualFundNav`'s time-series pattern in the sibling spec.

## 8. Frontend

Long-term picks appear in the same **Scan Results** tab as swing signals
(§9 of that spec), distinguished by a "Long-term" vs "Swing" tag per row
(derived from `horizon_days` being past some threshold, or simply the
strategy name) — one honest ledger, not a second competing table. No new
page needed.

## 9. Testing

- Same test shape as `ml_swing.py`'s existing strategy tests, adapted for
  the wider stop/target band and advisory-only default.
- Point-in-time correctness test for any fundamentals feature once the
  vendor is chosen — assert a feature computed "as of" date X never reflects
  data restated after X (mirrors the look-ahead-bias discipline already
  documented in `ml/features.py`'s module docstring).

## 10. Open items deferred to implementation planning

- Fundamentals vendor selection (spike, §4).
- Exact `prediction_horizon_days`/`target_return_pct` values — picked from
  backtested sensitivity at implementation/training time, not guessed here.
- Whether cap-tier variants (`_midcap`/`_smallcap`) are trained from day one
  or added after the large-cap version proves out.
