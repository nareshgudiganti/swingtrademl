# Five-day strategy protocol (fd-protocol-v1) — SIGNED 2026-10-24, freezes at the tag

Status: **signed by the owner on 2026-10-24** (section 9: D1–D5 and D7 as recommended; D6 agreed in
principle, waiting for tv22). It is frozen when the commit holding this file and the tool change is tagged
`fd-protocol-v1`. After that, the layer 1 confirmation run happens once and no setting changes after seeing
a result. No 5-day result has been looked at for this protocol before the tag.

Why this exists: the 15-day brain has frozen pass rules (`wf-protocol-v1`, evidence-defs-v2, Phase B). The
5-day version 1 bot has none. It trades on paper every day, but nothing says in advance what result would
count as "it works". This protocol fixes that, so the 5-day and 15-day strategies are each judged on their own
question, against their own frozen benchmarks, after costs (owner decision 2026-10-20: two horizons, both
intended; never pool them).

Scope: evidence only. Nothing here changes picks, orders, sizing, stops, limits or the frozen trial.

## 1. What the 5-day strategy really is today (read from prod, 24 Oct 2026)

| Item | Value on prod | Source |
|---|---|---|
| Strategies | `ml_swing_main` (id 1), `ml_swing_midcap` (4), `ml_swing_smallcap` (5); paper, auto | `/strategies` |
| Model question | "Will the stock gain 2% within 5 trading days?" | the 3 active models |
| Buy rule | model score ≥ 60% (+10 points when NIFTY is in a downtrend), liquidity, volatility and falling-knife filters | `strategies/ml_swing.py` |
| Exit levels on every BUY | target **+2.0%**, stop **−4.0%** (all 349 v1 BUYs in the last 60 days) | `/signals` |
| Time stop | 30 **calendar** days (settled rule, not to be changed) | `services/exit_policy.py` |
| Half out at +5% | never fires, because the +2% target is hit first | Atlas fx1 |
| Last BUY | 8 Oct 2026 (none since: weak market plus the bear-market boost) | `/signals` |

Plain-English consequence: with +2% to win and −4% to lose, **more than 2 trades in every 3 must win just to
break even before costs.** Old data already showed 5-day +2% trades losing after costs on the seen periods
(e.g. `horizon_grid_2025-02-03_2025-06-30.md`: 5d +2%/−2%, −0.38% a trade). That is information, not a
verdict: those periods are seen and do not count.

## 2. What is tested

Two parts, the same shape as the 15-day protocol, so the two horizons can be compared side by side but are
never added together.

- **Layer 1 (history):** the 5-day model's ranking, retrained every fold, scored on the trade rule in
  section 3, against the benchmarks in section 4.
- **Layer 2 (forward):** the version 1 paper bot itself, from the lock date, in a book of its own
  (see D6), against the same benchmarks over the same days.

Passing either part never counts toward the brain's M18 gate, and never makes trading more aggressive.

## 3. Fixed settings (proposed — the owner picks where marked D)

