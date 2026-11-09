# Model activation: audit, readiness checklist, guard design and rollback (REVISION 2, DRAFT for owner approval)

Status: revised 2026-11-09 after the owner's review. **A design and a plan. Nothing is built, nothing is activated.** No model is
promoted, retrained or replaced; live trading stays off; no signed protocol, sealed evidence, sizing, stop, risk or limit is touched.
Priority: **finish development first, activate models later.** Passing tests never authorises activation.

**Correction to revision 1.** Revision 1 said the activation routes had no owner check. That was wrong. Section 1 shows owner-only is
enforced centrally for every write; what is missing is different (section 1, "missing").

## 1. Read-only code audit (2026-11-09, `origin/main` `6242de1` plus #164)

### Safeguards that already exist

| Area | What exists | Where |
|---|---|---|
| Owner-only writes | Every non-GET route needs the owner or the shared API key, whatever the plan. Testers may write only two listed routes (tester buy, close position). `/ml/models/{id}/activate` and `/strategies/{id}/activate` are not in either list, so members and testers get 403. A test asserts a guest gets 403 on strategy activate. | `api/deps.py` `require_auth` (lines ~246-300), `TESTER_WRITES`; `tests/test_brain_owner_only_writes.py:46` |
| Promotion bookkeeping | One ACTIVE version per model **name**; promoting archives the previous one of the same name in one transaction; only TRAINED or ARCHIVED can be promoted; prediction cache cleared | `ml/registry.py` `activate_model`; `api/v1/endpoints/ml.py` |
| Two-latch live trading | Real broker orders need `TRADING_MODE=live` AND `ALLOW_LIVE_TRADING=true`; every order path asks `is_live_trading` | `core/config.py:397-405` |
| Separate real-holdings switch | Owner's manual real orders need `ALLOW_REAL_HOLDINGS_ORDERS`, market open, money limits, one waiting order per stock; the bot is not involved | `services/real_orders.py` |
| Entry halt (emergency) | `POST /safety/halt` stops new entries (checked in the risk gate and the real-order path); `/safety/resume`. Existing positions keep their stops. | `services/system_state.py`, `api/v1/endpoints/safety.py`, `services/risk.py:620` |
| Exit-disable switch | Exists but is dangerous (stops exits). **Must never be part of a rollback.** | `system_state.disable_exits` |
| Brain stage | shadow → approval → auto only by the owner endpoint; pause rules and switching the brain strategy off can only move it back | `services/brain_golive/stage.py` |
| Shadow lane | Off by default; needs `LANE_SHADOW_ENABLED`, an owner-chosen model in `LANE_SHADOW_MODELS`, and role `final`; never trades | `shadow_lanes/lane_job.py`, `services/lane_slots.py` |
| Model fingerprints (research path only) | h05 verifies each model file's sha256, feature-name list and feature code; lane freeze records the hash at registration | `brain/lanes/h05_models.py`, `shadow_lanes/lane_freeze.py` |
| Feature-parity check (research path only) | Compares today's feature code against each model's own scaler statistics | `brain/lanes/h05_parity.py` |
| Audit log service | `audit_log` rows written by `services/audit.py` (action and row commit together) | `services/audit.py` |
| Model role field | `model_role` in `fold`, `final`, `prod` exists on the model row | `db/models/ml.py:75`, `services/model_registry.py` |

### Safeguards that are missing (the gaps)

