# Quant + ML Gap Roadmap: Getting to ₹10 Lakh Live

Date: 2026-09-14
Status: analysis and plan, no implementation started
Reviews: `swing_trading_ml_quant_gap_roadmap.pdf` against the actual code on branch `develop`
Companion: `trading_platform_blueprint.pdf` gap analysis (published artifact, 2026-09-14)

**Goal this document serves:** deploy ₹10,00,000 into swing trades run by this
application, with the application deciding diversification and profit-booking
timing, and with evidence rather than hope behind the switch.

---

## 0. The headline

The PDF's diagnosis is right in direction and wrong in detail. It says the main
gap is "trained + validated ML ranking and regime intelligence". The ranking
model is already trained, active, and running daily. What is genuinely missing
is everything that makes a model's output *trustworthy and survivable at ₹10L*:
calibration, walk-forward evidence, portfolio-level diversification limits, and
an exit policy that agrees with what the model was trained to predict.

Four findings matter more than the rest.

**Finding 1 — the label and the exit policy describe three different trades.**
The model is trained to answer "will this rise ≥2% within 5 trading days"
(`ML_TARGET_RETURN_PCT = 0.02`, `ML_PREDICTION_HORIZON_DAYS = 5`). The default
take-profit is +15% (`DEFAULT_TAKE_PROFIT_PCT`). The time stop is 60 days. So
the model scores a 5-day question, and the position is then held for a 15%/60-day
outcome. Every confidence number in the UI is an answer to a question the system
does not actually act on. Both PDFs warn about label/horizon mismatch; this is
that mistake, sitting in production. Nothing else on this list should be built
before this is resolved. **Resolved 2026-09-14** — the trade is now defined as
+8% before −4% within 15 trading days; see §9.

**Finding 2 — at ₹10L, the absence of a sector cap is the single largest risk.**
Today: `MAX_OPEN_POSITIONS = 10`, `MAX_POSITION_PCT = 0.10`. Ten positions at
10% each is 100% deployed, always. There is no sector limit, no correlation
limit and no cash floor. The training universe spans 296 symbols across 16 NSE
sector buckets, and a momentum-flavoured ranker in a strong banking tape will
happily hand you ten banks. That is a ₹10L position in one sector wearing the
costume of a diversified portfolio. This is a deterministic, unglamorous fix and
it protects more capital than any model improvement on this page.

**Finding 3 — "book profits at the correct time" is currently a fixed rule, not
intelligence.** Exits fire on: stop hit, +15% target, 60-day time stop, or model
probability falling under 0.35. There is no partial profit booking, no exit
model, and no learned timing. The product promise the user is aiming at is
specifically the part with the least machinery behind it.

**Finding 4 — automated profit-booking is blocked by a ₹100 form, not by code.**
Without a DDPI on file with Zerodha, CDSL requires a TPIN and an OTP typed by a
human for every delivery sell. The bot can buy unattended and then cannot sell.
Full automation is otherwise within reach — see §5.

---

## 1. Correcting the PDF's status table

The PDF was written without reading the repository. Several items it lists as
"designed" or "need to build" are shipped and running; a few it does not
mention at all are missing. Acting on its table unedited would send effort to
the wrong places.

