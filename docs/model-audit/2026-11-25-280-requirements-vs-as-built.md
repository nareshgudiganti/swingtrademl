# #280 Gap list: approved #279 requirements versus the as-built models

Written 2026-11-25 (IST). **Read-only analysis. Recommendations are proposals only.** Nothing was trained, scored, activated, retired, replaced or deployed, and no new evidence was gathered. Everything below is read from records already in the repo.

- **Baseline commit:** `origin/main` HEAD `954ca84e0dea444f8df961d5c3c06eb112a52b8f`.
- **Approved requirements:** sign-off record `docs/superpowers/specs/2026-11-14-5d-paper-trial-protocol-v1.SIGNOFF.md` (owner approval 2026-11-25 00:57 IST, "approve as recommended") and spec revision 4, sha256 `c5cfbaf1c137311c31559a9da7b7cda52004c83f4badc4f8b64e4e0f965f934f`. Both are on PR #502 (head `b441b230`), not yet on `main` at this baseline. Sections 1 to 14 are the ones in `docs/model-audit/2026-11-24-279-requirements-draft.md`; the owner's approval table is `2026-11-24-279-approval-table.md`.
- **As-built records** (all in `docs/model-audit/`): `2026-11-24-as-built-models-2-16-17.md` (called **AB**), `2026-11-24-score-trace-and-obv-slope.md` (**ST**, with its 637-row addendum **ST-add**), `2026-11-24-research-candidates-10d-15d.md` (**RC**), `2026-11-24-prediction-provenance-proposal.md` (**PP**).

## Plain-English summary (for the owner)

1. **The three models answer the right question.** All three were trained on "will the stock close at least 2% higher five trading days later". That is exactly the target you approved (H-2b). So the purpose and target requirements are met.
2. **Most of the other requirements are not met, because the models predate the rules.** They were built in August 2026, before the signed protocol existed. They have no recorded training command, no data snapshot, no code version and no library versions. Their only evaluation is one 80/20 split with no confidence range. Every one of them scores an AUC of 0.52 to 0.54 (0.50 is a coin flip).
3. **Two known input problems affect what you see today.** (a) One input (`obv_slope`) is computed differently when scoring than when training, so served scores differ from what the models learned (for model 2, 42 stocks cross the 0.60 buy line because of it). (b) 539 of 637 saved model-2 predictions were scored on a day's candle that was not yet final, and a saved prediction can be overwritten by a later re-score.
4. **Models 16 and 17 score far more stocks than they were trained on.** Model 16 learned from 24 stocks but scores 150. Model 17 learned from 30 but scores 104. This is the single biggest gap for those two.
5. **The research files (`fd_h5`, `td_h10`, `wf_h15`) are not usable candidates.** They already failed their own protocols and were never activated. They are evidence, not starting points.
6. **Proposal in one line:** leave 2, 16 and 17 exactly as they are while the sealed h05 trial runs. Use model 2 as the incumbent benchmark. Do not retrain any of them. Any better model must be a brand-new fingerprinted candidate under #219 to #222 and must pass the signed protocol before you are even asked about promotion (R7). **Nothing is decided here; the "Owner decision" column is blank.**

Legend: **Met**, **Partly met**, **Not met**. "Not met" includes "not tested by any record" and says so in the text.

## Model 2: `swing_classifier` v2 (large caps, id 2, ACTIVE)

Facts: 37 inputs, 49 training stocks, 38,516 train rows, trained 2026-08-05 IST, artifact sha256 `d3a73b09...1f19`, ROC AUC 0.528 on its one test split (AB model 2 table).

