# Deploying to production

Written for: whoever is releasing this bot — including Claude in a future session.

Production is the DigitalOcean droplet behind <https://swingtrademl.com>. There
is no manual deploy step: **pushing to `main` is the deploy.**
`.github/workflows/deploy.yml` re-runs the whole test suite and only releases to
the droplet if it passes, so a red commit cannot reach production.

Prod configuration (`.env`) lives on the droplet at `/root/app/.env` and is *not*
in this repo. Nothing here can change it, and SSH from a dev machine is blocked —
so any fix that has to change prod behaviour must be a **code** change.

## The routine

1. **Branch off the current `origin/main`.** Never off a stale local `main`.

   ```bash
   git fetch origin
   git worktree add -b fix/<short-name> <tmp-dir> origin/main
   ```

   A worktree keeps whatever is half-finished in the main checkout untouched.
   More than one person (or session) edits this repo, so assume the working tree
   is not yours alone.

2. **Make the change, tests first.** See `CLAUDE.md` for the TDD expectation.

   **Branch adds or changes a migration?** Before deploying it, push the branch (not to `main`)
   and run Actions, **Restore drill**, Run workflow with `upgrade_check` ticked and the branch name
   in `ref`. It runs the branch's `alembic upgrade head` on a restored copy of the prod backup (a
   throwaway container, never the live database) and reports the revision before and after.
   Do not deploy if it fails. Details: `docs/QUALITY-CHECKS.md`, "Database upgrade test (qa5)".

3. **Verify — all three, every time.** A green run of the one file you touched is
   not a green suite.

   ```bash
   backend/.venv/Scripts/python.exe -m pytest -q          # needs Docker Postgres up
   cd frontend && npm run typecheck && npm run build
   backend/.venv/Scripts/python.exe -m ruff check <changed files>
   ```

   - The backend suite needs the Docker Postgres on port 5433. If it is down,
     DB tests hang for ~264s and then fail confusingly. A port check is not a
     liveness check — actually connect.
   - If the test DB schema is stale (errors like `column ... does not exist`),
     drop and recreate the schema of **`swing_trade_ml_test` only**.
   - `npm run lint` currently fails for lack of an eslint config. That is
     pre-existing; `typecheck` and `build` are the real gates.
   - Ruff has known pre-existing findings. Compare against `main` (stash and
     re-run) and only fix the ones you added.

4. **Rebase onto `origin/main` again before pushing.** It moves often.

   ```bash
   git fetch origin && git rebase origin/main
   ```

   Then re-run the suite — a clean rebase is not a passing one.

5. **Push, and let CI deploy.**

   ```bash
   git push origin fix/<short-name>:main      # fast-forward = deploy
   ```

   Or open a PR and merge it. Same result; the PR just gives a review surface.

6. **Watch the release, don't assume it.**

   ```bash
   curl -s "https://api.github.com/repos/nareshgudiganti/swingtrademl/actions/runs?per_page=5"
   ```

   Wait for `Deploy to production` on your SHA to reach
   `completed / success`. `script_stop: true` means a failed release step fails
   the run rather than half-applying.

7. **Confirm prod is actually serving it.**

   ```bash
   KEY=$(grep '^API_KEY=' .env | cut -d= -f2-)
   curl -s -H "X-API-Key: $KEY" https://swingtrademl.com/api/v1/status
   curl -s https://swingtrademl.com/api/v1/health
   ```

   `/status` does not expose the released commit, so a green deploy run plus a
   healthy `/health` is the available evidence. The deploy's `smoke` job does
   these checks automatically from outside (and messages Telegram on failure):
   see `docs/QUALITY-CHECKS.md`, "After-deploy smoke test (qa2)". Where the change is
   behavioural, name the observation that will confirm it and when it happens —
   for a scan change, that is the next 15:45 IST run.

8. **Clean up.** `git worktree remove <tmp-dir> --force && git worktree prune`.
   Leave the main checkout as you found it.

## Timing

The scan that trades runs at **15:45 IST, Mon–Fri**. Deploying during market
hours is fine — the scheduler runs inside the app and restarts with it — but a
deploy landing between 15:40 and 15:50 can interrupt the ingest → predict →
scan → fills chain for that day. Prefer outside that window.

## When the push is blocked

Claude Code's auto mode classifies a push to `main` as a production deploy and
blocks it unless the operator has granted permission. Claude **cannot grant
itself that permission** — writing the permission file is itself blocked as
self-modification, by design.

So either the operator merges/pushes, or they add the rules in
`.claude/settings.local.json` themselves (gitignored — never commit deploy
permissions to this public repo). See the "Letting Claude deploy" section of
whatever onboarding note the operator keeps; the rules needed are
`Bash(git push origin *)`, `Bash(git fetch *)` and `Bash(git rebase *)`, with
`Bash(git push --force*)` denied.

## Rollback

Revert the commit and push that — it is the same pipeline, and it re-runs the
tests on the way back:

```bash
git revert <bad-sha>
git push origin HEAD:main
```

Do not force-push `main`. It would skip the tested path and can silently drop
whatever else landed since.

## Database backups and restoring

Every deploy saves `pg_dumpall` output to `/root/backups/release-<time>-<sha>/database.sql`
on the droplet (same server, so it does not survive losing the droplet).

**A plain replay of that file is not a correct restore.** Found in the first restore drill
(2026-10-14): the rows all come back, but `candles` comes back as a plain table instead of a
TimescaleDB hypertable. Restore with Timescale's procedure instead:

1. Create the database and run `create extension timescaledb version '<X>'; select timescaledb_pre_restore();`
   in it, where `<X>` is the TimescaleDB version of the database the dump came from (prod is 2.29.0 as of
   2026-10-14; `select extversion from pg_extension where extname = 'timescaledb'`). A newer Timescale
   fails at step 3 with "catalog version mismatch" (found by the first prod drill, 2026-10-14). The
   `latest-pg17` image tag moves, so a rebuilt server may pull a newer Timescale than the backup's.
2. Replay the dump (`psql -d postgres -f database.sql`). "role / database / extension already exists"
   errors are expected.
3. Run `select timescaledb_post_restore();` in the database.

`infra/deploy/restore-drill.sh` does exactly this in a throwaway container and compares row counts
with the live database (read-only), then removes the container. Run it on the droplet outside market
hours: `bash /root/app/infra/deploy/restore-drill.sh`. It needs free disk space of about twice the
database size. The last result is written to `/root/backups/restore-drill-last.txt`.
