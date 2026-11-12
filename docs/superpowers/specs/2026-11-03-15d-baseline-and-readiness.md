# 15-day lab: baselines and readiness (2026-11-03)

Analysis and readiness check only. **No lab candidate (S0, S1, S2, S0M, S1M, S2M) was run, trained or scored. Nothing was tuned.** No change to prod, `.env`, Kite, the sealed trial, Phase B, the h05 lane or any order path. The held-back 129 stocks were never loaded.

Reproduce: `docs/brain/evidence/baselines_15d/baseline_15d.py` (local database, read-only), output `baseline_15d.json` beside it. Checked against `origin/main` at `1054613` and the tag `sl-protocol-v1` (`6371ea6`).

## Answers in short

1. **The lab can run today as far as the code is concerned.** The runner's own refusal gate returns nothing to refuse for S0 (tag present, frozen code files unchanged, amendment marked SIGNED, all 6 overnight moves over 20% classified, no run or ledger row exists yet). 92 lab tests pass.
2. **The 5 December start is a signed rule, not a code rule.** The runner has no date check at all. Only the text of Amendment 2 holds it back (section C).
3. **One real problem found: the design document the protocol is built on is not on `main` and not in the tag** (section D, item 1). It exists only on the branch `change/stock-page-clarity`, with further uncommitted edits in the owner's working copy. The runner lists it as a frozen file, but because it is missing from the tag, nothing is actually frozen for it, and adding it to `main` later would make the runner refuse. This needs an owner decision before 5 December.
4. **Baselines:** these can only be shown on history *before* the lab's window (2023-07-01 to 2026-08-15) without looking at the evaluation period in advance, so that is what I did. It is one mostly rising year, so treat it as a sense of scale, not as a target (sections A and B).

## A. Baselines (+8% target / -4% stop / 15 trading days, half sold at +5%, entry at next open, costs and 5 bps slippage each way)

Window: decision days 2022-06-24 to 2023-06-27 (the earliest day a stock has the 220 bars the lab asks for, to the last day whose 15-day trade finishes by 2023-06-30). All prices are cut at 2023-06-30 before any return is calculated. Only stocks that qualify as the lab's "reference group" that day are counted (220+ bars of history and median daily turnover of at least Rs 5 crore). Costs are the settled, Zerodha-checked ones in `docs/brain/COSTS-CHECK-2026-10.md`.

| | Large (49 stocks) | Mid (14 stocks) |
|---|---|---|
| Decision days / stock-days | 249 / 11,720 | 245 / 3,144 |
| **Every eligible stock: average result per trade** | **+0.37%** | **+0.04%** |
| Hit the +8% target | 18.0% | 29.6% |
| Hit the -4% stop | 38.9% | 53.4% |
| Ran out of time (15 days) | 43.1% | 17.0% |
| Trade made money | 52.7% | 47.6% |
| Random 5 a day, average per trade (1,000 draws; 5th to 95th percentile) | +0.15% (-0.50% to +0.77%) | -0.41% (-1.03% to +0.23%) |
| Five strongest 20-day risers a day | -0.31% | +0.08% |