| # | Requirement | Status | Evidence and gap |
|---|---|---|---|
| 1 | Purpose: top-5 ranking signal, not an order or a probability | Partly met | The brain's score for every stock is model 2 (AB "Runtime scoring path"; ST 1.1: score = round(100 x probability), `services/idea_report.py:222-226`). It works as a ranking. Gap: the 5-day score is shown against a 15-day plan (#341, noted in ST Part 2.4 and exit check) |
| 2 | Target: session-5 close at least signal close x 1.02 | Met | Label is exactly this, no stop (`abc9c0b` `ml/features.py:212-226`; artifact `horizon_days` 5, `target_return` 0.02; AB "Label"). Gap: the required label-parity test does not exist, and today's `ml/train.py` cannot reproduce the label (AB D1) |
| 3 | Universe: fixed 52-stock list, labelled selection-biased | Partly met | Trained on 49, scored on 52 (AB D7, comparison table). Today's lists carry survivorship bias (RC "Universe" note). No point-in-time membership yet (needs #389) |
| 4 | Inputs: one versioned formula for training and serving; completed bars only; write-once inputs | Not met | `obv_slope` served with a different formula since 2026-10-06 (ST 2.1 `ml/features.py:296-300`). 539 of 637 rows scored on a non-final bar, no completed-bar check (ST-add; `ml/predict.py:77`). Predictions overwritten on re-score (`ml/predict.py:192-198`). The artifact holds names only, no formula id (ST Part 3 R5). Partial cover: the write-once `score_ledger` stores scores, not inputs (PP) |
| 5 | Algorithm: no preference, winner proven out-of-sample | Partly met | LightGBM, 400 trees, code defaults, registry `hyperparameters` empty (AB D5). Chosen without a pre-registered config or out-of-sample contest |
| 6 | Baselines: every stock, momentum, random, NIFTY; incumbent model 2 as served | Not met | No baseline comparison in the registry. Model 2 is itself the incumbent baseline for candidates. Trial comparison is the sealed h05 job (not read here) |
| 7 | Evaluation: SELECTION and ECONOMIC, bootstrap, costs | Not met | Only one positional 80/20 split, no embargo or purge, no walk-forward, no confidence interval, no costs (AB "Evaluation recorded", "Split"). Precision 0.284 vs base rate 0.261 |
| 8 | Score meaning: uncalibrated, "ranking signal" | Partly met | Model is uncalibrated, as required (AB "Calibration"). UI wording was not audited here |
| 9 | Market conditions: model ranks always; Brain checks decide entry | Partly met | Model 2 uses only the stock's own candles (ST 1.2), so it ranks in every regime. Brain gating is a Brain rule (CLAUDE.md principle 5). No per-regime reporting exists |
| 10 | Explainability: score reconciles to saved prediction | Partly met | 637 of 637 stored predictions reproduce exactly from stored inputs (ST 1.4). But candles to stored inputs reproduce for only 49 of 637 (ST-add), and no saved KEC example exists (ST 1.3) |
| 11 | Reproducibility: sha256, config fingerprint, formula version, data hash, seeds, code SHA, library versions, command | Partly met | sha256 is pinned (`h05_protocol.py:42-43`) and seed is 42. Missing: code SHA (AB D3, Gap 2), command, data snapshot (Gap 4), LightGBM version (Gap 5), formula version. Training data cannot be rebuilt (candles re-ingested) |
| 12 | Monitoring; no auto-retrain; retrain = new candidate | Partly met | No auto-retrain exists. No daily drift report was found. Registry numbers "v2" are run counters, not lineage (AB "Version identity") |
| 13 | Failure behaviour: not scored, never more aggressive | Partly met | Any NaN input means no score, nothing imputed (ST 1.1 `ml/predict.py:83-88`); no model means no score (AB). Not met: stale or partial last bar is scored (ST-add) |
| 14 | Approval gates R0-R7 | Partly met | R0 evidence now exists (this folder). Activated 2026-08-28 before the gates existed (AB). Its keep/retire decision is the R3 gate this document feeds |

**Recommendation (proposal): KEEP as the active h05 model and as the incumbent benchmark. Do not build on it, do not retrain it, do not patch it in place.** Why: it meets purpose and target, and its stored scores reproduce exactly, so it is a sound yardstick. Its weak spots (AUC 0.53, `obv_slope` skew, partial-bar scoring) are exactly why it should be measured, not extended. A corrected `obv_slope` is a separate candidate version (approval table section D). It is superseded only if a #219 candidate passes the signed protocol and the owner approves at R7. Owner decision: ______

## Model 16: `swing_classifier_midcap` v2 (mid caps, id 16, ACTIVE)

Facts: 46 inputs, **24 training stocks**, 18,152 train rows, trained 2026-08-12 IST, sha256 `633259b0...2a20`, AUC 0.544. Byte-identical to its own v1 (id 15) (AB D6).

