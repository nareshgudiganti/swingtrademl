# #279 Model requirements: first draft of sections 1-14 (5D large cap)

Written 2026-11-24 (IST). **DRAFT, not approved.** This file fills in the 14 E2 sections of #279 with
recommended defaults. Points marked **[R0]** get their facts from the as-built audits
(`2026-11-24-as-built-models-2-16-17.md`, `2026-11-24-score-trace-and-obv-slope.md`) and are updated
when those land. **[OWNER]** marks the few points that need the owner. Everything else is a delegated
default the lead may refine.

Standing constraints, all already approved: h05 sealed (code, data, docs, evidence); 5D first; 10D and
15D research-only through R5; paper only; promotion only by written owner approval (R7); decisions only
move toward caution; modules pure, point-in-time reads bounded by `as_of`.

| # | Section | Recommended answer | Test method |
|---|---|---|---|
| 1 | Purpose | Rank today's eligible large-cap stocks by the chance the session-5 close is at least +2% above the signal close. The output is a **ranking signal** for the top 5 ideas, not a buy order and not a probability | The SELECTION verdict in the signed protocol |
| 2 | Target | Model target: session-5 close ≥ signal close × 1.02 (H-2b). Reference trade for evaluation: +2% / −4% from the entry fill, max 5 sessions (H-2). Both pinned in `hz-rules-v1` (#449) | Unit tests T1-T7 (spec) plus a label-parity test: the training label code equals the protocol definition **[R0]** |
| 3 | Universe | v1: the frozen 52-stock h05 large-cap list. Historical results on it are labelled **"selection-biased exploratory evidence"** because today's list carries survivorship. Point-in-time membership (delistings, new listings, index changes) comes from identity work (#389) and is required before any R7 promotion claim | Report-label test; universe hash stored per run |
| 4 | Inputs | Each input has a definition, source, as-of rule (known at the close of D), missing-data rule (not scored, with reason), and **one versioned definition used in both training and serving**. Any input whose serving formula differs from its training formula makes the model a distinct version (e.g. `obv_slope`, #272) | Per-artifact parity check: training vs scoring definition for every input, mismatches flagged **[R0]** |
| 5 | Algorithm choice | No preferred algorithm. A candidate wins only out-of-sample, after costs, against the baselines in section 6, on a pre-registered fingerprinted config (R4). Simple first: one shared gradient-boosted classifier (as model 2 is **[R0]**) before per-pattern models (#220 deferred, H-14) | Walk-forward with purged, non-overlapping test windows; config fingerprint checked before training |
| 6 | Baselines | Every eligible stock (the SELECTION benchmark), momentum five (20-session adjusted, ties A to Z), random five (200 draws, seed 7, sorted pools), NIFTY 50 for context. The incumbent model 2 as served is the baseline any new candidate must beat | Reproducibility test with shuffled input order |
| 7 | Evaluation | SELECTION and ECONOMIC, never merged; block bootstrap (5-day blocks, 2,000 draws, seed 7). Costs about 44 bps round trip plus a stress case (+30 bps per side, charges × 2) that is reported but never decides. See the "Forward gate" section below for counts and extension rules | Verdict unit tests (`h05_verdict` logic re-implemented in new trial storage) |
| 8 | Score meaning | Uncalibrated. Shown as "Model score NN/100 · 5D ranking signal", never as a chance or a percent probability, until a calibrated version passes its own gate | UI copy test; no "%" next to the score |
| 9 | Market-condition behaviour | The model ranks in every regime. The Brain's market and risk checks (DEFENSIVE / NO_NEW_TRADES) decide entry, and a failed or missing check blocks paper entry. Results are reported by regime, descriptive only | Regime split in reports; blocked-entry test |
| 10 | Explainability | Show only inputs of the verified model version; separate input values from measured contributions; mark missing evidence (#324). The score must reconcile to the saved prediction and model version | Reconciliation test on saved examples (#226) **[R0]** |
| 11 | Reproducibility | Every run stores the model artifact sha256, config fingerprint, input-definition version, data snapshot hash, universe hash, seeds and code SHA. A rerun on the same data gives identical picks and figures | Rerun-equality test |
| 12 | Monitoring and retraining | Daily: coverage, not-scored reasons, input drift against training ranges, score distribution. No automatic retraining. A retrained model is a new candidate, goes back through R4 to R7, and never replaces the old one in place | Drift report test; registry refuses an in-place overwrite |
| 13 | Failure behaviour | Stale candle, missing input, unverifiable prediction or missing risk check means NOT SCORED or no new paper entry, never a fallback that is more aggressive. Missing outcomes stay UNRESOLVED, never zero | Fault-injection tests per case |
| 14 | Approval gates | R0-R7 (decision brief §4). Owner approval at R1 (protocol), R3 (any keep/retire/replace of an **active** model), R4 (research envelope, once), R7 (promotion, written). 10D and 15D stop at R5 unless a separate gate is approved | Gate state recorded on #218 |

## Forward gate (R6) definition (owner item 12)

- **Observation unit**: one value per matured signal day (the day's average), never per pick. Picks
  overlap for up to 5 sessions, so consecutive days are **not independent**. The block bootstrap uses
  5-day blocks for that reason. A 60-session run is roughly 12 independent blocks, not 60 or 300
  observations.
- **Counts per run**: 60 consecutive sessions, at least 40 matured days, top 5 short of picks on at most
  20% of days, more than 20% of picks UNRESOLVED makes the run INCONCLUSIVE.
- **Costs**: base about 44 bps round trip for large cap. The stress case is reported alongside.
  ECONOMIC uses base costs.
- **Three runs**: 3 × 60 sessions, about 9 months of sessions in total. Combine per verdict (G2).
- **Extension rule**: runs are never extended, shortened or re-run after outcomes are seen. If the
  combined result is INCONCLUSIVE, a **new** pre-registered run set can be started only with a new spec
  version (`-v2`), and earlier runs stay in the record.
- **No promise of promotion**: a PASS is evidence for the owner's R7 decision. It is not an automatic
  promotion, and passing after 60 sessions (one run) is never enough.

## h05 protection (owner items 7-9)

- The new trial writes only to its own storage. It reads approved h05 reference data through a
  SELECT-only database role.
- **Required test (build task)**: using that role, a SELECT on approved h05 tables succeeds, and an
  INSERT / UPDATE / DELETE / TRUNCATE on any h05 table fails with a permission error. It runs in CI
  against the test database.
- **Discrepancy register**: every h05 code-vs-doc difference is listed with file:line, which behaviour
  the new trial adopts, and why. Known so far: cost total text (C), "eligible" vs "scored" (matured
  day), random-five pool order, the fixed 09:15 cutoff, plus #342. The full list is in the as-built
  audit **[R0]**.
