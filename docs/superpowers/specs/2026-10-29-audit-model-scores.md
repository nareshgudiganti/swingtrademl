# Audit: which model score means what, and where it is used (2026-10-29)

Read-only audit. No code, config, test, protocol or evidence file was changed. Prod was **not** queried
(the `API_KEY` variable was not set in this shell, and `.env` was not read), so every statement about prod
comes from code plus documents that recorded prod earlier. Those are marked **(prod: from docs)** and
should be re-checked with `GET /api/v1/ml/models` and `GET /api/v1/ml/models/active?name=swing_classifier`.

## Summary in plain words

1. **The brain's 15-day ideas are picked using a 5-day score.** Every brain idea in prod gets one number:
   the score of the active `swing_classifier` model (`brain/reader.py:460-496`). In prod that model
   (id 2) answers a different question: "will the close 5 trading days from now be at least 2% higher?"
   (prod: from docs, `five_day_train.py:4-8` and the 5-day protocol §11 C1). The brain then attaches a
   +8% / -4% / 15-trading-day plan to it. That score decides whether a stock counts as "liked" (score ≥ 0.60
   or the accepted buy level), and which liked stocks get the free slots first. This is the known
   tv23/tv24 gap. The code already handles part of it: the screens never call the number a chance, and the
   daily check reports the mismatch at "info" level. The selection itself still runs on the 5-day score.
2. **No part of the code turns a 5-day score into a 15-day chance.** The one place that could do this
   (the "honest chance" display, `brain/score_evidence.py`) refuses any model that was not trained on
   +8% before -4% in 15 days. In prod it shows "not measured". M06, the only real 15-day probability, is
   in trial (shadow) mode. It probably has nothing to run in prod either, because there is no active
   `swing_classifier_barrier` model to build it from (prod: from memory notes, unverified).
3. **That protection depends on today's model, not on the model that made the score.** Brain decisions do
   not store which model scored them. The display picks its evidence from whichever model is active now
   (`api/v1/endpoints/brain.py:79-97`). If `swing_classifier` is ever replaced by a 15-day model, every
   old 5-day score would be shown as a measured 15-day chance. That includes the sealed trial's ideas.
   The same gap lets M09 (the buy-level proposals) and the Observatory mix scores from different models.
4. **"Score 80 or more" means three different numbers.** In Phase B, B1 means the raw score of a 15-day
   barrier model retrained for each test window. In the sealed trial's "Score 80 or more" set, and in the
   owner's own reading rule, it means the prod brain score, which is the 5-day score. If B1 passes, that
   says nothing about the prod rule "look at scores over 80".
5. **Prod settings probably make new models answer the 5-day question.** The labels for new models come
   from `ML_PREDICTION_HORIZON_DAYS / ML_TARGET_RETURN_PCT / ML_STOP_RETURN_PCT`. Prod's v1 bot trades
   +2% / -4% (5-day protocol §11 C2, `services/rules_watch.py:73-84`), but the code defaults are
   15 / 8% / 4%. So prod's settings most likely say 5 days / 2%. If so, the documented droplet command
   (`swingtrade train --name swing_classifier_barrier_cal ... --calibrate`) would build a
   +2%-before-−4%-in-5-days model under a "real question" name. The tv23/tv24 fix itself would then
   produce the wrong model.
6. **Other places mix scores that are not comparable:**
   - The brain scores mid- and small-cap stocks with the large-cap model.
   - `/signals/picks` and `/top-picks` sort different strategies' "confidence" numbers together. One of
     those numbers is a made-up value from the SMA rule.
   - The stock page keeps one score per stock per day, and the last strategy to run wins.
   - The positions page uses the 5-day model's horizon for every position, including the brain's
     15-day positions.
   - Several numbers mix only once M06 is switched on: M07's slot order, the trial journal's sets and
     the brain-position bands would put calibrated chances (about 0.15–0.40) on the same scale as raw
     scores (0.5–0.9).

Nothing below should be "fixed" quietly. Fixes 3, 4, 6 and 8 would change which ideas the sealed 15-day
trial makes or how it is reported, so each one needs the owner's decision.

---

