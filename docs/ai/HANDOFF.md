# TradeMind AI Task Handoff

## Current task

Codex audit remediation, round 2. Owner decisions on 2026-11-16:
- Entry-lock corrections **accepted** for focused verification. Do NOT commit or push yet.
- `ml/predict.py` finding-9 guard **reverted and deferred** (it broke the frozen h05 protocol pin and 9 tests).
  Do not re-pin h05 without a separate owner decision.
- `learn.py` change (commit `1498b2c`) **approved**; to be recorded through `scripts/approve_trial_change.py`.

Phase 0 is committed locally (`1ca0aa3`). Everything below is UNCOMMITTED (staged in the index, not
committed). Nothing pushed; CI has not run. **STOPPED for Codex's final review.**
Owner: Claude Code (implementation). Reviewer: Codex (read-only).

Note: a local commit `f3f53f4` was made briefly, then undone with `git reset --soft HEAD~1` when the owner
said "do not commit before Codex's final review". The working tree is identical to that commit's content.

## Git snapshot

Branch `review/local-work-nov12`, HEAD `1ca0aa3`. Staged changes (`git diff --cached --stat`), 11 files,
+1069 / −180:
```
backend/src/swing_trade_ml/api/v1/endpoints/orders.py          |  83 +-----
backend/src/swing_trade_ml/services/brain_golive/approvals.py  | 103 +++++--
backend/src/swing_trade_ml/services/entry_lock.py   (new)      |  78 ++++++
backend/src/swing_trade_ml/services/execution.py               |  52 ++++
backend/tests/test_entry_lock.py                    (new)      | 297 ++++++++
backend/tests/test_entry_lock_integration.py        (new)      | 308 ++++++++
backend/tests/test_orders_no_manual_placement.py    (new)      |  43 +++
backend/tests/trial_freeze.json                                |  10 +-
docs/ai/HANDOFF.md                                             |
docs/ai/deferred/finding9-predict-guard.md          (new)      |  21 ++
docs/ai/deferred/test_prediction_history_guard.py.txt (new)    |  81 ++++++
```
Codex: review with `git diff --cached` (staged). By area:
- Entry lock: `services/entry_lock.py` (new), `services/execution.py`, `services/brain_golive/approvals.py`,
  `tests/test_entry_lock.py`, `tests/test_entry_lock_integration.py` (new).
- #2: `api/v1/endpoints/orders.py`, `tests/test_orders_no_manual_placement.py` (new).
- Deferred #9, parked outside the test tree: `docs/ai/deferred/finding9-predict-guard.md` (the reverted line +
  how to revive it), `docs/ai/deferred/test_prediction_history_guard.py.txt` (its 3 tests, not collected).
- `ml/predict.py` is back to byte-identical with HEAD (`git diff` empty).
Not mine, preserve: `.claude/`, `docs/ARCHITECTURE_REVIEW.md`, `docs/MASTER-CHECKLIST.md`,
`docs/superpowers/specs/2026-11-14-5d-paper-trial-protocol-v1.md`.

## What changed (unchanged from round 2, minus #9)

1. **Brain approval path locked.** `approvals.approve` (market open) and `_execute_one` (open job) run
   `_check` (fresh cash/risk), the claim and `open_position()` inside `entry_lock(current_mode())`, after a
   `db.commit()`. Busy: `approve` raises `ApprovalRefused` (stays pending); the open job leaves it waiting.
   Closed-market approvals place no order and take no lock.
2. **Fresh state after the wait.** Scan path re-queries positions (`populate_existing`) inside the lock.
   Approval path re-reads the approval row (`refresh`, status re-checked) and `_check` re-reads everything.
3. **Two-session integration tests** (5) with real sessions, committed rows, real `risk.check_entry` and
   `open_position`; 5 simultaneous entries vs a limit of 2: locked = 1..2 positions, unlocked controls > 2.
4. **Unlock result checked**: anything but true invalidates the connection.
5. `POST /orders` handler removed (now 405). GET, GET one, cancel, sync unchanged.

## Test results — FINAL (2026-11-16, after the owner recorded the learn.py approval)

