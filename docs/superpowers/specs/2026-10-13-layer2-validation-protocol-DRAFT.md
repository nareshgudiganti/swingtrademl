# Layer 2 validation protocol (wf-protocol-l2-v0) — DRAFT, not frozen

Status: draft written 2026-10-13 for owner review. Nothing here is signed off. Once signed off, freeze it the
same way as `wf-protocol-v1`: commit, tag, run once, no changes after seeing a result.

## 1. Why layer 2 exists

Layer 1 (`wf-protocol-v1`) tested only the model's daily top 5. Result on 21 untouched windows: predictive
skill fail, economic value fail. A failing score does not say how the whole brain behaves, because the brain
adds a risk check, sector rules, market mode (NORMAL / DEFENSIVE / NO NEW TRADES), top 5 a day, the score
over 80 reading, sizing and the 15% drawdown halt. Layer 2 asks:

> Does the whole brain, run as an account, make money after costs, stay inside its limits, and beat simple
> alternatives, in more than one kind of market?

## 2. What is tested

The full decision path as an account: daily ideas, risk check, sector cap, market-mode limit, sizing,
stops, half out at +5%, 15-day exit, 15% drawdown halt, capital-ladder limits. Same entry and cost rules as
layer 1 (next-day open, +8% / -4%, costs and slippage).

Not tested here: live order placement, broker behaviour, Kite sessions.

## 3. Comparisons (what the brain must beat)

| Arm | What it is |
|---|---|
| Brain | the full brain path above |
| Rules only | same limits, sectors, sizing, halt, but picks chosen without the model score (random among eligible, many draws) |
| Model only | layer 1 top 5, same account rules, no brain risk or mode logic |
| Do nothing | cash |
| Index | an index fund buy and hold, if candle data exists; otherwise omitted and stated |

"Rules only" is the key arm. If the brain does not beat it, the score adds nothing, and what remains is a
discipline layer. That is still a valid product, but it must be called that.

## 4. Data and samples

| Sample | Dates | Use |
|---|---|---|
| Development | everything used so far, up to 2026-09-08 | build and debug only, never pass or fail |
| Hold-out A | 2026-09-09 to the latest finished day, from prod | pass or fail, run once. **See `docs/brain/EXPOSURE-LEDGER.md`: prod 09-25 to 10-09 was already reviewed, so the clean start is **2026-10-14** (owner said "go ahead", 2026-10-13).** |
| Forward | practice-mode ideas recorded on prod after sign-off | confirmation, feeds the M18 gate |

Hold-out A has about 5 scoreable days on 13 Oct 2026. Do not run the pass or fail until it has at least 40
trading days of finished trades. Until then layer 2 may only be run on development data as a dry run.

Universe: state both runs: today's 49 and prod's real watchlist (currently 10). Results must say which.

Market mode: use recorded history only. Nightly banner recording is a prerequisite (section 8). Until it
exists, layer 2 cannot be run honestly, because earlier replays assume NORMAL every day.

## 5. Decision rule (proposed, owner to confirm)

Each answer is separate. Each needs at least 40 trading days and 60 finished brain trades, otherwise it reads
"insufficient", not "fail".

| Answer | Passes when |
|---|---|
| Money | account ends above start after costs, and average per trade after costs is above zero |
| Beats rules only | brain average per trade beats the middle of the rules-only draws, and the 5th percentile of rules-only draws is below the brain |
| Safety | worst fall stays under 15% in every window; the halt fires correctly if reached; no sector over 25%; no position larger than the ladder limit |
| Honesty | every idea has a stored WHY that matches the decision (WHY integrity check passes) |
| Caution | on days the banner is DEFENSIVE or NO NEW TRADES, the brain bought fewer or smaller positions than on NORMAL days |

Safety, honesty and caution are checks that must pass with no exceptions. Money and beats-rules-only are the
evidence answers.

## 5a. Forward gate: leaving Practice (M18), adopted for now

Status: the owner said on 2026-10-13 "go with your recommendation for numbers or days for now, later we can
change". These numbers are therefore in use for the forward trial but are **not frozen**; change them only
before looking at a result, and record the change here with a date.

