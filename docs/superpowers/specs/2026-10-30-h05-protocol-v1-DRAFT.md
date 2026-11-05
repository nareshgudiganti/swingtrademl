# h05 — 5 trading days · Existing model evaluation (DRAFT protocol, revision 4)

Status: **DRAFT revision 4 for owner review, 2026-10-30. Not accepted. h05 is disabled. No run has started.**
The lane is built and tested. It cannot write anything until the owner (1) sets `LANE_H05_ENABLED=true` and
(2) puts the protocol hash in `LANE_H05_ACCEPTED_PROTOCOL_HASH`. The U1–U4 values below are **proposals** written
into the protocol so that the hash can be accepted; they are not agreed until you accept that hash.
Code: `backend/src/swing_trade_ml/brain/lanes/`. Corrections to earlier statements: `2026-10-30-model-facts-corrections.md`.

**What the scores are (printed on every report):** *existing model weights scored with training-compatible inputs. This is
NOT an exact replay of what production served* (production has served a different `obv_slope` since 2026-10-06; see
`2026-10-30-obv-slope-incident.md`). Production scores are stored as a diagnostic only.

This is **evaluation only**: no retraining, no calibration, no activation, no order. It changes nothing in the v1 bot,
the sealed 15-day trial, Phase B or any trial-frozen file, and trains no new model.

## 1. What the code does today (verified 2026-10-30)

| Item | Verified fact |
|---|---|
| Models | Prod ids **2** `swing_classifier` v2, **16** `swing_classifier_midcap` v2, **17** `swing_classifier_smallcap` v1. All `label_kind=endpoint`, horizon 5, +2%, no stop, **not calibrated** |
| Label | close of the 5th bar after the signal ÷ signal close − 1 ≥ +2% (the training expression) |
| Inputs per model | **Large 37, mid 46, small 46** (today's builder makes 53). Each model's own list is saved in its file |
| Training stocks | **Large 49, mid 24, small 30**; training data ends 2025-10-09 / 10-28 / 11-05 |
| Files | sha256 pinned in the protocol and equal to prod's manifest |
| Evaluation universes | v1's three stock lists, 52 / 150 / 104, less two names in both mid and small lists (BLUESTARCO, JYOTHYLAB) = **52 / 148 / 102**. **Separate from the training stocks** |
| Brain | Scores ~302 stocks with model 2 only. h05 does not touch this |

## 2. What is frozen across all three runs, and what is allowed to move

**Frozen (any difference stops the lane):** the three model files (sha256), their input lists, the label definition,
the **feature code** (sha256 of `ml/features.py`, `ml/market_context.py`, `ml/sector_map.py`, `ml/predict.py`), the
scikit-learn and LightGBM versions, which inputs score a stock (the training basis, section 5), the stock universe
(hash), the entry/exit/cost/slippage rules, the verdict rules and this protocol (hash). Run 1 stores them; runs 2 and 3
and every later day must equal them.

**Moves normally (never frozen as one hash):** the daily candles. Each signal day records its provenance instead: the
NIFTY last session and session count, how many of the group's stocks and how many watchlist stocks had the signal-day
bar, and a fingerprint of that group's signal-day bars only. Every finished outcome records the window sessions it was
scored from and a fingerprint of those bars, so a later correction of a bar can be detected but never rewrites an outcome.

## 3. Two evaluations, two reference prices, two maturity times

| | Original model outcome (endpoint label) | Fixed-rule shadow trade |
|---|---|---|
| Question | did the close of session 5 reach ≥ +2% above the signal close? | +2% target / −4% stop / at most 5 sessions |
| Reference price | **signal close** | **executable entry fill** (open of session 1 plus buy slippage) |
| Matures | at the close of **session 5** | at its exit: target or stop on any of sessions 1–5, else the close of session 5 |
| Stored in | `label_*` columns | `trade_*` columns |

The entry session is holding session 1. Session 6 is never read (tested with a poisoned session-6 candle). A
missing candle is NOT EVALUATED (label) or UNRESOLVED (trade), never the stock's next bar. Tests: the label can be YES
while the trade loses; a trade can finish on session 2 while the label is still pending; both are pending with 4
sessions and final with 5; an expiring trade's exit day equals the label's day.

## 4. Rules written down before any run

| Topic | Rule |
|---|---|
| Signal | Close of the signal session; a stock is scored only if its last candle is that session |
| Calendar | Market sessions = NIFTY 50 daily bars; weekends and holidays skipped |
| Same candle touches both levels | Counted as the **stop**, flagged `same_candle_both_levels`, reported separately |
| Gap through a level | Fills at the open |
| Suspensions / missing candles | UNRESOLVED / NOT EVALUATED, never guessed |
| Corporate actions | Prices are not adjusted. A move over 20% overnight inside the window is flagged and kept; reported with and without |
| Eligibility | Frozen universe; unambiguous group; candle on the signal session; ≥ 220 bars; finite inputs. Otherwise **NOT SCORED** with the reason saved. **No liquidity or volatility filter, and none is added after outcomes are seen** |
| Routing | Each stock → its own group's model only |
| Ranking and selection | Within the group only; score descending, ties by symbol. Top 5 per group per day (up to 15); a shortfall is recorded |
| All scores kept | Every eligible stock is stored, selected or not (the baselines need them) |
| Repeats | A stock selected again within 4 sessions of a counted selection stays recorded but is not counted; all selections are reported too |
| Baselines | Every eligible stock in the group; random 5 from the group (200 seeded draws); same days, fills, exits, costs |
| Uncertainty | Block bootstrap over signal days, blocks of 5, 90% range. The 15 daily selections are **not** treated as 15 independent observations |

### One consistent failure rule (item 8)

If **any** frozen check fails for **any** group (a model file missing, changed or unreadable; an input list, label,
feature code or library version different from the frozen one), the **whole lane** records nothing for that signal day,
saves the reason as an event (it survives, because the stop is a normal return, not a rolled-back error), and **never
substitutes another model**. It resumes only when every identity equals the frozen one again. The report lists every
event and every signal day that was not recorded. Starting a run likewise refuses.
*Why whole-lane, not per-group:* a changed or missing model means the accepted protocol was violated; continuing for
the other groups would give three groups different amounts of evidence and invite a silent replacement.

## 5. Feature parity, not just names (item 5)

Method: today's feature code is run on each model's **own training stocks and period**, and every input's mean and
spread is compared with what that model's saved scaler learned (thresholds: mean shift ≤ 0.25 scaler-sd, spread ratio
0.75–1.25). A change of formula, lookback window, missing-value rule or price basis shows up as a shift.