## 1. Every score: who makes it, what it answers, who uses it

"Prod" = what documents say is live. Model *versions* in prod are not known from code; only ids
2 / 16 / 17 are recorded (5-day protocol §11 C1).

### S1–S3. Version 1 tier models: `swing_classifier`, `swing_classifier_midcap`, `swing_classifier_smallcap`

| Item | Detail |
|---|---|
| Producer | `strategies/ml_swing.py:97-129` (scan), `ml/predict.py:69-118` (`predict_instrument`), `ml/predict.py:121-166` (`predict_watchlist`, nightly job `workers/jobs.py:557`) |
| Selection rule | `get_active_model(db, real_question.resolve_model_name(params["model_name"]))` (`ml_swing.py:97`). With `ML_REAL_QUESTION_SUFFIX` empty (the default, `config.py:296`) the name is unchanged. One ACTIVE row per name (`ml/registry.py:50-81`). Each strategy row scores only its own `symbols` (or the watchlist if it has none) (`services/engine.py:39-52`) |
| Prod model | ids 2 / 16 / 17. `label_kind=endpoint`, horizon 5, target 0.02, no stop (prod: from docs, 5-day protocol §11 C1; `brain/five_day_train.py:4`) |
| Target | Close **5 trading bars** later ≥ +2% above the decision-day close. No stop in the label |
| Training label code | The old pre-`dd1f4c4` `build_label`. Current `ml/features.py:372-448` can no longer build it; it can only be rebuilt with `brain/five_day_train.py` (`endpoint_target`) |
| Calibration | **None**. LightGBM with `class_weight="balanced"` (`ml/train.py:41-73`), so the scores run high (0.6–0.9) and are not probabilities |
| Consumers and what they assume | `ml_swing.py:136-143`: BUY at ≥ 0.60 (+0.10 in a NIFTY down-trend). `:157-168`: EXIT at ≤ 0.35. `:211-222`: BUY takes stop/target from **settings** and `horizon_days = model.prediction_horizon_days`; reason text describes the model's own question correctly (`:40-59`). `Signal.confidence` feeds `/signals/picks` (sort, `signals.py:162`), `/top-picks` (≥ 0.70 "safe for real money", `signals.py:195,247,276`), `ml/calibration.py:132-168` (treated as "chance of target before stop within horizon"), `Position.entry/last_confidence`, the decay alert (`execution.py:796-889`), `position_action` text "Still bullish (72% today)" (`execution.py:933-979`), and the score trail bands strong / easing / weak at 0.60 / 0.475 (`services/score_history.py:43-50`). Predictions are graded by `ml/predict.py:272-327` |

### S4. The brain's "model" score (what every prod brain idea uses today)

