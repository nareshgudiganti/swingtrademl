# SwingTradeML — Consolidated Gap Analysis and Continuous Roadmap

## Context

You asked for a complete analysis of what is missing, and a plan that runs **without breaking** (no stop-start, no track that waits on another) and is **flexible to switch as the market changes**.

This plan was built by auditing the actual code on `feature/factor-foundation`, not by accepting the 11-document synthesis. **Three of that PDF's headline claims are wrong**, and one is right but differently shaped. Correcting them changes what work is needed:

| PDF claim | Reality in code | Effect on plan |
|---|---|---|
| Cost model still assumes ₹20/order | `PAPER_BROKERAGE_PER_ORDER = 0.0`, with 22.3bps statutory + ₹15.93 DP fee (`core/config.py:87-109`, `services/costs.py`) | **Already fixed.** No work. Delete from every backlog. |
| Sharpe/Sortino/drawdown formulas are broken | Formulas are correct (decimal returns, running-peak drawdown, √252). The real bug is narrower | Small, precise fix — not a reporting rewrite |
| Model answers "+2% in 5 days" while trade is "+8%/−4%/15d" | `build_label()` *is* the +8/−4/15 barrier. But the three **order-placing** models are still old `endpoint`-label models; the barrier models exist only as **unpromoted advisory shadows** | The fix is a **promotion decision on evidence**, not a retrain |
| Factor layer "not wired into the scan" | Correct, and worse — `services/factors.py` is imported only by its own test. There is no shortlist step anywhere | Confirmed as the largest structural gap |

**Trade spec is settled and unchanged:** +8% / −4% / 15 trading days, scale out half at +5%, 30 calendar-day time stop, 15% drawdown halt. The PDF's "+5/−3/10d, 5% halt" is recorded as a **rejected draft**. Nothing gets retrained on its account.

---

## The gap register

Severity: **P0** blocks real money · **P1** blocks trustworthy evidence · **P2** the flexibility you asked for · **P3** operational durability

### A. Measurement is not trustworthy yet (P1)