| # | Requirement | Status | Evidence and gap |
|---|---|---|---|
| 1 | Purpose: ranking signal | Partly met | Used by the v1 mid-cap strategy and the h05 lane (`h05_models.py:31,169-206`), not by the brain (AB model 16 "Runtime path"). Same uncalibrated-probability caveat as model 2 |
| 2 | Target | Met | Same label as model 2 (AB model 16 "Label"; `7da460c` `build_label` unchanged). Same missing label-parity test |
| 3 | Universe | Not met | Trained on 24 stocks, but local strategy 4 lists **150** (overlap 24). Most scored stocks were never in its training data (AB D7). How the 24 were chosen is not recorded (AB Gap 3). Survivorship label also applies |
| 4 | Inputs | Not met | Same `obv_slope` mismatch (ST 2.2 and 2.3: 69 stocks cross 0.60, served mean probability +6.6 points). Nine context inputs (index, sector, VIX) checked for formula identity only, not data identity (ST 2.4, Gap 8). No completed-bar check |
| 5 | Algorithm | Partly met | Same LightGBM defaults as model 2 (AB). No out-of-sample contest |
| 6 | Baselines | Not met | None recorded. Hit rate at >= 0.60 is 0.358 on a 0.319 base rate, one split |
| 7 | Evaluation | Not met | One positional 80/20 split, no embargo, no costs, no interval (AB) |
| 8 | Score meaning | Partly met | Uncalibrated. UI wording not audited |
| 9 | Market conditions | Partly met | Adds `nifty_volatility_20` and `nifty_trend_regime` inputs (AB). No per-regime results |
| 10 | Explainability | Not met | 98 saved rows (2026-08-17 to 08-21) exist (AB), but no reconciliation was run for model 16 (ST reconciled model 2 only) |
| 11 | Reproducibility | Partly met | sha256 pinned (`h05_protocol.py:48-52`). Training code inferred (`7da460c`), command, data snapshot, library versions missing (AB Gaps 2, 4, 5). Scikit-learn 1.9.0 at training vs 1.9.1 now (AB D10) |
| 12 | Monitoring and retraining | Partly met | No auto-retrain. v2 is a duplicate of v1, so "v2" implies no retrain or improvement (AB D6). v3 (144,228 rows, a larger model) is archived |
| 13 | Failure behaviour | Partly met | Same as model 2: NaN means not scored; partial bars are scored |
| 14 | Approval gates | Partly met | Activated 2026-08-28 before the gates. R3 decision pending (this document) |

**Recommendation (proposal): KEEP unchanged inside the sealed h05 trial; flag as the weakest-grounded of the three; do not build on it; do not retrain it.** Why: the 24-versus-150 universe mismatch means most of its scores are extrapolation, which the trial will then measure honestly. After the trial, and only by owner decision at R3, consider limiting or retiring it for stocks outside its 24. Any mid-cap replacement is a new fingerprinted candidate under #221, only after the large-cap work in #219 and #220 (R4 order). Owner decision: ______

## Model 17: `swing_classifier_smallcap` v1 (small caps, id 17, ACTIVE)

Facts: 46 inputs, **30 training stocks**, 22,734 train rows, trained 2026-08-21 00:04 IST, sha256 `75675a4e...d358`, AUC 0.525 (the lowest of the three).

| # | Requirement | Status | Evidence and gap |
|---|---|---|---|
| 1 | Purpose: ranking signal | Partly met | As model 16 (h05 lane and v1 small-cap strategy, not the brain) |
| 2 | Target | Met | Same label (AB model 17 "Label") |
| 3 | Universe | Not met | Trained on 30, local strategy 5 lists **104** (overlap 30) (AB D7). Selection rule not recorded. Survivorship applies |
| 4 | Inputs | Not met | Same `obv_slope` mismatch (ST 2.3: 3 stocks cross 0.60, top-5 overlap 4 of 5, the mildest effect). The saved `obv_slope` scale is 46.5, so its scaler is dominated by rare extreme rows (ST 2.2; AB comparison table). Context inputs not data-checked |
| 5 | Algorithm | Partly met | Same defaults. No out-of-sample contest |
| 6 | Baselines | Not met | None recorded. Hit rate at >= 0.60 is 0.316 on a 0.292 base rate |
| 7 | Evaluation | Not met | One split, no costs, no interval (AB) |
| 8 | Score meaning | Partly met | Uncalibrated. UI not audited |
| 9 | Market conditions | Partly met | Same context inputs as model 16. No per-regime results |
| 10 | Explainability | Not met | 49 saved rows, all on 2026-08-21 (AB). No reconciliation run |
| 11 | Reproducibility | Partly met | sha256 pinned (`h05_protocol.py:54-58`). Same missing items as model 16 |
| 12 | Monitoring and retraining | Partly met | No auto-retrain. v2 (98,595 rows) is archived (AB). No drift report found |
| 13 | Failure behaviour | Partly met | As model 16 |
| 14 | Approval gates | Partly met | Activated 2026-08-28 before the gates. R3 decision pending |

**Recommendation (proposal): KEEP unchanged inside the sealed h05 trial; treat as a benchmark only; do not build on it; do not retrain it.** Why: its record is the thinnest (lowest AUC, 30-versus-104 universe, smallest saved prediction history), but changing it mid-trial would break the seal. After the trial, owner decision at R3 on limiting it to its 30 stocks or retiring it. Any small-cap replacement is a new fingerprinted candidate under #222, after #219 to #221. Owner decision: ______

## Research files (fd_h5, td_h10, wf_h15)

These are not models 2/16/17 and none was ever activated. All three families share one layout: 53 inputs, LightGBM, uncalibrated, 49 stocks (RC main table). Only a requirement-level view is useful, so the 14 sections are grouped by what the records show.