This gate is separate from sections 5 and 10. Those judge a one-time replay of the whole brain. This one
judges the live practice ideas the brain records on prod, as they finish, using the trial journal
(`python -m swing_trade_ml.brain.trial_journal --from <trial start>`).

**What counts.** Brain ideas with the word TRADE from live nightly runs, scored by the settled rule (next-day
open, +8% / -4%, half out at +5%, 15 trading days, costs and slippage). Ideas the risk check blocked are
reported next to them but do not count, the same as `COUNT_BLOCKED_TOWARD_GATE = False` today.

**Minimum before any answer.** Both must hold, otherwise the answer is "too early":

| Minimum | Value |
|---|---|
| Sessions in the trial | 15 |
| Finished TRADE ideas | 30 |

**The answer.** Once the minimum is met:

| Check | Passes when |
|---|---|
| Profit | average result per finished idea, after costs, is above 0 |
| Beats random | average daily difference against "every stock the brain looked at that day" is above 0 |
| Safety | no idea broke a settled limit (stop, sector cap, drawdown halt) in the trades recorded |

- **Pass** (all three): the owner may move to "Your OK needed". Each buy still needs the owner's Approve.
- **Behind** (profit or beats-random fails): stay in Practice and keep recording. Nothing is switched off; practice buys nothing.
- **Clearly worse**: if, after the minimum, the average per idea is more than 1 percentage point below "every
  stock", the report says so in its first line, so it cannot be missed.

**What a pass does not mean.** 30 ideas over 15 sessions cannot give a confidence bound; one good or bad
fortnight can decide it. A pass is permission to try manual approval, never evidence for automatic trading.
The automatic stage still needs the full layer-2 pass (section 5).

**Why these numbers.** 15 sessions matches the trade's own 15-day horizon, so at least one full holding
period is seen. 30 is the existing M18 count, kept so nothing about the current gate is loosened; this
section only adds conditions to it.

**Expected wait.** With prod's 10-stock watchlist and a DEFENSIVE market, most ideas end as WATCH, so 30
finished TRADE ideas may take well over 15 sessions. "Too early" for a long time is a correct answer, not a
fault.

## 6. Report must show

Per window: banner mix, ideas, trades, average per trade, account change, worst fall, days below peak. Overall:
the five answers, the arms side by side, results by market type, trades the risk check blocked, the smallest
edge this sample could detect, and the limits (survivor bias, daily candles cannot say which of target or stop
came first, small sample).

## 7. Known limits

- Survivor bias: universe is a current watchlist.
- No history of market mode before it is recorded.
- Daily candles: a bar touching both target and stop counts as the stop.
- Small sample; many market types are unseen.
- A pass does not justify automatic live trading. Manual approval comes first.

## 8. Prerequisites before this can run

1. Record the market banner every night (so replays use real modes).
2. Zero-ideas health alert and an end-to-end test that an idea reaches the "N of 30" counter.
3. Decide the prod watchlist size (10 vs 49), because the brain only sees the watchlist.
4. Rules-only arm built into `portfolio_sim.py` (random eligible picks, many draws).
5. At least 40 trading days of finished trades in Hold-out A.

## 9. Decisions needed from the owner

- [ ] Confirm the five answers and the 60-trade, 40-day minimums.
- [ ] Confirm "rules only" as the arm the brain must beat.
- [ ] Hold-out A stays sealed until 40 trading days exist.
- [ ] Pick the prod watchlist size for the practice run.
- [ ] Confirm that a brain that fails "beats rules only" is relabelled a discipline layer, not a picker.
- [x] Forward gate numbers in section 5a: adopted for now (owner, 2026-10-13), open to change before a result is seen.

## 10. Freezing mechanics

1. Owner signs off section 9.
2. Commit this file and the runner; tag `wf-protocol-l2-v1`.
3. Run once on Hold-out A. No re-runs with changed settings.
4. Later changes become `v2`; old results stay on record.
5. Output goes to `docs/brain/evidence/`, never counted toward the M18 gate.
