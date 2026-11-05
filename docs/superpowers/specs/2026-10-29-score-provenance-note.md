# Score provenance note — what "score" and "0.80" mean, and what the sealed trial tests (2026-10-29)

Status: **record, owner-requested (Q13, Q12 approved 2026-10-29).** Documentation only. Nothing here changes a
model, setting, protocol, trial rule, Phase B criterion or result. It amends no locked file: Phase B's settings
(`2026-10-22-phase-b-settings.md`, tag `phase-b-settings`) and the trial's rules are untouched, and nothing in
Phase B is reinterpreted — this note only states what each number is.

## 1. Production facts (read-only checks, 2026-10-29 ~16:30 IST)

Source: prod REST API, GET only, owner-approved (Q12). No model activated, no retraining, no config change.

| Check | Endpoint | Result |
|---|---|---|
| 1. Models | `GET /api/v1/ml/models`, `/ml/models/active?name=swing_classifier` | 20 models. **Every one is `label_kind=endpoint`**; none is a barrier (+8% / −4%) model; no `swing_classifier_barrier*`, no `*_barrier_cal`. ACTIVE: **id 2 `swing_classifier` v2** (activated 2026-08-28), id 16 `swing_classifier_midcap` v2, id 17 `swing_classifier_smallcap` v1 — all **horizon 5, target +2%, no stop, no calibration**. |
| 2. Daily check | `GET /api/v1/brain/daily-checks/latest` (2026-10-29) | "Score matches the trade plan: **NOT matched**. The plan trades +8% before −4% within 15 days, but swing_classifier asks 'closes +2% or more after 5 days'; [midcap, smallcap the same]." |
| 3. Rules watch (in the daily check) | same | "Paper only; brain on 15 days at +8% / −4%; v1 bot on 5 days at +2% / −4%; half out at +5%, 30-day time stop, 15% halt, 25% sector cap." |
| 4. Strategies | `GET /api/v1/strategies` | id 1 `ml_swing_main` (auto, paper, `swing_classifier`, 52 stocks); id 4 `ml_swing_midcap` (auto, paper, `swing_classifier_midcap`, 150); id 5 `ml_swing_smallcap` (auto, paper, `swing_classifier_smallcap`, 104); id 2 `sma_crossover_benchmark` (auto, paper, 52); id 6 `real_trading` (advisory, live-account tracking, 8); **id 7 `TradeMind brain` (advisory, paper)**; id 8 `tester_paper` (inactive). |
| 5. M06 | `GET /api/v1/brain/modules`, `/brain/runs/{latest}/trace` | M06 mode **shadow**. In the 2026-10-29 nightly run M06 took 4 ms, "recorded, not used", and the reasoning step fell back ("no module answered") to the model score. With no barrier base model in prod, M06 has nothing valid to combine. |

End-to-end sample (nightly run `nightly-20261029T102000-d761a6`, 302 decisions, banner DEFENSIVE): ACC → WATCH,
confidence 0.68, horizon 15 days, reason **"The active model (swing_classifier v2) scores this stock 68%; its buy
level is 60%."**

## 2. The model-selection path (code, checked)

```
brain universe (watchlist + symbols of every active auto v1 strategy: ~300 stocks, all cap tiers)
  → brain/reader.py:460-496  model_probability(): get_active_model(db, "swing_classifier")  [FALLBACK_MODEL_NAME, reader.py:42]
       = prod id 2, "close ≥ +2% after 5 trading days", uncalibrated, large-cap model for EVERY stock
  → brain/fallbacks.py:117-145  Opinion(source="model", probability=p, threshold=accepted level or 0.60)
  → brain/opinions.py  pick_opinion: "combined" (M06) preferred, else "model" → in prod always "model"
                       liked = p ≥ threshold ; strength = p  (slot order)
  → M07 risk: only liked stocks, slots by rank_strength (p + small sector/event tilt)
  → M08 decide: attaches the locked plan +8% / −4% / half at +5% / 15 trading days (m08_decide/policy.py:12-18)
  → BrainDecision.confidence = p, horizon 15  (the decision does NOT store which model scored it)
```

