# A8 pause-number check — protocol `pause-check-v1`

Written and committed 2026-10-22, **before** the run. One run. No retuning afterwards.
Diagnostic on development data (`docs/brain/EXPOSURE-LEDGER.md`), not proof.

## Question

Amendment 1, section A8 (tag `evidence-defs-v2`) sets three **provisional** performance-pause numbers:

1. **8 losing finished brain ideas in a row**;
2. **two calendar months below the every-stock baseline, after costs**;
3. **the brain's own book falls 8% from its peak** (before the account-wide 15% halt,
   `MAX_PORTFOLIO_DRAWDOWN_PCT`).

A8 asks, before they are switched on: (i) how often would each pause **by bad luck alone**, and
(ii) does each trigger **before**, and never conflict with, the 15% halt? This run answers both on old
data. It does **not** change any number: the owner decides. No Phase B or trial (prod, 2026-10-14 onward)
data is read.

## Data (all development data)

- Local daily candles of the 49 watchlist stocks (the walk-forward universe), decision days
  **2022-01-03 to 2026-08-14**; outcomes may run to the end of local data (2026-09-07).
- Every idea is scored with the settled strict rule (`replay_scoring.strict_score`: next-day open, +8% /
  -4%, half out at +5%, 15 trading days, real charges and 0.05% slippage a fill).
- **Every-stock baseline**: on each decision day, every stock with a finished strict outcome.
- **Real model stream** (as it would really have been): walk-forward best 5 a day in the two stored
  windows, **2023-07-01 to 2025-01-31** (wf-protocol-v1 period, spent) and **2025-10-01 to 2026-08-15**
  (first walk-forward, spent), same 28-day folds. Each fold's existing `wf_h15_<cutoff>` model (+8% /
  -4% / 15 days) is reused when it is in the local database; otherwise it is trained exactly as
  `walk_forward._train` does (registered, never activated). **Reproduction check:** pooled model ideas and
  average after-cost result must equal the stored JSON (`wf_v1/…json`, `walk_forward_2025-10-01_…json`);
  a mismatch is reported, not hidden.
- Brain pace reference (no new run): the ps12 point-in-time replay brain account made **16 TRADE ideas in
  25 days (0.64 a day)** (`pit_replay/checkpoint_brain.json`); the owner's cap is 5 a day.

## Simulated strategies (fixed)

A strategy picks stocks on real days from that day's every-stock list. Its **edge** is its average
after-cost result per idea minus the every-stock average on the same days.

| Edge per idea (vs every stock) | Meaning |
|---|---|
| -1.0% | clearly bad (about the as-of replay model's gap to random) |
| -0.5% | bad |
| 0 | **no edge: bad luck alone** (random picks; same hit rate and payoff as every stock) |
| +0.3% | genuinely slightly good |
| +1.0% | good |

- An edge other than 0 is made by weighted random choice with weights `exp(theta x outcome)` (a
  deliberate look-ahead **used only to manufacture a strategy of known edge**); `theta` is found by
  bisection so the pooled edge over the whole period equals the target (calibration seed 20261022, 20
  draws). Edge 0 is `theta = 0` (plain random).
- **Pace:** 5 ideas a day (the cap) and 0.64 a day (one idea on a day with probability 0.64, the ps12
  brain pace).
- **Windows:** 12-month paths starting on the first trading day of each month 2022-01 to 2025-08 (44
  starts). A rule "fires within N months" if its fire day is before start + N calendar months.
- **Seeds:** base 20261022; path seed = base + 1000 x edge-index + 100000 x pace-index + 100 x start-index + draw.

### Rules as simulated (the exact reading used)

1. **Losing streak:** finished ideas ordered by exit day (then decision day, then stock); a loss is an
   after-cost result below zero; a result of zero or more resets the count. Fires on the exit day of the
   8th loss in a row. Ideas count whether or not they were bought (A8 counts finished brain ideas).
2. **Two months below every stock:** ideas grouped by **decision** month; the month's average result
   against the every-stock average of the same decision days. Fires when **two consecutive** calendar
   months are both below; the fire day is the last exit day of the second month's ideas (when it is
   known). A month with no idea gives no verdict and breaks the run. (Sensitivity row: any two months, not
   consecutive.) No minimum number of ideas a month (A8 sets none).
