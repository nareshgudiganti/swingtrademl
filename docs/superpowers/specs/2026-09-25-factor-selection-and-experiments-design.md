# Factor Selection, Cap Tiers and Paper Experiments — Design Spec

Status: awaiting user review
Date: 2026-09-25

## 1. Problem

The user wants to choose which market-cap tiers the bot trades, weight a set
of stock-selection factors (suspecting trend matters most), test those
choices in paper mode, and use a calculator to decide how to spread money
before investing. None of that is possible today, and two of the foundations
it assumes do not exist.

**Cap tier is not the stock's cap.** `strategies/tier.py` derives a tier from
a `_midcap` / `_smallcap` suffix on `params.model_name`, and
`risk.check_entry` (risk.py:556) gates on that. Every stock traded by
`ml_swing_midcap` is treated as a midcap whether or not it is one.
`Instrument` (db/models/market.py:25) has no market-cap column and no sector
column — Kite's instrument dump carries neither.

**There is no factor concept.** `ml/features.py` holds 53 flat columns
feeding one classifier. Nothing ranks stocks against each other.

**There is no way to try a configuration.** Strategy `params` is a JSON
column that could hold one, but nothing reads a selection config from it, and
nothing compares two configurations on the same evidence.

The motivating constraint is [[project_ml_accuracy_roadmap]]: the model sits
at walk-forward ROC AUC 0.556-0.583 and cannot find needles across ~300
stocks. `docs/ROADMAP_TRACKER.md` section 3 concludes that restricting the
model to already-sensible candidates raises the base rate it starts from. A
factor layer is that restriction.

## 2. Goal

Three connected pieces:

1. **Real cap tiers** for every watchlist stock, sourced from NSE index
   membership, replacing the model-name proxy. Delivers per-stock sector as a
   side effect.
2. **A factor scoring and selection layer** that ranks stocks
   cross-sectionally each day and hands the ML model a shortlist instead of
   the whole watchlist.
3. **A customisation area** where a configuration (cap tiers, factor weights,
   shortlist size, thresholds) is saved as an experiment, run as a shadow
   strategy in paper mode, and compared against the live baseline on
   resolved-signal outcomes.

Plus a **money calculator** that projects the existing risk-ladder and regime
logic into a plain-English allocation plan, including a what-if for adding
capital.

Success is measured the same way every other data family has been
([[project_ml_accuracy_roadmap]]): a configuration is only adopted if it
moves walk-forward ROC AUC or top-bucket precision by more than noise.
Anything that does not clear that bar is dropped, not kept for looking
sensible.

## 3. Non-goals (YAGNI)

- **No fundamentals in this phase.** Value and Quality need company
  financials; that is an NSE XBRL project measured in weeks with a
  restatement trap (ROADMAP_TRACKER section 4). They ship as visible,
  disabled stubs labelled "needs fundamentals" — never faked.
- **No auto-promotion.** A winning experiment is reported, never switched on
  by itself. An automated propose-and-adopt loop is the fastest route to
  curve-fitting on recent trades.
- **No changes to the ML model, training or features.** The classifier is
  used as-is; it simply receives fewer candidates.
- **No new broker or execution behaviour.** Experiments never place orders.
- **No manual per-trade override.** The user sets a configuration, not
  individual buys.
- **No changes to the capital ladder's numbers.** The calculator reads
  `limits.py` and `deployable.py`; it does not redefine them.

## 4. Cap tiers from NSE index membership

NSE publishes constituent lists as static CSVs on the archive host already
used for bhavcopy, bulk and block deals (`services/market_feeds.py:41-43`).
Verified 2026-09-25, all returning HTTP 200:

| Tier | URL under `https://nsearchives.nseindia.com/content/indices/` |
|---|---|
| large | `ind_nifty100list.csv` |
| midcap | `ind_niftymidcap150list.csv` |
| smallcap | `ind_niftysmallcap250list.csv` |

Columns: `Company Name, Industry, Symbol, Series, ISIN Code`.

`Symbol` joins to `Instrument.tradingsymbol`. `Industry` gives per-stock
sector, which the codebase currently lacks — `ml/sector_map.py` maps to
sector *indices*, not to a stock's own sector label.