| Gap | Evidence |
|---|---|
| `max_drawdown_pct` is `max()` over **every snapshot ever taken**, unbounded by window — one bad snapshot poisons it permanently, even after full recovery | `services/portfolio.py:310` |
| Sharpe/Sortino annualised by √252 on a handful of snapshots, with no sample-size guard or out-of-range flag | `services/portfolio.py:307-331` (the code's own comment admits it) |
| `bot_book_only` filters trade stats but drawdown/Sharpe stay **account-wide** — the dashboard compares two populations under one heading | `services/portfolio.py:231-234` |
| `/strategies/performance` is `Trade`-based, so the three barrier shadow strategies **always report 0 trades / 0% win rate**. The one endpoint that looks like the comparison cannot see the evidence | `services/portfolio.py:366`, `api/v1/endpoints/strategies.py:44` |
| No endpoint counts resolved signals per strategy. You must call `/ml/calibration?strategy_id=` and read `total_scored` | — |
| `MLModel.n_samples` records the **pre-split pool**, overstating what the fitted model trained on by ~20% | `ml/train.py:363` |
| Label horizon is **trading bars**; signal-ledger horizon is **calendar days**. The training label and the live ledger measure different windows | `ml/features.py:395-398` vs `ml/predict.py:350` |

> This is distinct from the 30-day time stop, which correctly agrees with the 15-trading-day horizon. Do not "fix" 30 to 15.

### B. The edge is unexplained (P1)

- Full-system replay: **−0.1% to −0.4% per 8-month window** after costs, vs NIFTY +6% (`docs/superpowers/research/2026-09-21-system-replay.md`).
- Simplified top-5% test: **+0.22R/trade**. That test has no portfolio limits, no confidence threshold, no ranking, entry at signal-day close, and mild look-ahead in the cutoff — its own doc says so.
- The doc lists **five hypotheses** for where the edge dies (scale-out changing the trade, confidence-based exits, the 0.60 threshold picking a different set, position caps diluting to ~0.4% risk per trade, slippage). **None has been isolated.**
- Barrier models are trained, registered, and running as shadows with ROC AUC 0.556–0.583 — **not promoted**, waiting on resolved signals.
- `BlockDeal` and `InstitutionalFlow` are ingested daily and **read by nothing** — no feature, no filter, no factor.

### C. Selection is built but unwired (P2 — the core of your flexibility ask)

- `services/factors.py` is complete and correct — trend + low-vol cross-sectional percentiles, honest stubs for value/quality/size — and **orphaned**.
- **No shortlist step exists.** `engine.run_strategy` evaluates every eligible instrument straight through `impl.evaluate()`.
- `Instrument.cap_tier` / `sector` and `IndexMembershipSnapshot` are **uncommitted working-tree changes**; no loader populates them.
- `risk.py:556` still derives cap tier from a **model-name suffix** (`strategies/tier.py`), not from the stock.
- **Live bug:** `risk.active_strategy_count()` counts advisory strategies, deflating every real strategy's slot share. With 4 shadows + `real_trading` active, an 8-slot account gives its trading strategy `max(1, 8 // 6) = 1` position.
- **Branch hazard:** `feature/factor-foundation` branched from `990de8f` and is **missing `78fe87b`** ("Let the bot buy again"). Merging as-is looks like reverting that fix.
- `main` is **4 commits ahead of `develop`**, not behind. The earlier note that fixes sit unmerged on `develop` is stale.

### D. Money decision is incomplete (P2)

- There is no tier-budget allocator. `deployable.py` gives one account-wide invested **ceiling**; `limits.py` gives an account-size ladder with a small-cap **ceiling**. Neither turns "70% invested, split 50/30/20" into explicit budgets.
- Leftover cash is never explained or offered to the next candidate.

### E. Real money is blocked (P0)

| Blocker | State |
|---|---|
| After-close entry method (AMO / next-open limit) | **Not built.** `execution.py:153,504` always sends `MARKET` + `VARIETY_REGULAR`. A live exchange rejects these at 15:45 |
| Approval workflow | **Not built.** Telegram is send-only — no webhook, no polling, no pending-approval table, no approve/reject endpoint |
| Broker-held stop (GTT) | **Not built.** Stops exist only inside the 60-second polling loop — an outage leaves positions unprotected |
| DDPI activation, static IP whitelisting | **Owner actions**, status unknown |
| Market protection | **Done** (`brokers/kite.py:403-407`) |

### F. Operations (P3)

No model-artifact backup (three files were lost before), no drift monitor, no challenger automation, no scheduled retrain. Training is CLI/API only.

---

## Locked decisions — these are not reopened

1. Trade spec: **+8% / −4% / 15 trading days**, half out at +5%, 30-day time stop, **15%** drawdown halt.
2. The bot **picks a selection profile automatically from market regime**; you can **pin** one to override and unpin to resume auto.
3. Regime and profiles may change **selection only** — cap tiers considered, factor weights, shortlist %, minimum confidence, names per sector — plus the existing account-wide deployable ceiling. **Locked always:** stop, target, risk-per-trade, sector capital cap, time stop, drawdown halt, cash floor, and which trained model runs.
4. A profile change affects **recommendations only**. Real and paper books stay on the default safe profile until that profile has **30+ resolved signals**. A pin overrides the *regime choice*, never the *promotion gate*.
5. Switching mid-flight **never touches open positions**.
6. Custom profiles capped at 5, labelled untested, never trade real money.
7. One codebase. "Version 1" is the safest built-in profile, not a branch.

---

## The plan — four tracks that never block each other

This is the "without break" requirement. Each track has its own gate and can progress while the others are stalled. Nothing here waits on the edge question being answered, and nothing waits on Zerodha.

```
T1 TRUTH      ─────▶ trustworthy scorecard ──┐
T2 SELECTION  ─────▶ regime switching ───────┼──▶ GO/NO-GO ──▶ assisted live
T3 EDGE       ─────▶ where the edge dies ────┤     (all four
T4 PLUMBING   ─────▶ AMO + approvals + GTT ──┘      gates green)
```

### Track 1 — Truth (start immediately, ~2 days, unblocks every other track's evidence)

Do this first because every other track reports its results through these numbers.

1. **Window-bound the drawdown.** Change `performance_stats` to recompute drawdown from the snapshot value series within the requested window, as `backtest.py:249-257` already does correctly — reuse that shape rather than inventing one. Add a data-quality guard that ignores snapshots whose `total_value` moved more than a configurable threshold in one day.
2. **Guard the ratios.** Return `null` for Sharpe/Sortino below a minimum snapshot count, and flag values above 4 as "sample too short to be meaningful". The code already says this in a comment; make it structural.
3. **Fix the population mismatch.** Either scope drawdown/Sharpe to the same book as `bot_book_only`, or label them explicitly "account-wide" in the response so the UI cannot merge them.
4. **Make shadow evidence visible.** Add resolved-signal counts and signal-based win rate to `/strategies/performance`, so the barrier shadows stop reporting 0. Reuse `ml/calibration.py::signal_calibration` — it already filters by `strategy_id` and reports `total_scored`.
5. **Fix `MLModel.n_samples`** to record `len(train_df)`.
6. **Reconcile the two horizons.** Make `evaluate_pending_signals` walk trading bars, matching `build_label`. Until then every comparison between training metrics and the live ledger is slightly off.
7. **Back up model artifacts** (also Track 4): a scheduled job copying `MODEL_ARTIFACT_DIR` off-server. Three models were lost before; this is an hour of work.

**Gate:** the scorecard reproduces the same numbers twice on the same data, and shadow strategies show non-zero evidence.

*Critical files:* `services/portfolio.py`, `api/v1/endpoints/strategies.py`, `ml/train.py:363`, `ml/predict.py:350`

### Track 2 — Selection and regime switching (the flexibility you asked for, ~2 weeks)

**Step 0 — unblock the branch.** Commit the working-tree schema changes (plan Task 2), then **rebase `feature/factor-foundation` onto `main`** to pick up `78fe87b`. Doing this later means the merge looks like a revert.

**Step 1 — Feature cache (`ml/feature_cache.py`, new).** Cross-sectional scoring needs the whole day's features at once, but `ml_swing.evaluate()` builds its own. Memoise the **last row only** (~1KB vs ~230KB), keyed on window identity `(instrument_id, first_ts, last_ts, row_count)` — not `(instrument, date)`, because a 310-bar and a 400-bar window produce genuinely different rolling values, and both exist today. Follow the `clear_cache()` convention already in `ml/market_context.py`; clear it at the two sites that already clear a sibling cache (`workers/jobs.py:322`, `api/v1/endpoints/ml.py:107`).

This is a **pure speedup of the existing path** — several `ml_swing` strategies already rebuild identical features over an overlapping watchlist. It is what makes N shadow profiles nearly free instead of N× the scan cost.

**Step 2 — Fix the live slot bug.** `risk.active_strategy_count()` excludes `execution_mode == "advisory"` and `long_term_value`. Import the type list from `core/strategy_policy.py`; never re-type the string. This fixes `engine._rank_out_reasons:76` at the same time.

Also filter advisory strategies out of `workers/jobs.py::_blocked_entries` and suppress the advisory Telegram for shadow rows — otherwise four profiles produce a daily "🚫 No buys today" alert nobody reads, and the one alert that must stay credible is lost.

**Step 3 — The locked boundary, in the type system.** `SelectionProfile` as a frozen Pydantic model with `extra="forbid"`. A profile dict carrying `stop_loss_pct`, `risk_per_trade_pct`, `sector_cap_pct`, `time_stop_days` or `model_name` raises at load — there is no field for them, so it cannot express one even by accident. Backed by a test asserting the locked key set is disjoint from `model_fields`, **and** that `risk.py` and `execution.py` never import the selection module. That third assertion is the one that stops a future refactor from turning a selection knob into a risk knob.

**Step 4 — Regime → profile resolver (`services/selection_profiles.py`, new).** Reuse `deployable.current_deployable(db)` verbatim — it never raises, already falls back to `"unknown"`, and is the same regime the capital ceiling reads, so the two can never disagree.

| Regime (from `deployable.py`) | Deployable | Profile | Emphasis |
|---|---|---|---|
| `stressed` | 10% | Steady Large Caps | low-vol, widest shortlist |
| `weak` | 30% | Calm Movers | low-vol weighted |
| `normal` | 55% | Broad Market | trend + low-vol |
| `strong` | 75% | Broad Market | trend-weighted |
| `very_strong` | 85% | Small Cap Explorer | trend, small caps in |
| `unknown` | 30% | Steady Large Caps | conservative fallback |

Pin lives on `SystemState` (three nullable columns) — it is one scalar describing current state that must take effect on the next scan, which is exactly what that table is for. API sits beside the halt/resume latches in `api/v1/endpoints/safety.py`.

> **Ship Small Cap Explorer last.** `risk.py:556` still reads tier from the strategy's model name, so a large-cap strategy selecting small-cap names would have them counted as `large` and sail past the small-cap budget. Until `risk.py` reads `Instrument.cap_tier`, restrict the catalogue to the three profiles that do not widen tiers.

**Step 5 — The selection step (`services/selection.py`, new), off by default.** Insert into `engine.run_strategy` between `eligible_instruments()` and the loop, behind `SELECTION_ENABLED = False`. Order inside: resolve profile → pass through if the universe is under 20 names (a percentile over 5 symbols is noise, and `DEFAULT_WATCHLIST` is 5) → build the panel from the feature cache → hard filters (cap tier, intersected with the locked `limits.allowed_cap_tiers` so a profile can only *narrow*) → `factors.factor_scores()` + `composite_score()` **used unmodified** → names-per-sector using `ml/sector_map.get_sector_bucket`, the same function `risk.py:582` enforces the sector cap with → keep top `shortlist_pct`, floored at 8 names.

**Guard:** if no instrument has a non-null `cap_tier`, skip the tier filter and log it. Otherwise switching this on empties the universe on day one and the scan silently reports zero signals.

**Step 6 — Evidence attribution.** Each non-default profile runs as its own **advisory `Strategy` row** with the same `model_name`, so `/ml/calibration?strategy_id=` compares profiles with **zero changes** to `ml/calibration.py`. Additionally tag `Signal.features` with `selection_profile / regime / source / score / rank` — needed because the auto strategy's own profile changes over time. Plus a `selection_runs` table recording what ran each day, so a zero-signal day is distinguishable from "never tried".

**Gate:** flag off → scan output is byte-identical to today (prove with a snapshot test). Flag on → shadows accumulate toward 30 resolved signals.

*Critical files:* `services/engine.py:96`, `services/risk.py:87`, `services/factors.py` (reused unmodified), `services/deployable.py` (reused unmodified), `strategies/ml_swing.py:112-113,134`

### Track 3 — Find where the edge dies (research, runs in parallel, ~1 week)

The system-replay doc names five hypotheses and isolates none. Run them **one change at a time** against the same windows, as the Nine Steps audit recommends:

1. Scale-out **off** — does the half-out at +5% destroy a trade the model scored as +8%?
2. Confidence-based exits **off** — is the 0.35 exit threshold cutting winners?
3. Confidence bar raised 0.60 → 0.70 → top-5%-equivalent — does the threshold, not the model, explain the gap?
4. Position caps removed — is the edge real but diluted to ~0.4% of account per trade?
5. Entry at next open instead of signal close — how much is slippage?

Extend `services/backtest.py` with these as flags rather than writing new scripts; it already replays exits in live priority order and uses the real cost model. Its own docstring lists what it does *not* replay (sector cap, liquidity, small-cap budget, market-conditions ceiling) — close that list as part of this work, or the answer is contaminated.

**Also here:** re-run the ablation on the barrier label including bulk/block and FII/DII, which have never been tested as features and currently sit as dead data.

**Gate:** a one-page answer naming which component destroys the edge, with the replay numbers for each isolated change.

### Track 4 — Live plumbing (parallel, mostly independent of everything above)

1. **AMO / next-open limit entry.** The blocker. Decision already made: approve tonight, order at tomorrow's open with a limit attached, auto-cancelling if the open is beyond it. Needs `variety=AMO` support in `brokers/kite.py` and an order-method choice in `execution.py`.
2. **Approval workflow.** A pending-approval table, a Telegram webhook or polling loop for replies, and approve/reject endpoints. This is the manual-approval trial phase you want before full auto — it does not exist today in any form.
3. **Broker-held GTT stops**, so a server outage does not leave positions naked.
4. **DDPI + static IP** — owner actions with Zerodha, start now because they have lead time and gate automated selling entirely.
5. **Model artifact backup** (shared with Track 1).

**Gate:** a full paper fire-drill — kill switch, forced outage, AMO placement, approval round-trip — passes end to end.

---

## The go/no-go before real money

All four gates green, plus: **30+ resolved signals** on the barrier shadows with calibration beating the live endpoint models over the same window. Only then is promotion a decision rather than a guess. Assisted-live (every order approved by you) comes before any unattended running, and the capital ladder governs size at every rung.

---

## What this deliberately does not do

- Does not add data sources or features. Sector, breadth, VIX and delivery % were each tried and each moved nothing (−0.0013 mean AUC for delivery). Measure first.
- Does not retrain on +5/−3/10d. Recorded as rejected.
- Does not let regime or profile touch stop, target, risk-per-trade, sector cap, time stop or drawdown halt.
- Does not build the tier-budget allocator (gap D) yet — it sits behind the selection layer, because budgets over a universe you have not narrowed are budgets over the wrong universe.

---

## Verification

Tests run as `cd backend && ./.venv/Scripts/python.exe -m pytest` — a bare `python -m pytest` fails. Postgres must be up via `docker-compose` on port **5433**; if it is down, DB tests hang silently for ~264 seconds. A port check is not a liveness check.

1. **Byte-identity:** with `SELECTION_ENABLED=False`, a full scan against a seeded DB produces the same signals as `main`. This is the "without break" guarantee — the existing path is untouched until you switch it on.
2. **Boundary:** every locked key raises `ValidationError`; `risk.py` and `execution.py` do not import the selection module.
3. **Cache correctness:** `feature_cache.latest_row` returns values identical to `build_features(...).iloc[[-1]]` for the same window, and a different window is a cache miss.
4. **Slot fix:** with 1 auto + 5 advisory strategies and an 8-slot ladder, the auto strategy's share is 8, not 1.
5. **Mid-flight switch:** pin a profile with open positions; assert stop, target, scale-out and time stop are unchanged on every one.
6. **Regime mapping:** each of the six regime strings resolves to the expected profile, and `unknown` falls back to Steady Large Caps.
7. **Promotion gate:** a profile with 29 resolved signals does not reach an order-placing strategy; at 30 it does.
8. **End to end:** run the 15:45 scan against the live prod API (`/status`, `/signals`, `/risk/limits` with the local `.env` API key — SSH is blocked) and confirm `rejection_reason` explains every non-entry.

On execution, the task-level plan with per-task TDD steps goes to `docs/superpowers/plans/2026-09-28-selection-and-regime-switching.md`, and `docs/ROADMAP_TRACKER.md` gets updated rather than superseded — it stays the status source of truth.