| # | Gap | Evidence |
|---|---|---|
| G1 | Promotion has **no evidence guard**: no check of artifact hash, signed protocol, evidence reference, scope, or `model_role`. Any owner-level call promotes any TRAINED/ARCHIVED model. | `registry.activate_model` checks only status |
| G2 | **No hash is stored on the model row** and the serving path never recomputes the artifact hash. Only the research lanes do. | no sha256 column in `MLModel`; `registry.load_artifact` loads without checking |
| G3 | Activation and strategy-on are **not audited** (no `audit.record` call in either endpoint). | `ml.py`, `strategies.py` |
| G4 | "Owner" means **any account with role `owner` or the shared API key**, not a named approver; prod has several owner accounts. Activation is therefore not tied to one named person. | `api/deps.py:76` `is_owner` |
| G5 | **Unnamed lookups follow the global newest ACTIVE model.** `get_active_model(db)` without a name returns the most recently activated model of any name. Callers: portfolio horizon display, system status, brain evidence fallback via `FALLBACK_MODEL_NAME`, CLI, `predict` evaluation. Promoting a mid-cap or small-cap model can change what those show (this is the 12 Aug incident class). Strategies and the watchlist predictor already pass a name. | `registry.get_active_model`; `api/v1/endpoints/portfolio.py:212`, `system.py:179`, `ml/predict.py:495`, `cli.py:526` |
| G6 | **No explicit slot map.** Which model name serves which cap group and horizon is implied by strategy `params["model_name"]` and name suffix rules (`ML_REAL_QUESTION_SUFFIX`), not written in one place with a test. | `strategies/ml_swing.py:97`, `ml/real_question.py:24` |
| G7 | **Rollback is the same unguarded route**, not audited, and not restricted to previously approved versions. | `activate` reused for ARCHIVED |
| G8 | Train/serve mismatch is detected only in the research lane; **nothing blocks promotion** on it. Known case: `obv_slope` on models 2, 16, 17. | `h05_parity.py` not called by promotion |
| G9 | Promotion, shadow, paper and live authorisations are **not separate objects**; activation is one boolean on one row. | `ModelStatus` only |
| G10 | No **pending-order reconciliation or position-protection check** tied to a model change. Order reconciliation exists in `services/execution.py` and the scheduler, but a rollback does not run or require it. | `workers/jobs.py`, `execution.py` |
| G11 | **No quantitative thresholds or minimum sample sizes** are written for each signed protocol as an activation requirement. | docs only |
| G12 | No test covers unauthorised activation by hash mismatch, missing evidence, scope mismatch, rollback or live-order isolation. Existing: guest 403, registry newest-per-name tests. | `tests/test_model_registry.py`, `test_brain_owner_only_writes.py` |

## 2. Four separate authorisations (never one switch)

| Level | Question it answers | Effect | Needs |
|---|---|---|---|
| L1 Registry promotion | May this version be ACTIVE for its name? | Serving path for that name only | Evidence guard approval of scope `registry` |
| L2 Shadow evaluation | May this model be scored in a lane, shadow only? | Lane records, no orders | Scope `shadow`, lane flags, `final` role |
| L3 Paper-trading | May a paper strategy use it for entries? | Paper orders only | Scope `paper`, strategy is_active, paper mode confirmed, drawdown/sector rules unchanged |
| L4 Live-order | May it influence real money? | Real orders | Scope `live`, **separate** written owner decision, both latches. **Out of scope until the owner separately decides; the guard refuses scope `live` unconditionally in this plan.** |

An approval for one level never implies the next. Promotion (L1) alone must not create orders: the guard test proves that promoting
a model changes no strategy, no order and no flag.

## 3. Model-consumer and cap/horizon slot map (to be written as code and verified by a test; values below are what must be proven)

The map is a single frozen table (`services/model_slots.py`, proposed) listing, per slot: cap group, horizon, model **name**, consumers.
Today (from code, to be verified against prod before it is frozen): large-cap watchlist predictor uses `swing_classifier`;
small/mid-cap names carry suffixes (for example `swing_classifier_smallcap`); the real-question switch appends
`ML_REAL_QUESTION_SUFFIX` to the name; the brain reader falls back to `FALLBACK_MODEL_NAME = "swing_classifier"`; the 5D lane uses models
2/16/17 by id; the lab and shadow slots use `LANE_SHADOW_MODELS` ids. A promotion for slot X must satisfy:
- it archives only versions of the **same name** (already true);
- every unnamed `get_active_model(db)` caller is changed to a named lookup, or shown to be display-only (G5);
- a test activates a model in one slot and asserts every other slot's resolved model id is unchanged.

## 4. Quantitative thresholds and minimum samples (to be recorded inside each signed protocol; none are invented here)