| Item | Detail |
|---|---|
| Producer | `brain/reader.py:460-496` `model_probability` → `predict_instrument` with `get_active_model(db, "swing_classifier")` (`FALLBACK_MODEL_NAME`, `reader.py:42`) |
| Selection rule | Always the **large-cap** `swing_classifier`, for every stock in the brain universe (watchlist plus every symbol of v1's active auto strategies, mid- and small-cap lists included: `brain/universe.py:19-40`). The real-question switch is ignored here. Buy level = M09's accepted level, else `ML_MIN_CONFIDENCE` 0.60 (`reader.py:490-495`). No bear-market boost |
| Target / label / calibration | Same as S1 (prod: 5-day endpoint, uncalibrated) |
| Consumers and what they assume | `brain/fallbacks.py:117-145`: opinion with `probability=p`, `threshold`, stance `2p−1`; text "The active model (swing_classifier vN) scores this stock 72%; its buy level is 60%". `brain/opinions.py:44-63`: `liked` (p ≥ threshold) and `strength` (= p, used for ranking). `m07_risk/module.py:44-74`: only liked stocks are risk-checked and slots go to the highest `rank_strength` first. **Sizing uses the fixed -4% stop, not the score** (`:29,119`). `m08_decide/engine.py:136-181`: TRADE draft with the **+8% / -4% / 15-day** plan (`policy.py:15-18`); evidence text says "that score ranks stocks, it is not a probability" (`engine.py:113-118`). `m08_decide/module.py:110-117`: the holding score for the strength trail. Stored as `BrainDecision.confidence` with `score_source="model"` (`brain/service.py:309-310`). Downstream: `strategies/brain.py:134-161` (BUY signal confidence), `services/brain_position_score.py` (trail with v1's bands), M09 `learn.py:108,164-166` (by-band report and buy-level proposals), `trial_journal.py:41,77-88,287-296` (top 5 and "Score 80 or more"), Observatory `score_bands.py:99`, `what_would_change.py:69-80` (rank), and the brain API `honest_score` (`api/v1/endpoints/brain.py:88-97`). Frontend: `scoreText.ts` ("Rank N of M today", "not a chance"), `SwingPicks.tsx:42-47` (filters "Ranking 60+ / 70+ / 80+" under the **15 Days** window), `IdeaCard.tsx:143-151`, owner's "score > 80" reading rule |

### S5. M06 combined chance (`source="combined"`)

| Item | Detail |
|---|---|
| Producer | `brain/modules/m06_reason/module.py:96-157`. Default mode **SHADOW** (`:93`): its output is recorded, not used (`brain/runner.py:66-69`) |
| Selection rule | The newest `brain_meta_vN.joblib` in `MODEL_ARTIFACT_DIR` (`artifact.py:59-69`). Base models are pinned by **name and version** from the artifact (`module.py:76-79,104-108`), by default `swing_classifier_barrier` and `swing_classifier` (`training.py:32-42`). Replays only use a combiner created before the replay day (`module.py:100-103`) |
| Target | +8% reached before -4% within **15 trading bars**; a same-day touch of both counts as the stop. `dataset.py:94` calls `build_label` with its **function defaults** 15 / 0.08 / 0.04 (`features.py:372-377`), not settings, so this one cannot drift |
| Inputs | `logit(p_barrier)`, `logit(p_swing)` + 6 context columns (`trainer.py:39-48`). `p_swing` is the 5-day score in prod; here it is only an input to a model that is refit on 15-day outcomes, which is legitimate |
| Calibration | The best of raw_barrier / meta / meta_recent (meta_recent re-anchors the meta score on the last 3 months; `trainer.py:215-222`) by walk-forward Brier, among those with AUC ≥ 0.55. Then the **HonestyMap** (isotonic, capped at the level backed by ≥ 20 different days, `trainer.py:128-162`) |
| Consumers | Liked when the chance ≥ break-even + 0.05 (`module.py:31-38,132`). `pick_opinion` prefers it over "model" (`opinions.py:21`). M08 "Calibrated chance of +8% before −4%" text (`engine.py:103-112`), `score_source="combined"`, API `honest_score.status="calibrated"` (`brain.py:93-94`), trial journal, brain position trail |
| Prod | Probably **absent**: no active `swing_classifier_barrier` in prod (memory 2026-09-28, unverified) means `meta-train` cannot run there. Even if an artifact existed, SHADOW mode keeps it out of decisions |

### S6. `swing_classifier_barrier` (M06 input) and S7. `*_barrier_cal` (the real-question switch)

| Item | Detail |
|---|---|
| Producer | `ml/train.py:287-433` (`swingtrade train`, `cli.py:985-1010`) |
| Target | **Taken from settings** unless passed on the command line (`train.py:314-316`). Recorded on the row (`label_kind`, horizon, target, stop: `train.py:391-406`) |
| Calibration | `--calibrate` → `CalibratedEstimator` (isotonic on the later 25% of training dates, `train.py:132-152`) |
| Consumers | S6: M06 only. S7: `ml_swing` and `predict_watchlist` when `ML_REAL_QUESTION_SUFFIX` is set, with buy 0.40 and exit 0.10 (`real_question.py:24-43`; `config.py:296-298`) |
| Prod | S7 not trained or active (evidence 2026-10-09: "nothing copied to production"). The switch is off |

### S8. As-of replay models `swing_classifier_asof_YYYYMMDD`

`ml/asof.py:42-52` trains with `train_model` and **labels from settings** (not pinned). Scores reach the
brain only in replays (`reader.py:437-458`), against `ML_MIN_CONFIDENCE`. The question these models
answer depends on the `.env` of the machine that trained them.

### S9. Evidence fold models (walk-forward, horizon grid, Phase B, 5-day protocol)

Labels are pinned: `walk_forward.py:235-246`, `horizon_grid.py:215-228`, `phase_b.py:57,1286-1301`
(15 / 0.08 / 0.04), `five_day.py:65-67` + `five_day_train.py` (endpoint 5 / 0.02). None of them is
calibrated (raw LightGBM scores). **Phase B B1 = raw per-window 15-day barrier score ≥ 0.80**
(`phase_b.py:58`; settings decision 3).

### S10. Score-evidence honesty map (display transform, not a model)

`brain/score_evidence.py` plus `score_evidence_barrier.json`: isotonic map and per-band hit rates from
15-day barrier fold models, 2025-10-01 to 2026-08-14 (10,531 stock-days, 12 windows; the 0.80+ band is
40.8% over only 6 windows). It is applied only when `model_matches(active swing_classifier)` is true
(`:110-123`), so prod shows `not_measured`. It never feeds a decision.

### S11. `long_term_value` and S12. `sma_crossover` "confidence"

- S11: `strategies/long_term_value.py:98-175`. The horizon (250 days), target (+30%) and stop (-20%)
  shown in the signal come from **strategy params**, not from the model's stored label (`:163-170`). Buy
  level 0.65. Its `probability` is also written to the stock-score trail (see D6).
- S12: `strategies/sma_crossover.py:98,118,127,146`. This is not a model: 0.5 + (ADX − 20)/100, capped at
  0.85, with fixed 0.7 / 0.3 / 0.0 values. It is stored in `Signal.confidence` next to model
  probabilities.

---

## 2. Mismatches

Classes: **CONFIRMED** = the code proves it. **LIKELY** = needs prod data or is a process risk.
**NOT A DEFECT** = checked and fine.

| # | What | Class | Severity | Prod picks | Sealed 15D trial | Phase B / locked protocols |
|---|---|---|---|---|---|---|
| D1 | Brain 15-day TRADE ideas are selected and given slot priority by the 5-day endpoint score (S4); the +8/-4/15 plan is attached to it | CONFIRMED in code; that the prod model is 5-day is LIKELY (docs say ids 2/16/17 are endpoint/5/2%) | High (known tv23/tv24) | **Yes**, every idea | **Yes**: this is exactly what the trial tests. Any change mid-trial breaks it | No |
| D2 | Brain scores mid- and small-cap stocks with the large-cap model (`reader.py:470`, `universe.py:19-40`); v1 scores the same stocks with tier models. M06 is also trained on the watchlist only (`training.py:22-29`) but serves the whole universe | CONFIRMED in code; whether the mid/small strategy rows are active "auto" with symbol lists is LIKELY (rows 4/5 per 5-day protocol C9) | Medium–High | Yes | Yes (part of what is tested) | No |
| D3 | A stored score does not record which model made it (`db/models/brain.py:82,106`: only `confidence` and `score_source`). The display picks evidence from the **currently** active model (`brain.py:79-97`). M09 by-band and buy-level proposals (`learn.py:108,164-166`) and Observatory bands (`score_bands.py:99`) pool every "model" row whatever the model or question | CONFIRMED | High (dormant until the model changes; then old 5-day scores show as measured 15-day chances, and a proposed buy level would mix two questions) | Indirect (an accepted buy level changes picks) | **Yes**: sealed ideas could be shown or evaluated with the wrong evidence after tv23/tv24 ships | No |
| D4 | "Score ≥ 0.80" means three things: B1 (15-day barrier fold model, `phase_b.py:58`), the trial's "Score 80 or more" set (prod 5-day score, `trial_journal.py:41,86,292`), and the owner's reading rule (prod 5-day score). The 40.8% hit rate of the 0.80+ band in S10 belongs to the 15-day barrier models, not to prod's model | LIKELY (process; no code compares them yet) | High for decisions | Indirect (the owner reads >80) | Yes: the trial's over-80 results must not be read as "B1 confirmed" | **Phase B B1** results must not be carried over to prod's score |
| D5 | Different kinds of score put on one scale: (a) M07 slot order and opportunity strength (`opinions.py:51-63`) mix "combined" (about 0.15–0.40) with "model" (0.5–0.9) in one run, because M06 only scores stocks with full features and the fallback scores the rest. (b) Trial journal top 5 / over 80 accept any `score_source` (`trial_journal.py:288-292`). (c) Brain position bands put calibrated chances against v1's 0.60 / 0.35 bars (`brain_position_score.py:43,128-138` → `score_history.score_band`), and those bars move to 0.40 / 0.10 when the real-question switch is on, while the brain still scores with the raw 5-day model. (d) `/signals/picks` and `/top-picks` sort and filter confidence across strategies: tier models, long-term, the SMA pseudo-number and brain scores (`signals.py:162,195,247,276`) | CONFIRMED. (a)–(c) only take effect once M06 is ON or the switch is set; (d) is active now if SMA or long-term rows are active | Medium | (d) yes (displayed picks, "real money" shortlist); (a) would change slot order | Yes, if M06 were switched on during the trial | No |
| D6 | Stock page trail: one row per stock per day (`db/models/trading.py:435`). Every strategy that scans the stock writes to it and the last writer wins (`engine.py:144-148,166-167`), including long_term_value's 250-day score, all banded with the swing buy level | CONFIRMED | Low–Medium (display) | No | No | No |
| D7 | The positions page uses `get_active_model(db)` with **no name** (most recently activated model of any kind) for every position's `horizon_days` (`portfolio.py:212-213`). Brain 15-day positions get "original 5-day call has passed" after 5 days. Same anti-pattern as the Aug 12 incident; also in `system.py:179`, `cli.py:526`, `predict.py:495` | CONFIRMED (the value 5 is LIKELY) | Medium (display text and "Needs attention") | No (display) | Display only | No |
| D8 | Labels and plan values follow settings, and prod settings are probably 5 days / +2%. `rules_watch.py:73-84,195-199` treats 5 / +2% / -4% as an agreed v1 setting and the 5-day protocol C2 says prod ml_swing targets +2%, while `config.py:278-280` defaults are 15 / 0.08. Consequences: (a) `swingtrade train` without label flags, `train_asof_model` (`asof.py:42-52`) and the 10-09 "turn it on" commands would build **5-day / +2%** models, including under the names `*_barrier_cal` and `swing_classifier_barrier`. (b) `holdings_health.py:47` `PLAN_TRADING_DAYS` would be 5, not the 15 its docstring says. (c) `beginner_views.py:514-516` returns `target_pct` / `stop_pct` from settings next to a brain plan (+8/-4); the frontend reads only `sell_half_pct` today | LIKELY (needs prod settings; names only) | **High** for (a): it is how tv23/tv24 would be built. Medium for (b), Low for (c) | (a) yes, if activated. (b) display | (a) would feed the trial only if activated mid-trial | No locked file; `score_evidence.model_matches` and `brain_daily_check.check_model_question` would at least flag a wrong-question model |
| D9 | A v1 BUY signal mixes questions: the confidence is the model's question, the levels come from settings, `horizon_days` is the model's (5 trading days), the signal is graded in `evaluate_pending_signals` within 5 trading days, but the position runs up to 30 calendar days with a trailing stop. `signal_calibration` (`calibration.py:132-168`) calls the confidence "target before stop within horizon" and by default pools all strategies (SMA pseudo-numbers and brain scores included) | CONFIRMED | Low–Medium (evidence reports) | No | Brain signals are excluded while sealed (`calibration.py:153-162`) | No (fd-protocol-v1 uses its own tool) |
| D10 | Endpoint predictions are graded on **calendar** days plus a 4-day slack (`predict.py:309-318,426-467`); the label was 5 **trading** bars. A "5-day" grade can read a close 6–7 sessions out | CONFIRMED | Low (predictions scoreboard only) | No | No | fd-protocol-v1 C1 cites "as `ml/predict.py` grades endpoint predictions" for the rule `forward_return >= target`; changing predict.py's window does not touch the frozen files, but the owner should know the reference exists |
| D11 | `long_term_value` signal text and levels state 250 days / +30% / -20% from params, not from the model's stored label (`long_term_value.py:163-170`) | CONFIRMED | Low | Advisory only | No | No |
| D12 | When the real-question switch is on, v1 moves to calibrated models but the brain keeps the raw 5-day model and the 0.60 bar (`reader.py:470,495`), while the shared bands and alerts move to 0.40 / 0.10 (`score_history.py:45`, `execution.py:813,933`) | CONFIRMED (dormant; the switch is off) | Medium if switched | Yes when switched | Yes when switched | No |

### NOT A DEFECT (checked)

- **No 5-day score is turned into a 15-day chance anywhere in code.** `score_evidence.present` returns
  `not_measured` with "its score only ranks stocks" unless the active model is barrier/15/0.08/0.04
  (`score_evidence.py:110-141`). The frontend never adds a % sign or the word "chance" to a raw score
  (`scoreText.ts:1-14,59-68`; `honest.tsx:5-20`; `ScoreTrail.tsx:105-106`). M08's evidence line says
  "that score ranks stocks, it is not a probability" (`engine.py:113-118`). Note D3: this protection keys
  on today's model.
- **M06's question is fixed** at 15 / 0.08 / 0.04 through `build_label` defaults (`dataset.py:94`).
  The meta-model's walk-forward, its purge and the honesty map are horizon-consistent
  (`trainer.py:73-97`). Using the 5-day score as an input is fine, because the meta-model is refit to
  15-day outcomes.
- **Phase B B1's score is horizon-consistent**: 15-day barrier fold models with pinned labels
  (`phase_b.py:57,1286-1301`). Its 0.80 is a raw, uncalibrated LightGBM score (a ranking line, not 80%),
  which the settings file already states ("raw per-window model score").
- **5-day protocol tools pin their label** (endpoint 5 / 0.02, `five_day.py:65-67`) and never mix with
  15-day numbers (`five_day.py:749`). Walk-forward and the horizon grid pin theirs.
- **M09 grades every brain idea on the 15-day rule**, and by-band reports use only `score_source="model"`
  (`learn.py:102-108`). Calibrated and raw scores are not pooled there; pooling across model versions is
  D3.
- **v1 decay alerts skip the brain** (`execution.py:1142-1147`), and the brain strategy strips confidence
  from HOLD signals (`strategies/brain.py:162-164`).
- `what_would_change.model_ranks` ranks only "model" rows (`:69-80`).
- **Model rows carry their label** (`db/models/ml.py:61-73`). Old rows were migrated as
  `label_kind=endpoint` (`alembic/versions/20260915_1040_barrier_label_definition.py:31`), and
  predictions copy the model's `label_kind` (`predict.py:190`).

---

## 3. How a model is chosen in prod when several exist

| Path | Which model scores a stock |
|---|---|
| v1 large-cap strategy (row 1) | ACTIVE `swing_classifier` (prod id 2), for the row's `symbols` or the watchlist |
| v1 mid-cap strategy (row 4) | ACTIVE `swing_classifier_midcap` (prod id 16), for that row's `symbols` |
| v1 small-cap strategy (row 5) | ACTIVE `swing_classifier_smallcap` (prod id 17), for that row's `symbols` |
| Same, with `ML_REAL_QUESTION_SUFFIX=_barrier_cal` | `<name>_barrier_cal`. If that model is missing the strategy gives **no signal** (no fallback) |
| Brain (every stock in watchlist + all v1 auto rows' symbols, any tier) | ACTIVE `swing_classifier` only (prod id 2). Ignores tier and the switch. Buy level = accepted M09 level or 0.60 |
| M06 (if an artifact exists and the mode is ON) | Base models fixed by name+version inside `brain_meta_vN` (default `swing_classifier_barrier` + `swing_classifier`). Stocks missing any feature get no M06 opinion, and the fallback model score speaks for them |
| Nightly predictions table | ACTIVE `swing_classifier`, watchlist only (`workers/jobs.py:547-557`) |
| Positions page horizon, `/status`, `swingtrade status`, accuracy-at-horizon | `get_active_model(db)` with no name = **most recently activated model of any name** (D7) |
| Replays | An as-of model passed in explicitly; otherwise no model score (`fallbacks.py:120-121`) |

Uniqueness: one ACTIVE row per name (`registry.py:57-81`). Two ACTIVE rows of the same name can only
happen through a manual database edit; `get_active_model` would then take the newest `activated_at`.

---

## 4. Proposed fixes (proposals only, nothing done)

Each item names what it would touch. Anything that changes which ideas the brain makes, or how the sealed
trial is reported, needs the owner's approval. For the trial it should wait for the evaluation, or start a
new trial version.

| # | Proposal | Fixes | Touches | Owner approval because |
|---|---|---|---|---|
| F1 | Store `score_model` ("name:version") and `score_question` ("endpoint 5d +2%" / "barrier 15d +8/-4") on every `BrainDecision` and `Signal`, as additive columns. Backfill old brain rows from the reason text "The active model (… vN) scores …" | D3 | Brain storage (service `_store`), migration | It changes brain code during the sealed trial; additive only, no decision changes |
| F2 | Choose the score evidence by the **stored** model (F1), never by today's active model. Rows with no stored model get `not_measured` | D3 | `api/v1/endpoints/brain.py:79-97` (display only) | Display of sealed-period ideas |
| F3 | Group M09 by-band / buy-level proposals, Observatory bands and trial-journal sets by `(score_source, score_model)`. Refuse a buy-level proposal that mixes models | D3, D5b | `m09_learn/learn.py`, `score_bands.py`, `trial_journal.py` | `trial_journal.py` is sealed-trial reporting; changing what a set contains needs an exposure-ledger note |
| F4 | The real tv23/tv24: train a 15-day barrier model with **explicit** `--horizon-days 15 --target-return 0.08 --stop-return 0.04` (calibrated), under a dedicated name (e.g. `brain_barrier15`). Point the brain reader at that name. If `score_evidence.model_matches` is false, the brain says WAIT ("no model for the 15-day question"), which is the cautious choice | D1, D4 | `brain/reader.py`, model registry, prod data | **Changes production picks and the sealed 15-day trial.** Do it after the trial evaluation, or as a new trial with its own start date |
| F5 | Make `swingtrade train` refuse to run without explicit label flags (or when the name contains `barrier`/`_cal` and settings are not 15 / 0.08 / 0.04). Pin `train_asof_model` and M06 `train_and_save` (refuse base models whose stored label is not 15 / 0.08 / 0.04 for the barrier input). Correct the 10-09 evidence doc's droplet commands in a **new** note (do not edit the evidence file) | D8a | `cli.py`, `ml/asof.py`, `m06_reason/training.py`, a new doc | Normal approval; no picks change. Should come **before** F4 |
| F6 | Tier routing for the brain: score each stock with the model whose training list contains it, or limit the brain universe to the large-cap model's training symbols | D2 | `brain/reader.py`, `brain/universe.py` | Changes picks → after the trial or a new trial |
| F7 | Never compare different score kinds: rank within the same source (and model) only; refuse to switch M06 ON while the trial is sealed; put brain-position bands on M06's own threshold for "combined" and on fixed raw bars for "model" (not `real_question.min_confidence()`) | D5a–c, D12 | `brain/opinions.py`, `m07_risk`, `brain_position_score.py`, `score_history.py` | M07 ordering changes picks once M06 is on → owner. A "no M06 ON during the seal" guard is the low-risk part |
| F8 | `/signals/picks` and `/top-picks`: only sort and filter `ml_swing` raw model scores against each other. Show SMA / long-term / brain rows in their own groups without a common confidence bar | D5d, D9 | `api/v1/endpoints/signals.py` (v1 API) | Principle 8 (v1 path untouched) |
| F9 | Positions page horizon from the position's own entry signal (`Signal.horizon_days`) or, for brain rows, the decision's `horizon_days`. Never `get_active_model(db)` without a name. Same for `/status` / `swingtrade status` (list all active models) | D7 | `portfolio.py`, `system.py`, `cli.py` | v1 display |
| F10 | Brain items take plan numbers from `DecidePolicy` and v1 items from settings: `holdings_health.PLAN_TRADING_DAYS` by the position's strategy, and `beginner_views` `target_pct` / `stop_pct` from the decision | D8b, D8c | `holdings_health.py`, `beginner_views.py` | Display |
| F11 | Stock-score trail: key it by (stock, day, model), or record only the stock's tier model; skip `long_term_value` | D6 | `score_history.py`, `engine.py`, migration | v1 display |
| F12 | Grade endpoint predictions over trading bars (`trading_horizon_end`) | D10 | `ml/predict.py` | v1 path; note the 5-day protocol's C1 reference to predict.py's rule (the rule `>= target` stays; only the window changes) |
| F13 | Label the 15-day screens honestly until F4: "Ranked by the 5-day model (closes +2% after 5 days); the 15-day plan has no matching model yet", matching `horizons.ts:37-49` | D1 | `SwingPicks.tsx`, `IdeaCard.tsx`, `scoreText.ts` | Customer text during the trial (shows no results, so the seal allows it, but it is owner-visible wording) |
| F14 | Write down, in a new note (not in the locked `phase-b-settings` file), that B1's 0.80 is on 15-day barrier fold models, that the trial's "Score 80 or more" is the prod 5-day score, and that adopting B1 in prod requires the prod score to be the same kind of model (F4) and B1 re-checked on it | D4 | New doc only | Interpretation of Phase B and the trial |

### Prod checks that would settle the LIKELY items (read-only)

1. `GET /api/v1/ml/models` → name, version, status, `label_kind`, `prediction_horizon_days`,
   `target_return_pct`, `stop_return_pct` for ids 2 / 16 / 17, and whether any `swing_classifier_barrier*`
   or `*_barrier_cal` row exists (D1, D8, M06 status).
2. The daily brain check's "Score matches the trade plan" line (`brain_daily_check.check_model_question`)
   already lists every active model's question.
3. The rules-watch check (`services/rules_watch.check`) states the v1 horizon / target settings in its
   detail line (D8), without exposing secrets.
4. `GET /api/v1/strategies` → which rows are active, auto, and their `symbols` (D2), plus whether
   `sma_crossover` / `long_term_value` rows are active (D5d, D6).
5. Is `brain_meta_v*.joblib` present, and what is M06's mode (D5a–c)?

---

## Addendum 2026-10-30 — verified model facts and a new finding (D13)

Appended; nothing above was edited. Full list of corrections: `2026-10-30-model-facts-corrections.md`.

- **Inputs per model (corrects any reading of section 1 that assumes the same inputs):** prod ids 2 / 16 / 17 use
  **37 / 46 / 46** inputs, not the 53 of today's feature builder. **Training stocks:** 49 / 24 / 30 (data to Oct–Nov 2025).
  The 52 / 150 / 104 lists are v1's trading lists; 51 / 150 / 104 trained the *barrier* models, not these.
- **D13 (CONFIRMED, new): the production score is not computed from the inputs the model was trained on.** On
  2026-10-05 (`fcaef35`) `obv_slope` changed from `obv.diff(10) / obv.rolling(20).mean().abs()` to
  `obv.diff(10) / volume.rolling(20).mean()`. Replaying today's code on each model's training data reproduces every
  other input's saved mean and spread but not `obv_slope` (spread ratio 0.52 / 1.53 / 0.10 against 1.01 / 1.00 /
  1.00 with the old formula). On 2026-09-07, rank correlation between production-path and training-basis scores
  was 0.69 / 0.87 / 0.93 and the large-cap top 5 overlapped 3 of 5. Touches: v1 (all three models) and the brain
  (model 2) since the 2026-10-05/06 deploy, so the sealed trial's scores. Severity: Medium–High for score meaning;
  effect on outcomes unknown. **Do not fix quietly:** `ml/features.py` is trial-frozen.
- **F15 (proposal only):** record the formula version with every stored score (extends F1); after the trial
  evaluation decide whether serving should use the training formula for these three models or the models should be
  retrained on the new formula. Either needs the owner.