By market type (the lab's own rule: a 28-day window is "rising" if the average stock gained more than 3%, "falling" if it lost more than 3%, otherwise "sideways"):

| Market | Large: days / avg per trade / hit target | Mid: days / avg per trade / hit target |
|---|---|---|
| Rising | 73 / **+2.03%** / 31.3% | 113 / **+1.77%** / 44.9% |
| Sideways | 155 / -0.24% / 12.6% | 114 / **-1.23%** / 18.4% |
| Falling | 19 / **-1.28%** / 8.6% | 18 / **-2.16%** / 10.8% |

What this tells us:

- **The market type decides almost everything.** Buying every eligible stock earned +2% a trade in a rising window and lost 1% to 2% in a falling one. A model that scored well on a mostly rising stretch would prove nothing. This is why the lab reports by market type.
- **Mid-cap stocks swing harder.** More targets *and* many more stops, and fewer time-outs, so outcomes are more spread out.
- **Luck alone has a wide range.** Random picks over this year gave anything from -0.5% to +0.8% a trade (large). A single year of about 17 independent trades cannot separate skill from luck, so no model should be judged on a result this size.
- **Already published, same rule, large 49, 2025-02-01 to 2026-08-15** (`ranking_diag/ranking_diagnostics_2025-02-01_2026-08-15.md`, inside the lab window and already public, so quoting it is not a new look): every stock -0.27% a trade, 16% hit rate; random 5 -0.28%; the 5-day score's best 5 -0.14%; average daily rank correlation +0.011. Together with the table above: the same plain "buy everything" baseline swings from +0.37% to -0.27% between years. For mid-caps there is no earlier published baseline.
- **Important about what the lab actually measures.** The lab is **ranking only**: its label is "in the top 30% of that day's stocks" (relative), and Amendment 2 forbids any profit, cost or account figure. The +8/-4 numbers above are context for the later money check that Amendment 2 says a "next step" would need. They are not the lab's pass line, and I did not invent any threshold from them.

Frozen benchmark set (`evidence-defs-v2`): every stock, 200 random-5 accounts, the 5 strongest 20-day risers, NIFTY 50 held, cash. I computed the first three (random-5 uses 1,000 draws, one trade-day in every 15, not 200 accounts). NIFTY and cash are not part of the lab's ranking measures and were not computed.

## B. Label base rates

| | Large | Mid |
|---|---|---|
| Lab label ("beats the day's median and is in the top 30%") share of 1s, pre-window | 30.6% (3,555 of 11,613) | 30.4% (928 of 3,053) |
| Target barrier hit (+8% before -4%), every eligible stock | 18.0% | 29.6% |

The lab's label share is about 30% by design, so an always-"yes" guesser is right 30% of the time. Whether it holds when the model is trained is for the lab to show.

**Lab-window structure (counts only, no returns or labels looked at), 2023-07-01 to 2026-08-15, 775 trading days:**

| | Large | Mid |
|---|---|---|
| Stocks with price data | 49 of 49 | 14 of 14 |
| Reference stocks on the thinnest day (the lab needs at least 10) | 49 | **14** |
| Days with too few reference stocks (no labels) | 0 | 0 |

Mid has no safety margin: it has 14 stocks and the lab drops a day if fewer than 10 qualify. Today all 14 qualify every day, so no day is lost. The group is derived at run time from the **active** local `swing_classifier_midcap` model (id 16, 24 training stocks) minus the held-back set. If anyone activates a different mid-cap model on the laptop before the run, the group changes. The 14 today: BHEL, BSE, COFORGE, DIXON, IDFCFIRSTB, LAURUSLABS, MARICO, MFSL, MOTILALOFS, NAUKRI, PAYTM, POLYCAB, POWERINDIA, SUZLON. PAYTM has one flagged overnight move over 20% (classified).

## C. Why the six runs are locked to "not before 2026-12-05"

Quoted from the signed Amendment 2 (`2026-11-02-evidence-plan-amendment-2.md`, signed 2026-11-02, tag `sl-protocol-v1`):

> "**Start no earlier than 2026-12-05**, after Phase B's lock date (2026-12-04). Phase B runs unchanged."

and the reason section:

> "The plan has no phase for the 15-day selection lab ... After Phase B it allows only Phase C or the December review. This amendment lets the lab run, offline, after Phase B, under limits that keep Phase B, the sealed trial and the live brain exactly as they are."

Owner decision A2-1: "The lab may run after 2026-12-05 ...". The design document (rev 3) adds the intent: sign before 9 Nov "so Phase B's results cannot shape these rules", and keep Phase B's three candidates (9 Nov to 4 Dec, locking `wf-protocol-v2` by 4 Dec) "untouched and separate", since both use the same development data.

**Plain verdict: it is a hard rule by owner signature, but it is a scheduling rule, not a technical or data one.** Nothing in the code enforces it (`selection_lab_run.py` has no date check; `refusal_reasons` has no date input). Nothing is missing that would make an earlier run fail. The reason is ordering: Phase B finishes and locks first, so neither phase can influence the other. Running earlier would need a new written amendment from the owner; I would not treat the date as optional.

**What can safely be prepared before 5 December without breaking that rule** (none of it runs a candidate):

1. Resolve the frozen-document problem in section D, item 1 (an owner decision, then a commit).
2. Rehearse the data path and the refusal gate read-only (done today; repeat on 4 Dec).
3. Time one fold's training in a scratch database, not the real one, to estimate total run time and disk (about 41 folds per candidate; not measured, since training would register models).
4. Prepare a clean checkout of `main` for the real run (the runner refuses a dirty tree, and the owner's working copy is dirty).
5. Pre-write the incident-note template for the "technical rerun" rule and the plain-English reading guide for the results.

## D. Readiness checklist, verified against the code and repository today

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | **Frozen design document (rev 3) is in the tag and on `main`** | **MISSING, owner decision** | `selection_lab_run.py` lists `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` as frozen, but `git ls-tree sl-protocol-v1` and `origin/main` do not contain it. It is only on `change/stock-page-clarity` (commit `6e200af`), and the working copy has further uncommitted edits. If it is committed to `main` after the tag, `git diff sl-protocol-v1 -- <file>` lists it and the runner refuses ("differs from the tagged version"). Options for the owner: (a) move the tag to a commit that includes the final spec (allowed in principle, since no candidate has run and the ledger has no `sl-protocol-v1` row, but it re-signs the freeze); (b) leave the spec out and accept that the run is not reproducible from the tag alone; (c) remove it from `FROZEN_FILES`, which is a code change and so a protocol change. I did not pick one. |
| 2 | Tag `sl-protocol-v1` exists and is in `main`'s history | Done | tag on `6371ea6`; runner `git_state` reports tag merged into HEAD |
| 3 | Frozen code files unchanged since the tag | Done | `selection_lab.py`, `selection_lab_run.py`: no diff against the tag |
| 4 | Amendment 2 signed marker | Done | `docs/brain/evidence/sl_v1/EVIDENCE_PLAN_AMENDMENT_SIGNED.md` contains SIGNED (in force once merged; it is on `main`) |
| 5 | Overnight moves over 20% classified for all lab stocks (49 + 128 + mid 14) | Done | 6 flagged in 177 stocks (one in the mid 14, PAYTM), 6 on file (real gap, verified error, unresolved), 0 unclassified |
| 6 | Locked stock split file and hash | Done | `docs/brain/evidence/stock_split/`; `load_split` verifies the hash; held-back set asserted absent from every list |
| 7 | Price data for all lab stocks, no gaps in the lab window | Done | 177 of 177 stocks loaded, candles 2021-08-05 to 2026-09-08; 0 days short of 10 reference stocks, large and mid |
| 8 | Mid group source: ACTIVE local `swing_classifier_midcap` | Fragile | present (id 16, 24 stocks); the group is rebuilt from it at run time, so changing the active model changes the group; archived id 19 has 150 stocks. Do not activate another mid-cap model on the laptop before the runs |
| 9 | Lab code and tests | Done | 6 test files, 92 passed (Docker Postgres on port 5433 confirmed with real queries) |
| 10 | Exposure ledger row written automatically before scoring | Done in code | `add_ledger_row`; 0 `sl-protocol-v1` rows today (nothing has run) |
| 11 | No earlier run or attempt on file | Done | no `sl1-*` folders under `docs/brain/evidence/sl_v1/`; ledger has none |
| 12 | Comparison order enforced (S1 after S0, S2 after S1, mid alike) | Done in code | `COMPARE_WITH`; the runner refuses a candidate whose comparison result is missing |
| 13 | Clean, committed tree for the run | Not yet | the owner's working copy has uncommitted changes (the runner refuses when dirty). Use a clean worktree of `main` on the day |
| 14 | Start date 2026-12-05 | Not before | policy only (section C); no code guard |
| 15 | Run time and disk estimate | Unknown | ~41 folds x 6 candidates; each fold trains a model and registers it TRAINED. Not measured |
| 16 | Dry-run record from 2 Nov | Not verifiable | my notes say the data path was rehearsed on 2 Nov; I found no file in the repository recording it |
| 17 | S2r, S3 | Intentionally not built | S2r only if the owner adds it in writing; S3 blocked until company-data timestamps and licensing are verified |
| 18 | Better-inputs proposal B1 (PR #132) | Not needed for the six runs | it concerns later models; still waiting on owner answers P1 to P3 |
| 19 | After-lab "money check" (cost-inclusive picks), forward slot rule | Not built, not authorised | Amendment 2 grants neither; the baselines in section A are inputs for whoever designs it |

## What I changed

- This note; `docs/brain/evidence/baselines_15d/baseline_15d.py` and `baseline_15d.json`.
- One row in `docs/brain/EXPOSURE-LEDGER.md` recording that the pre-window 2022-06-24 to 2023-06-30 prices were looked at (no model) and that the lab window was only counted, not read for outcomes.