| PDF item | PDF status | Actual status in the code |
|---|---|---|
| Rule-based scanner | "Designed" | **Shipped.** `sma_crossover` (20/50, ADX ≥ 20, RSI ≤ 70) runs as the deliberate benchmark the ML model must beat. |
| Paper/live architecture | "Designed" | **Shipped and strong.** One `Broker` interface; `PaperBroker` charges 5bps slippage, ₹20 brokerage, 12bps tax, ₹20 DP per sell, enforces finite cash, refuses limit fills the market has not reached. Live needs `TRADING_MODE=live` **and** `ALLOW_LIVE_TRADING=true`, re-checked inside `KiteBroker.place_order()`. |
| Risk controls | "Designed conceptually" | **Shipped at trade level.** Risk-per-trade sizing off distance-to-stop, max position %, max open positions, 20% drawdown breaker, 5-day stop-loss cooldown, trailing stop, 60-day time stop, stale-price guard, idempotency. **Missing at portfolio level** — see Finding 2. |
| LightGBM/XGBoost ranking | "Need to train" | **Trained and active.** LightGBM is the default with a graceful fallback to sklearn GBDT; random forest, gradient boosting and logistic regression are selectable. Seven ablation artifacts dated 2026-09-09 sit in `backend/data/models/`. |
| Feature engine | "Partially designed" | **Shipped, ~50 features**, covering every family the PDF §3 lists except liquidity/spread. Includes relative strength vs NIFTY *and* vs the stock's own sector index, INDIA VIX as a percentile rank, and two cross-sectional breadth measures. |
| Historical clean OHLCV | "Must verify" | **Present.** 1,825-day backfill; sector indices carry ~1,240 daily bars. TimescaleDB hypertable keyed on `(instrument_id, interval, ts)`. |
| Chronological splits | "Need to build" | **Shipped.** `chronological_split()`, never random, with the leakage reasoning documented and tested. |
| Model versioning + rollback | "Needed for mature production" | **Shipped.** One `ACTIVE` model per name; activating archives its predecessor, so rollback is one API call. |
| Walk-forward backtesting | "Designed; must verify" | **Not built.** One chronological split, not rolling folds. |
| Confidence calibration | "Need to build" | **Not built.** Correctly identified. |
| Market regime engine | "High priority" | **Not built as an engine.** Regime exists as model *features* and as one knob: `bear_market_confidence_boost` raises the bar 10 points in a NIFTY downtrend. |
| Portfolio allocator | "Need to build" | **Not built.** Correctly identified. |
| Post-exit Day 1/3/5/7 | "Need to build" | **Partial.** `recent_post_exit_watch()` tracks 21 days against live price and pushes it into the daily Telegram digest. No D1/3/5/7, no benchmark comparison, no exit-quality label. |
| Drift detection | "Needed before live scale" | **Partial.** `confidence_decay_status()` alerts when an open position's model confidence drops ≥15 points. No feature-distribution or outcome drift monitoring. |
| Champion/Challenger | "Needed for mature production" | **Not built**, but the registry already supports the versioning and rollback half of it. |

**Two things the PDF misses entirely:** the label/exit mismatch (Finding 1), and
that the ablation experiments already run have **no written results**. Seven
model artifacts exist comparing baseline vs market-only vs sector-only vs
combined features, for large and mid cap — and nothing in the repo records what
they showed. That research is currently unreproducible and, in practice, lost.

---

## 2. What is genuinely missing, in priority order

Combining both PDFs and filtering to what the code actually lacks.

### Tier 0 — the number in the UI must mean something

1. **Barrier labels.** Replace "+2% within 5 days" with "+X% before −Y% within N
   days", after costs. Today a stock that falls 8% and then recovers to +2%
   counts as a win; that is a trade the risk engine would have stopped out of.
   The model is being rewarded for trades the system would never have held.
2. **Align the exit policy to the label.** Pick one trade definition and make
   the label, the take-profit, the time stop and the exit threshold all express
   it. This is a decision, not just code — decided, see §9.
3. **Walk-forward validation.** Rolling train/test folds so no single lucky test
   window can flatter a model indefinitely, plus one final untouched window.
4. **Calibration buckets.** Observed win rate, average return, downside and
   sample size per confidence bucket (0.55–0.60, 0.60–0.70, 0.70–0.80, 0.80+).
   Until this exists, the confidence percentage shown on every signal card is
   decorative.
5. **Write down the ablation results.** Re-run the 9 Sep experiments, record
   what each feature family actually bought, delete what it did not.

### Tier 1 — survive ₹10 lakh

6. **Sector and correlation caps.** Max exposure per sector bucket; a cap on
   simultaneous positions whose returns are highly correlated. Sixteen buckets
   already exist in `ml/sector_map.py`, so the data is there.
