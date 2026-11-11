# Integration drill (branch integration/saas-private), 2026-11-11

Chain under test: wlquantity01 -> ownerprivate01 -> usernamemob01 -> authtokens01 -> billing01 (single head billing01).

- `drill_a.py` clean database, full chain, column/table checks, down/up of the last four migrations. Target: `drill_int_clean`.
- `drill_b.py` legacy database built to wlquantity01, seeded (`seed_legacy.py`), upgraded, verified (`verify_upgrade.py`), sign-in (`signin_int.py`, `signin_plans_on.py`). Target: `drill_int_legacy`.
- `C_image.log`, `C_build.log` built image run with `--network none`; no database.
- `drill.log` every command with the database it targeted (TARGET lines). `drill_earlier_run_with_B_expectation_fix.log` is a first run where one check of mine was wrong (a Free member is refused the Pro-only buy-list on main already); the check was corrected, nothing in the app changed.
- Both drill databases were dropped at the end. Passwords in the scripts are synthetic. No connection address is printed or stored.
