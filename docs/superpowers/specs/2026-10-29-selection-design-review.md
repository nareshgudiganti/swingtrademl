# Review of `2026-10-29-selection-model-experiments-design.md` (sl-protocol-v1)

Reviewer: independent quant/ML review, 2026-10-29. I read the design as the developer who must build it
without asking the owner anything. I checked it against the code and the locked documents. No code, protocol,
ledger or evidence file was changed. Line numbers are from the working tree on `change/stock-page-clarity`.

**Overall.** The direction is sound: a cross-sectional "beat the others" label, ranking and money judged
separately, rules fixed before results, and the held-back stocks kept out of training. Before it is signed,
fix three things:

1. Several "reuse as is" claims are wrong in ways that change the build:
   - the trainer has no label or feature hook;
   - the as-of scorer drops any row with a missing input;
   - the Phase B guard does not refuse a dirty git tree.
2. Two rules clash with locked evidence definitions:
   - Stage 2 "PASS" on historical data;
   - spending during Phases A–C.
3. Experiment B quietly changes two things at once.

Findings are grouped as asked: **(c)** needs an owner decision, **(a)** is answered elsewhere in the repo,
**(b)** is minor, with a proposed setting. Within each group the most severe come first.

---

## (c) Owner decisions needed — each changes what gets built

### C1. Stage 2 "PASS / Confirmed historical" clashes with the locked meaning of PASS
- The design says Stage 2 on pre-2021 data gives **PASS / FAIL / INCONCLUSIVE**, shown as "Confirmed
  historical" (design l.239–243, l.258–266).
- Amendment 1 (`evidence-defs-v2`) defines PASS only "on data nobody had looked at (confirmation data, plan
  section 4)" (`2026-10-21-evidence-plan-amendment-1.md` l.31).
- Plan section 4 says "**Nothing before the lock counts as confirmation**"
  (`2026-10-15-evidence-and-pilot-plan.md` l.147).
- Pre-2021 data is untouched, but it is *before* the lock. Under the locked definitions it can be
  "NO WARNING (diagnostic)" at best.
- **Decide one of two:**
  - (i) Approve an amendment (`evidence-defs-v3`) that adds a label for untouched historical data, for
    example "PASS (historical, untouched)". It must never be shown as forward proof.
  - (ii) Downgrade Stage 2 to "NO WARNING (untouched historical)".
- Recommendation: (ii). It keeps the meaning of PASS unchanged across the project.

### C2. Paid data during Phases A–C, and how far the licensing question reaches
- The plan, which is frozen, says: "No spending increase during Phases A–C: no new paid services or
  infrastructure" (plan l.201). Phase C runs to about June–September 2027.
- Releases 2–3 (EODHD $60–100 a month, NSE or CMIE licence; design l.462–463) are therefore blocked unless
  the plan gets a change-log entry (plan section 7).
- R0 (quotes only, no purchase) does not conflict.
- **The licensing question is wider than KEI.** v1 production already fetches these from NSE every day
  (`services/market_feeds.py` l.41–51):
  - bhavcopy (delivery);
  - bulk and block deals;
  - FII/DII flows;
  - the event calendar;
  - corporate actions;
  - ASM/GSM lists.
- The live brain's "results soon" rule (M13) and v1's `services/avoid.py` depend on that NSE event
  calendar. Q8 (design l.522) only asks about the KEI filings job.
- **Decide two things:**
  - whether R0 may lead to a purchase before Phase C ends (needs a plan amendment);
  - whether Q8 covers every NSE feed.

### C3. F1 tests a rule that is already live; what does its result change?
- The brain already blocks new ideas when results are due within **5 trading days**
  (`brain/modules/m13_news/calendar.py` l.4–5, l.25).
- v1 already blacks out results within **3 days** (`services/avoid.py` l.24, `RESULTS_BLACKOUT_DAYS = 3`).
- The design presents F1 as a new rule (l.155–165) and never mentions either one. Both files are frozen
  for the trial (`backend/tests/trial_freeze.py` l.13–38).