7. **Regime → deployable capital.** Decide how much of ₹10L deserves to be in
   the market today *before* deciding which stocks. Cash as an explicit,
   reportable position rather than a residue.
8. **Cash floor and staged deployment.** A minimum reserve that the allocator
   may never spend.
9. **Kill switch, risk events table, audit log.** One backend-enforced switch
   that halts entries instantly; every rejection and breaker trip recorded.
10. **Partial profit booking.** Scale-out — take some off at the first target,
    trail the rest. Currently every exit is all-or-nothing.

### Tier 2 — make the model better, honestly

11. **Exit model.** Its own target: probability the original edge has decayed
    enough to leave within K days. Reading exits off the entry model's
    probability is the "one giant model" mistake.
12. **Hysteresis on exit.** A band around the threshold so a probability
    oscillating near 0.35 cannot flip the decision daily.
13. **Fundamentals.** The one whole feature family at zero coverage.
14. **Liquidity and execution features.** ADV, turnover, spread, size-vs-liquidity.
15. **Drift monitoring.** Feature distribution shift, outcome drift by bucket,
    regime-conditional performance.
16. **Champion vs challenger.** Both models score the same forward paper stream;
    promote only on a robust win across enough trades and more than one regime.

### Tier 3 — only after the above earns it

17. Replayable decisions (`scan_runs`, `scan_candidates`, `exit_decisions`).
18. Assisted-live approval flow.
19. News and alternative data.

---

## 3. Feasible, hard, and not worth doing

The user asked explicitly for this split. Effort estimates assume the existing
codebase and one developer working with an agent.

### Comfortably feasible — days to two weeks each

| Item | Why it is easy here |
|---|---|
| Barrier labels | `build_training_dataset()` already carries `ts` and per-symbol OHLCV; the barrier is a forward-window scan over data already loaded. |
| Walk-forward folds | `chronological_split()` becomes a loop. The training path is already deterministic with a fixed seed. |
| Calibration buckets | Predictions are already scored at horizon (`evaluate_pending_predictions`, 16:15 daily). This is a group-by over data already being collected. |
| Sector caps | 16 buckets and a 296-symbol map already exist; the check slots into `check_entry()` beside the existing limits. |
| Cash floor, deployable % | One deterministic function in front of the sizing call. |
| Kill switch, risk events | A settings flag read fresh plus a table. The pattern is already established by the two-flag live latch. |
| Partial profit booking | The order path already supports partial quantities; this is exit-rule logic, not plumbing. |
| Post-exit D1/3/5/7 | Candles for exited symbols are already ingested daily. |
| Exit model | Same training harness, different label and feature window. |
| Drift on features | Compare recent feature distributions against the training window. Pure pandas. |
| Champion/challenger | Registry versioning and rollback already exist; what is needed is a shadow scoring stream and a comparison report. |

### Feasible but genuinely hard — weeks, with real risk of doing it wrong

| Item | The hard part |
|---|---|
| **Fundamentals** | The vendor research (`2026-09-12-fundamentals-vendor-decision.md`) concluded there is **no credible paid point-in-time fundamentals API for Indian equities** at retail scale — FMP and Finnhub coverage is doubtful, Tijori and Trendlyne have no documented public API. The chosen path is parsing NSE's public XBRL filings. That is free and legitimate, but it means building an XBRL parser, a tag-to-feature mapping, and a discipline for restatements. **Restatements are the leakage trap:** using today's revised figures for a historical date makes the backtest brilliant and the live model worthless. Budget weeks and treat it as its own project. |
| **Liquidity / spread features** | Kite exposes depth on quotes, but we do not store it. Spread history **cannot be backfilled** — it only exists going forward. The correct move is to start recording depth snapshots now so the feature exists in a year. Anything using spread is unavailable for historical training until then. |
| **Regime engine as a learned model** | Five years of history contains very few genuine regime transitions. A *learned* regime classifier will overfit. A **rule-based** regime state (index trend, breadth, VIX percentile — all features we already compute) is the honest version and is much easier. Recommend rules, not a model. |
| **Correlation caps** | Rolling correlation is easy; choosing a threshold that is not arbitrary is not. Start with the sector cap, which captures most of the same risk for a fraction of the difficulty. |

