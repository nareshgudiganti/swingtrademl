# h05 readiness report (2026-10-30; revision 3 section at the end)

Status: **h05 is disabled. Run 1 has not started. The sealed trial and every signed protocol are unchanged.** No model
was retrained, calibrated or activated. This report covers the 12 checks asked for before protocol acceptance.
The revised protocol is `2026-10-30-h05-protocol-v1-DRAFT.md`; corrections are in `2026-10-30-model-facts-corrections.md`.

## Readiness table

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | Full backend suite | **Done, see section 1** | counts below |
| 2 | Correct requirements and audit notes | **Done** | `2026-10-30-model-facts-corrections.md` (6 dated corrections, earlier statements quoted); appended addenda to the model-score audit (new D13, F15) and the score-provenance note; revised protocol. Inputs 37 / 46 / 46, training stocks 49 / 24 / 30, evaluation universes 52 / 148 / 102 kept separate |
| 3 | Training membership on each prediction, reported by group | **Done** | `h05_signals.trained_on_symbol`; report breaks each group into "in training" / "not in training" as a **diagnostic** (no verdict, labelled "not a second chance to pass"). Of the evaluated stocks: large 49 of 52 were in training, mid 24 of 148, small 28 of 102 |
| 4 | Dry-run exclusions explained | **Done** | TMCV (large): `short_history`, 204 bars of the 220 needed. HEG (small): `stale_data`, last candle 2026-09-04 vs signal 2026-09-07. Plus BLUESTARCO and JYOTHYLAB excluded at the universe step (in both mid and small lists). All reach the report: `universe_excluded`, per-group `not_scored_events`, and the markdown |
| 5 | Feature parity, not just names | **Done; one real mismatch found and handled** | Saved scalers vs today's code on each model's own training data: every input reproduced except `obv_slope`, which changed formula on 2026-10-05. The lane's primary score uses the formula the models were trained on; the production-path score is a stored diagnostic. A run refuses to start if parity fails. Section 3 |
| 6 | Freeze artifacts, feature definitions, universe, rules, protocol across all three runs; data advances normally | **Done** | Identity stored at run 1 and compared every day and every run: model sha256, input lists, feature-code sha256, library versions, universe hash, protocol hash. Daily data is not hashed as one block: each day stores its own provenance (NIFTY last session, bar counts, a fingerprint of that group's signal-day bars); each outcome stores its window sessions and bar fingerprint |
| 7 | Separate reference prices; verify maturity | **Done** | Label: signal close → close of session 5. Trade: entry fill → exit. Tests: both pending with 4 sessions, final with 5; an expiring trade exits on the label's day; a session-6 candle is never read; an early exit is final while the label is pending; label YES while the trade loses |
| 8 | Missing-model behaviour | **Done, one rule** | Any failed frozen check for any group stops the **whole lane** for that signal day; the reason is saved as an event; no replacement model is ever used; it resumes only when identities match again; missed days are listed in the report. Tested |
| 9 | Execution realism | **Done (proposal)** | Slippage per side 10 / 20 / 25 bps with a spread-estimate basis, higher-cost sensitivity (+30 bps, charges ×2) stored with every trade and reported; results are labelled hypothetical fixed-rule selections; no filter and none added after outcomes |
| 10 | U1–U4 together | **Done (proposal)** | 60 signal sessions per run; ≥ 40 matured days; 90% block range verdict with INCONCLUSIVE; 2-of-3-runs plus pooled range. Justified by the +1.0% edge needed to beat the losing baseline, daily noise of about 1.0–1.1%, and `n_eff = days ÷ 5`. A 15-day run could only detect edges above ~1.6–1.9% |
| 11 | Reporting | **Done** | No verdict before acceptance (stated); after acceptance the frozen verdict is calculated mechanically when a run is closed and all outcomes have matured. Tested both ways |
| 12 | Merge side effect | **Inspected; separation proposed** | Section 4 |

## 1. Full backend suite

Two complete runs (commands: `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE backend/.venv/Scripts/python.exe -m pytest tests`, Docker Postgres up):

- **Before the hardening changes:** 3,572 passed, 30 skipped, 0 failed (the h05 test files were run separately: all passed).
- **After all changes (final complete run, 246 s):** 3,667 passed, 30 skipped, **1 failed**. The failure was my own older h05 test
  (`test_group_summary_compares_picks_with_every_eligible_stock_and_counts_ambiguous_cases`): its data had 3 stocks a day,
  and the new, intended rule "a day needs at least 10 eligible stocks to count as evidence" correctly dropped those days.
  It failed only because of the change made in this work (nothing predates it). I fixed the test's data; all 96 h05 tests
  now pass. I did not re-run the other 3,572 tests after that test-only fix.

No other failure appeared in either run. The 30 skipped tests are existing skips.
The sealed-trial freeze test and the sealed-result leak tests are in the suite and pass.

## 2. Dry run on the real production files (2026-10-30, local data, nothing stored)

| Group | Universe | Scored | Not scored | In training |
|---|---|---|---|---|
| Large | 52 | 51 | TMCV `short_history` | 49 |
| Mid | 148 | 148 | none | 24 |
| Small | 102 | 101 | HEG `stale_data` | 28 |

## 3. Feature parity detail

| Group | Inputs | Training basis | Production path |
|---|---|---|---|
| Large | 37 | all reproduced, max mean shift 0.031 sd, spread ratio 0.983–1.013 | `obv_slope` fails (spread ratio 0.52) |
| Mid | 46 | all reproduced, shift 0.000, ratio 1.000 | `obv_slope` fails (mean shift 0.40 sd, ratio 1.53) |
| Small | 46 | all reproduced, shift 0.000, ratio 1.000 | `obv_slope` fails (ratio 0.10) |

Cause: `fcaef35` (2026-10-05) changed `obv_slope`'s denominator from the OBV level to the 20-day average volume. The old
formula needs the full stored history; production loads the newest 400 bars. Effect on 2026-09-07 scores: rank
correlation between the two paths 0.69 / 0.87 / 0.93; large-cap top-5 overlap 3 of 5, mid and small 4 of 5.
`ml/features.py` is trial-frozen, so nothing was changed; this is a finding for after the trial (audit D13, F15).

## 4. Merge side effect (`c9d19f2`)

`c9d19f2` ("Merge origin/main into change/stock-page-clarity", 2026-10-30 12:26 IST, parents `6e200af` and `89dfee5`)
contains **exactly two h05 files**, both added by the merge commit itself (absent from both parents):

| File in the commit | Content then | Effect |
|---|---|---|
| `backend/src/swing_trade_ml/brain/lanes/__init__.py` | a docstring | none |
| `backend/src/swing_trade_ml/brain/lanes/h05_protocol.py` | an early draft: constants, a settings class, helper functions; imports only `pydantic_settings` and `core.config` | none: nothing in that commit's tree imports or references `brain.lanes` / `h05` |

Checked at the commit: no importer anywhere in `backend/src`, `backend/alembic` or `backend/tests`; **no migration**, **no
model registration**, **no router entry**; the sealed-trial freeze list does not include the folder. So imports, the
migration chain (single head `f9c3o7m1p5n2`) and startup behaviour are unchanged by that commit. The branch has no upstream,
so the commit is local and unpushed. Everything else I built is uncommitted. The working copy of `h05_protocol.py` now
differs from the committed draft (it is the revision-2 protocol).

### Proposed clean separation (nothing run; no history rewritten; your unrelated work untouched)

1. Make a separate worktree for the lane from current `main`, never a bare `git stash`:
   `git worktree add ../swing-trade-bot-h05 -b feat/h05-lane origin/main`
2. Copy only the h05 files into it (list below), run `backend/.venv/Scripts/python.exe -m pytest tests/test_h05_*.py tests/test_trial_freeze.py`, and commit there as one reviewable change.
3. On `change/stock-page-clarity`, add **one follow-up commit** that removes the two early lane files, so that branch no longer
   carries a partial lane and the two branches cannot collide when both reach `main` (otherwise Git sees the same two
   paths added with different contents):
   `git rm backend/src/swing_trade_ml/brain/lanes/__init__.py backend/src/swing_trade_ml/brain/lanes/h05_protocol.py`
   (a normal commit; `c9d19f2` stays in history). Do this only when you say so.
4. Leave the owner's own uncommitted edits (M07 module, `config.py`, `risk.py`, frontend files) exactly where they are.

### The h05 file set (for the separate branch)

New: `brain/lanes/{__init__,h05_protocol,h05_rules,h05_features,h05_parity,h05_models,h05_service,h05_report,h05_verdict,h05_cli}.py`,
`db/models/lanes.py`, `api/v1/endpoints/h05.py`, `alembic/versions/20261030_1200_h05_lane.py`,
`tests/test_h05_{rules,service,hardening}.py`, and the four docs in `docs/superpowers/specs/2026-10-30-*`.
Two existing files get one additive edit each: `db/models/__init__.py` (register the models) and `api/v1/router.py` (one route include).
Also appended (not edited): addenda in `2026-10-29-audit-model-scores.md` and `2026-10-29-score-provenance-note.md`.

## 5. What is still yours to decide

- Accept or change the protocol (U1–U11), in particular **run length** (60 sessions per run is about 12 weeks; shorter runs
  cannot detect an edge below ~1.3–1.9% per trade), **slippage** and **U11** (score on the inputs the models were trained on).
- Whether the D13 `obv_slope` finding needs action on the live bot and brain; that is outside h05 and waits for the trial evaluation.
- When to wire the daily job and build the owner screen; both wait for acceptance.

## 6. Revision 3 (four further items, same day)

h05 is still disabled, run 1 has not started, the sealed trial and every signed protocol are unchanged, no model was retrained.
Protocol was `h05-protocol-v1-DRAFT-3` here; see section 7 for DRAFT-4.

| # | Item | Result |
|---|---|---|
| 1 | Label: existing weights + training-compatible inputs, not an exact production replay | Printed on every report, in the API and in the hashed protocol. Original `obv_slope` verified against **historical code**: `ml/features.py` at `d2f723d` (and `7da460c`) run on 36 stocks' full history gives inputs identical to the lane's (largest difference 0 over about 35,000 rows per version); test `test_h05_historical_features.py` with a hash-pinned vendored copy. Production scores stay a diagnostic |
| 2 | Separate selection and economic verdicts | Two verdicts per group, never merged; economic is absolute (a negative baseline cannot give it a PASS, tested); combined across runs per group and per type; the report prints the pair and a plain sentence |
| 3 | Reproducible run-length and false-pass support; missing-day rules; cost units; slippage as assumption | `h05_cli power` runs the exact decision procedure on local history (dependence across dates, groups and runs; missed sessions). **The earlier "0.7% per group / 2% any group" is replaced**: random picks give a SELECTION PASS up to 1.7% per group and 1.0–4.5% for any group; ECONOMIC about 0% in this history. 60 sessions gives about 90% power for a +1.0% selection edge. Slippage is labelled an ASSUMPTION; every unit is tabulated; missed sessions are never made up and runs are not extended (U12) |
| 4 | obv_slope incident | `2026-10-30-obv-slope-incident.md`: two periods (old formula on 400 bars until the deploy; new formula since the first confirmed deployment, `f69134a`, 2026-10-06 ~20:29 IST), effect sizes, proof, what stays untouched. Nothing patched, no history rewritten, trial scores and interpretation preserved |
| + | Disabled daily job | `h05_job.run_daily` / `h05_cli daily`: lock, existence check and unique keys against duplicates; waits for data until 09:00 IST next day; missed sessions reported once with a reason; outcomes matured on every pass; run closed after its last session; never starts a run. `register(scheduler)` adds nothing unless enabled and accepted and is **not** wired into `workers/scheduler.py` |

Tests: full backend suite after these changes: **3,693 passed, 30 skipped, 0 failed**. The h05 files hold 121 tests.

## 7. Revision 4 (five pre-acceptance confirmations)

`h05-protocol-v1-DRAFT-4`: collection vs finalisation and unresolved outcomes specified and tested; selections persisted before entry (`recorded_at`, refusal from 09:15 IST of session 1, late rows never simulated); position size and rounding documented and tested identically for picks and baselines; the "market, not the model" wording replaced; zero economic false passes labelled conditional on the simulation; power labelled as the full three-run decision with per-run figures and the injection method. Section 9 and 9b of the protocol document.