**Point-in-time honesty.** NSE publishes current membership only; there is no
historical constituent archive at these URLs. Membership therefore follows
the rule already established for every feed in ROADMAP_TRACKER section 4:
store a dated snapshot on each fetch, and treat only snapshots from the day
we started recording as point-in-time safe. Any backtest reaching further
back uses today's membership and carries survivorship bias. That limitation
is recorded on the experiment result, not hidden.

A stock in none of the three lists keeps tier `unknown` and is excluded from
tier-filtered universes rather than defaulting to large — defaulting is how
the current model-name proxy became wrong.

The fetch runs in the existing `daily_market_feeds` job, wrapped like every
other NSE fetch so a failure raises a Telegram alert rather than silently
serving stale membership (risk R6 in the tracker).

## 5. Factor scoring

Every factor is a **cross-sectional percentile rank, 0-100, computed across
the eligible universe on that day**. Ranking across stocks — not against an
absolute threshold — is what makes a factor a factor, and what keeps it
meaningful when the whole market moves together.

### 5.1 Trend (buildable now)

The user's hypothesis, and the cheapest to test. Composed from existing
`FEATURE_COLUMNS`:

- `sma_50_ratio`, `sma_200_ratio` — price standing above its long averages
- `sma_50_200_cross` — golden-cross state
- `adx_14`, `trend_strength` — whether the trend is orderly or noisy
- `relative_strength_20d` — beating the index, not merely rising
- `return_20d` — medium-term return

**Proposed addition:** academic momentum is a 12-month return skipping the
most recent month. We hold enough candle history to compute `return_120d`
and `return_250d`, and neither exists yet. Adding them makes this a real
momentum factor rather than a medium-term trend composite. They are added as
factor inputs only — `FEATURE_COLUMNS` and the trained model are untouched
(section 3).

### 5.2 Low Volatility (buildable now)

Inverted so calmer stocks rank higher:

- `volatility_20`, `atr_14_pct`, `volatility_percentile_rank`

### 5.3 Size (partial)

Index membership gives a coarse three-way tier, which is what the user asked
to select on. A continuous within-tier size rank needs real market
capitalisation, which we do not have. Size therefore acts as a **universe
filter, not a scored factor**, and the UI says so.

### 5.4 Value and Quality (stubbed)

Disabled, visible, labelled "needs fundamentals". No placeholder numbers.

### 5.5 Composite

Weights apply to **enabled factors only** and are renormalised to sum to 1,
so disabling a factor redistributes its weight rather than silently shrinking
every score. Default: Trend 70, Low Volatility 30.

## 6. The selection algorithm

```text
Daily, per configuration:

1. UNIVERSE    watchlist ∩ selected cap tiers          [new, section 4]
2. LANDMINES   results within 3 days, corp actions,
               ASM/GSM/T2T                             [services/avoid.py, exists]
3. SCORE       percentile-rank each enabled factor
               across today's universe                 [new, section 5]
4. COMPOSITE   weighted blend, weights renormalised    [new, section 5.5]
5. SHORTLIST   top K% by composite (default 25%,
               floor 10 names)                         [new]
6. ML SCORE    existing classifier, shortlist only     [ml/predict.py, exists]
7. RANK        ML probability, composite breaks ties   [new]
8. GATE        risk checks and sizing                  [services/risk.py, exists]
```

Steps 2, 6 and 8 are existing code called unchanged. Steps 1, 3, 4, 5 and 7
are new and live in one new service.

The mechanism of benefit is narrowing: at AUC ~0.56 the model discriminates
weakly, so raising the quality of the pool it starts from matters more than
adding another feature inside it. This is also why the factor scores are
deliberately **not** appended to `FEATURE_COLUMNS` — that experiment has been
run four times (sector, breadth, VIX, delivery %) and moved nothing each time.

## 7. Experiments as shadow strategies

### 7.1 Why shadow, not paper positions

Paper positions are capped at 8 for the current account, and each strategy
receives `max_positions // active_strategy_count` slots — 2 each with 4
active strategies today. Ten position-taking experiments would resolve to
`8 // 14 = 0`, floored to 1 slot each: no statistical power, and a near
repeat of the starvation that blocked buying from 16 Sept
([[buying-blocked-sept-2026]]).