### Not feasible, or not worth it now

| Item | Why not |
|---|---|
| **LSTM / transformers / foundation models** | ~296 symbols × ~1,240 bars is a few hundred thousand rows with a noisy, weakly-separable label. Gradient-boosted trees are the right tool at this data scale. Both PDFs agree; so do I. Revisit only if a tree baseline is proven and plateaued. |
| **LLM-based buy/sell decisions** | No point-in-time discipline, no reproducibility, no calibration. It would undo the leakage hygiene the codebase has been careful about. |
| **News and sentiment, now** | Bolting it on is easy; getting *point-in-time* Indian-market news without look-ahead is not, and coverage of mid and small caps is thin. High effort, unmeasurable benefit until calibration exists to measure it against. Defer — and note this reverses my earlier suggestion that news was ready to start, which assumed calibration was in place to evaluate it. |
| **True point-in-time fundamentals with restatement history** | Not purchasable in India at this budget. Approximate from XBRL filing dates and state the limitation. |
| **Predicting the exact top to book profits** | Not achievable, and promising it would be dishonest. What is achievable: a trained exit model, partial scale-outs, and post-exit measurement that shows honestly when exits were early. |
| **₹10L switched on in one step** | Not a technical limit, a judgment one. See §6. |
| **Intraday or tick-level alpha** | A different product with different data and different infrastructure. |

---

## 4. The ₹10 lakh question specifically

What the application must do that it cannot do today, stated plainly against
the user's own words: *"think and diversify those and book profits on correct time."*

### Diversify

| Today | Needed |
|---|---|
| 10 positions max, 10% each, no sector limit, no correlation limit | Max per sector (e.g. 25% of deployed), max correlated cluster, cap-tier budget |
| Always ~100% deployed if signals exist | A deployable-capital decision each day, with cash as a valid answer |
| No cash floor | A reserve the allocator cannot touch |
| Cap tier inferred from a model-name suffix | Real market-cap classification on the instrument record |

Concretely, at ₹10L with a 25% sector cap and a regime-driven deployable band,
a neutral market might put ₹5L to work across at least four sectors with ₹5L
held in cash — instead of today's ₹10L across ten names that could all be banks.

### Book profits at the right time

| Today | Needed |
|---|---|
| Fixed +15% target | Target derived from the label definition and from volatility (ATR-scaled), not a constant |
| All-or-nothing exit | Scale-out: part at the first target, trail the remainder |
| Exit = entry model's probability under 0.35 | A dedicated exit model with its own label |
| Threshold with no band | Hysteresis, so noise does not churn positions |
| Exit quality never measured | D1/3/5/7 post-exit, benchmark-relative, classified as protected / good / neutral / early / poor |

The last row is the one that turns "book profits at the correct time" from a
claim into something measurable. Until exits are scored, no one — including the
model — knows whether they are good.

---

## 5. Full automation: what actually stands in the way

The question is whether this can run with no human touching any individual
trade — the bot decides, buys, monitors and books profits by itself.

**It can. Nothing in the way is a software limitation.** Three account-level
unlocks stand between here and there, none of them code, all one-time, and one
of them is a hard blocker nobody had spotted.

### 5.1 The three unlocks

**1. DDPI — the one that blocks automated selling entirely.**

Without a Demat Debit and Pledge Instruction on file, CDSL requires a **TPIN plus
an OTP, typed by a human, for every delivery sell**. The bot could buy
automatically and then be unable to sell without you. "Book profits on the
correct time" is simply impossible in that state, however good the exit model is.

DDPI is activated online with Zerodha, one-time, ₹100 + GST. With it, sells go
through the API unattended. **This is the single highest-value action on the
whole roadmap** — every other item improves the system; this one is the
difference between automated and not.

