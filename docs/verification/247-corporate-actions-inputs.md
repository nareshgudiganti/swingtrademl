# #247 Verification: corporate actions, and training-to-scoring input consistency

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev4b_test`. Written 2026-11-24 (IST).
Tests and this note only. No frozen file (`ml/predict.py` and others), model, risk rule or ingestion behaviour was changed.
Nothing sensitive is in this note: no settings, keys, production data or model files were read.

## In plain English

- **Open positions are handled well.** A verified split or bonus on a stock the paper book holds changes the share count
  and every price level (entry, stop, target, trailing high) by the same factor, so shares times price is unchanged. Anything
  unverified, a demerger, a dividend, a fractional result or a real-money position is only flagged for the owner, never changed.
- **Stored prices are not adjusted for splits.** The app keeps candles as traded. Nothing in the app adjusts history; the only
  restatement is when the data vendor re-sends old prices and our upsert logs the correction. So after a split the model inputs
  show a one-day crash (a 2-for-1 split reads as -50%) until the vendor restates history.
- **Short-term guards cover it for a while.** For roughly 20 trading days (held at 15 sessions, gone by 25) after a split the "fell too much in 5 days" and "too
  volatile" filters hold the version 1 scan back from buying (checked for a split and a reverse split).
- **After that the guards forget, the distorted inputs do not.** The 200-day inputs stay off for up to a year. Version 1 scoring
  never looks at corporate actions, so a stock split 40 sessions ago is scored on distorted inputs and can be bought.
  **Gap 1.**
- **The Brain's data check excuses the split day itself.** If a split is on record for a day, a 50% price step that day is not
  penalised. That is right when prices are adjusted, but a step that matches the split means they are NOT adjusted, which is
  exactly the case that distorts the model. **Gap 2.**
- **Training and scoring use the same inputs.** The 53 inputs, their names, order and values for the same stock and day are
  identical in training and scoring (existing test, re-run). A model file whose input list differs from its record is refused when
  it is activated. The known obv_slope difference on production models is documented in the project notes (#272), not repeated.
- **The h05 lane's "parity ok" is a real check with known blind spots.** It proves each input's average and spread today match what
  the model learned, within a quarter of a standard deviation and a 0.75 to 1.25 spread band. It cannot see a wrong input that
  keeps the right average and spread, and it cannot see a problem the training data already contained (such as an unadjusted
  split), because both sides use the same stored candles. Its main (primary) check also swaps `obv_slope` for its training
  formula, so a primary "ok" does not cover how production serves obv_slope; only the production-path (diagnostic) check in the
  same report shows that skew.
- **Identity:** a symbol change keeps the one security and old dates still resolve by the old symbol. A split cannot create a
  security because the identity writer never reads corporate actions (asserted); the test adds a split record only to show nothing else moves.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| a1 | Split or bonus on an open paper position | `services/corporate_action_accounting.py:82-96` (factor, `PRICE_FIELDS`); `db/models/corporate_actions.py` | shares x factor, every price level / factor, value unchanged, idempotent | `test_corporate_action_accounting.py` (2-for-1, 1:1 and 1:2 bonus, 5-for-1, apply twice, cash identity) | Pass |
| a2 | Dividend, demerger, rights, merger, buyback, unverified, fractional, real-money book | same file, `SUPPORTED_KINDS` | flagged for review, nothing changed | `test_corporate_action_accounting.py:130` (parametrised), `:125,:136,:106` | Pass |
| a3 | Split or bonus contamination of stored candles is detected | `services/split_check.py` (ex-date moves over 30%); `services/price_change_detector.py` (restatements and step signatures, report only) | reported, never auto-changed | `test_split_check.py`, `test_price_change_detector.py` | Pass |
| a4 | Vendor restates old prices | `services/ingestion.py:394` logs `CandleCorrection`, invalidates feature snapshots from that bar | correction logged | `test_candle_corrections.py:19,:48` | Pass |
| a5 | Is there an adjusted-price layer? | none in `src` (CLAUDE.md principle 8 describes one as future) | n/a | candles are raw: `test_an_unadjusted_split_reaches_the_model_inputs_as_a_fifty_percent_crash_*` | Not present (stated) |
| a6 | Short-term protection after a split | `strategies/ml_swing.py:84,185-192` (5-day fall, 20-day volatility) | no BUY right after a step | `test_right_after_a_split_the_fall_and_volatility_filters_hold_the_buy_back` (split and reverse split) | Pass |
| a7 | Longer-term protection | `strategies/ml_swing.py:104-107`, `ml/predict.py` read candles and market context only (no corporate-action lookup) | a stock with a split in its feature window is not bought | `test_a_stock_with_a_split_step_in_its_feature_window_*` (strict xfail) | **GAP 1** |
| a8 | Brain data gate on a recorded split day | `brain/modules/m01_quality/quality.py:90-96`; `brain/reader.py:189-200` (`action_days`) | an unadjusted step on a split day is reported | gate passes it as fresh (pinned by `test_brain_m01_quality.py:94`); `test_a_split_sized_step_on_a_recorded_split_day_*` (strict xfail) | **GAP 2** |
| a9 | Which events excuse a big move | `brain/reader.py:189-200` takes every `corporate_action` event, dividends included; `split_check.py` keeps only split or bonus text | split or bonus only | `test_the_brain_excuse_list_holds_every_recorded_corporate_action_*` | Observed (P3) |
| a10 | Identity after a split or a rename | `services/identity/writer.py` (`ensure_for_instrument`, `set_symbol`) | same security | `test_a_symbol_change_keeps_one_security_and_identity_never_reads_corporate_actions`; `test_identity_s1_database.py` | Pass (the rename and old-date lookups are the real checks) |
| b1 | The 53 inputs are exactly this list in this order, and identical in training and scoring (names, order, values) | `ml/dataset.py` (training) vs `ml/predict.py:69-110` (scoring); `ml/features.py` (`FEATURE_COLUMNS`, 53) | identical for the same stock and day; market context joins the previous day | `test_train_serve_parity.py` (5 tests, including ones that must fail when an input or order is wrong) | Pass |
| b2 | Input list pinned per model and refused on mismatch | `ml/registry.py:98-130` (`load_model_artifact`), `MLModel.feature_names` | a differing order or count is refused | `test_the_input_list_of_a_model_file_is_pinned_to_its_row_*` | Pass (at activation) |
| b3 | Is the pin repeated when scoring? | `ml/predict.py:44-51` (`_get_bundle` loads and caches without the row check) | (consistent by construction) | `test_scoring_trusts_the_loaded_file_*` | Observed (P3) |
| b4 | An input the scoring code no longer builds, or a NaN input | `strategies/ml_swing.py:119-121` | no guess | missing input raises (the engine reports that stock and buys nothing); NaN gives no score | Pass |
| b5 | obv_slope train versus serve | project notes, #272 | documented | not repeated | Cited |
| c1 | What the h05 parity check compares | `brain/lanes/h05_parity.py:38-71` (`compare_window`), `h05_protocol.py:80-81` | each input's average within 0.25 sd and spread within 0.75 to 1.25 of the scaler; order against the code | `test_it_passes_an_input_inside_the_thresholds` (0.2 sd; spread 0.8 and 1.2), `test_it_flags_just_outside_the_thresholds` (0.3 sd; 0.7 and 1.3), `test_it_flags_*`; the primary basis swaps `obv_slope` for its training formula (`h05_parity.py:46`), so only the production-path basis (`DIAGNOSTIC_BASIS`) shows the serving skew: `test_the_primary_basis_swaps_obv_slope_*` | Pass |
| c2 | What it cannot see | same | (limits) | scrambled input keeps its average and spread and passes; a split already inside the training data is reproduced and passes | Limits (by design) |

## Gaps (strict xfail, not fixed)

1. **Gap 1 (`strategies/ml_swing.py`, issue #464):** version 1 scoring has no corporate-action awareness; the fall and volatility filters
   forget a split after about 20 sessions while the 200-day inputs stay distorted for up to 252, so a recently split stock can
   be bought on a high score. Fix idea (not applied, needs owner approval): skip a stock with a recorded split or bonus in the
   last ~252 sessions unless its history is verified adjusted (`ml/exclusion_report.py` already tracks that status). The gap test
   replaces `build_features` with a fixed stand-in, so it proves the missing guard, not the distorted score; the distortion itself
   is shown by the features test. The forgetting point is bracketed by `test_the_volatility_filter_forgets_a_split_between_fifteen_and_twenty_five_sessions`.
2. **Gap 2 (`brain/modules/m01_quality/quality.py:90-96`, issue #464):** the gate excuses any recorded split day. A step that matches the
   split on that day shows the stored prices are not adjusted, yet it passes as clean. Fix idea (not applied): keep the excuse
   but add a plain issue, "split step in unadjusted prices", so the Brain downgrades until history is restated. The fix touches
   the reader and M01 together: `assess_bars` receives only the excused dates (`reader.py:189-200`), so the reader would also have to
   pass the split ratio for M01 to compare the step with it.

## Limits and observations for the owner

- The h05 parity result (ok in production) means "today's feature code reproduces the training statistics", not "the inputs
  are right". Corporate actions that were in the training data are part of what it calls normal.
- The row-versus-file input check is not repeated at scoring time (b3); a file changed after activation would not be noticed there.
- Dividends and other non-split events excuse a big move in the Brain's data gate (a9).

## Re-run for this note (dev4b)

`test_corporate_action_accounting.py`, `test_split_check.py`, `test_price_change_detector.py`, `test_candle_corrections.py`,
`test_train_serve_parity.py`, `test_brain_m01_quality.py`, `test_model_artifact_safety.py`, `test_identity_s1_database.py`
and the new `test_corporate_actions_inputs.py`: and the cited suites: **162 passed, 2 xfailed** (the two gaps are strict xfails).
