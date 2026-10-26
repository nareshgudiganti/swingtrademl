# fd-protocol-v1 layer 1 — run notes (2026-10-26)

- Run once, from the signed tagged commit 271eb1c, owner's conditional GO (option a) of 2026-10-26.
- Database: Docker Postgres on port 5433 (system identifier verified); the Windows PostgreSQL on 5432 was not used. Candles: local development copy, ending 2026-09-06.
- Attempt 0 (`attempt0_launcher_failed_no_state_written.txt`): my launcher connected to port 5432 and failed in 6 seconds at the first query, before any ledger row, model or output existed. Not a run. The only change before the real run was patching the loaded database setting in the launcher (outside the repo). No tool, setting, date or guard changed.
- The manifest says "uncommitted changes present" because the tool writes the exposure-ledger row (a tracked file) before it computes the manifest. No code file was modified (git status showed only the ledger row and this folder).
- Side effects: 21 `fd_h5_*` models registered in the local database with status TRAINED (none activated). No orders, no change to the 15D trial.
- Result: both parts FAIL under the signed rule (see five_day_2023-07-01_2025-01-31.md). No re-run, no tuning.