**2. External TOTP as the account's active second factor.**

The unattended login is already written and scheduled (`auto_login()` in
`brokers/kite.py`, the 06:10 job). It fails for one reason: Zerodha's login step
reports this account accepts `["app_code", "sms"]` and not `totp`. Having
"External TOTP" switched on in the profile is not the same as it being the
account's active method.

The fix is a 2FA reset in Kite — reset the password by email or SMS, then choose
**Method 2: External authenticator** and capture the seed with the "Can't scan?
Copy key" link. Zerodha's own documentation states app code is not required once
external TOTP is in use, which is exactly the state the code needs. Once set,
`KITE_TOTP_SECRET` is already wired and the daily login stops being a human task.

**3. A static IP whitelisted against the API key.**

Mandatory for all Kite Connect API users under the SEBI framework, regardless of
order rate. The production droplet at `147.182.176.105` already has a static IP —
this is a registration step with Zerodha, not an infrastructure change.

### 5.2 Regulation is not the obstacle

SEBI's retail algo framework became mandatory for brokers on 1 April 2026. The
threshold that triggers real obligations — exchange registration, a unique
Algo ID, disclosing strategy logic — is **10 orders per second per exchange per
client**.

This system places roughly two to ten orders *per day*. That is about five orders
of magnitude below the threshold. Under it, a self-use algo needs **no exchange
registration, no Algo ID, and no strategy disclosure** — only the static IP.

Two honest caveats. This reading comes from public summaries and Zerodha's own
explanatory posts, not from legal advice; confirm it with Zerodha support at the
same time as whitelisting the IP. And the framework governs algos run for *your
own* account — the moment anyone else's money or a published recommendation is
involved, a different rulebook applies.

### 5.3 What is already automated

More than expected. Fifteen scheduled jobs already run unattended: quote
refresh and exit checks every minute during market hours, order reconciliation,
daily ingestion, the post-close scan, prediction and signal scoring, the Telegram
digest, weekly instrument sync — and the Kite auto-login itself. Order placement
through the broker adapter is automatic today in paper mode and would be in live
mode with no code change.

The automation is essentially built. It is gated on account permissions.

### 5.4 What stays manual on purpose

Four things should never be automated, and the design is right to keep them out:

| Stays manual | Why |
|---|---|
| Turning live trading on | Two independent server flags, re-checked inside `place_order()`. A UI toggle must never be able to reach the exchange. |
| Promoting a new model | A drift alert starts an investigation, never a swap. Both source documents are explicit, and an auto-promoting model can quietly replace a working one with a worse one. |
| Changing risk limits | Drawdown ceiling, sector cap, cash floor — these encode your risk appetite, which no model can infer. |
| Adding or withdrawing funds | Outside the system entirely. |

None of these is per-trade. Once set, they are touched monthly at most.

### 5.5 What is manual now and should not be

**Model retraining** is CLI-only — there is no scheduled job for it. A monthly
retrain that produces a *challenger* (never an auto-promotion) belongs in the
scheduler. Watchlist refresh is the other one, and is occasional enough to leave
alone.

### 5.6 The residual risks that survive full automation

Automation removes the human from the loop; it does not remove these:

- **The auto-login drives undocumented endpoints.** Zerodha's own Connect flow
  has no password-in/token-out API. If they change those endpoints, the login
  breaks — silently, at 06:10, on a morning you are not watching. The existing
  Telegram nag is the safety net and must stay even after auto-login works.
- **Storing the password and TOTP seed on a server is real account risk.** It
  works around a security control by design. The droplet's hardening becomes part
  of your trading risk, not just your IT hygiene.
- **A model that is wrong for a month will be wrong automatically**, at full
  size, without hesitating. This is what the drawdown breaker, sector cap and
  kill switch exist for — they matter more under automation, not less.
- **Broker and exchange incidents** still need a no-new-entry mode that trips on
  its own.