So: **every 15-day brain idea in production is chosen and ordered by a score trained to answer a 5-day, +2%
question.** No code converts that score into a 15-day probability; screens call it a ranking, not a chance
(`score_evidence.py`, `scoreText.ts`). This is a confirmed architectural mismatch (audit D1, now confirmed in
prod), not a display bug.

## 3. What the sealed 15-day trial actually tests

The trial (from 2026-10-14, strategy id 7, practice/shadow, sealed) tests **this combination**:

> stocks ranked by the **5-day +2% `swing_classifier` v2 score** (large-cap model applied to all ~300 stocks),
> filtered by the market banner, M07 limits and M13 events, then held under the **15-day +8% / −4% plan**.

It does **not** test a 15-day model, M06, or anything Phase B will evaluate. Its results, when unsealed, answer
"does a 5-day ranking score pick good 15-day trades?". The trial is preserved exactly as it runs; this note
changes nothing in it.

## 4. "Score 0.80" — three different numbers

| Where | What 0.80 is | Model | Question |
|---|---|---|---|
| Phase B candidate **B1** | raw LightGBM score ≥ 0.80 of a model **retrained per test window** | 15-day barrier fold model (`phase_b.py:57-58`) | +8% before −4% within 15 days |
| Trial set **"Score 80 or more"** (`trial_journal.py:41,86`) | prod brain score ≥ 0.80 | `swing_classifier` v2 (id 2) | close ≥ +2% after 5 days |
| Owner's reading rule "read scores over 80" (2026-10-09) | the same prod brain score | `swing_classifier` v2 (id 2) | close ≥ +2% after 5 days |
| Score-evidence map, 0.80+ band "40.8%" (`score_evidence_barrier.json`) | raw score of 15-day barrier fold models, 2025-10 → 2026-08 | barrier fold models | +8% before −4% within 15 days |

Consequences, stated without reinterpreting Phase B:

1. A 5-day score of 0.80 and a 15-day score of 0.80 are **not the same quantity**; neither is "80% chance".
2. Whatever Phase B's B1 shows, it is a result about **15-day barrier models**, and does **not** validate the
   owner's "read scores over 80" rule, which reads the 5-day score.
3. The 40.8% figure belongs to 15-day barrier models and must not be quoted next to prod scores.
4. Adopting any B1 result in production would first require the prod score to be the same kind of model
   (a separate, approved change after the trial), and B1 re-checked on it.

## 5. Status of the audit items after the prod checks

| Item | Before | Now |
|---|---|---|
| D1 15-day ideas chosen by the 5-day score | confirmed in code, prod LIKELY | **CONFIRMED in prod** |
| D2 mid/small-cap stocks scored by the large-cap model | confirmed in code | **CONFIRMED** (strategies 4/5 active auto with 150/104 stocks; brain scored 302 stocks with id 2) |
| D4 "0.80" means different numbers | LIKELY | **CONFIRMED** (section 4) |
| D5d different score kinds sorted together | confirmed in code | **active**: `sma_crossover_benchmark` is active auto |
| D8 prod labels follow 5 days / +2% | LIKELY | **CONFIRMED for models and v1 rules** (all 20 models endpoint; rules watch: v1 on 5 days +2%). Settings values themselves not read |
| M06 has nothing to run on | LIKELY | **CONFIRMED in effect** (no barrier base model; trace shows no answer) |

Fixes stay proposals (audit F1–F14). Any that changes the trial's picks or reporting (F3, F4, F6, F7) waits for
the trial's evaluation or a new trial, with owner approval.

---

## Addendum 2026-10-30 (appended; nothing above was edited)

1. The production score in section 2's chain is computed by `ml/predict.py: predict_instrument` from the **newest 400
   bars** with today's `obv_slope` formula, which differs from the formula the saved models were trained on (D13 in
   `2026-10-29-audit-model-scores.md`). So "the trial tests the 5-day score" is accurate for the score as it is
   served, which is not the score as trained.
2. The models behind that score use 37 / 46 / 46 inputs and were trained on 49 / 24 / 30 stocks
   (`2026-10-30-model-facts-corrections.md`).