Each protocol's own signed text is the source. Activation requires a one-page evidence note that quotes, for each candidate:
(a) the number and date range of matured out-of-sample decisions; (b) the pre-signed minimum sample size; (c) the pre-signed pass
thresholds for edge, net economics against the momentum and no-trade baselines, and drawdown; (d) the observed values with
confidence bounds; (e) PASS or FAIL per threshold. If a protocol has no written threshold or minimum, **that protocol cannot support
activation** until the owner adds one in a signed amendment before the run. Already written: Phase B survival rule S1 and tie ladder;
15D lab is ranking-only (cannot by itself support L3 or L4); SX5 verdict `sx_verdict_v1` with `MDE_H = 0.0018` and `E* = 0.10 pp`;
h05 needs about 40 matured days before a non-INCONCLUSIVE verdict.

## 5. Blockers

**Global (block every activation):** protocols unsigned or unrun; production flags not read directly on the droplet; no evidence guard
(G1, G2); no audit (G3); no slot map or test (G5, G6); rollback not restricted or audited (G7); backups not restore-tested; trial still sealed.
**Model-specific:** 5D models 2, 16, 17: `obv_slope` train/serve mismatch, forward verdict INCONCLUSIVE until about late December or later; TMCV
unscorable until 252 bars; 15D candidates: no run yet, mid-cap file hash unverified; SX5: unsigned, untrained, `E*` set but protocol and hash
refresh at signing outstanding; 10D: failed its test, deferred.
Rule: a train/serve mismatch **blocks the affected model's promotion** until fixed or accepted in a signed note, and never by changing a sealed trial.

## 6. Proposed fail-closed activation evidence guard (design, not built)

A promotion at any level succeeds only if **every** check passes; any error, missing item or ambiguity refuses and writes an audit row.
1. Caller is the owner (existing) **and** a named approver in a new setting `ACTIVATION_APPROVERS` (default empty, so default is refuse).
2. An approval record exists in the database table `model_activation_approvals` (new, additive migration), created by an owner-only
   command, containing: model id, name, version, artifact SHA-256, evidence tag, evidence commit, protocol file SHA-256, evidence-note SHA-256,
   scope (`registry` | `shadow` | `paper`; `live` always refused), slot, approver, created and expiry timestamps.
3. The record carries an **HMAC-SHA256** over its canonical JSON using `ACTIVATION_SIGNING_KEY` (a secret only in the droplet environment, never in git),
   so a Markdown file or a database edit alone cannot create an approval. Key missing means refuse.
4. At promotion time the guard recomputes: the artifact file SHA-256 (must equal the record and a hash taken at training registration),
   the protocol and evidence-note SHA-256 from the deployed copies, and checks model id, name, version, `model_role == final`, the slot name,
   and that the requested scope equals the approved scope. Any mismatch refuses.
5. The evidence tag and commit must be present in the repo copy deployed with the app; absent means refuse (no network lookup).
6. Train/serve parity result for that model must be recorded `PASS`, or a signed acceptance note hash must be present (G8).
7. Strategy activation for an ML strategy reads the same record for its `model_name` and refuses without L3 approval.
8. Promotion changes only status and `activated_at` as today, plus the audit row; it touches no strategy, order, limit or flag.

## 7. Rollback after the guard exists (emergency stays possible)

Rollback is **owner-authorised, audited, and limited to a previously approved version**; it does not need a fresh evidence approval, because the target
already had one.
1. Owner-only, same named approver list; reason text required; an `audit_log` row is written with before and after model ids.
2. Allowed targets: only versions that have a valid past approval record (or the version that was ACTIVE at the freeze, recorded in the freeze note). Any
   other target refuses.
3. **Emergency disable first, independent of the guard:** `POST /safety/halt` (new entries off) is always available to the owner and never needs approval.
4. Sequence, written as a runbook and a read-only check script: halt new entries → record open positions and their stops → confirm protective exits are
   untouched (never call `disable_exits`) → switch model or strategy → reconcile pending orders → re-check stops on every open position → watch the first
   sessions → resume entries only on the owner's say-so.
5. Strategy deactivate already only stops new entries; open positions keep stops. A test proves rollback leaves every open position's stop and target unchanged.

## 8. Pre-activation checklist (every line PASS and attached, then the owner decides, per level)