- **Decide:**
  - (i) F1 is report-only and its result changes nothing live until after the trial. This is the
    recommendation.
  - (ii) F1 takes no part in choosing the survivor, Stage 2 or Stage 3. The design is silent on what
    happens when F1 passes.
- **Also: F1 cannot run on history with the data we have.**
  - `upcoming_events` is "refreshed every morning rather than accumulated as history" (`db/models/feeds.py`
    l.75–78).
  - Board-meeting notices with past timestamps exist only from when that feed started.
  - So F1 belongs in Release 3, after R1, and it really is (as the design already has it).

### C4. Experiment B changes two things, not one
- S2's training label uses "comparable stocks = the candidate's own training set" (design l.110–111,
  l.490–491).
- So going from S1 to S2 changes **both** the training rows (49 → 177) **and** the reference for the
  label: the median of the 49 becomes the median of up to 177.
- R4 ("S2 vs S1") then cannot say which change helped. That breaks "each one measures exactly one change"
  (l.86–87).
- **Decide:**
  - (i) For every candidate, the label's reference group is **the 49** on that day. The 128 extra stocks
    are labelled against the 49's median. This keeps it to one change, so I recommend it.
  - (ii) Accept the confound and write it into the protocol.

### C5. A second 15-day forward test running next to Phase C
- If Phase B also produces a survivor (`wf-protocol-v2`), Stage 3 means **two** 15-day candidates in forward
  shadow on the same days. That is two chances to pass.
- The plan speaks of "the locked candidate", singular (plan l.150).
- The horizon-lanes draft has **no lane for a second 15-day model**. It only has `h05` and `h10`; `h15` is
  the frozen trial and "not re-implemented as a lane" (`2026-10-26-horizon-lanes-design.md` l.22–27).
- So "reuse the lane shadow store" (design l.368) needs a new lane type, for example `sl15`, in a draft
  that has not been reviewed.
- **Decide one of two:**
  - (i) Only one 15-day forward candidate at a time.
  - (ii) Both run, with the forward significance split between them (2.5% each). This needs a lane-design
    change before C0.

### C6. "Baseline = M06 (15-day)" versus what S0 actually is
- **The owner's wording.** The decisions say "baseline model = M06 (15-day)" (design l.11).
- **What M06 is.** M06 is a meta-combiner of the barrier model, the **5-day swing model** (`logit_swing`)
  and market context (`brain/modules/m06_reason/trainer.py` l.39–48). It is not retrained per fold by any
  locked tool.
- **What S0 is.** The design makes S0 the raw 15-day barrier model retrained per fold (l.486–489).
  - This is the right call. It matches the owner's Phase B decision 3: "The raw per-window model score …
    Not the brain's M06 chance" (`2026-10-22-phase-b-settings.md` l.21).
  - But it is not what the owner's sentence says.
- **Decide (confirm only):** S0 = the raw barrier model per fold, as in Phase B. Rebuilding M06 per fold
  would be a different and much larger build. It would also mix in the 5-day horizon, which A7 forbids.

---

## Top 5 of (a)/(b) — the ones a builder trips on first

1. **(a) The trainer has no label or feature hook. Use the `five_day_train.py` pattern, not
   `walk_forward._train`.**
   - `walk_forward._train` takes only `cutoff`, `horizon`, `target` and `stop` (`brain/walk_forward.py`
     l.235–246).
   - `train_model` always builds the barrier label (`ml/dataset.py` l.121; `ml/features.py` l.372–448).
   - `fit_and_score` hard-codes `FEATURE_COLUMNS` (`ml/train.py` l.120–123).
   - The working pattern for a different label already exists: `brain/five_day_train.py` l.30–63 builds
     the dataset, replaces `target`, then calls `chronological_split` and `fit_and_score`, then registers
     the model as TRAINED.
   - Use that pattern for S1–S3, plus a `symbols` argument.
   - S3's 61 inputs need a parallel `fit_and_score` that takes the column list. Do not edit `ml/train.py`:
     it is the v1 path (principle 8).