| Setting | Proposed value |
|---|---|
| Trade rule scored (D1) | next-day open entry, **+2% target / −4% stop, held up to 30 calendar days**, costs and slippage (= what prod runs) |
| Also reported, never counted (D1) | the same trade closed at the end of day 5 (= what the model's question says) |
| Model labels | +2% within 5 trading days (as the prod models) |
| Picks per day (D2) | **best 5 by model score** for the skill part; the prod buy rule (≥ 60% + filters) for the money part |
| Fold length / retrain | 28 calendar days / once per fold (as 15-day) |
| Confidence blocks | 5 trading days for the 5-day exit; 21 trading days for the 30-calendar-day hold |
| Universe | the 49 model stocks (survivor bias, stated in the report) |
| Costs | the cost model checked against Zerodha on 17 Oct (`docs/brain/COSTS-CHECK-2026-10.md`), plus the cost-stress levels as a side report |

## 4. Benchmarks (frozen, after costs, same days, same rule)

Reuse the evidence-defs-v2 baselines exactly (no new maths): every stock (= random expected value), 200
random-5 accounts, 5 strongest 20-day risers, NIFTY 50 held, cash. The "rules only" yardstick is added only
once tv7 names the official one (D5).

## 5. Sample (D3)

Candles run 2021-08 to now. Models need about 2 years, so the first test day is 2023-07-01.

| Sample | Dates | Status for the 5-day rule | Use |
|---|---|---|---|
| **Confirmation** | 2023-07-01 to 2025-01-31 (21 folds) | never scored with a 5-day rule; already used for 15-day tests, bad-market windows and cost stress | pass or fail (layer 1) |
| Seen | 2025-02-01 onwards | 5-day variants looked at in the horizon grids | reported only |
| **Forward** | lock date + 6 months (one pre-set extension to 9 months only if under 100 trades) | untouched | pass or fail (layer 2) |

Honest limit: "never scored with a 5-day rule" is not "never seen". The market in that period has been
studied for the 15-day brain. If the owner does not accept that, layer 1 is reported only and the forward
test is the only pass or fail.

## 6. Decision rule (same thresholds as 15-day, frozen at sign-off)

Eligible fold: at least 10 test days and 20 finished trades. Each part needs at least 12 eligible folds and
100 finished trades; otherwise the answer is **insufficient**, never "fail".

| Part | Fold won when | Also required |
|---|---|---|
| **Predictive skill** | average result per day beats every stock | ≥ 60% of eligible folds won, and the lower bound of the daily edge over every stock above zero |
| **Economic value** | average result per day after costs above zero | ≥ 60% of eligible folds won, and the average per trade over all folds above zero |
| **Beats the benchmarks** (layer 2) | — | after costs, above every stock **and** NIFTY held over the forward period; worst fall stays inside the 15% halt |

A pass in layer 1 alone is not enough to call the 5-day strategy proven. Both layers must pass.

## 7. Report must show

Horizon label on every number ("5-day"), never next to an unlabelled 15-day figure. Per fold: test days,
market type, trades, hit rate, average per trade after costs, benchmarks. Overall: the answers per part,
hit rate needed to break even, worst fold, worst fall, and the limits below.

## 8. Known limits

- Survivor bias: today's 49 stocks.
- Daily candles cannot say whether target or stop came first on the same day (counted as the stop, cautious).
- The v1 bot and the brain share the paper account's slots today, so forward results are not independent
  until D6 is decided.
- A pass never justifies live trading. Manual approval and the owner's go-live call still come first.

## 9. Owner decisions (signed 2026-10-24)

| # | Question | Recommendation |
|---|---|---|
| D1 | Which trade rule is the pass/fail one: as prod runs (+2/−4, up to 30 calendar days) or as the question says (closed at day 5)? | As prod runs; the day-5 version reported alongside |
| D2 | Picks: best 5 a day for skill, the prod buy rule for money? | Yes |
| D3 | Accept 2023-07 to 2025-01 as the confirmation sample for the 5-day rule? | Yes, with the limit in section 5 written in the report |
| D4 | Same thresholds as 15-day (60% of folds, 12 folds, 100 trades, lower bound above zero)? | Yes, so the two horizons are judged the same way |
| D5 | Add "rules only" as a benchmark once tv7 names the official one? | Yes; until then the report says it is missing |
| D6 | Forward test in a book of its own (needs tv22 and a trial-change waiver, or waits until the trial ends)? | Own book; decide together with tv22 |
| D7 | Stop date: verdict 6 months after the lock, one extension to 9 months only if under 100 trades, no early stop? | Yes (same as the 15-day plan) |

Signed by the owner on 2026-10-24 ("go ahead" on the recommendations above):

- [x] D1 as prod runs (+2% / −4%, up to 30 calendar days) is the pass/fail rule; closed-at-day-5 reported alongside.
- [x] D2 best 5 a day for skill; the prod buy rule for money.
- [x] D3 confirmation sample 2023-07-01 to 2025-01-31, with the section 5 limit written in the report.
- [x] D4 same thresholds as the 15-day protocol.
- [x] D5 "rules only" added as a benchmark once tv7 names the official one; until then the report says it is missing.
- [~] D6 own book for the forward test: **agreed in principle, not yet decided.** It changes slots and
  sizing during the frozen trial, so it needs the owner's tv22 decision (and a trial-change waiver, or the
  end of the trial). Layer 2 does not start until then; layer 1 can run.
- [x] D7 verdict 6 months after the forward clock starts; one extension to 9 months only if under 100 trades; no early stop.

## 10. Freezing mechanics

1. Owner signs section 9. **Done 2026-10-24.**
2. Build: `walk_forward.py` needs a separate hold length from the label length (5-day label, 30-calendar-day
   hold) and the prod buy rule as a pick mode. Tests first; no live code touched.
   **Built 2026-10-24:** `backend/src/swing_trade_ml/brain/five_day.py` (tests `backend/tests/test_brain_five_day.py`).
   Run (backend/): `python -m swing_trade_ml.brain.five_day --from 2023-07-01 --to 2025-01-31`
   (or `python -m swing_trade_ml.brain.walk_forward --protocol fd-protocol-v1 ...`). It refuses unless the tag
   `fd-protocol-v1` is in HEAD's history, this file and the tool are unchanged since the tag, and no report exists yet.
3. Merge this file and the tool change to main; tag that merge commit `fd-protocol-v1`.
4. Run layer 1 once on the confirmation sample. Start the forward clock. No re-runs with changed settings.
5. Any later change is `fd-protocol-v2`; old results stay on record. Output goes to `docs/brain/evidence/fd_v1/`.
