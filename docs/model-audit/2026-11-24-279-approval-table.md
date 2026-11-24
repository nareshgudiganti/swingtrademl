# #279 final approval table (5D large cap): for owner sign-off

Written 2026-11-24 (IST). **NOT APPROVED.** Nothing here takes effect until the owner signs below.
Spec under review: `docs/superpowers/specs/2026-11-14-5d-paper-trial-protocol-v1.md`, revision 4,
sha256 `c5cfbaf1c137311c31559a9da7b7cda52004c83f4badc4f8b64e4e0f965f934f` (local, uncommitted).
Background: `2026-11-24-279-decision-brief.md`, `2026-11-24-279-requirements-draft.md`, and the two R0 audits in this folder.

**Legend.** **SIGN** = needs the owner's explicit yes / no / edit. **DELEGATED** = recommended default; the lead may refine it within the stated rule. Signing the table approves every SIGN row as recommended unless edited.

## A. Section H decisions

| # | Decision | Recommended | Need | Why (one line) |
|---|---|---|---|---|
| H-1 | Governing protocol | v1 spec file, frozen by sha256, separate from h05 | **SIGN** | One rule book that cannot be edited, and h05 is not touched |
| H-2 | Reference exit | +2% / −4% from the entry fill, max 5 sessions, stop checked first, both-levels candle = stop, gaps fill at the open | **SIGN** | Same code as h05 and `hz-rules-v1` |
| H-2b | Model-target anchor | Session-5 close ≥ signal close × 1.02 | **SIGN** | R0 verified the training label is exactly this (as-built audit, model 2 "Label") |
| H-3 | Fill window | Session-1 open; record before that session opens, otherwise `recorded_late` | DELEGATED | Mechanical anti-backdating rule |
| H-4 | Slippage, large cap | 10 bps per side | DELEGATED | Conservative assumption, labelled as such |
| H-5 | Cost wording | About 44 bps round trip; h05 text fixed only after its trial | DELEGATED | Code already correct. Text-only correction |
| H-6 | ₹1,00,000 | Reference order size, charges on top | DELEGATED | Matches h05 code |
| H-7 | Pass gates | SELECTION and ECONOMIC only, never merged | **SIGN** | Defines what "success" means |
| H-8 | Momentum | 20-session adjusted return, ties A to Z, comparison only | DELEGATED | Not a gate in v1 (turning it into a gate would be a SIGN) |
| H-9 | Random five | Comparison only, 200 draws, seed 7, pools sorted by symbol | DELEGATED | Fixes the h05 ordering issue in the new trial only |
| H-10 | Matured day | At least 10 **scored** stocks plus at least one finished counted pick | DELEGATED | Matches h05 code |
| H-11 | Minimum evidence | 60-session runs, at least 40 matured days, top 5 short on at most 20% of days | **SIGN** | Sets how much evidence is enough |
| H-11b | Three-run rule | Per verdict: at least 2 PASS, no FAIL, pooled range above 0 | **SIGN** | Sets the final verdict rule |
| H-12 | UNRESOLVED picks | More than 10% warning; more than 20% run INCONCLUSIVE | DELEGATED | Only moves toward caution |
| H-13 | Repeat rule | Blocked D+1..D+4, counts from D+5 | DELEGATED | Same as h05 code |
| H-14 | Separate cap or pattern models | Defer until the 5D large-cap verdict | DELEGATED | Deferral only |
| H-15 | Financial year | April | DELEGATED | Indian FY |

## B. Section 11 clarifications (revisions 2-4)

None changes how a reference outcome is calculated. Recommended: accept all six.

| # | Clarification | Need |
|---|---|---|
| 11.1 | Repeat-rule wording corrected (D+1..D+4 blocked) | DELEGATED |
| 11.2 | Repeat memory resets at each run boundary (from h05 code) | DELEGATED |
| 11.3 | Repeat-blocked picks keep reference rows, excluded from verdicts | DELEGATED |
| 11.4 | Rev 2: market-check meaning, report words, one position per stock, stale marks, sealed-trial access, restart de-duplication | **SIGN** (changes what users see and how portfolios behave) |
| 11.5 | Rev 3: safety result vs top-5 fact, unverifiable prediction blocks entry, three cohorts, publication states, DB-permission read-only h05 | **SIGN** (three cohorts and portfolio behaviour) |
| 11.6 | Rev 4: stale cut-off counted from session 0; unverified at session 5 = final unresolved | DELEGATED |

## C. Requirement sections 1-14

| # | Section | Recommended (short) | Need |
|---|---|---|---|
| 1 | Purpose | Ranking signal for the top 5 large-cap 5D ideas; not an order, not a probability | **SIGN** |
| 2 | Target | As H-2 / H-2b | covered by H-2 |
| 3 | Universe | Fixed 52-stock list; all historical results labelled "selection-biased exploratory evidence"; point-in-time membership required before any promotion claim | **SIGN** |
| 4 | Inputs | One versioned formula for training and serving; a differing serving formula = a new model version. **Open (R0):** candle-to-stored-feature rebuild matched 13 of 200; addendum pending | **SIGN** after the 13/200 addendum |
| 5 | Algorithm | No preference; winner chosen out-of-sample after costs on a pre-fingerprinted config; shared model before per-pattern | DELEGATED |
| 6 | Baselines | Every eligible stock, momentum five, random five, NIFTY 50; incumbent model 2 as served | DELEGATED |
| 7 | Evaluation | As H-7, H-11, H-11b; costs about 44 bps plus a stress case (reported only) | covered by H rows |
| 8 | Score meaning | "Model score NN/100 · 5D ranking signal", never a % chance | DELEGATED (already agreed UI rule) |
| 9 | Market conditions | Model ranks always; the Brain's checks decide entry; per-regime results descriptive only | DELEGATED |
| 10 | Explainability | Verified-version inputs only; score reconciles to the saved prediction (R0: 637 of 637 reproduce exactly from stored inputs) | DELEGATED |
| 11 | Reproducibility | Store artifact sha256, config fingerprint, input-formula version, data snapshot hash, universe hash, seeds, code SHA, library versions, training command. R0 showed models 2/16/17 lack most of these | DELEGATED |
| 12 | Monitoring | Daily coverage, drift and score-distribution checks; no automatic retraining; retrain = new candidate | DELEGATED |
| 13 | Failure behaviour | Not scored or no entry on bad data; UNRESOLVED never zero | DELEGATED (standing principle) |
| 14 | Approval gates | R0-R7; owner at R1, R3 (active models), R4 (one research envelope), R7 (written) | **SIGN** |

## D. Forward gate (R6) and h05 protection: recommended, part of the R1 signature

- One value per matured day; overlapping 5-day holds mean days are not independent (5-day block bootstrap). A 60-session run is about 12 independent blocks.
- Costs: base about 44 bps decides ECONOMIC; stress case reported only.
- No run is extended, shortened or re-run after outcomes are seen. INCONCLUSIVE leads only to a new pre-registered `-v2` run set.
- A PASS is evidence for the owner's R7 decision, never an automatic promotion. One 60-session run is never enough.
- The new trial writes only to its own storage. A CI test proves a SELECT-only role can read approved h05 data and cannot INSERT/UPDATE/DELETE/TRUNCATE h05 tables.
- A corrected `obv_slope` is a separate candidate version, never a silent fix to model 2.

## Sign-off

SIGN rows: H-1, H-2, H-2b, H-7, H-11, H-11b, 11.4, 11.5, sections 1, 3, 4 (after the addendum) and 14. DELEGATED rows are accepted with them unless edited.

Owner: ____________ Date (IST): ____________ Edits: ____________