3. **Brain book falls 8%:** one account (`portfolio_sim.Book`: capital ladder, sector rule, 1% risk at the
   stop, top 5 a day, NORMAL mode every day, same exits and costs). Fires on the first day the brain book's
   closing value is 8% or more below its own running peak.
   - **Case A:** the brain is the whole account, ₹9,79,792 (paper trial start).
   - **Case B:** the account is ₹9,79,792 split equally between the brain book and a second book of
     zero-edge random picks at 5 a day (a stand-in for the v1 bot).
   - **15% halt:** evaluated on the **whole account's** closing value (as `services/risk.py` does); while it
     is 15% or more below its running peak, neither book buys at the next open. Halt day = first such day.

### Simulations (fixed)

- **Real days (keeps market clustering):** rules 1 and 2 for every edge x pace x 44 starts x 50 draws.
- **Shuffled (no market clustering, the textbook Monte Carlo):** rules 1 and 2; 20,000 sequences per
  edge x pace, each idea drawn independently from the pooled (tilted) every-stock outcomes; a month = 21
  trading days x pace ideas; rule 2 compares each month with the pooled every-stock average.
- **Accounts (rule 3 and the 15% halt):** Case A for every edge x both paces; Case B for brain edges
  -1.0%, 0 and +0.3% at 5 a day; 44 starts x 10 draws each. Pre-declared fallback: if the first 20
  accounts show the account runs would take over 60 minutes, draws drop to 5 per start, and the result
  says so.
- **Real model stream:** rules 1, 2 and 3 (Case A, ₹9,79,792) run once on each window's actual walk-forward
  picks, with the account-wide halt; first fire day of each rule and the halt day are reported.

## Reported per rule

Chance of firing within 3, 6 and 12 months (no edge, and +0.3%); median months to the first false pause
(no edge; "more than 12" when under half the paths fire); how fast it catches -1.0% and -0.5% (chance within
6 months, median months); for rule 3 and the halt: in paths where both fire, how often rule 3 fired first, the
same day, or after; paths where the halt fired and rule 3 never did; and fires of rules 1-3 **after** the
halt day.

## Reading rule (fixed now)

- **False alarm** (no edge, real days, 12 months, 5 a day): under 10% = "rarely by chance"; 10% to 33% =
  "sometimes"; over 33% = "often by chance".
- **Stops a good strategy** (+0.3%, same reading): the same three words.
- **Catches a bad one:** -1.0% fires within 6 months in at least 80% of paths = "catches it quickly";
  else within 12 months in at least 80% = "catches it slowly"; else "may miss it".
- **Order with the 15% halt:** "always before" only if rule 3 fired on or before the halt day in every
  Case A and Case B path where the halt fired; otherwise the count of paths where the halt came first is
  the finding. A **conflict** is a case where a pause and the halt would give opposite instructions; both
  only stop new buys, so a conflict can only be a pause that is made impossible or pointless (fires only
  after the halt already stopped buying); these are counted.
- **Recommendation words** (for the owner; nothing is changed here): "keep" when the false-alarm reading is
  "rarely" or "sometimes" and the catch reading is "quickly" or "slowly"; "consider loosening" when false
  alarms are "often"; "consider tightening" when it "may miss it". The owner decides.
- Development data: a good reading is never called evidence. Nothing in the brain, its rules, the trial or
  `tests/trial_freeze.py` changes because of the result.

## Command

```
cd backend
python -m swing_trade_ml.brain.pause_check --out ../docs/brain/evidence/pause_check
```

## Known limits (stated before the run)

- Survivor bias: today's 49 watchlist stocks; sectors from today's map.
- Accounts assume NORMAL mode every day (no replayed banner), as portfolio_replay; DEFENSIVE days would
  buy fewer and smaller positions, so real books fall more slowly.
- The manufactured edges keep real prices but are not a real strategy; they show how the rules respond to a
  known edge, not what the brain's edge is.
- Case B's other book is random picks, not the real v1 bot.
- Monthly verdicts with few ideas (0.64 a day, about 13 a month) are noisy by nature.

## Result (run 2026-10-22, one run)

- Reproduction: both walk-forward windows reused the stored models and matched the stored results exactly
  (1,980 ideas, -0.204% a trade; 1,075 ideas, -0.104% a trade). Account draws: 10 per start (no fallback).
- No-skill paths firing within 12 months (real days, 5 a day): rule 1 100%, rule 2 88%, rule 3 (Case A) 66%.
  Reading: all three "often by chance" → "consider loosening" (rule 1 also stops a +1% strategy within 3 months
  in 91% of paths).
- Order with the 15% halt: in all 1,218 accounts where the halt fired, the brain book's 8% fall came on an
  earlier day (none same day, after or never). No opposite instructions possible; rule 2 sometimes fires only
  after the halt (up to 24 of 440 accounts).
- Nothing changed: the provisional numbers stay as the owner set them. Full report: `pause_check.md`.
