# #389 database approval document (unified stock identity)

Status: FOR OWNER DECISION. Written 2026-11-26 (IST) against `origin/main` `933d3e0c`. Read-only: no migration was
run against any database, no code was changed, nothing was touched in production. Anything not checked is marked
UNVERIFIED. Related docs (not repeated here): `docs/architecture/IDENTITY-READ-API.md` (as built, on main); on
unmerged branches `docs/389-stock-identity-design`, `docs/389-identity-contracts`, `docs/389-consolidated-audit`.

## In plain English

The identity database changes you are being asked about are **already on `main`**: migration `identity01` (PR #448)
created four new tables. Slices #452 (consumers) and #456 (verify) added code only, no migration. What is still
**only proposed** is smaller: a stock-id column on a few old tables, an ISIN source, and a prediction key.
Whether `identity01` is deployed to production is UNVERIFIED (no prod access by design). Your approval covers:
(a) deploying what is on main, and (b) which proposed changes get built next.

## 1. Existing schema vs proposed schema

**On main today** (migration `20261123_1200_identity_phase1.py:42-120`, models `db/models/identity.py`). All four tables are
new; no existing table was altered.

| Table | Purpose | Key columns |
|---|---|---|
| `securities` | one row per company, permanent id | `id` (PK), `isin` (nullable, unique), `name`, `status` (default `active`), `successor_of_id` (self FK) |
| `security_symbols` | dated symbol history (renames) | `security_id`, `exchange`, `symbol`, `valid_from`, `valid_to` |
| `security_aliases` | outside ids (for example the Kite token) | `security_id`, `provider`, `external_id` |
| `score_ledger` | write-once daily score history | `security_id`, `session_date`, `horizon_days`, `source`, `model_name`, `model_version`, `score`, `status`, `revision`, `supersedes_id` |

Other tables on main that already point at `securities.id`, added by separate later migrations (not by `identity01`):
`horizon_records` (`horizon01`, `20261124_1200_horizon_records.py:41`) and the `sim_*` tables (`simulation01`,
`20261125_1200_simulation_persistence.py:41,139,160,175`). `signals.signal_key` (`signalkey01`) is a string key built from
`instrument.id`, not from `security_id`.

**Still proposed (nothing built):**

| Proposal | Source | Status |
|---|---|---|
| nullable `security_id` on `instruments` and `user_watchlist_items` | consolidated audit decision 5 | proposed, one migration, not written |
| ISIN loaded into `securities.isin` (no source yet) | audit decision 2 | proposed; ISIN is empty today |
| one prediction key / `prediction_id`; `predictions.model_id` CASCADE to RESTRICT | audit decisions 3 and 6 | proposed; `predictions` is overwritten by frozen `ml/predict.py` |
| signal key moved from `instrument.id` to `security_id` + `rule_version` | audit decision 4 | proposed |

## 2. Exact migration revisions

Chain at the end of main (read from each file's `revision` / `down_revision`, checked by script over
`backend/alembic/versions/`; exactly **one head**, `signalkey01`):

`wlsales01` -> **`identity01`** -> `horizon01` -> `simulation01` -> `modswitch01` -> `simulation02` -> `signalkey01` (head)

| Revision | File | down_revision | Where |
|---|---|---|---|
| `identity01` | `20261123_1200_identity_phase1.py` | `wlsales01` | main (PR #448, merge `90f0250f`) |
| `horizon01` | `20261124_1200_horizon_records.py` | `identity01` | main |
| `simulation01` | `20261125_1200_simulation_persistence.py` | `horizon01` | main |
| `modswitch01` | `20261124_1400_module_switches.py` | `simulation01` | main |
| `simulation02` | `20261126_1200_simulation_rule_ref.py` | `modswitch01` | main |
| `signalkey01` | `20261126_1200_signal_key.py` | `simulation02` | main (PR #465 merged) |
| security_id on instruments / watchlist | not written | would follow `signalkey01` | proposed only |

Unmerged branches add **no new revision**. `feat/389-identity-phase1` carries the `identity01` file and it is identical to
main's (`git diff origin/main feat/389-identity-phase1 -- backend/alembic/versions/20261123_1200_identity_phase1.py` is
empty). Its other file differences come from being branched earlier (not checked line by line: UNVERIFIED, as the
consolidated audit also says). `feat/389-identity-verify` carries `simulation01`, which is also on main.

Branches (`git cherry origin/main <branch>`):

| Branch | Unique commits | Verdict |
|---|---|---|
| `feat/389-identity-phase1` | 8 | duplicate of merged #448 (same migration); stale |
| `feat/389-identity-consumers` | 4 | duplicate of merged #452; stale |
| `feat/389-identity-verify` | 3 | duplicate of merged #456; stale |
| `test/389-identity-defects` | 1 | strict-xfail tests for two suspected defects; not run, may fail on main (UNVERIFIED) |
| `docs/389-stock-identity-design`, `docs/389-identity-contracts`, `docs/389-consolidated-audit` | 2 / 1 / 1 | design docs only, not on main |
| `feature/389-stock-identity-phase1`, `-consumers`, `-verify` | 0 | already merged into main (these are the real PR branches) |

Correction to the working assumption: it is the `feat/389-*` names that are the duplicates; the `feature/389-*` names are the
merged work. Nothing was deleted.

## 3. Identity constraints and indexes (as built in `identity01`)

| Item | Rule |
|---|---|
| `securities.isin` | unique, **nullable** (no ISIN source yet) |
| `security_symbols` | unique `(exchange, symbol, valid_from)`; check `valid_to IS NULL OR valid_to >= valid_from`; indexes on `security_id` and `(exchange, symbol)` |
| `security_aliases` | unique `(provider, external_id)`; index on `security_id` |
| `score_ledger` | unique expression index `uq_score_ledger_key` on `(security_id, session_date, coalesce(horizon_days,-1), source, model_name, model_version, revision)`; check `status IN (scored, missing, stale, late, no_score)`; check `revision >= 1`; `supersedes_id` self FK |
| Foreign keys | every `security_id` is `NOT NULL` and `ON DELETE RESTRICT`: a security cannot be deleted while history points at it |
| Append-only | database triggers refuse UPDATE, DELETE and TRUNCATE on `score_ledger` (`install_triggers` in the migration) |
| Partial index | none in `identity01`; the only partial unique index nearby is `uq_signals_signal_key` (`signalkey01`, only where the key is set) |

Not recommended: making `isin` NOT NULL before an ISIN source exists.

## 4. Existing-data preservation and backfill

- `identity01` is additive: four new tables, no old table or row is touched (migration docstring).
- Old tables (`instruments`, `stock_score_history`, `predictions`, `signals`) keep working unchanged; v1 and the
  frozen trial do not read the new tables.
- Backfill is a **separate, manual** command, never scheduled (`services/identity/admin.py:1-17`).
  `backfill-instruments` (`writer.py:176 backfill_instruments`) gives each equity instrument a security: token alias first,
  else symbol history, else a new security. `backfill-scores` (`ledger.py:309`) copies old daily scores in as `backfill`
  rows, model name and version copied as stored (empty if none, never guessed), horizon `None`.
- It refuses to run unless the database is a local `*_test` one or the command carries `--owner-approved`. `--dry-run`
  rolls back and prints counts only.
- **Unmatched rows stay visible.** A symbol that matches another company's history raises a conflict and is counted as
  `skipped`, left unlinked and unchanged, never guessed (`writer.py:176-200`). Old rows are never deleted. Gap:
  `backfill_from_stock_scores` skips a conflicting instrument without counting it (`ledger.py:326-329`); whether that
  total is surfaced anywhere is UNVERIFIED. Recommendation: count and print it before the owner-approved run.
- Idempotent: test `test_the_backfill_gives_each_instrument_one_security_and_is_idempotent`
  (`tests/test_identity_s1_database.py:117`); score backfill writes only new rows because `append_score` is write-once on
  the unique key.

## 5. Account isolation

- The identity tables have **no `user_id` column** (`db/models/identity.py`): they are global reference data (one company
  has one id for everyone). Per-user data (watchlist, holdings, orders) stays in the existing user-scoped tables.
- The proposed `user_watchlist_items.security_id` would be a plain nullable pointer; it adds no cross-user visibility.
- The tenant-isolation tests (#414, "Core: tenant-isolation tests for customer data") are **OPEN and not on main**: no test
  file with that purpose was found. Closest existing coverage: `tests/test_real_account_private.py`,
  `tests/test_account_deletion.py`, `tests/test_brain_owner_only_writes.py`; identity admin writers are admin-only
  (`tests/test_identity_admin.py`). So isolation of identity-linked per-user data is **not yet proven by #414**.

## 6. Rollback and migration tests

| Revision | Downgrade | Data lost on downgrade |
|---|---|---|
| `identity01` | drops the triggers, `score_ledger`, aliases, symbols, `securities`, the trigger function | all identity and ledger rows. Back up the ledger first once used: it is score evidence. Blocked by RESTRICT foreign keys while `horizon01` / `simulation01` rows exist, so downgrade must go newest to oldest |
| `horizon01` | drops 3 `signals` columns, triggers, `horizon_records` | `horizon_records` rows |
| `simulation01` | drops 8 `sim_*` tables | synthetic simulation rows |
| `simulation02`, `modswitch01` | drop their added columns/tables | UNVERIFIED in detail (not read) |
| `signalkey01` | drops index and column | signal keys only |
| proposed `security_id` columns | would drop the new columns | the links only; old rows stay |

Tests that exist: `tests/test_identity_migration.py` (upgrade creates exactly the four tables; columns match models;
parent is `wlsales01`, line 76-78; ledger triggers; key behaviour; downgrade then a second upgrade, line 121);
`tests/test_identity_s1_database.py` (resolver and backfill). CI step "Migrations build the schema from an empty
database" runs `alembic upgrade head` and `scripts/check_migrations.py` (one head, table and column names;
`.github/workflows/test.yml:73-89`). `alembic check` (column types) is **advisory only** (`test.yml:93-99`).
Needed before approving new migrations: a full-chain downgrade round trip to `wlsales01` and back; a backfill test with a
conflicting row proving it is reported; a migration test for any new `security_id` column on `instruments`.
I did not run any test (they need Docker Postgres; no database was touched).

## 7. Dependencies and frozen-file impact

- **Frozen files:** `backend/tests/trial_freeze.json` lists 98 files. None of the identity files
  (`db/models/identity.py`, `services/identity/*`, the identity migration) is in the list. The only frozen file near this
  work is `ml/predict.py` (it overwrites predictions); the plan avoids editing it. **No frozen file is touched** by what
  is on main or by the proposed `security_id` columns. Changing `predictions` or moving the signal key would touch or
  affect frozen/trial behaviour.
- **#387 (horizons):** its tables already reference `securities.id` (`horizon01`), so `identity01` stays below it. Branch
  `feat/387-5d-horizon-flow` carries identity commits and needs a rebase (`docs/ai/EXECUTION-QUEUE.md:109`).
- **#388 (Groww):** wants Discover-added stocks mapped to `security_id`; its branches touch `db/models/__init__.py`, shared with #389.
- **#390:** absorbed into #389 (consolidated audit); no migration of its own.
- **#360 / `signalkey01`:** merged (PR #465), the current head; deployed status UNVERIFIED. New identity migrations must chain after it.
- **Other unmerged heads:** the queue lists #260 (scan history and rank) and G9 as future migrations
  (`EXECUTION-QUEUE.md:267,350`); I found none written, so no second head exists on main. Unpushed work: UNVERIFIED.
  Rule: one migration at a time, each rebased on the then-current head, with the single-head CI check.

## 8. Decisions for the owner

1. **Deploy what is on main** (`identity01` through `signalkey01`) in one approved deploy. Recommend yes, after a backup and the full-chain downgrade test.
2. **Run the backfill** (`backfill-instruments`, then `backfill-scores`): first `--dry-run`, then `--owner-approved`. Recommend yes, once the skipped-score count is surfaced.
3. **ISIN source:** Groww holdings, a manual NSE file, or an NSE licence? Recommend Groww holdings for your own stocks now; keep `isin` nullable.
4. **Add nullable `security_id` to `instruments` and `user_watchlist_items`** (one migration, no frozen file). Recommend yes, after 1 and 2.
5. **Prediction key and `predictions.model_id` RESTRICT:** needs one chosen key and touches the frozen `ml/predict.py` area. Recommend defer until after the trial.
6. **Signal key to `security_id`:** recommend keep `signal_key` as is; revisit with decision 4.
7. **Stale branches:** archive the three `feat/389-*` twins; keep the docs branches until one merged design doc replaces them. Recommend yes (nothing is deleted without you).
8. **#414 tenant tests** must exist before identity ids reach customer screens. Recommend yes.