- Owner ran `scripts/approve_trial_change.py` (commit `1498b2c`). `tests/trial_freeze.json` diff checked: one
  new approval entry listing only `brain/modules/m09_learn/learn.py`, and only that file's fingerprint changed.
- Freeze test: **3 passed.**
- Focused (freeze + lock + orders + brain approvals): `test_trial_freeze.py`, `test_entry_lock.py`,
  `test_entry_lock_integration.py`, `test_orders_no_manual_placement.py`, `test_brain_m18_approvals.py`:
  **103 passed, 0 failed.**
- Other order tests: `test_kite_order_reauth.py`, `test_real_holdings_orders.py`,
  `test_blocked_entry_reporting.py`: **31 passed, 0 failed.**
- **Full backend suite, no deselection: 4612 passed, 0 failed, 31 skipped, 10m41s. Fully green.**
  No `-k`/`--deselect` used and `pyproject.toml` has no `addopts`, so nothing was deselected. The 31 skips are
  the suite's existing conditional skips (not added by this branch).
- Ruff: clean on `entry_lock.py`, `approvals.py`, `orders.py` and the 3 new test files. `execution.py` has 3
  ruff findings (I001 import order at line 9, E501 at lines 645 and 1501); all 3 exist identically at HEAD
  `1ca0aa3` and none is on a line this branch changed, so left alone (correcting the earlier "ruff clean on
  every file I touched" claim).
- `git diff --cached --check`: clean (removed one trailing blank line at EOF of `test_entry_lock.py`; that
  file re-run: 13 passed).
- All runs with `backend/.venv/Scripts/python.exe`, `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY
  -u TRADING_MODE`, Docker `stml-postgres` + `stml-redis` healthy.

Earlier run (before the approval was recorded), kept for the record:
- **Full backend suite, no deselection: 4611 passed, 1 FAILED, 31 skipped, 18m38s.**
  The single failure is `test_trial_freeze.py::test_no_decision_file_changed_without_the_owners_approval`,
  for `brain/modules/m09_learn/learn.py` only. `predict.py` is no longer listed.
- The 9 h05 failures from round 2 (`test_h05_hardening.py`, `test_h05_service.py`) are gone.
- Freeze test alone: 1 failed (learn.py), 2 passed.
- A read-only pre-check showed `learn.py` is the ONLY frozen file differing from `tests/trial_freeze.json`,
  so running the approval script now records exactly that one file.

## CI result (2026-11-16, manual dispatch, NO PR)

Pushed `4961507` to `review/local-work-nov12` only (also carried its unpushed parents `1ca0aa3`, `9278ca8`;
`main` untouched at `64ac6d3`). Run https://github.com/nareshgudiganti/swingtrademl/actions/runs/43879721454 on
`496150787d84f75aa11a77169954992a2544ab62`: **FAILED**. frontend success, e2e success, backend failure at
"Test" (migrations, drift, lint passed): **3 failed, 4590 passed, 50 skipped.**
- `test_final_hash_sheet.py::test_real_repo_files_reproduce_the_verified_v3_hashes`
- `test_money_kite_broker.py::test_auto_login_walks_redirects_to_request_token`
- `test_money_kite_broker.py::test_login_diagnostics_paths`

Root cause (reproduced locally, not caused by this branch's code): `pyproject.toml` pins only minimums, so CI
installed newer libraries than the local venv: numpy 2.5.5 vs 2.5.4, pandas 3.1.1 vs 3.1.0, pyotp 2.12.0 vs
2.10.0.
- Hash sheet: the SX recipe sha256 includes library versions by design. With numpy 2.5.5 / pandas 3.1.1 it
  is exactly CI's `80e58295…`; with the frozen versions it is the evidence's `fa6b3e97…`.
- Kite: pyotp 2.12 rejects secrets under 112 bits. The test's dummy `TOTP_SEED` is 16 base32 chars (80 bits).
  With pyotp 2.12 installed locally: the same 2 tests fail.
Owner approved both fixes (2026-11-16), committed on the review branch:
- `backend/tests/test_money_kite_broker.py`: dummy `TOTP_SEED` now 32 base32 chars (160 bits). Test-only.
- `backend/ci-constraints.txt` (new) + `.github/workflows/test.yml`: CI installs with `-c ci-constraints.txt`,
  pinning the 5 recipe libraries to the frozen evidence versions. App/production install unchanged;
  `dependency-audit.yml` deliberately left on newest versions.
- Local checks: Kite tests 30/30 under pyotp 2.10 AND 2.12; `pip install --dry-run -c ci-constraints.txt`
  resolves; full suite with pyotp 2.12 on the path: **4612 passed, 0 failed, 31 skipped**, no deselection.
- Owner to confirm (without revealing it) prod `KITE_TOTP_SECRET` is >= 23 chars, else pyotp 2.12 in a fresh
  prod build would break auto-login.
No merge, no deploy.

### CI run 2 — https://github.com/nareshgudiganti/swingtrademl/actions/runs/43908194612 (`4e251d1`)

**FAILED: 1 failed, 4592 passed, 50 skipped.** frontend/e2e success; backend Install/migrations/lint success.
The pins worked (CI installed lightgbm 4.7.0, scikit-learn 1.9.1, numpy 2.5.4, pandas 3.1.0, scipy 1.18.1;
pyotp 2.12.0) and all 3 run-1 failures are fixed.
- New failure: `test_selection_lab_evaluate.py::test_a_model_that_knows_nothing_does_not_pass`. Not caused by
  this branch: a FLAKY TEST. Its "knows nothing" score used built-in `hash((symbol, day))`, which Python
  randomises per process (PYTHONHASHSEED). Reproduced: fails with PYTHONHASHSEED=7, passes for the other 39 of
  seeds 0-39 (~1 in 40 runs).
- Fix (local, UNCOMMITTED, awaiting owner OK to commit/push/re-run): test-only, `_noise()` uses `hashlib`
  sha256 so the score is the same every run. File passes 15/15 under seeds 7, 0, 1, 2, 3, 99 and default;
  ruff clean. `selection_lab.py` (the evaluator) untouched.
- Note for the owner: a pure-noise model passed check r1 in 1 of 40 random draws, i.e. r1 alone has a small
  chance of passing by luck. That is a property of the evaluation threshold, not of this test; worth knowing
  when reading selection-lab verdicts.
- Low-priority backlog: ~14 tests make instrument tokens with `hash(symbol) % N`, also random per run; two
  symbols could rarely collide. None has failed. Not changed.

## Open findings

1. **RESOLVED 2026-11-16: owner ran the approval script; freeze test green.** (History:) Running `scripts/approve_trial_change.py` was
   DENIED by the permission layer again, and the freeze hook says not to hand-edit `trial_freeze.json`.
   Not worked around. Owner, from `backend/`:
   `.venv/Scripts/python.exe scripts/approve_trial_change.py "Owner approved 2026-11-16: M09 learn.py change from 1498b2c, parity-proven by the M09 parity test in 1ca0aa3" 1498b2c`
   then `.venv/Scripts/python.exe -m pytest tests/test_trial_freeze.py` (expect 3 passed). The full suite should then be fully green.
2. **#9 deferred** (see `docs/ai/deferred/finding9-predict-guard.md`). Needs an owner decision on re-pinning
   h05 or a different approach before it comes back.
3. CORRECTED (Codex final review): the `execution.py` call to `open_position()` (line 1336) is inside
   `_process_buy()` (line 1238), which `process_decision` runs inside `entry_lock(mode)` for every
   order-capable strategy (lines 1207-1226); only the advisory path skips the lock, and it places no order.
   The `tester_paper.py` caller does not take the lock; it is intentionally isolated from the bot account.
4. Freeze test is already green. Push now waits for: local commit, owner approval of the push, then CI.
5. DB guard cannot see a localhost port-forward to a remote database.
6. Column type/default drift between models and migrations remains advisory only.
7. gitleaks not installed.

## Codex review 2026-11-16 (12:22 IST): status of its backlog

Codex's note that "the tree has not changed and still reports nine failing tests" is STALE: `predict.py` was
reverted at 12:22 IST, and the full suite run afterwards showed 4611 passed / 1 failed (freeze, learn.py only).
- Item 1 (revert H05-breaking predict.py change): DONE, deferred per owner.
- Item 2 (record learn.py approval): DONE, owner ran the script.
- Item 3 (fully green suite + CI): local suite fully green (4612 passed); CI not run (no push yet).

## Separate feature tasks (owner order, 2026-11-16; not started)

Each gets its own branch, plan and tests. Order-path ones need `review-risk` + owner approval before `main`.
Paper mode only throughout; no real orders.
1. **Model artifact / version safety** (Codex 4). Make model version allocation and artifact publishing
   concurrency-safe (`ml/registry.py` `save_artifact` / `activate_model` / `get_active_model`); verify the
   artifact matches its `ml_models` row (hash, feature names, version) before serving; safe fallback on
   mismatch or missing file. Mind the h05 hash pins and the trial freeze (`ml/predict.py` is frozen).
2. **Broker submission and fill recovery** (Codex 5, 6, 7):
   - uncertain submission (order sent, no reply / timeout) is recovered, never double-submitted;
   - partial fills are reconciled even when broker status stays unchanged (incl. OPEN past the session in
     `_finish_reconciled_order`, `ARCHITECTURE_REVIEW.md` lines 286 and 700);
   - final fills are reconciled before a cancellation is marked complete.
3. **Data freshness before decisions** (Codex 8, 9, 10): gate scans on confirmed current-session ingestion;
   never use stale prices for execution; side-feed historical replays respect publication time (no look-ahead).
4. **Migration checks** (Codex 11): type/default drift and upgrade-path checks become enforcing, not advisory.
5. **Dependency and Git-history secret scanning** (Codex 12; gitleaks not installed).

Later audit phases (not yet audited, per Codex): security/API (endpoint authorization and ownership
isolation, rate-limit bypass), database (all migrations + rollback), ML/evidence, workers/data (retry and
idempotency, Redis failure), frontend (permissions, accessibility, responsive, error states), operational
recovery (restore from real backups, load with production-sized data). External API consumers outside the
repo stay unknown. Runtime checks against production need separate owner approval.

## Next action

Owner's sequence (2026-11-16):
1. DONE 2026-11-16 18:22 IST: Codex approved the code for local commit; its 3 documentation corrections
   (open_position lock statement, push-waiting reason, finding9 note wording) were applied. **Codex** reviews the final staged diff (`git diff --cached`): lock released on every path, commit before
   waiting and re-read after, integration tests exercise real paths, POST /orders gone with nothing else
   broken, `trial_freeze.json` records only `learn.py`, `ml/predict.py` unchanged. Findings → `docs/ai/REVIEW.md`.
2. If clean: **Claude** commits locally.
3. Push ONLY the review branch `review/local-work-nov12`, with the owner's approval.
4. Run CI via a PR or manual dispatch (`test.yml` runs on PR or manual dispatch only).
5. Do NOT merge into `main` until CI is green AND the owner separately approves (order-placement change).

Next implementation task after this branch: **H1, safe model version allocation and artifact publishing**
(feature task 1 below). Today `ml/registry.py::next_version` counts rows (`v{count+1}`) and `save_artifact`
writes straight to `{name}_{version}.joblib`, so two concurrent trainings of the same name can get the same
version and overwrite each other's file. Callers: `ml/train.py`, `brain/five_day_train.py`,
`brain/selection_lab.py`. Then **H2/H3 broker recovery** (feature task 2) before any real-money trading.
Not started; brainstorming was opened and paused when the owner asked to finish this branch first.

## Restrictions

No production access, deployments, migrations against production, model activation, push to `main`, merge
or order execution without explicit approval. Do not commit or push this round until the owner says so.
Require approval for schema migrations. Never read or expose secrets. Keep trading in paper mode and preserve
all risk controls. Approval requirements do not override the trading and secrets rules in `CLAUDE.md` and
`AGENTS.md`.
