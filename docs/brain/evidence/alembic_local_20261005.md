# Alembic local upgrade — 2026-10-05

## Symptom

`alembic upgrade head` failed with `DuplicateTable: brain_runs` while `alembic_version` showed only the plans branch revision `5a2f9d4e8c13`. Schema already had the main brain tables from an earlier partial path.

## Safe fix (no data drop)

1. Confirm brain tables exist and main-line schema matches at least `p1a2n3s4f5r6` (e.g. `brain_runs.requested_by`, `brain_approvals`, etc.).
2. Add the missing branch revision (only if absent):

   ```sql
   INSERT INTO alembic_version (version_num)
   SELECT 'p1a2n3s4f5r6'
   WHERE NOT EXISTS (
     SELECT 1 FROM alembic_version WHERE version_num = 'p1a2n3s4f5r6'
   );
   ```

3. From `backend/`: `.venv\Scripts\python.exe -m alembic upgrade head`

## Result

- Applied `c7d8e9f0a1b2` (Service 1 P0: `watchlist_snapshots`, `candle_corrections`).
- Merged to `m3r6e5p1s1v1`.

**Prod:** If deploy hits the same fork, use the same insert-then-upgrade pattern after verifying schema; do not `stamp` blindly without checking tables.