2. **(a) The as-of scorer would quietly drop S3's stock-days.**
   - `ml/asof._score_all` keeps only rows with **no** missing input (`ml/asof.py` l.84–86).
   - It builds only `build_features` columns (l.76–83), so company columns would raise a KeyError.
   - Even if it were patched, a missing filing would remove that stock-day. S3 would then be scored on fewer
     days than S2, and "same days and stocks" (l.153) breaks.
   - It needs a new scorer that lets company inputs be missing. Base inputs stay required, as today.
3. **(a) The Phase B guard is not a clean-tree guard, and it is hard-wired to Phase B.**
   - `phase_b.git_commit` *records* a dirty tree; it does not refuse to run (`brain/phase_b.py`
     l.1317–1330, l.1433).
   - Its tags, start date, candidate list and ledger marker are Phase B constants (l.53–55, l.212–215,
     l.1040).
   - The guard the design describes (tag in HEAD's history, frozen files unchanged since the tag, refuse a
     re-run) is `brain/five_day.py` l.903–957. Copy that pattern, and add a `git status --porcelain` refusal.
4. **(b) The first test folds have about 3 months of training data.**
   - The local dataset effectively starts in **September 2022** (`wider_universe_data_check_2026-10-12.md`
     l.44). The reason is the 252-bar inputs: `high_52w_dist`, `volatility_percentile_rank` and
     `vix_percentile_rank`.
   - `train_model` then holds back the last 20% of that for its own test split (`ml/train.py` l.352).
   - With test folds from 2023-01-01 (design l.208–209), the first folds learn from roughly 2–3 months of
     49 stocks. They will be noisy and still count toward R3 and the pooled IC.
   - Proposed setting: first test fold **2023-07-01**, as wf-protocol-v1 and fd-protocol-v1 used.
     2023-07 → 2026-08-15 gives about 41 folds, which still clears ≥ 12 eligible.
   - Change it before signing.
5. **(a) The held-back set has already been used three times, not once.**
   - Phase B runs the reject-set check for **each** of B1, B2 and B3 (`brain/phase_b.py` l.842–853,
     called from `evaluate` for every candidate).
   - After Phase B, the 129 have had 3 uses. S2 and S3 make **5**, not the "untouched except Phase B's one
     check" of design l.274.
   - Correct the count in the protocol and in Q5.

---

## (a) Answered elsewhere in the repo

