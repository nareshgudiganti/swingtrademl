# P0 security release: deploy and rollback runbook

Owner approval needed for every step marked (LOCK). Nothing here changes trading.

## Before deploy
1. Role table approved (spec section 6.5): `sudeeksha` only owner (owner decision 2026-10-16).
2. All tests green on `feature/p0-security` (pass count: ___).
3. Migration rehearsal printed OK (Task 11 Step 2); old-code rehearsal evidence pasted below.
4. Placeholder-secret check: the API refuses to start outside local if `JWT_SECRET_KEY` or `API_KEY`
   is a placeholder. Production already runs with `ENVIRONMENT=production`, and an existing settings
   validator already refuses `change-me` secrets there, so this is reassurance, not a new risk.
   (LOCK) Owner still confirms both are real values on the droplet (names only, never values).
   If unsure, run the startup guard on the droplet: `docker compose exec api python -c "from swing_trade_ml.core.config import settings; from swing_trade_ml.core.security import assert_secrets_safe; assert_secrets_safe(settings); print('ok')"`.
5. Database backup taken on the droplet (`pg_dump`), file name noted: ___.
6. Tell Vijay and other users: everyone signs in again once after deploy.

## Deploy
7. (LOCK) Owner merges to `main` (push to main = deploy).
8. Watch: `GET /health` ok; `GET /api/v1/status` (API key) shows `environment: production`, `trading_mode: paper`.
9. Owner signs in (password and Google). Google lands on the app with no `token=` in the address bar.
10. Vijay buys and closes one practice position in his testing book. Works.

## Apply roles (after deploy, one at a time, each audited)
11. `swingtrade audit-roles`: matches spec section 6.5, no warning lines.
12. (LOCK) Owner decision 2026-10-16: **`sudeeksha` is the only owner**; everyone else is secondary
    (no owner powers, no My Holdings). `REAL_ACCOUNT_USERS` stays `sudeeksha`. Run, in this order:
    `swingtrade set-role --username naresh --role member --reason "owner decision 2026-10-16: sudeeksha only owner"`
    `swingtrade set-role --username vijay --role tester --reason "owner decision 2026-10-16: secondary; testing book only"`
    `swingtrade disable-user --username admin --reason "unknown holder"`
    `swingtrade disable-user --username claude_verify_tmp --reason "leftover test account"`
    `swingtrade disable-user --username claudecheck1787413845531 --reason "leftover test account"`
    (`naresh.gudiganti23` is already a member, no command needed.)
    Then sign in as `sudeeksha` and confirm My Holdings still opens; sign in as `naresh` and confirm
    My Holdings and owner screens are refused.
13. `swingtrade audit-roles` again; `GET /admin/users` shows the same.

Other owner commands: `swingtrade unlock-user --username U`, `swingtrade revoke-sessions --username U`.
`swingtrade create-user` now requires `--role`.

## Rollback
- **Code:** revert the merge on `main` (deploys the previous build). Rehearsed: the old code boots
  on the new schema (its migration step fails on the unknown revision, then it falls back to
  `create_all`) and logins work. See the evidence below.
- **Roles after rollback:** old code reads only `is_superuser`, which mirrors `role`. A tester stays
  non-owner, so Vijay's testing writes are refused on old code. If needed, temporarily
  `swingtrade make-owner vijay` (username is positional; fixed on the next roll-forward via `audit-roles`).
- **Schema (only if required):** `alembic downgrade d8a1y2c3h4k5` drops the new columns and
  tables. The audit trail is lost, so export `audit_log` first.
- **Roll-forward after a rollback:** run `swingtrade audit-roles`. Any warning (accounts created by old
  code get `role=member` with `is_superuser=true`) is fixed with `set-role`.

## Acceptance (release A done when all true)
- [ ] Only `sudeeksha` has `role=owner`; `audit-roles` shows no warning; only `sudeeksha` opens My Holdings.
- [ ] 5 wrong passwords pause sign-in for 15 minutes; message identical for every failure.
- [ ] Password change / sign out everywhere end old sessions.
- [ ] Google sign-in URL never contains a session token.
- [ ] A member account gets 403 on house screens; tester keeps their testing book only.
- [ ] API refuses to start with placeholder secrets outside local.
- [ ] Every sign-in, role, plan and switch change is in `audit_log`.
- [ ] Real-account routes refuse testers and members; `TRADING_MODE`/`ALLOW_LIVE_TRADING` unchanged.

## Observed rehearsal evidence (2026-10-16, scratch DB `swing_trade_ml_p0_rehearsal`, since dropped)

**Migration** (`backend/scripts/rehearse_p0_migration.py`, run on an empty database, whole chain from the
first revision, 7 users shaped like prod):

```
INFO  [alembic.runtime.migration] Running upgrade d8a1y2c3h4k5 -> e1p0s2e3c4u5, P0 security: roles, session versions, sign-in lockout, audit log, login codes
INFO  [alembic.runtime.migration] Running downgrade e1p0s2e3c4u5 -> d8a1y2c3h4k5, P0 security: roles, session versions, sign-in lockout, audit log, login codes
INFO  [alembic.runtime.migration] Running upgrade d8a1y2c3h4k5 -> e1p0s2e3c4u5, P0 security: roles, session versions, sign-in lockout, audit log, login codes
OK P0 migration: upgrade, backfill, downgrade, re-upgrade all as expected
```
Backfill: exactly `naresh`, `sudeeksha`, `vijay` (the three superusers) became `owner`; everyone else `member`.

**Old code (`develop`, pre-P0) on the upgraded schema**, uvicorn on port 8077, `DB_AUTO_MIGRATE=true`:

- Server booted; `curl localhost:8077/api/v1/health` returned
  `{"status":"ok","app":"Swing Trade ML","environment":"local","version":"0.1.0"}`.
- The server's own log stops after the alembic lines (old `alembic/env.py` calls `fileConfig`, which
  silences later app log lines), so the two fallback log lines were not visible in the server log. The same
  startup code (`init_database`: `run_migrations()`, on error `create_all_tables()`) run directly against the
  same database printed:

```
2026-10-16 17:45:50 [info     ] db.migrate.start               alembic_dir='...\backend'
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
db.migrate.failed error= Can't locate revision identified by 'e1p0s2e3c4u5'
2026-10-16 17:45:50 [warning  ] db.create_all.fallback
create_all finished without error
```
  (The `db.migrate.failed` line is the printed exception; in the server it is the `log.warning("db.migrate.failed", error=...)` call.)
- Old CLI `create-user --username rb --password rollback-check-1` succeeded; then
  `POST /api/v1/auth/login` returned **HTTP 200** with an access token.
- `SELECT username, role, is_superuser FROM users WHERE username='rb'` gave `rb | member | t`
  (the mismatch described above; `audit-roles` flags it after roll-forward). `alembic_version` stayed `e1p0s2e3c4u5`.
