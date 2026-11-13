# TradeMind AI Task Handoff

## Current task

Task: Codex audit remediation, **Phase 0 — test safety and migration check** (no trading behaviour change).
Owner: Claude Code (implementation). Reviewer: Codex (read-only).
Status: **Implemented, backend suite green, awaiting Codex re-review and the owner's decision on the
frozen-file test.** Not closed. CI has not run.
Plan: ten audit findings, phased; Phase 1 (#3 scan lock, #9 prediction guard) starts only after Phase 0 closes.

## Git snapshot

Branch: `review/local-work-nov12`
Commit: `9278ca8` (all Phase 0 work is **uncommitted**, by instruction).
Not mine, preserve: `.claude/`, `docs/ARCHITECTURE_REVIEW.md`, `docs/MASTER-CHECKLIST.md` (untracked).

## Changed files (all uncommitted)

- `backend/src/swing_trade_ml/core/db_guard.py` (new): shared guard. Accepts only a PostgreSQL URL on
  localhost, database name ending `_test`, no URL query string; and refuses while PGHOSTADDR, PGHOST,
  PGPORT, PGDATABASE, PGSERVICE, PGSERVICEFILE, PGSYSCONFDIR, PGOPTIONS or PGTARGETSESSIONATTRS is set.
  Errors never print the URL, credentials or variable values.
- `backend/tests/_env_safety.py` (new) and `backend/tests/conftest.py`: forced (not `setdefault`) safe
  settings, credentials blanked, guard applied before anything is imported.
- `backend/scripts/check_migrations.py` (new): one head, database at head, table AND column names match
  the models; same guard.
- `.github/workflows/test.yml`: new blocking step (empty database -> `alembic upgrade head` ->
  `check_migrations.py`) and an advisory `alembic check` step for column types/defaults.
- New tests: `backend/tests/test_test_environment_safety.py`, `backend/tests/test_check_migrations_script.py`,
  `backend/tests/test_m09_scored_rows_parity.py` (old-vs-new M09 `_scored_rows` parity; see Open findings 1).
- `docs/ai/HANDOFF.md`: this file.
- Earlier, committed in `9278ca8`: `AGENTS.md`, `CLAUDE.md`, `.codex/config.toml`, `docs/ai/REVIEW.md`.

## Test results

- Parity test `test_m09_scored_rows_parity.py`: 8 passed, ruff clean (run alone; the full-suite figure below
  predates it).
- New tests: 61 passed (`test_test_environment_safety.py`, `test_check_migrations_script.py`), including a
  child pytest session started from a hostile shell (live trading flags, fake credentials, PGHOSTADDR).
- Migration script, run by hand against a throwaway local database built with `alembic upgrade head`:
  passes; fails on a dropped column, an extra column, a query-string reroute and PGHOSTADDR.
- Ruff clean on every file added or edited.
- **Full backend suite, final code (PGHOSTADDR fix included): 4585 passed, 31 skipped, 1 deselected,
  0 failed, exit 0, 18m16s.** The one deselected test is the frozen-file test in Open findings 1, which
  fails for a reason that predates this task. The run used the Docker Postgres on port 5433.
- **CI: NOT RUN.** The workflow was only checked for valid YAML; its first GitHub run is the real test.

## Open findings

1. `tests/test_trial_freeze.py::test_no_decision_file_changed_without_the_owners_approval` FAILS and is
   deselected from my runs. Frozen file `brain/modules/m09_learn/learn.py` changed in commit `1498b2c`
   ("WIP: owner local work", before this task): a speed change to `_scored_rows` (37 lines added, 15
   removed). Fingerprint in `tests/trial_freeze.json` = `07b1b52c8288be1b` (identical to the file at
   `6f00380`); current file = `9393455c01622de1`. **Fingerprint NOT updated; nothing approved.**
   **Parity demonstrated (2026-11-13):** old (`6f00380`) and new `_scored_rows` return identical
   normalized rows and identical downstream results (`learning_report`, `one_per_day`, buy-level
   proposal) on isolated rolled-back local test data: empty database; null confidence, score source,
   return and run context; repeated symbols within and across runs and same-instant runs; non-done and
   unscored rows; IST-midnight run boundaries; several `since` dates; and a large set that produces a
   real proposal. Deliberately wrong versions were all caught. **Preserved as a regression test:**
   `backend/tests/test_m09_scored_rows_parity.py` (8 tests, uncommitted). It embeds the original
   implementation verbatim as a reference copy (no git dependency, so it works in CI) and compares it
   with the live `_scored_rows`. Not covered: production data volume and speed (new code issues 2
   queries instead of 1 by design). **Owner decision:** approve with
   `scripts/approve_trial_change.py "<why>" 1498b2c`, or revert.
   **Correction (resolved by the owner):** an earlier note said `1498b2c` also changed
   `m09_learn/scoring.py`. It did not: `1498b2c` changed only `learn.py` under `brain/`. The
   `scoring.py` difference seen between `6f00380` and `1498b2c` comes from `8ea5e63` ("One market
   clock", already on `main`), and the owner confirms that version was already in the original freeze
   baseline. No action needed on `scoring.py`. (I did not independently trace the baseline's history.)
2. Not covered by the guard: a localhost port-forward or SSH tunnel to a remote database looks like
   localhost. Keep that in mind when running tests.
3. Column types and server defaults still differ between models and migrations (pre-existing); advisory
   only. Baselining them so new drift fails is not done.
4. `POST /orders` unchanged. No repo callers found; external callers unknown. Recommendation: remove, as
   its own Phase 1 change, with tests.
5. gitleaks is not installed; commits are not secret-scanned (repo is public).

## Next action

- Codex: re-review the PGHOSTADDR/routing-variable fix in `db_guard.py`, `_env_safety.py`,
  `check_migrations.py` and their tests; write findings to `docs/ai/REVIEW.md`.
- Claude: after Codex's re-review is resolved, start Phase 1: #3 (advisory
  lock around entries, two-connection concurrency test) and #9 (do not overwrite evaluated predictions,
  prediction-history test). Flag any frozen-file change before editing it.
- Owner: decide open finding 1; approve `POST /orders` removal; approve any commit.

## Restrictions

No production access, deployments, migrations against production, model activation, push, merge or order
execution without explicit approval. Keep changes uncommitted until the owner approves a commit. Require
approval for schema migrations. Never read or expose secrets. Keep trading in paper mode and preserve all
risk controls. Approval requirements do not override the trading and secrets rules in `CLAUDE.md` and
`AGENTS.md`.