| Check | Result (real production files, 2026-10-30) |
|---|---|
| Order | The saved order follows the code's order, all three models |
| Formulas, lookbacks, missing-value treatment, price basis (36 + 45 + 45 inputs other than `obv_slope`) | Reproduced: mid and small caps exactly (shift 0.000, spread ratio 1.000); large cap within 0.031 sd, ratios 0.983–1.013 |
| `obv_slope` with **today's production formula** | **Not reproduced** in any model (spread ratio 0.52 large, 1.53 mid, 0.10 small) |
| `obv_slope` with the **old formula on full history** | **Reproduced** (shift ≈ 0, ratio 1.01 / 1.00 / 1.00) |
| **Historical code, not scaler statistics** | `ml/features.py` as committed before the change (git blob `d2f723d`, and the earlier `7da460c`) was run on the real full history of 36 stocks (12 per group): the largest absolute difference from the lane's training-basis inputs over every input of each model is **0** (about 35,000 complete rows per version). `tests/test_h05_historical_features.py` repeats it on synthetic candles from a vendored, hash-pinned copy of the old file |
| Missing values | A row missing any input of the model is skipped in training and in serving; nothing is imputed. The lane does the same |
| Availability at the signal time | Inputs use bars up to the signal-day close only; scoring requires that bar to be the newest. The index-based inputs of the mid and small models need the NIFTY bar of the signal day; if it is missing the stock is NOT SCORED. Breadth, sector and VIX are not inputs of any of the three models |