| # | Design says | What the repo says | Evidence |
|---|---|---|---|
| a1 | S1–S3 reuse `walk_forward._train` / `train_model` | No label or feature hook; use the `five_day_train.py` pattern (Top 5 #1) | `walk_forward.py` l.235–246; `train.py` l.120–123, l.325–329; `five_day_train.py` l.30–63 |
| a2 | Scoring reuses `ml/asof.score_series` | Drops rows with any missing input and builds base inputs only (Top 5 #2) | `ml/asof.py` l.76–86 |
| a3 | "Phase B guard refuses unless the tree is clean" | Phase B records dirty, does not refuse; the `five_day` guard is the reusable one (Top 5 #3) | `phase_b.py` l.1317–1330; `five_day.py` l.903–957 |
| a4 | 129 held-back stocks used once so far | Used 3 times by Phase B; 5 after S2 and S3 (Top 5 #5) | `phase_b.py` l.842–853 |
| a5 | "All 55 model inputs" (l.34, l.91) | `FEATURE_COLUMNS` has **53** | `ml/features.py` l.21–65 |
| a6 | Cost stress: 2× charges and fills **0.1%** worse (l.204, l.400) | The locked ps3 setting is 2× and **0.3%** (`EXTRA_SLIP = 0.003`); ps3 already showed FAIL at the harsh setting (Amendment 1 A9) | `brain/cost_stress.py` l.36–42 |
| a7 | "₹5 crore liquidity line already used in the 2026-10-12 universe check" | That check reported counts from the **delivery feed, April–October 2026 only** (a snapshot of today, not point-in-time), and set no line | `wider_universe_data_check_2026-10-12.md` l.20–21 |
| a8 | r is "split/bonus-adjusted"; gate: "every > 30% gap must match a corporate action" | `candles` are raw. There is no corporate-action history: `split_check.py` reads only `upcoming_events`, which holds one split or bonus event. The look-ahead audit marks corporate actions NOT TESTABLE. So the gate cannot be met with local data | `services/split_check.py` l.1–6, l.20; `split_contamination_latest.md`; `lookahead-audit-2026-10-20.md` item 14 |
| a9 | "No class re-weighting needed" (l.117–118) | The trainer always uses `class_weight="balanced"`. Harmless for ranking, but the sentence is wrong | `ml/train.py` l.69 |
| a10 | Ranking metrics are new code | `brain/ranking_diagnostics.py` already has `daily_rank_correlation` (needs at least 10 stocks a day) and `topk_middle_bottom`. Reuse those functions. **Do not call `run_diagnostics`**: it hard-codes 2023-07-01..2025-01-31 as protected. The ledger now marks that window spent, so the lab may use it, but the reason belongs in the protocol | `ranking_diagnostics.py` l.44–46, l.98–128; `EXPOSURE-LEDGER.md` l.22 |
| a11 | Calibration via `ml/calibrated_model.py` from out-of-fold predictions (l.428–432) | `CalibratedEstimator` is a fit-time wrapper on the late 25% of training. The out-of-fold, day-backed map is `m06_reason/trainer.fit_honesty` (needs at least 20 different days). That file sits in a frozen directory: import it, never edit it | `calibrated_model.py` l.24–37; `trainer.py` l.143–162; `trial_freeze.py` l.13 |
| a12 | Company features as "a separate list" | Required anyway: `ml/features.py`, `ml/market_context.py`, `ml/calibrated_model.py` and `brain/modules/**` are trial-frozen. New inputs go in new files only | `backend/tests/trial_freeze.py` l.13–38 |
| a13 | Board-meeting notices: "history depth unknown" (l.298) | None before the feed started: `upcoming_events` is refreshed, not accumulated; the brain reads it PIT by `created_at` | `db/models/feeds.py` l.75–78; `brain/reader.py` l.208–209 |
| a14 | KEI shareholding is usable under L1/L5 | `company_filing_shareholdings.filed_on` is a **Date**, not a dissemination timestamp, so it fails L1 and L5 as stored. Announcements have `announced_at` (a timestamp) | `db/models/company.py` l.29, l.44–45 |
| a15 | Stage 3 results on the owner screen | Plan section 4: shadow returns are kept out of the Observatory "until the verdict"; only counts at 3 months. The lab tab must apply the same seal to Stage 3 rows. It is not covered by `trial_seal.py`, which only seals the brain trial | plan l.157–159; `services/trial_seal.py` l.9–18 |
| a16 | Earnings-exposure list of open paper positions | Allowed under the seal if it shows symbols and dates only, with no P&L ("counts … symbols" stay; `seal_journal` keeps symbols) | `trial_seal.py` l.126–131 |
| a17 | Bad-bar checks are new | M01 already defines `MIN_BARS = 220`, a spike at 20% and gap limits. Reuse its wording and numbers where they apply | `brain/modules/m01_quality/quality.py` l.25–29 |
| a18 | `feature_set_version` in the config | Exists: `m02_perception.snapshot.feature_set_version()` (12 characters) | used in `brain/data_manifest.py` l.13 |
| a19 | Fold eligibility as wf-protocol-v1 | Correct: `MIN_FOLD_DAYS = 10`, `MIN_FOLD_IDEAS = 20`, `MIN_FOLDS = 12`, `FOLDS_SHARE = 0.6` | `walk_forward.py` l.51–55 |
| a20 | Append-only `lab_runs` "as `experiment_selections`" | The trigger pattern exists | `alembic/versions/20261017_2000_horizon_experiments.py` l.25–35 |

## (b) Minor — a sensible builder can settle these; proposed settings

**b1. The 1.25% bound.**
- `bootstrap_low` hard-codes the 5th percentile (`walk_forward.py` l.175). Locked tools call it
  (wf-v1, Phase B, baselines).
- Do not edit it. Add `selection_lab._block_quantile(values, q)` with the same blocks, 2,000 draws and seed
  7.
- At 2,000 draws, 1.25% is the 25th value, which is fine.
- Bonferroni over 4 is conservative and acceptable. The pass rules inside a candidate are joined by AND, so
  they do not inflate the false-positive rate.
- Say in the protocol that the family is {S1, S2, S3, F1}, and that choosing "the highest lower bound"
  among survivors is selection on development data. It is then corrected by Stage 2 or 3 being one fresh
  test.

**b2. The label, in full.**
- Day 1 and day 15 come from the **market calendar** (NIFTY bars).
- r(s,d) needs the stock's bar on both days. If either is missing, the label is missing and the stock is
  left out of that day's cross-section, and counted.
- open(t+1) is joined from `candles`. The dataset carries only the close-to-close `forward_return`
  (`features.py` l.444–446).
- Compute the cross-section on every eligible stock with a valid r **before** dropping rows with missing
  inputs.
- At least 10 eligible stocks a day (as `ranking_diagnostics`); otherwise no label that day.
- Positive = percentile rank (average ties) ≥ 0.70.
- `label_end_ts` = the bar t+15, the same as the barrier label, so the existing `apply_cutoff` and purge
  stay exact.
- Note for the report: S0's label is measured from today's close and S1's from the next open (audit F-06:
  a small effect).
- Spearman IC on e equals IC on r (the same median is taken off every stock that day). The excess matters
  only for the label and for top-5 excess.

**b3. S0 parity.**
- Every candidate trains exactly like `train_model`:
  - the 20% chronological hold-back at the code default (`Settings.model_fields["ML_TRAIN_TEST_SPLIT"]
    .default`, as `five_day_train` does, so `.env` cannot change it);
  - LightGBM defaults;
  - `calibrate=False`.
- Pass `used_49` **explicitly**. Never use `symbols=None`, which reads today's `is_watchlisted`
  (`dataset.py` l.90–94; `walk_forward.py` l.274–277).
- Model names: `sl1_<cand>_<cutoff>`, registered TRAINED, never activated.

**b4. The liquidity filter.**
- Apply it only to the label's comparable group.
- Score universe = the 49 with at least 220 bars, as Phase B, with **no** liquidity filter on picks, so
  candidates, S0 and every baseline choose from the same pool.
- Turnover = close × volume from `candles`, median of the 20 sessions up to and including d, ₹5 crore =
  5e7.

**b5. The data-quality gate, made concrete.**
- Bad bar: leave out the bar's own row **and every label whose window [d+1, d+15] contains it**. That is the
  15 labels *before* it, not the "next 15" of l.132.
- Inputs that use the bar for up to 252 sessions afterwards are also affected. Report that; do not drop
  them.
- "Stock-year" = calendar year.
- "≥ 200 sessions" = in practice, "has a complete input row" (about 272 bars).
- `build_training_dataset` also needs `min_rows = 300`.

**b6. Corporate actions in E1.**
- There is no action history (a8). List every close-to-open move above 30% on the 177 stocks (audit F-07
  found 5 such moves).
- For each one, leave out that stock's labels whose window spans it, and its rows for the next 252
  sessions.
- Report this as "unadjusted; affected windows removed". Never write "adjusted".

**b7. Company-input timing.**
- t0 = the first session whose 15:30 IST close is after `public_at`.
- Input 5 (reaction) = close(t0+2)/close(t0−1) − 1, minus NIFTY over the same days. It is missing until the
  t0+2 close.
- Inputs 1–3 use the first-filed value for both quarters (L3).
- Input 2 is missing when the year-earlier profit is ≤ 0.
- Use consolidated figures when that filing has them, otherwise standalone, with a flag. Do not switch
  basis inside one comparison.

**b8. Cost stress.** M2 = 2× charges (as written). Also report the locked ps3 settings (fills 0.3% worse,
and both together) as diagnostics, not as pass rules.

**b9. Which baselines code.**
- `services/brain_observatory/baselines.py` and `phase_b.py` implement random-5 differently: one draws from
  the whole pool (`baselines.py` l.72–73), the other only from finished ideas (`phase_b.py` l.403).
- Use **`phase_b`'s functions** so the lab compares like for like with Phase B. They also include
  risk-matched random and NIFTY matched.
- State this in the protocol.

**b10. H1 detail.**
- On the 129: IC and every-stock both measured *within the 129*.
- Use Phase B's ≥ 30-day INCONCLUSIVE gate, and count INCONCLUSIVE as "does not survive", as
  phase-b-settings does.

**b11. Where the tables live.**
- Alembic has no schema handling (`alembic/env.py` has no `include_schemas`).
- Use public-schema tables named `research_*`, the same precedent as the `company_filing_*` rename
  (commit 4de482a).
- Keep them local-only until Stage 3 is approved.

**b12. Stage 2 design** (owner signs it with the protocol, but these blanks must be filled):
- Expanding walk-forward, 28-day folds, first test fold **2016-01-01**, last 2021-07-31.
- Training from the first complete input row, with the same purge.
- **R0's list must add** pre-2021 NIFTY 50, INDIA VIX and the 16 sector indices. All inputs use them
  (`features.py` l.346–365).
- **R0's list must also add** a point-in-time breadth universe. Breadth is built from today's watchlist
  (`market_context.load_market_breadth` l.140–167).

**b13. Inputs built from today's watchlist.**
- The breadth inputs use today's 49 for every stock and date: survivorship, look-ahead audit item 12.
- Record the watchlist set and its hash in `manifest.json` so a later run can detect a change.

**b14. Small factual fixes.**
- 2023-01-01 → 2026-08-15 is about 48 folds, not 44 (l.458). With the later start in Top 5 #4 it is about 41.
- Compute is likely 1–3 hours per candidate, not 30–90 minutes. Inputs are rebuilt for every stock in every
  fold, in both training and scoring (`dataset.py` l.111–129; `asof.py` l.70–83).
- "Nothing in the ledger is edited" (l.280–281) should read "no existing row is edited". New rows are
  required (ledger l.8–9).

**b15. R4 days and survivor ties.**
- R4 uses the days on which both models scored at least 10 stocks.
- Ties on the survivor's IC lower bound: lower model complexity wins (S1 < S2 < S3).
- F1 is never a survivor (see C3).

**b16. R1/R3 per-fold IC.** A fold's IC counts only if the fold is eligible under a19. For the mean,
average per day, not per fold.

---

## Leakage check summary (what was asked)

| Area | Verdict |
|---|---|
| 15-day overlapping labels | Safe if the new label sets `label_end_ts` = bar t+15 and goes through `apply_cutoff`. Fold cutoff = day before the test (`walk_forward.py` l.75; `dataset.py` l.33–39). The cross-sectional median ends on the same bar, so no extra purge is needed |
| Excess label, same-day cross-section | No look-ahead, provided eligibility uses only data up to d. One risk: stocks without a day-15 bar must be listed and left out (b2), not silently dropped |
| Liquidity filter | PIT if computed from candles up to d (b4). The quoted "₹5 crore check" source is not PIT (a7) |
| Company filings | L1–L6 are right in principle. Holes: the reaction input's 3-day window (b7); `filed_on` stored as a Date (a14); the scorer dropping missing rows (a2) |
| Calendar | Use market-calendar days for the label; strict scoring keeps per-stock bars as today (b2). Always `.astimezone(IST).date()` |
| Survivorship / adjustment | Not fixable locally; the gate as written cannot be met (a8, b6) |

## Files read

`brain/walk_forward.py`, `brain/phase_b.py`, `brain/replay_scoring.py`, `brain/portfolio_sim.py`,
`brain/stock_split.py`, `brain/five_day.py`, `brain/five_day_train.py`, `brain/ranking_diagnostics.py`,
`brain/cost_stress.py`, `brain/data_manifest.py`, `brain/modules/m06_reason/trainer.py`,
`brain/modules/m13_news/calendar.py`, `ml/train.py`, `ml/dataset.py`, `ml/features.py`, `ml/asof.py`,
`ml/calibrated_model.py`, `services/brain_observatory/baselines.py`, `services/trial_seal.py`,
`services/split_check.py`, `services/market_feeds.py`, `services/avoid.py`, `db/models/feeds.py`,
`db/models/company.py`, `backend/tests/trial_freeze.py`, the evidence plan, Amendment 1, the phase-b
settings, `EXPOSURE-LEDGER.md`, the horizon-lanes draft, the wider-universe and look-ahead audit evidence.