- [ ] Evidence note per section 4, with tags, hashes and thresholds; PASS on every threshold.
- [ ] Train/serve parity PASS or signed acceptance (section 5).
- [ ] Section 6 guard built, tested, deployed; approval record created and verifies.
- [ ] Slot map frozen and its test green; unnamed lookups resolved.
- [ ] Full backend and frontend suites and CI green on the exact commit; secret scan green.
- [ ] Production flags read directly on the droplet and recorded: `TRADING_MODE`, `ALLOW_LIVE_TRADING`, `ALLOW_REAL_HOLDINGS_ORDERS`, `TESTING_NO_LIMITS`, `BRAIN_ENABLED`, `LANE_SHADOW_ENABLED`, `LANE_SHADOW_MODELS`.
- [ ] ACTIVE model ids and versions per slot written down (rollback targets); offsite backup and restore verified.
- [ ] Deploy only after 16:30 IST on a weekday.
- [ ] Owner's written approval names level, model id, version, hash, slot, scope, date.

## 9. Proposed implementation plan (NOT started; each item needs the owner's separate approval because it touches model-decision code)

| Step | Change | Files (affected) | Risk |
|---|---|---|---|
| 1 | Slot map table plus a verification test; no behaviour change | new `services/model_slots.py`; new test | none (read-only) |
| 2 | Named lookups for unnamed `get_active_model` callers (or mark display-only) | `api/v1/endpoints/portfolio.py`, `system.py`, `ml/predict.py`, `cli.py`, `brain/reader.py` | display and fallback only; test each |
| 3 | Audit rows on activate, deactivate and rollback | `api/v1/endpoints/ml.py`, `strategies.py`, `services/audit.py` (use) | low |
| 4 | Approval table (additive migration) and HMAC verifier | new `db/models/activation.py`, one Alembic revision, new `ml/activation_guard.py` | new table only |
| 5 | Wire the guard into promotion and ML-strategy activation, default refuse | `ml/registry.py`, `api/v1/endpoints/ml.py`, `strategies.py` | **changes what promotion allows (only blocks)**; needs approval |
| 6 | Guarded rollback path and emergency runbook plus read-only check script | `ml/registry.py`, `api/v1/endpoints/ml.py`, `scripts/` | owner approval |
| 7 | Store artifact hash at registration; recompute on load (log and refuse on mismatch) | `ml/registry.py` (`load_artifact`) | touches serving; staged, shadow first |
| 8 | Quantitative-threshold template for protocols (docs) | `docs/superpowers/specs/` (new template only; no signed file edited) | none |

## 10. Test plan (all synthetic; no production model touched)

1. Unauthorised activation: member, tester and no-credential calls to model and strategy activate return 401 or 403; non-approver owner refused.
2. Missing evidence: no approval record, expired record, wrong signature, missing signing key each refuse and audit.
3. Hash mismatch: artifact bytes changed, protocol file changed, evidence note changed each refuse.
4. Scope mismatch: approval for `shadow` cannot promote at `registry` or `paper`; `live` always refuses.
5. Wrong identity: wrong model id, version, name, role not `final`, wrong slot each refuse.
6. Slot isolation: promotion in slot X leaves every other slot's resolved model unchanged; unnamed lookups unchanged or fixed.
7. Rollback: allowed only to an approved prior version; refused to an unapproved one; audit row written; open-position stops unchanged; entries halted first; `disable_exits` never called.
8. Live-order isolation: promotion, shadow and paper approval change no `TRADING_MODE`, `ALLOW_LIVE_TRADING` or `ALLOW_REAL_HOLDINGS_ORDERS`; `is_live_trading` stays false; no broker call.
9. Parity block: a model with a recorded parity FAIL refuses promotion; the sealed-trial files are untouched (fingerprint test stays green).
10. Default state: with no settings changed the guard refuses everything (fail closed).

## 11. Owner approvals required before any of section 9 starts

1. Approve building steps 1 to 3 (read-only map, named lookups, audit) now.
2. Approve the guard design (step 4 to 6), including: named approvers list, `ACTIVATION_SIGNING_KEY` held only on the droplet, and the permanent refusal of scope `live`.
3. Approve step 7 (hash recompute on load) separately; it touches the serving path.
4. Confirm that no step may run against prod data or the sealed trial. None of them needs to.
