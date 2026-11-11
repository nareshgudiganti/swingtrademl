# Integration drill (branch integration/saas-private), 2026-11-11

Chain under test (updated 2026-11-11 after main gained a second head): wlquantity01 -> {ownerprivate01, f11m0d3l5c0r3} -> mergeheads01 -> usernamemob01 -> authtokens01 -> billing01 (single head billing01). `alembic downgrade -1` is ambiguous at the merge point, so drill A steps down with explicit revisions.

- `drill_a.py` clean database, full chain, column/table checks, down/up of the last four migrations. Target: `drill_int_clean`.
- `drill_b.py` legacy database built to wlquantity01, seeded (`seed_legacy.py`), upgraded, verified (`verify_upgrade.py`), sign-in (`signin_int.py`, `signin_plans_on.py`). Target: `drill_int_legacy`.
- `C_image.log`, `C_build.log` built image run with `--network none`; no database.
- `drill.log` every command with the database it targeted (TARGET lines). `drill_earlier_run_with_B_expectation_fix.log` is a first run where one check of mine was wrong (a Free member is refused the Pro-only buy-list on main already); the check was corrected, nothing in the app changed.
- Both drill databases were dropped at the end. Passwords in the scripts are synthetic. No connection address is printed or stored.

## Run 2, 2026-11-11 (after `mergeheads01` joined the two heads on main)

- `drill_a.py` now steps down with explicit revisions (billing01 -> authtokens01 -> usernamemob01 -> mergeheads01 -> ownerprivate01 -> wlquantity01, `downgrade -1` being ambiguous at the merge point) and back up (mergeheads01 -> usernamemob01 -> authtokens01 -> billing01). Target: `drill_int_clean`. PASS.
- `drill_b.py` seeds 3 `stock_score_history` rows (so `f11m0d3l5c0r3` runs on data: `model_name` backfilled to `swing_v7`, `swing_v7` and empty for the row with no version) besides the users and strategies. Target: `drill_int_legacy`. PASS.
- Both databases dropped afterwards. The built image (C) was NOT rebuilt in run 2; run 1's image result covered the earlier chain. `alembic heads` for run 2 is in `drill.log`.
- The new run starts at the `=== RUN 2` line in `drill.log`; run 1 above it is kept.
