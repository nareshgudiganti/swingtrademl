# Evidence plan — Amendment 2 (proposed `evidence-defs-v3`) — DRAFT

Status: **DRAFT for owner sign-off. Nothing changes until the owner signs section 3 and the commit is
tagged `evidence-defs-v3`.** Must be decided **before Phase B starts on 2026-11-09**. Tracker: Atlas → tv7.

Amends: `2026-10-15-evidence-and-pilot-plan.md` (`evidence-defs-v1`) and
`2026-10-21-evidence-plan-amendment-1.md` (`evidence-defs-v2`). Those stay in force; this file only fixes
two things they left loose.

**Rule for this amendment.** It applies only to results produced **after** the tag. Nothing already run is
re-labelled (ps1, ps12 and every walk-forward keep the version they were made with). The live forward trial
(from 2026-10-14) keeps its rules, its freeze and its seal (A4); this file only says *when* it is judged.
Docs only: no code, no tag, no setting is changed by this draft.

---

## R1. One official "rules-only" comparison

**The question it answers:** does the model's score add anything over the brain's rules alone?
Today three different things are called "rules-only":

| # | Where | Definition | What it really answers | Flaw |
|---|---|---|---|---|
| 1 | Amendment 1, A2; `phase_b.rules_only_real` (`brain/phase_b.py:1304-1314`) | whole brain, M06 removed, no model fallback | in practice: "what if we never buy?" | **It can only hold cash** (code trail below). Cash is already its own baseline, so this arm adds nothing and, worse, is labelled as if it were a real choice |
| 2 | ps12 (`brain/pit_replay.py:85, 199-204, 597`) | whole brain, but every stock with a price gets one **flat score equal to the buy level**; the brain's rules, modifiers (sector, setup, events, portfolio), banner and risk gate choose; ties fall to alphabetical order | "brain with the model replaced by *no preference*" — exactly what the model adds | ties are broken alphabetically, so early-alphabet stocks are favoured on tied days; one deterministic run, no spread |
| 3 | Layer-2 draft section 3; `portfolio_sim --rules-only` (PR #59, `brain/portfolio_sim.py:518-700`) | random draws (200, seeds 11-210) from stocks the brain **did not call AVOID** that day, same count a day as the brain bought | "brain's timing and count, but random stock choice inside its non-AVOID list" | the eligible pool is **not model-free**: WATCH / WAIT words come partly from the score (its own limits text, `portfolio_sim.py:529-532`); needs stored brain runs as input; for the trial it is blocked until the seal lifts (`portfolio_sim.py:712`) |

**Code trail for definition 1 (read, not executed).** With M06 out, the REASON step falls back to
`fallbacks.reason` (`brain/fallbacks.py:265`). In a replay with no as-of model it returns nothing
(`fallbacks.py:117-121`), so no stock has a non-modifier opinion. `opinions.pick_opinion` then returns
`None` (`brain/opinions.py:33-36`; modifiers never speak for a stock, lines 7-9, 22, 34). The risk gate skips
every such stock (`modules/m07_risk/module.py:44-46`) and the decision engine says WAIT "No opinion about this
stock today" (`modules/m08_decide/engine.py:139-140`). So `rules_only_real` returns an empty dict every day.
Note: an empty dict is **not** `None`, so Phase B today would print a rules-only row with **0 ideas**, not
`NOT TESTABLE` (`phase_b.py:802-806, 823-827`).

### Recommendation

- **Official rules-only = definition 2 (flat score), run on the point-in-time account (ps12 method).** It is
  the only version that keeps every rule the brain really uses and removes only the model's preference, and
  it is already built, tested and used once (ps12), so Phase B and ps12 read side by side.
- **Reported alongside, without its own pass label: definition 3 (random among non-AVOID, matched count, 200
  draws).** It gives the spread that a single flat-score run cannot, and shows how much the alphabetical
  tie-break matters. Where the two disagree, the report says so in plain words.
- **Definition 1 is retired** as a comparison. "Never buy" is already reported as Cash.

**Exact definition text (to replace the A2 Rules-only row):**

> **Rules-only (official).** The same brain on the same decision days, with the same account, limits, banner,
> risk gate, fills, exits and costs, but the model's score is replaced by one flat score equal to the buy
> level (`ML_MIN_CONFIDENCE` for the run) for every stock that has a price that day, through the reader the
> model fallback already uses (`PointInTimeReader(flat_score=...)`). M06 gives no opinion (it is in shadow
> mode and, on past days, no combiner existed yet). Ties are ordered alphabetically, as in ps12. One run.
> **Supplement (no label):** 200 seeded accounts drawing, each day, as many stocks as the brain bought from
> the stocks the brain did not call AVOID (`portfolio_sim.compare_with_rules_only`, matched count).
> If no flat-score replay is supplied, the report says **NOT TESTABLE** — never 0 ideas and never cash.

**What Phase B needs (described only; no code is changed by this draft):**

1. `phase_b.rules_only_real` must call the flat-score replay instead of `module_ablation.run_variant(...,
   "M06", asof_model=None)`: e.g. run `pit_replay.run_brain_day(..., flat_score=level)` day by day on a
   point-in-time account and collect the TRADE words the risk gate approved. This also removes the runner
   default's known limit "the replay sees today's account" (`2026-10-22-phase-b-settings.md`).
2. `RULES_ONLY_MISSING` text (`phase_b.py:756-758`) changes to name the flat-score replay; an empty result for
   the whole window should read NOT TESTABLE with a reason, not a 0-idea row.
3. Optional: feed the same replay's stored words into `portfolio_sim.rules_only_inputs` for the supplement.
4. Cost: one brain run per day. ps12 took about 2.5 minutes a day, so the 2025-02-01..2026-08-14 window (~380
   trading days) is roughly 16 hours per run. It is resumable (checkpoint files). Plan it before 2026-11-09.
5. Because `phase-b-settings` lists the rules-only default, changing it is a new settings version with its own
   tag (that file's own rule), done **before** the first candidate runs.

## R2. When the blind forward trial (Hold-out A) is judged

Fixed: the trial started **2026-10-14** (owner, 2026-10-13; `trial_journal.TRIAL_START`). Proposed rule,
taken from the layer-2 draft (sections 4-5):

- **Decision window:** the first **40 NSE trading days** from 2026-10-14, counted from the market calendar
  (not from nightly runs, so a missed run never moves the date). Day 40 = **Friday 2026-12-11**.
- **Settling:** ideas from the last decision day are bought at the next open and may run 15 trading days, so
  every trade has finished about 15 sessions later: **earliest evaluation ≈ Monday/Tuesday 2027-01-04/05**
  (session 55 = 2027-01-04; one spare day for the last close to be stored).
- **Minimum trades:** at least **60 finished brain TRADE ideas** (layer-2 section 5) and at least 30 trading
  days with ideas (A1/A5). Below either, the label is **INCONCLUSIVE**, never FAIL, and the seal stays. The
  owner then picks, before anyone looks, a **count-only** next check (proposal: every further 20 trading
  days, decided on the count alone, as Phase C's extension rule).
- **Realism note:** with a 10-stock watchlist and a DEFENSIVE market most ideas end as WATCH, so 60 finished
  TRADE ideas by January is unlikely. INCONCLUSIVE in January would be the honest result, not a fault.
- **Smoke test only:** the existing 15-session / 30-finished-idea gate (layer-2 section 5a,
  `trial_journal.MIN_SESSIONS = 15`) is an operational check that the brain works end to end on paper. It is
  never evidence of skill, never unseals anything and never allows real money (plan section 4).
- **Exposure caveat:** trial results were on display ~2026-10-15/16 to 2026-10-21 and whether anyone looked
  is UNKNOWN (A4, EXPOSURE-LEDGER.md). The evaluation report must carry that caveat on its first line.

**Calendar used** (`backend/src/swing_trade_ml/core/holidays.py`, which says it is compiled from public
calendars, **not the official NSE circular**): holidays skipped 2026-10-20 (Dussehra), 2026-11-10 (Diwali
Balipratipada), 2026-11-24 (Guru Nanak Jayanti), 2026-12-25 (Christmas, only affects the settling date).
**To check before signing:** all four against NSE's 2026 circular; Diwali Laxmi Pujan 2026-11-08 is a Sunday
(Muhurat session only, not counted); 2027-01-01 is assumed a normal trading day. One extra holiday before
2026-12-11 moves day 40 to 2026-12-14.

## 3. Sign-off checklist (owner)

R1 and R2 depend on the still-open tv7 items of the layer-2 draft (section 9), so they are settled in the
same sign-off (rows L2-1 to L2-5).

- [ ] **R1a** Official rules-only = flat score at the buy level on the point-in-time account (ps12 method).
- [ ] **R1b** Random among non-AVOID (200 draws, matched count) reported alongside, without a pass label.
- [ ] **R1c** Literal A2 "M06 off, no fallback" retired (it can only hold cash; Cash is already reported).
- [ ] **R1d** Phase B's rules-only input is changed to R1a before 2026-11-09, with a new `phase-b-settings`
      version and tag; a missing replay reads NOT TESTABLE.
- [ ] **R2a** Hold-out A decision window = first 40 NSE trading days from 2026-10-14 (to 2026-12-11).
- [ ] **R2b** Earliest evaluation ≈ 2027-01-05, after every trade from the window has finished.
- [ ] **R2c** Minimums 60 finished TRADE ideas and 30 trading days with ideas; below them INCONCLUSIVE, seal
      stays, next check by count only (proposal: every 20 trading days).
- [ ] **R2d** The 15-session / 30-idea gate is a smoke test only.
- [ ] **L2-1** Confirm the five answers (money, beats rules-only, safety, honesty, caution) and the
      60-trade / 40-day minimums (layer-2 section 5).
- [ ] **L2-2** Confirm rules-only (as R1a) is the arm the brain must beat.
- [ ] **L2-3** Hold-out A stays sealed until R2's evaluation date and minimums are met.
- [ ] **L2-4** Pick the prod watchlist size for the practice run (10 today vs 49).
- [ ] **L2-5** A brain that fails "beats rules-only" is relabelled a discipline layer, not a picker.
- [ ] Calendar dates in R2 checked against the NSE 2026 circular.
- [ ] Tag `evidence-defs-v3` on the commit that records this sign-off; add a change-log row to plan section 7.