| # | Requirement | `fd_h5` (21 files, 5D) | `td_h10` (21 files, 10D) | `wf_h15` (20 files, 15D) |
|---|---|---|---|---|
| 1 Purpose | Met in intent (5D ranking). Never served | Not met. 10D is out of scope (research-only, R5 stop) | Not met. 15D is out of scope |
| 2 Target | Met. Label `endpoint`, +2% at day 5, no stop, same as H-2b (RC main table) | Not met. Barrier +6% before -3.5% in 10 days | Not met. Barrier +8% before -4% in 15 days |
| 3 Universe | Partly met. 49 stocks, survivorship caveat (RC) | Same | Same |
| 4 Inputs | Partly met. 53 inputs saved in each file. Whether `obv_slope` in these files used the old or new formula was not stated in RC, so not verified here | Same | Same |
| 5 Algorithm | Partly met. Per-fold walk-forward with embargo = horizon (`brain/five_day_train.py:62`, read not re-run) | Embargo not separately checked (RC) | Embargo unknown (RC) |
| 6 Baselines | Met. Compared with every stock under `fd-protocol-v1` | Met (picks beat every stock in 8 of 21 folds) | Partly met. Verdict covers other files (RC discrepancy 2) |
| 7 Evaluation | Met. 10 of 21 folds predictive, 3 of 17 economic, both FAIL, best-5 average -0.37% a trade (RC Evidence) | Met. Both FAIL, -0.34% a trade | Partly met. 7 of 21 folds FAIL, but the v1 files behind it are missing and the 20 files on disk have no evidence of their own (RC discrepancies 2, 3) |
| 8 Score meaning | Met (uncalibrated) | Met | Met |
| 9 to 10 Market and explainability | Not met. Never served, no explanations | Not met | Not met |
| 11 Reproducibility | Partly met. Tag `fd-protocol-v1` (`271eb1c`), manifest says uncommitted changes (explained, RC discrepancy 7). Library versions and data snapshot not stored | Partly met. Tag `td-protocol-v1` at `45880ac1` | Not met. v2 retrain commit unknown, 130 registry paths dead (RC discrepancy 4) |
| 12 Monitoring and retraining | Not applicable (inactive) | Not applicable | Not applicable |
| 13 Failure behaviour | Not applicable | Not applicable | Not applicable |
| 14 Gates | Partly met. Owner decision "FAILED, stay inactive" 2026-10-26 (RC Status) | Partly met. FAILED and deferred (`CURRENT-STATE.md` line 66); ledger text not updated (RC discrepancy 6) | Partly met. Protocol run FAILED |
| Six planned 15D lab candidates (S0 to S2M) | Not built: no files, no registry rows, runner refuses to start before 2026-12-05 IST, Amendment 3 unsigned (RC) | | |

**Recommendation (proposal): RETAIN AS EVIDENCE ONLY, never as starting points.** Keep the files and the committed evidence. Do not activate, reuse or retrain them. `td_h10` and `wf_h15` are out of scope for the 5D #279 requirements; `fd_h5` already failed and its fold cut-offs (2023-06-30 to 2025-01-10) are tied to that verdict. New 5D candidates are built fresh under #219 (R4 envelope: local machine only, 5D only, at most 6 candidates, each fingerprinted before training, today's 53 inputs plus the corrected `obv_slope` as its own version, LightGBM and logistic regression, momentum comparison). Housekeeping worth doing: repair the 130 dead `wf_h15` registry paths and the `td` ledger wording (RC discrepancies 4 and 6). Owner decision: ______

## Cross-cutting findings that drive the proposals

1. **Same training code is gone.** Today's `ml/train.py` builds a different label (15 bars, +8%/-4%), splits by date with a purge, and cannot reproduce models 2/16/17 (AB D1). This is why "retrain in place" is not an option: it would produce a different model under the old name.
2. **Evidence is thin by design.** One positional split, no embargo, no confidence interval (AB). The signed protocol, not the registry, is where real evidence will come from.
3. **Provenance fix is proposed, not built.** PP adds six nullable columns to `score_ledger` (needs migration approval). Until then a saved score cannot be tied to inputs and model file.
4. **Baseline for any candidate** is model 2 as served (approval table section C row 6), which includes the `obv_slope` mismatch. A candidate that beats it must also say whether it beats model 2 as trained.

## Open questions for the owner

1. Which saved score is "the KEC example" in #226? None exists in the local data (ST 1.3).
2. After the h05 trial ends, should models 16 and 17 be restricted to their training stocks (an R3 decision), or simply left to be measured?
3. Approve the provenance migration in PP, and the sign-off of 11.4 and 11.5 (still unsigned per the SIGNOFF file)?
4. Were prod's artifacts and registry identical to local? Only local copies were hashed (AB D9, Gap 1); no prod access was used here.
