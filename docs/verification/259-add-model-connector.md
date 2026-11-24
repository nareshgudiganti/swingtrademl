# #259 Verification: how to add a model or a data connector

Baseline: main at 5de3b9c (24 Nov 2026 IST). Tests and this note only. No model was activated, no connector was added to the real list, no behaviour was changed. Every model, file, slot and feed in the tests is private to the test.

## In plain English

- **Adding a model is safe by default.** Registering a model stores its version, forecast horizon, inputs and file, and activates nothing. The old model keeps serving until someone activates the new one, and the API refuses activation while the promotion switch is off. A file that is not the one its record describes (wrong inputs, wrong version, changed bytes, missing) is refused. A model file is never overwritten.
- **A model stays research-only** unless its name and horizon match a known slot. A new slot is checked before it is accepted, and adding a slot runs nothing: a lane also needs the owner's switch and an owner-chosen model. Of the research rules, only the 5-day horizon is not research-only.
- **Adding a data feed is one entry** in `brain/connectors.py`. The quality check (M01) then reports that feed when it is empty or behind, but a late side feed only adds a line to the report: it never stops trading on its own.
- **Adding an optional module is one declaration.** It is on by default, the registry refuses a core module being switched off or a dependency being broken, and it records every request.
- **Four gaps found** (each a strict expected failure, none fixed):
  1. Activation does not check that the model's inputs exist in the live feature pipeline.
  2. Activation does not compare the new model's horizon with the one it replaces.
  3. A model registered without a horizon is stored as 15 days, not as unknown.
  4. A feed that reports a day after the run date is treated as fresh and nothing is said.

## How to add a model (checklist)

| Step | What to do | Backed by |
|---|---|---|
| 1 | Train, then publish: take the next version, write the file once, store the row with horizon, inputs and file hash | `ml/registry.py:137` (`next_version`), `:57` (`save_artifact`); tests `step_1`, `step_3b` |
| 2 | Set the horizon explicitly (5, 10 or 15). Do not rely on the default (gap 3) | `db/models/ml.py:63`; test `a_model_registered_without_a_horizon...` (xfail) |
| 3 | Check the file against the row before use | `ml/registry.py:98`; test `step_3` |
| 4 | Name it so the registry can place it: exact verified name or a lane prefix, with a known horizon. Otherwise it is "Unassigned" and role "unmarked" | `services/model_registry.py:71`, `:87`; test `step_2b` |
| 5 | For a new lane slot: add one `LaneSlot` (horizon, tier, key, prefixes ending in `_`, the pinned rule). It is validated and stays dormant | `services/lane_slots.py:135` (`_check`), `:159` (`register`); test `step_6b` |
| 6 | Research rules per horizon live in one pinned version | `core/research_config.py:62`; test `step_6` |
| 7 | Scoring for a horizon refuses a model of another or unknown horizon | `brain/horizons/guard.py`; test `step_7` |
| 8 | Activating is the owner's separate act: status must be TRAINED or ARCHIVED, the file must match, only the same name's old version is archived, the API is refused while the promotion switch is off | `ml/registry.py:161`, `core/release_switches.py:100`; tests `step_4`, `step_4b`, `step_5` |
| 9 | Before activating, check by hand that every input is in `ml/features.py` `FEATURE_COLUMNS` and that the horizon matches the model it replaces (gaps 1 and 2) | tests `activation_refuses...` (xfail) |

## How to add a data connector (checklist)

| Step | What to do | Backed by |
|---|---|---|
| 1 | Ingestion (fetch and store) stays with v1's jobs. Store a dated row per day | `brain/connectors.py` header |
| 2 | Add one `FeedSource(name, latest)` to `FEEDS`. Build `latest` with the shared helper so it is bounded by the run date | `brain/connectors.py:23`, `:35`; test `a_feed_that_uses_the_shared_latest_helper...` |
| 3 | Free: M01 reports the feed when empty or behind | `brain/modules/m01_quality/module.py:62`; test `a_new_feed_is_one_entry...` |
| 4 | Not free: if the feed must block trading, add that rule. Today a late side feed only adds an issue line | `m01_quality/quality.py` (`summarise`); test `a_late_new_feed...` |
| 5 | Not free: to use the data in a decision, add a dated read method to `DatedReader` bounded by the run date (existing: `event_rows`, `restriction_rows`, `delivery_rows`, `deal_rows`) | `brain/reader.py:202-270`; `test_brain_m12_stock.py` |
| 6 | A `latest` that is not built with the helper is not checked (gap 4) | test `a_feed_that_claims_a_day_after...` (xfail) |
| 7 | For an optional module: declare it in `REGISTRY` with its routes, jobs and dependencies; keep it off by default while in development | `core/modules.py:102`, `:162`; tests `a_new_optional_module...`, `a_declaration_that_breaks...` |

## Gaps (strict xfail, not fixed)

- `test_activation_refuses_a_model_whose_inputs_the_live_pipeline_does_not_produce`: a model with an unknown input can become the active model.
- `test_activation_refuses_a_model_whose_horizon_differs_from_the_one_it_replaces`: a 10-day model replaced the 15-day base model.
- `test_a_model_registered_without_a_horizon_is_unknown_not_fifteen`: stored as 15.
- `test_a_feed_that_claims_a_day_after_the_run_date_is_flagged`: no issue is raised.

Gaps 1 and 2 matter only if promotion is switched on, which needs the owner. Related: #247, #385.

## Tests

New: `backend/tests/test_add_model_connector_259.py` (16 pass, 4 strict xfail). Re-run with it: `test_model_artifact_safety`, `test_model_promotion_switch`, `test_model_role`, `test_lane_slots`, `test_horizon_guard`, `test_research_config`, `test_module_registry`, `test_brain_m01_quality`, `test_brain_m01_module` (178 passed in total, 4 xfailed).