Experiments therefore run with `execution_mode = "advisory"`. They generate
`Signal` rows with `advisory_only = True` and take no positions. The scoring
machinery already exists: `Signal` carries `outcome`, `outcome_pct` and
`horizon_days`, and the scheduled `evaluate_signals` job backfills them once
the horizon elapses. Unlimited experiments, zero interference with the live
book, real measured outcomes.

### 7.2 Required fix

`risk.active_strategy_count` (risk.py:87) counts every active strategy in a
mode, including advisory ones. Shadow experiments would dilute the real
strategies' slot share — the latent bug noted in
[[position-slot-starvation-bug]], which this feature makes live.

It must exclude advisory strategies, matching
`core/strategy_policy.is_advisory`. Covered by a regression test asserting
that adding N advisory strategies leaves the automatic strategies' share
unchanged.

### 7.3 Storage

A configuration is a `Strategy` row with `execution_mode = "advisory"` and
`params` holding:

```json
{
  "selection": {
    "cap_tiers": ["large", "midcap"],
    "factor_weights": {"trend": 70, "low_volatility": 30},
    "shortlist_pct": 25,
    "shortlist_floor": 10,
    "min_confidence": 0.60,
    "horizon_days": 15,
    "max_per_sector": 2
  }
}
```

No schema change to `Strategy`. The selection service reads this block; a
strategy without it behaves exactly as today, so existing strategies are
unaffected.

## 8. Guardrails against false positives

Running many configurations and keeping the best finds noise. The project's
own record shows how convincing that noise is: delivery %, sector, breadth
and VIX all looked plausible and all moved nothing
([[project_ml_accuracy_roadmap]]). Three rules are part of the feature, not
advice around it:

1. **Minimum sample.** Below 30 resolved signals a configuration shows "not
   enough evidence yet" — no win rate, no ranking, no badge. The count is
   displayed alongside every result thereafter.
2. **Concurrency cap of 5.** Testing twenty blends guarantees one looks
   excellent by chance. Creating a sixth requires archiving another.
3. **Baseline always shown.** Every comparison displays the current live
   configuration and `sma_crossover_benchmark` beside the experiment. "Good"
   means better than what we already do, not better than zero.

The comparison view states how many configurations are under test, so the
multiple-comparisons risk is visible rather than implied.

## 9. The money calculator

A read-only projection of existing logic — `services/limits.py` (the ladder)
and `services/deployable.py` (the regime ceiling). It introduces no new
limits and no arithmetic of its own.

Shows, for the current account and regime:

- Deployable now, against total account value, with the regime named in plain
  English (today: ₹97,979 of ₹9,79,792, "under stress", 10%)
- Maximum positions and typical position size, with the minimum sensible
  position
- Cash floor never deployed
- The chosen cap-tier split in rupees
- Sector ceiling

**What-if:** given an added amount, recompute against the ladder and show
what changes at the next rung. This answers the user's stated need — decide
before investing — and makes the ladder legible rather than something that
silently changes behaviour as the account grows.

It must state plainly that a stressed regime is the reason a large cash
balance is not being deployed. Without that line the calculator looks broken
([[feedback_jargon_free_ui]]).

## 10. Interfaces

### Schema

- `Instrument.cap_tier` — String(16), nullable, indexed: large / midcap /
  smallcap / unknown
- `Instrument.sector` — String(64), nullable, from the Industry column
- New table `index_membership_snapshots`: `(fetched_on, symbol, tier,
  industry)`, unique on `(fetched_on, symbol)` — the dated snapshots section
  4 requires

No change to `Strategy`, `Signal`, `Position` or `Trade`.

### API

- `GET /api/v1/selection/factors` — factor definitions, which are enabled,
  and why the others are not
- `GET /api/v1/selection/preview?config=...` — today's shortlist for a
  configuration, without saving it
- `POST /api/v1/experiments`, `GET`, `DELETE` — configuration CRUD, cap of 5
- `GET /api/v1/experiments/compare` — results with sample sizes and baseline
- `GET /api/v1/calculator?added_capital=...` — the allocation plan

### UI

A new top-level **Lab** tab, separate from the main flow as the user asked,
holding: cap-tier selection, factor sliders with the two stubs visible and
disabled, shortlist preview, the experiment list with sample sizes, and the
calculator. Plain English throughout, detail on tap
([[feedback_jargon_free_ui]]).

