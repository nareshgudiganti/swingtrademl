# Final drill: integrated revision `acctdelete01` (branch change/saas-final, PR #202)

Run 2026-11-11, local, disposable databases only. Scripts and logs: `docs/deploy/evidence/final-drill/`
(adapted from `integration-drill/`; database names `drill_fin_clean`, `drill_fin_legacy`).

## Chain under test

`wlquantity01` -> {`ownerprivate01`, `f11m0d3l5c0r3`} -> `mergeheads01` -> `usernamemob01` -> `authtokens01` -> `billing01` -> {`servicekeys01`, `adminmfa01`} -> `acctdelete01` (single head; `acctdelete01` is the join, so no extra merge revision is needed). `downgrade -1` is ambiguous at both join points, so every step uses an explicit revision.

## Migration drill: PASSED

| Part | Result | Evidence |
|---|---|---|
| A. Clean database | PASS (36 checks). Empty to single head `acctdelete01`, all expected columns and tables (including `service_keys`, `admin_mfa`, `admin_recovery_codes`, `account_deletions`), no index on `users.mobile`. Explicit down: `billing01` (the four new tables vanish, billing tables stay), `authtokens01`, `usernamemob01`, `mergeheads01`, `ownerprivate01`, `wlquantity01`; back up through `mergeheads01`, `usernamemob01`, `authtokens01`, `billing01`, `head`; all objects return. | `drill.log` (DRILL A PASS), `drill_a.py` |
| B. Legacy database | PASS. Built to `wlquantity01`, seeded 6 users, 8 strategies, 8 instruments, 8 signals, 3 score-history rows, upgraded to `acctdelete01`. Row counts unchanged, `owner_private` backfill correct (private and visible sets), only Google-with-email users get `email_verified_at`, `model_name` backfilled. Logins return 200 for owner, members, tester (also by email), a wrong password gives 401, Google accounts cannot use a password. Plans off and plans on visibility as expected. | `drill.log` (DRILL B PASS), `seed_legacy.py`, `verify_upgrade.py`, `signin_*.py` |
| C. Built image | PASS. Production image built from `backend/`, run with `--network none` (no database). `common_passwords.txt` is in `site-packages/swing_trade_ml/core/` (5,242 bytes, 491 entries); `passwordpassword` and `short` refused, a long passphrase accepted; `alembic heads` inside the image is `acctdelete01`. Image removed afterwards. | `C_image.log`, `C_build.log`, `c.py` |

A second `upgrade head` on the legacy database is a no-op: drill B ran `upgrade head` once on the seeded database and the row counts and checks after it match; no separate second-run check was added in this drill (the earlier drills covered it for `usernamemob01`).

## Isolation: what the evidence supports

- Only `drill_fin_clean` and `drill_fin_legacy` were created, used and dropped. Every command that touches a database goes through helpers that assert the name is one of those two and log a `TARGET db=<name>` line first (`drill_common.py`, `drill.log`).
- The connection address is never printed or stored. The maintenance database `postgres` was used only to run CREATE and DROP of the two names.
- After the run, `select count(*) from pg_database where datname like 'drill_%'` returned 0 (`dropped_proof.txt`), and the throwaway image no longer exists.
- Postgres activity counters are not used as evidence. The drill never connected to production.

## Full backend suite on this revision

- CI run `42982375200` on PR #202 (no `-x`): **2 failed, 5872 passed, 89 skipped, 1 xfailed.** Both failures are real and come from combining the branches, not flaky:
  1. `tests/test_plans_route_coverage.py::test_every_route_is_classified`: the 8 new `/admin/console/*` routes (admin console, PR #199) are not classified in the route-coverage test. They are guarded by `require_admin_user` and `require_admin_mfa`, which the test does not recognise as an owner-style check.
  2. `tests/test_service_keys.py::test_migration_chains_from_billing01_and_head_is_single`: asserts the head is `servicekeys01`; the head is now `acctdelete01`. Same kind of stale assertion as the one already fixed in `test_user_name_mobile.py`.
- A local run with `-x` stopped on failure 1 after 4002 passed (11 min); it saw nothing else before stopping.
- No production code needs to change for either. Both are test updates: add the two admin dependency names to the route-coverage test's recognised checks (or list the routes with a reason), and change the head assertion in `test_service_keys.py` to accept `acctdelete01`. They were **not** applied on this branch; they need an owner-visible decision on how the route-coverage test should classify admin-console routes.
