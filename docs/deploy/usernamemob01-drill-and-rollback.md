# Migration `usernamemob01` — drill record and rollback notes

Branch `change/user-name-mobile`, drill commit **ae83428**, run 2026-11-10 (local, disposable databases). This file travels with the branch and its pull request. The scripts and logs are in `docs/deploy/evidence/usernamemob01-drill/`.

## What the migration does

Adds three optional columns to `users`: `full_name` (varchar 80), `mobile` (varchar 10, not unique, not indexed) and `email_verified_at` (timestamptz). On the first run only, it sets `email_verified_at` for existing Google accounts that have an email (Google verified that email). Nothing in the app reads `email_verified_at` yet.

## Drill result: PASSED on ae83428

| Part | Result | Evidence |
|---|---|---|
| A. Clean database | PASS. The full chain builds from empty to the single head `usernamemob01`. Columns have the right types, there is no unique or other index on `mobile`, downgrade one step then upgrade again works, and a leftover `ix_users_mobile` from the earlier draft is dropped. | `A_up.log`, `url.py` |
| B. Pre-change accounts | PASS. Six seeded accounts (owner, two local members, two Google users, one tester) all survive with old columns unchanged. Only the Google user with an email gets `email_verified_at`. Logins for the owner, both members and the tester return 200 (also by email). `/auth/me` is correct. Wrong password gives 401, a Google account cannot log in by password, and the lockout still refuses the correct password after 5 wrong tries. A second `upgrade head` is a no-op and does not overwrite a value set by hand. | `seed.py`, `signin.py`, `B_before.txt` |
| C. Built image | PASS. The production-style image builds. Inside it the bundled common-password list loads (491 entries) from `site-packages/swing_trade_ml/core/common_passwords.txt` (5,242 bytes). `passwordpassword` and `short` are rejected, a long passphrase is accepted. The throwaway image was removed. | `c.py`, `C_build.log`, `C_time.log` |

The accounts in `seed.py` are synthetic and exist only in throwaway databases. The strings in `signin.py` (`test-api-key`, `test-jwt-secret`) are placeholders, not real secrets.

## Isolation: what the evidence supports

- The drill ran against exactly two disposable databases, `drill_clean_um` and `drill_legacy_um`, created for the drill inside the local Docker Postgres container and dropped afterwards (a `pg_database` query then returned no matches).
- Connection targets: `url.py` builds the connection address from the test connection details with the database name given as an argument, and alembic and the sign-in script receive it through the `DATABASE_URL` environment variable for that process only. The direct SQL used `psql -d <drill database>`.
- The scripts and logs in this folder show how each step was aimed. They do not by themselves record the database name used in each command, and the Postgres server does not log connections (`log_connections` is off), so there is no server-side proof either. The statement that only the two drill databases were touched rests on the scripts, the cleanup check and the drill's own account of its commands.
- Shared Postgres activity counters (`pg_stat_database`) on the real and test databases changed during the window. Other work was running tests at the same time. Counters do not show what caused activity, so they are **not** used as evidence either way.
- The drill never connected to production.

## ROLLBACK WARNING: downgrading loses saved verification dates

`downgrade()` drops `email_verified_at`, `mobile` and `full_name`. Dropping the column destroys every saved verification date. If you then upgrade again, the backfill re-stamps Google accounts with the time of the new upgrade (`now()`), not their original date, and every email a person verified through the signup flow shows as unverified again.

This does not matter today because nothing reads the column. It matters as soon as email verification is enabled (`REQUIRE_EMAIL_VERIFICATION` on). Before that switch is turned on, the rollback runbook must:

1. Prefer rolling back the **application** image, not the database. The three columns are optional, and older code ignores them, so leaving them in place is harmless.
2. If a database downgrade is truly needed, first save the dates:
   `CREATE TABLE users_email_verified_backup AS SELECT id, email_verified_at FROM users WHERE email_verified_at IS NOT NULL;`
   After re-upgrading, restore them:
   `UPDATE users u SET email_verified_at = b.email_verified_at FROM users_email_verified_backup b WHERE u.id = b.id;`
3. Never run a downgrade with verification enforcement on and no backup, because people could be locked out of sign-in until they verify again.
4. Rehearse this backup and restore once on a disposable copy before verification is enabled in production.

## Release checks tracked separately (not covered by this drill)

| Check | Status | Why it is separate |
|---|---|---|
| Production verification of this migration (applied on the live database, real accounts still sign in, one head on the server) | OPEN | The drill used throwaway databases only. |
| Real Google sign-in end to end | OPEN | The drill seeded Google users straight into the database. It did not exercise the Google OAuth flow. |
| Kite smoke test (login, token, a read-only call) | OPEN | Not touched by the drill. Kite logins go to production only. |
| Rollback runbook updated with the warning above before verification is enabled | OPEN | Must be done before `REQUIRE_EMAIL_VERIFICATION` is turned on. |

## Integration note, 2026-11-11

At integration (branch `integration/saas-private`) the parent of `usernamemob01` changed from `wlquantity01` to `ownerprivate01` (the owner-private migration that reached `main` first). The chain is now `wlquantity01 -> ownerprivate01 -> usernamemob01 -> authtokens01 -> billing01`. The drill above covered `ae83428` on the old parent only and must be re-run on the final integration commit. See `docs/deploy/evidence/integration-drill/`.