## 11. Testing

Per [[local-tests-need-docker-postgres]] the suite needs Postgres on :5433
and hangs silently without it. Docker's engine was returning HTTP 500 as of
2026-09-23 and must be working before this lands.

- Factor scoring is pure and table-driven: a fixed frame in, known percentile
  ranks out. Covers ties, single-stock universes, and all-identical values.
- Weight renormalisation: disabling a factor redistributes its weight.
- Universe filter: `unknown` tier is excluded, not defaulted to large.
- `active_strategy_count`: N advisory strategies leave the automatic
  strategies' share unchanged (the section 7.2 regression).
- Shortlist: K larger than the universe returns the whole universe.
- A strategy with no `selection` block in `params` reproduces today's
  behaviour exactly.
- Calculator: matches `limits_for()` at each ladder rung and at a value
  between two rungs.
- NSE parser: a saved CSV fixture, plus a malformed file raising rather than
  writing partial membership.

## 12. Build order

| # | Piece | Size |
|---|---|---|
| 1 | NSE index membership fetch, schema, tier + sector backfill | S |
| 2 | Factor scoring service (trend, low-vol, `return_120d`/`return_250d`) | M |
| 3 | `active_strategy_count` advisory fix | XS |
| 4 | Selection pipeline wired into the scan behind a config block | M |
| 5 | Experiment CRUD and shadow runner | M |
| 6 | Comparison view with guardrails | M |
| 7 | Money calculator | S |

Items 1 and 3 are independent and can land first. Item 4 is the point of no
return for scan behaviour and must ship behind the "no selection config means
today's behaviour" default in section 7.3.

## 13. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | The factor layer shows no improvement | Expected and acceptable. The bar in section 2 decides; a null result is recorded and the layer stays off. Same exit test the roadmap applies to every data family |
| R2 | Multiple-comparisons mining | Section 8: sample floor, concurrency cap, baseline always visible |
| R3 | Survivorship bias from current-only membership | Section 4: dated snapshots, limitation stated on results, backtests before the start date flagged |
| R4 | NSE changes or blocks the index URLs | Same archive host and `fetch()` wrapper as existing feeds; failure alerts rather than serving stale data |
| R5 | Narrowing starves the scan of candidates | Shortlist is a percentage with a floor of 10 names, so it scales with universe size; the preview endpoint shows the shortlist before committing; the risk gate behind it is unchanged |
| R6 | User reads factor scores as predictions | Scores are ranks within today's universe and are labelled as such. Calibration discipline from [[project_ml_accuracy_roadmap]] applies |

## 14. Open questions

1. ~~**Universe size.**~~ **RESOLVED 2026-09-25 against prod.** Every active
   strategy carries an explicit `symbols` list, so
   `engine.eligible_instruments` never reaches the watchlist fallback:
   `ml_swing_main` 52, `sma_crossover_benchmark` 52 (same list),
   `ml_swing_midcap` 150, `ml_swing_smallcap` 104, `real_trading` 8.

   Two consequences, both folded into the design above:

   - **Cap tiering already exists de facto**, hand-maintained inside
     `strategy.symbols` and shaped like the NSE index lists (52 ≈ NIFTY 50,
     150 ≈ NIFTY Midcap 150). Those lists are frozen and go stale at every
     NSE rebalance. Section 4 therefore *replaces* a manual list with a
     self-refreshing one — a stronger case than the model-name defect alone.
   - **K must be a fraction, not a constant.** Top-30 is a 5x cut on a
     150-name universe and barely filters a 52-name one. Section 6 step 5 now
     uses a percentage with a floor, so the same configuration means the same
     thing on every tier.

   Still worth settling separately: the watchlist flag covers at least 1000
   instruments (`limit: int = Query(100, le=1000)` returned its full cap)
   while `db/models/market.py:46` claims only watchlisted instruments get
   candles ingested. Not a blocker for this work, since the fallback is
   unreachable, but the flag no longer means what its docstring says.
2. Should an experiment inherit the live model, or be pinnable to a model
   version so a factor change is not confounded by a model change?
3. Is the 15-day horizon per experiment, or fixed to match the trained
   barrier label? Mismatched horizons make comparisons invalid.