**Consequence (U11):** the saved models expect the **old** `obv_slope`; production has served a different one since
2026-10-05. The lane's **primary score** therefore uses the training-basis inputs (full stored history, old `obv_slope`);
the **production-path score** is stored next to it and reported as a diagnostic (rank correlation and top-5 overlap per
day), and never selects. Measured on 2026-09-07: rank correlation 0.69 / 0.87 / 0.93; large-cap top 5 overlap 3 of 5.
A run cannot start unless the parity check passes on the training basis. Re-run it any time:
`python -m swing_trade_ml.brain.lanes.h05_cli parity`.

## 6. Training membership diagnostics (item 3)

Every row stores `trained_on_symbol` (the stock was in that model's training list). The report breaks each group's
result into **in training** and **not in training**: stocks, counted picks, label hit rate and shadow-trade result for
picks and for every eligible stock in the subset. These are **diagnostics of the same frozen result**: the headline
and the verdict use the whole group; no verdict is computed for a subset; the report labels it "not a second chance to
pass". Because the models were trained on 49 / 24 / 30 stocks, most mid- and small-cap names fall in "not in training".

## 7. Dry-run exclusions (item 4)

Dry run on signal day 2026-09-07 (local data, nothing stored). Eligible universe 52 / 148 / 102; scored 51 / 148 / 101.

| Stock | Group | Reason | Detail |
|---|---|---|---|
| **TMCV** | large | `short_history` | 204 daily bars; the scorer needs 220 (recent listing after the Tata Motors demerger) |
| **HEG** | small | `stale_data` | last candle 2026-09-04, not the signal day 2026-09-07 |
| BLUESTARCO, JYOTHYLAB | none | `ambiguous_group` | in both the mid and small lists; excluded at the universe step, never scored |

All of these appear in the report: the run's `universe_excluded`, and per group a `not_scored_events` list of
(stock, reason, number of days), also printed in the markdown. Counts by reason are in `not_scored`.

## 8. Execution realism (item 9)

No liquidity filter exists in the lane, so results are **hypothetical fixed-rule selections**, not evidence of
executable portfolio returns; the report prints that on every page. The filter is not added after seeing outcomes.

**Slippage is an ASSUMPTION, not a measurement.** It is derived from daily-candle high–low ranges: no quotes, no order book, no fills.
Real fills may be better or worse; the sensitivity below brackets it. The chosen values are rounded (large is slightly below its
estimate of ~12 bps per side).

**Every cost number and its unit:**

| Item | Unit | Value |
|---|---|---|
| Slippage | basis points of **price**, per side, against us on entry and exit (1 bp = 0.01%) | 10 / 20 / 25 (large / mid / small) |
| Taxes | basis points of **turnover**, per order | buy 11.9, sell 10.4 |
| Depository charge | **rupees** per sell order, flat (≈ 15.9 bps of a ₹1,00,000 order) | ₹15.93 |
| Brokerage | rupees per order | ₹0 |
| Order size | rupees, whole shares | ₹1,00,000 per trade |
| Net return | a **fraction** of the cost basis after all of the above (0.01 = +1%) | — |
| Round-trip cost, approx. | bps of notional | ≈ 58 / 78 / 88 |
| Higher-cost sensitivity | +30 bps of price per side on top of slippage, and charges ×2 | reported, never decides |

Proposed per-side slippage (U5), with the evidence behind it:

| Group | Estimated full spread (median, p75) | Proposed slippage per side | Higher-cost sensitivity (per side) |
|---|---|---|---|
| Large | 24 bps, 34 bps | 10 bps | 40 bps, charges ×2 |
| Mid | 36 bps, 45 bps | 20 bps | 50 bps, charges ×2 |
| Small | 51 bps, 65 bps | 25 bps | 55 bps, charges ×2 |

The spread estimates are a Corwin–Schultz high–low estimator on our own daily candles (last 250 sessions): a rough
proxy, not a quoted spread, so they are a hypothesis and the sensitivity exists to bracket them. Median 20-day turnover
is ₹333 crore / ₹126 crore / ₹26 crore (small-cap 10th percentile ₹3.7 crore), so a ₹1 lakh order is tiny against
volume and price impact is not modelled. **Sensitivity (the ps3 precedent):** every trade is also scored with every fill
30 bps worse and charges doubled; the report shows picks and baseline under it. It never decides a verdict.
Frozen taxes and charges: buy 11.9 bps, sell 10.4 bps, depository ₹15.93 per sell, brokerage ₹0.

## 9. U1–U4 proposed together: two verdicts, run length, false-pass rate

### The two verdicts (never merged)

| | Question | Daily series | PASS | FAIL |
|---|---|---|---|---|
| **SELECTION** | Does the ranking pick better trades than the group's average eligible stock (same days, fills, exits, costs)? | counted picks' average net return **minus** the average of every eligible stock | 90% block range wholly above 0, and the label-edge range is not wholly below 0 (a backwards ranking vetoes) | range wholly below 0 |
| **ECONOMIC** | Do the picks make money after the assumed costs, whatever the baseline? | the counted picks' **own** average net return (no baseline) | 90% block range wholly above 0 | range wholly below 0 |

Everything between is INCONCLUSIVE, as is any run with fewer than 40 matured days. **Beating a losing baseline is a SELECTION result
only**: with the picks at −0.2% a trade and the average stock at −0.5%, selection can PASS while economic is FAIL (tested). The report
prints the pair and one plain sentence (for example "the ranking beat the group's average stock, but the picks lost money after the
assumed costs: relative skill, no economic result"). Money earned while the ranking does *not* beat the average stock is printed as
"Profitable under the stated assumptions; model advantage over the baseline was not established." The higher-cost sensitivity is shown beside both and decides neither.

### How the three runs combine, per group and per verdict type, separately

**PASS** if at least 2 of the group's 3 runs PASS, none FAIL, and the 90% block range of the pooled daily series (the three runs joined in
order) is wholly above 0. **FAIL** if the pooled range is wholly below 0 or at least 2 runs FAIL. Otherwise **INCONCLUSIVE**.
So each cap group ends with two words, SELECTION and ECONOMIC. The three groups are never pooled, and an INCONCLUSIVE run is a normal
outcome, not a failure.

### Effect size to detect

The fixed-rule trade loses on average for *every eligible stock* in every group, with no model involved. Over 2022-06 to 2026-09 on local
candles (1,042 sessions, the lane's own trade rule and assumed costs): **−0.38% / −0.68% / −0.85% per trade** (large / mid / small).
Picks must beat the average stock by about **+0.4% / +0.7% / +0.85%** just to break even, so a **+1.0% net edge per trade** over the group's
average stock is the smallest edge worth detecting for selection, and a *positive economic result* needs roughly +1.5% to +2% for mid and
small caps (table below).

### Reproducible support (exact decision procedure)

`h05_cli power --replicates 1000 --seed 7 --out docs/brain/evidence/h05/power/power_support` (about 30 minutes; needs the local candle
database). Results are stored in `docs/brain/evidence/h05/power/power_support.{md,json}`; the table of outcomes it is built from has sha256
`8a314947ffea144c…`. It calls the **same** `run_decision` / `combined_decision` / `block_range` code as the report. Around them it simulates:

| Dependence | How it is kept |
|---|---|
| **Across dates** | real consecutive history windows ("history"), or a stationary bootstrap of whole days in blocks of about 20 sessions ("bootstrap"), so overlapping 5-day trades stay overlapping; the lane's repeat rule (a stock counts once per 5 sessions) is applied; "sticky 0.8" keeps each pick with 80% probability the next day, as a smooth model score would |
| **Across groups** | a day is ONE cross-section for large, mid and small, so a market-wide good or bad day hits all groups together; "any group passes" is not a product of three independent chances |
| **Across runs** | the three runs are consecutive slices of one path and are pooled in order |
| **Missing days** | each session is dropped with probability 0%, 10% or 20% for the whole lane; never made up; the run is not extended |

Limits: the outcomes are the local five years (only **5 non-overlapping 180-session windows**), so "history" is a small sample and
"bootstrap" is the wider but model-based view; a real model's picks are approximated by the stickiness setting; the endpoint-label edge is
left at zero in the "real edge" runs, which makes power slightly conservative; no liquidity or impact. Monte Carlo error of a 4% rate with
1,000 paths is about ±0.6 points.

### False-pass rate with RANDOM picks (no skill), exact procedure

| Setting (history or bootstrap · stickiness · lost sessions) | SELECTION PASS large / mid / small / **any group** | ECONOMIC PASS, any group |
|---|---|---|
| history · 0 · 0% | 1.7% / 1.0% / 1.0% / **3.6%** | 0.0% |
| history · 0 · 20% | 1.7% / 1.3% / 1.1% / **4.1%** | 0.0% |
| history · 0.8 · 0% | 1.3% / 1.7% / 1.6% / **4.5%** | 0.0% |
| history · 0.8 · 20% | 0.7% / 0.5% / 0.3% / **1.5%** | 0.0% |
| bootstrap · 0 · 0% | 0.8% / 1.2% / 0.9% / **2.9%** | 0.0% |
| bootstrap · 0 · 20% | 1.5% / 1.1% / 1.6% / **4.0%** | 0.0% |
| bootstrap · 0.8 · 0% | 1.7% / 1.0% / 1.5% / **4.1%** | 0.1% |
| bootstrap · 0.8 · 20% | 0.4% / 0.3% / 0.3% / **1.0%** | 0.0% |

**This replaces the earlier statement** ("about 0.7% per group, about 2% for any group"), which came from an independent-day model and is too
optimistic. With the exact procedure the SELECTION false-pass rate is **up to about 1.7% per group and 1.0%–4.5% for any of the three groups**
(central estimate 3–4% when sessions are not lost). Losing sessions lowers it only because fewer runs reach 40 matured days. The 0.0% ECONOMIC
false passes are **conditional on this historical simulation** (2022-06 to 2026-09, where the average stock lost money after the
assumed costs); they are not a general error-rate guarantee. Other costs, a different period or a rising market could give a different rate. In a strongly rising period the
baseline could be positive and random picks could show an economic PASS, which is exactly why an economic PASS without a selection PASS is
read as "Profitable under the stated assumptions; model advantage over the baseline was not established."

### Run length (U1): chance of a combined PASS if the picks really have an edge of `delta` per trade

**What the power numbers mean.** Every figure in the table below is the **full three-run decision** (a *combined* PASS: at least 2 of 3
runs PASS, none FAIL, pooled range wholly above 0), not the chance that one run passes. For one 60-session run with a +1.0% edge the chance
of a run-level PASS is lower: selection **83% / 82% / 77%** and economic **54% / 27% / 17%** (large / mid / small); with no edge, a single run
passes selection 8.6% / 8.0% / 7.7% of the time (which is why the three-run rule exists). **How the +1.0% was injected:** the picks are
random (sticky 0.8) picks from the real outcomes, and `delta` is added to the net return of every counted pick on every day; so the
selection edge equals `delta` (the group's pool is unchanged) and the economic series is the group baseline plus `delta`. The
endpoint-label edge is not shifted.

Bootstrap · sticky 0.8 · 10% of sessions lost. Selection = vs the group's average stock; economic = the picks' own net return.

| Sessions per run | delta | SELECTION PASS large / mid / small | ECONOMIC PASS large / mid / small |
|---|---|---|---|
| 30 | 0.5% | 36% / 29% / 27% | 6% / 1% / 0% |
| 30 | 1.0% | 76% / 69% / 68% | 33% / 12% / 5% |
| 30 | 2.0% | 85% / 84% / 85% | 89% / 79% / 68% |
| **60** | 0.5% | 62% / 51% / 45% | 6% / 0% / 0% |
| **60** | **1.0%** | **93% / 91% / 87%** | 57% / 16% / 6% |
| **60** | 1.5% | 94% / 95% / 91% | 93% / 69% / 49% |
| **60** | 2.0% | 94% / 95% / 91% | 99% / 95% / 88% |
| 90 | 1.0% | 97% / 96% / 95% | 70% / 21% / 6% |
| 90 | 2.0% | 97% / 97% / 96% | 100% / 100% / 98% |

Reading it: **60 sessions per run gives about a 90% chance of a selection PASS for a +1.0% edge** in every group; 30 sessions about 70%;
90 sessions about 96%. The ceiling of about 94% at large edges is not a flaw of the edge: it is the label veto (left at zero in these runs) and
runs where a persistent top 5 produced fewer than 40 days with a newly countable pick. **An economic PASS needs a much bigger edge than a
selection PASS**: at +1.0% the economic chance is 57% / 16% / 6% (large / mid / small) because the average stock starts at −0.4% to −0.85%.
That is a property of the assumed costs, not a bug; it means a modest real ranking skill will usually show up as SELECTION PASS with ECONOMIC
INCONCLUSIVE for mid and small caps.

| | Proposal |
|---|---|
| **U1 run length and boundaries** | **60 consecutive signal sessions per run** (about 12 weeks); runs back to back, no gap or overlap; an outcome matures at the close of session 5. Three runs ≈ 36 weeks plus 5 sessions. 90 sessions per run would raise the +1.0% selection chance from ~90% to ~96% at 54 weeks in total; 30 lowers it to ~70% |
| **U2 minimum evidence (per group, per run)** | ≥ **40 matured signal days** (a day counts when ≥ 10 stocks were eligible and at least one counted pick has a finished outcome); the top 5 short on at most 20% of days. Otherwise the run is INCONCLUSIVE for that group |
| **U3 verdicts per group per run** | Two, as above: SELECTION and ECONOMIC, 90% block range of 5-day blocks, INCONCLUSIVE allowed |
| **U4 three runs combined** | Per group and per verdict type, as above |

**What this does and does not guard against.** With random picks, the chance that any group shows a combined SELECTION PASS is about 1–4.5%.
INCONCLUSIVE is a normal and expected outcome. Three positive runs are not assumed to prove an edge, and a PASS means only "no contradiction
under this frozen test of hypothetical fixed-rule selections". It is not a statement about live trading.

## 9b. Run collection, finalisation, entry timing and position size

**Collection vs finalisation.** Collection of a run ends after its 60th signal session (the job closes the run: status `closed`).
Finalisation waits until every outcome of the run, **selected and baseline**, has matured, that is until session 5 after the run's last
signal day. Until then the report says "waiting: N outcomes not matured" and shows no verdict. **Unresolved outcomes** are final states, not
pending ones: a trade with a missing candle in its window is UNRESOLVED, a label with no candle on session 5 is NOT EVALUATED, a price above
the order size buys no share. They are never guessed, replaced or retried; they leave that group's daily series, are counted in the report
(picks and baseline separately) and do not block finalisation. A run whose group falls below 40 matured days is INCONCLUSIVE for that group.
(Test: `test_collection_ends_after_the_last_session_but_the_verdict_waits_for_every_outcome`.)

**Selections are stored before their simulated entry.** The entry fills at the open of session 1 (09:15 IST of the next trading day).
`score_day` refuses, with nothing written, from that moment on; the daily job's cut-off is 09:00 IST, earlier still. Every selection row and group-day
row stores `recorded_at`, always before the entry open; the outcome step never simulates a row whose `recorded_at` is at or after its entry
open (it becomes UNRESOLVED, flagged `recorded_late`). A Friday signal may be recorded over the weekend but not after Monday 09:15.
So a delayed retry can only miss the session, never backdate an opening fill. (Tests: one minute before the open is accepted, at 09:15 and
days later refused with nothing written; weekend case; late-row guard.)

**Position size and rounding (identical for selections and baselines).** Every simulated trade buys `floor(Rs 1,00,000 / entry fill)` whole
shares. Net return = (proceeds − cost) / cost with cost = shares × entry fill + buy charges, proceeds = shares × exit fill − sell charges. The
rupee depository charge (Rs 15.93 per sell) therefore becomes a percentage of the amount actually invested (for example a Rs 3,000 stock buys 33
shares, about Rs 99,100, and the charge is about 16.1 bps of that). Taxes are bps of each order's turnover. A price above Rs 1,00,000 buys no
share and is UNRESOLVED for picks and baselines alike; the report counts those separately. The same function produces every number, so a pick
and a baseline stock at the same prices get the same return (tested).

**Recommended default: ₹1,00,000 per trade, whole shares (floor).** Cost impact of the order size, measured on a flat-price round trip
(the cost before any price move, large-cap slippage 10 bps):

| Order size | ₹100 stock | ₹3,000 stock | ₹20,000 stock | ₹60,000 stock |
|---|---|---|---|---|
| ₹50,000 | −0.454% (₹49,950 in) | −0.455% (₹48,048) | −0.462% (₹40,040) | no share, UNRESOLVED |
| **₹1,00,000** | **−0.438%** (₹1,00,000) | **−0.438%** (₹99,099) | **−0.442%** (₹80,080) | **−0.449%** (₹60,060) |
| ₹2,00,000 | −0.430% | −0.430% | −0.431% | −0.431% |
| ₹5,00,000 | −0.425% | −0.425% | −0.425% | −0.425% |

Going from ₹1 lakh to ₹5 lakh changes the round-trip cost by about 0.013 percentage points, because only the flat ₹15.93 depository
charge scales with size; rounding costs at most 0.01 points up to ₹20,000 a share. Both are far smaller than the 0.4–0.85% average loss per
trade, so the order size does not drive any verdict. ₹1 lakh matches your ₹1–5 lakh capital range and keeps the figures comparable.

## 10. Reporting, missing days and the daily job

**Reporting.**
- **Before the protocol hash is accepted:** measurements, baselines, uncertainty ranges and diagnostics, and **no verdict**
  (the report says so). That is correct and intended.
- **After acceptance:** the report calculates the frozen verdicts **mechanically**, group by group, when a run is closed
  and every outcome of that run has matured; otherwise it shows "waiting: run not closed" or "waiting: N outcomes not
  matured". The combined decision needs all three runs final. No human edit is involved.
- **Two verdicts per group, never merged** (section 9). The report prints the pair and one plain sentence for it; there is no
  single go / no-go word. "Beat a losing baseline" is printed as relative skill, never as profit.
- Every report: the title "5 trading days · Existing model evaluation", the scoring label (existing weights, training-compatible
  inputs, not an exact production replay), the earlier failed 5-day test, the hypothetical-selection note, the slippage
  ASSUMPTION and the cost units, and "a score is a ranking number, not a probability of profit".

**Missing-day rules (U12).**
1. A signal session of a run window that no pass recorded (job did not run, data not ready by the cut-off, or a lane stop) is
   **MISSED**. It is listed in the report with its reason, saved once as an event.
2. It is **never scored late** (once a later candle exists a stock is no longer eligible for that session), **never replaced**, and the
   run is **not extended**: a run is 60 *sessions*, not 60 recorded days.
3. A day with fewer than 10 eligible stocks in a group is recorded but is not evidence for that group.
4. A day whose trade outcomes stay unresolved (missing candle) drops out of that group's daily series; it is not filled.
5. A group with fewer than 40 matured days in a run is INCONCLUSIVE for that run. With 60 sessions the job can lose 20 and still count.
6. The simulation in section 9 includes missed days (10% and 20% of sessions lost) so the false-pass and power figures already allow for them.

**The daily job (built, disabled, not wired into the scheduler).** `h05_job.run_daily` (CLI: `h05_cli daily`):
1. does nothing, and writes nothing, unless the lane is enabled and the protocol hash accepted;
2. takes a database lock, so two passes can never run at once;
3. matures the outcomes of every run: the label after session 5, the trade at its exit; a finished outcome is never rewritten;
4. for the active run records the latest closed session **once**, only when the NIFTY bar exists and at least 90% of the frozen
   universe has its candle (U13); otherwise it waits and retries (proposed schedule: Mon–Sat 07:30, 08:30, 18:30, 20:30, 22:30 IST)
   until **09:00 IST on the next calendar day**, after which the session is missed;
5. reports every unrecorded session of the window once, with the reason (data not ready / lane stopped by a frozen-model check /
   the job did not run);
6. closes the run after its last session is recorded or missed. It **never starts a run** (the owner does, after reading the
   protocol).

Duplicate prevention has three layers: the lock, an existence check before scoring, and the tables' unique keys (an
`IntegrityError` is read as "already recorded"). `register(scheduler)` adds the job only if enabled and accepted; it is not called
from `workers/scheduler.py`, so the existing bot is untouched. Wiring it is one additive call, waiting for your approval.

## 11. Choices you confirm by accepting the hash

| # | Choice | Value in this draft |
|---|---|---|
| U1–U4 | Section 9 | proposed |
| U5 | Slippage and sensitivity | 10 / 20 / 25 bps; +30 bps and charges ×2 |
| U6 | Levels from the entry fill (v1 uses the signal close) | entry fill |
| U7 | No liquidity or volatility filter, ever added after outcomes | none |
| U8 | Repeats counted once per 5 sessions | yes |
| U9 | Universe frozen for all three runs | frozen |
| U10 | Corporate-action-flagged trades | kept; shown with and without |
| U11 | Primary score = inputs the saved model expects (training basis) | yes; production path is a diagnostic |
| U12 | Missed sessions are never made up; runs are not extended; < 40 matured days = INCONCLUSIVE for that group | proposed |
| U13 | Daily job records a session once ≥ 90% of the universe has its candle; waits until 09:00 IST next day; later = missed | proposed |

## 12. Differences from the v1 bot (not silently included or removed)

- v1 buys at score ≥ 0.60 (+0.10 in a NIFTY downtrend); h05 takes the top 5 per group whatever the score.
- v1 exits early at a score ≤ 0.35, trails its stop and holds up to 30 calendar days; h05 has none of these.
- v1 skips stocks with 20-day average volume under 100,000, daily volatility over 6% or a 5-day fall of 8%; h05 has no filter (U7).
- v1 needs 260 bars; h05 needs 220.
- v1 sets levels from the signal close; h05 from the entry fill (U6).
- v1 scores with the newest 400 bars and today's `obv_slope`; h05's primary score uses full history and the training formula (U11).
- v1 uses position slots and a money ceiling; h05 holds none.

So the shadow trade is **not** a reproduction of v1.

## 13. Isolation (tested)

Disabled by default; every write refuses unless enabled, complete and accepted. Imports no broker, order, risk,
portfolio, engine, execution or brain-decision code; reads one trading table (`Strategy`). Nothing outside the lane
imports it except its own owner-only, GET-only route. No lane file is on the sealed trial's freeze list. Separate
tables (`h05_runs`, `h05_signals`, `h05_group_days`, `h05_events`), no foreign key to any money table.

## 14. Earlier 5-day test stays on record

fd-protocol-v1 (run once, 26 Oct 2026): FAIL on both parts: skill 10 of 21 folds (lower bound −0.155%), money 3 of 17
folds (−0.42% per trade). h05 does not replace, re-run or reinterpret it. Source:
`docs/brain/evidence/fd_v1/five_day_2023-07-01_2025-01-31.md`. Every h05 report prints it.

## 15. Known limits

- Prices are unadjusted and the stock lists are today's lists (survivorship); flags are recorded, not corrected.
- The Corwin–Schultz spread is a proxy; no bid–ask data exists locally. **Slippage is an assumption, not a measured fill.**
- The noise level of a random 5-stock selection was measured on one year of prices; it is the design basis for run length, not a guarantee.
- The lane needs the daily ingest to be complete before scoring; the per-day provenance shows how many stocks had the bar.
- The owner screen is **not built** (the API, CLI and report exist). The daily job is built and tested but disabled and not wired into the scheduler.

## 16. How a run starts (after you accept)

1. Read this document; change any proposal you disagree with (the hash changes with it).
2. Run the tests; put the new `protocol_hash` in `LANE_H05_ACCEPTED_PROTOCOL_HASH`; set `LANE_H05_ENABLED=true`.
3. On the server: `h05_cli check`, `h05_cli parity`, then `start-run --run-no 1 --start … --end …`. After that either you approve
   wiring the daily job (it then scores, matures outcomes and closes the run by itself), or run `h05_cli daily` yourself on the
   schedule above. `report` any time. Starting runs 2 and 3 stays a manual `start-run`.