### 5.7 The answer, plainly

Full automation is reachable, and the remaining distance is smaller than the
rest of this roadmap. The order to clear it in:

1. Activate DDPI. Until this is done, automated profit-booking cannot work at all.
2. Switch the account to External TOTP. The code is waiting.
3. Whitelist the droplet's IP with Zerodha, and confirm the algo framework
   position with their support while you are there.
4. Add a scheduled monthly retrain that produces a challenger.
5. Build the kill switch and the drawdown breaker *before* the first unattended
   live order, not after.

Steps 1 to 3 are yours and can be done this week, in parallel with Stage 1 of the
plan in §8. Nothing else in this document is blocked on them.

## 6. What the user needs to decide, supply, and practice

The PDF's §2 is right that the gap is quant judgment, not chart reading. But
most of what is needed from a non-expert owner is **decisions and discipline**,
not study. Split accordingly.

### 5a. Decisions only the owner can make — these are blocking inputs

These cannot be derived from data. Every one of them is a number that goes into
the risk engine, and the portfolio layer cannot be built without them.

1. **Maximum drawdown you will tolerate, in rupees.** Not a percentage — the
   actual figure that would make you switch the system off. If ₹10L falling to
   ₹8L is unacceptable, the 20% breaker is already wrong for you.
2. **Maximum loss on any single trade, in rupees.** This sets
   `RISK_PER_TRADE_PCT`. At ₹10L, 1% is ₹10,000 per trade.
3. **Maximum share of capital in one sector.** A starting suggestion is 25%, but
   it is your call.
4. **Minimum cash reserve** that never gets deployed regardless of signal quality.
5. **Sectors or companies you will not hold** — for any reason, including
   personal ones. Cheaper to encode as an exclusion list than to argue with later.
6. **Which trade you are actually buying:** a ~5-day, ~2–3% move, or a multi-week,
   10–15% move. This single answer settles the label, the target, the time stop
   and the exit threshold (Finding 1). Everything in Tier 0 waits on it.

### 5b. Operational discipline — the real dependency

**The Kite login is the hard one.** Tokens expire daily around 06:00 IST and
cannot renew unattended; TOTP auto-login is unavailable on this Zerodha account.
At ₹10L live, a missed morning login means open positions going unmanaged for a
full trading day — stops not checked, exits not fired. Before any real money:
demonstrate 30 consecutive trading days of logging in by 09:00, using the
Telegram nag. If that habit does not hold in paper, it will not hold with money
on the line, and the conclusion should be a smaller position count rather than
hoping.

Also monthly, roughly 30 minutes: review the challenger model against the
champion and approve or reject promotion. A drift alert should start an
investigation, never an automatic swap.

### 5c. What to actually learn — a short list

Not chart patterns. Not candlestick names. Not more indicators. Five concepts,
in order of payoff:

1. **Position sizing from distance to stop.** Why a 10% stop gets a smaller
   position than a 3% stop so both risk the same rupees. This is already how the
   code works and is the highest-leverage idea in the whole system.
2. **Reading a calibration table.** "Of the 40 signals scored above 0.70, 23
   won" — and why a bucket with 6 samples means nothing.
3. **Drawdown vs return.** Why 50% down needs 100% up to recover, and why
   sequence matters more than average.
4. **Correlation and diversification.** Why ten good-looking bank trades are one
   trade.
5. **Regime.** Why the same signal is worth less when breadth is narrow and VIX
   is elevated.

Each of these is a screen the application can teach you rather than a book you
have to read. Tier 0 and Tier 1 work should surface all five as plain-English
readouts — which also serves the jargon-free UI principle already established
for this project.

### 5d. Explicitly not homework

Learning to read charts manually, memorising indicator formulas, or following
market commentary. None of it improves this system, and acting on it would
conflict with the model rather than help it.

---

## 7. Readiness gates for ₹10 lakh

Decided in advance, so a few good weeks cannot be mistaken for evidence. Every
gate is measurable from data the system already collects or will collect under
Tier 0.

| # | Gate | Threshold |
|---|---|---|
| 1 | Closed trades through the production pipeline | ≥ 150 |
| 2 | Calibration error per bucket, buckets with n ≥ 30 | ≤ 10 percentage points |
| 3 | Walk-forward folds after realistic costs | ≥ 3 folds, none negative |
| 4 | Distinct market regimes covered by the evidence | ≥ 2 |
| 5 | Worst paper drawdown | ≤ the rupee figure from §5a.1 |
| 6 | ML strategy vs the SMA crossover benchmark | Beats it on risk-adjusted return |
| 7 | Post-exit tracking live, exits classified | Early-exit rate known and acceptable |
| 8 | Kill switch, stale-data guard, duplicate-order guard | Tested by deliberate drill, not assumed |
| 9 | Consecutive clean daily Kite logins | ≥ 30 |
| 10 | Sector cap, cash floor, deployable-capital layer | Live in paper for ≥ 1 month |

**Then stage the capital rather than switching it on.** ₹1L assisted (you approve
each order from Telegram) → ₹3L assisted → ₹3L auto → ₹10L auto. Each step needs
at least a month and no gate regression. Going from paper to ₹10L full-auto in
one move throws away the only thing this whole exercise is building: evidence.

---

## 8. Sequenced plan

**Stage 1 — Make the number honest.** Barrier labels; align exit policy to the
label; walk-forward folds; calibration buckets; write down the ablation results.
*Exit criterion: a calibration table exists and the confidence shown in the UI
is defensible.*

**Stage 2 — Make ₹10L survivable.** Sector caps; regime-driven deployable
capital; cash floor; kill switch and risk-events log; partial profit booking;
real market-cap classification.
*Exit criterion: no single sector shock can take more than the stated share of
the book, and cash is a reportable position.*

**Stage 3 — Make exits intelligent.** Exit model with its own label; hysteresis;
full post-exit outcome engine with D1/3/5/7, benchmark comparison and exit-quality
classification.
*Exit criterion: exit quality is measured, and early exits are visible.*

**Stage 4 — Make it improvable.** Drift monitoring; champion vs challenger with
shadow scoring; fundamentals from NSE XBRL; start recording depth snapshots for
future liquidity features.
*Exit criterion: a new model can be proposed, compared and promoted or rejected
on evidence.*

**Stage 5 — Earn the live switch.** Replayable decisions; assisted-live approval
from Telegram; staged capital per §6.

News, alternative data and anything deep-learning sit after Stage 5, and only if
a proven baseline has visibly plateaued.

---

## 9. Decisions taken, and what is still open

Settled by the owner on 2026-09-14:

| Question | Answer |
|---|---|
| Which trade are we buying | **+8% before −4%, within 15 trading days.** Half the position banked at +5%, the rest trailed. Time stop 30 days. |
| Maximum drawdown | **Halt new entries at −₹1,50,000 (15%).** Never force-sells. |
| Maximum in one sector | **25% of capital.** |
| Profit booking | **Sell half at the first target, trail the remainder.** |

Defaulted unless corrected: risk per trade ₹10,000 (1%); cash floor ₹1,00,000
never deployed; no exclusion list.

Also settled: because the scan runs at 15:45, after the 15:30 close, approvals
are *approve in the evening, order at tomorrow's open with a limit price
attached*, auto-cancelling if the open is beyond it. Moving the scan earlier was
rejected — it would evaluate a half-formed daily candle.

Still open, and only these:

1. **The three account unlocks in §5.1** — DDPI, External TOTP, static IP
   whitelisting. Owner actions, not code.
2. Whether the personal-finance and mutual-fund modules are feature-complete for
   now. They are roughly a third of the front end and will otherwise keep
   competing for the same hours as this roadmap.

*Planning document. Nothing in it is a projection or guarantee of returns.
Paper-trading results, backtests and calibration statistics are evidence about a
model's past behaviour, not about future capital.*
