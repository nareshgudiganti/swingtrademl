# Deploying to production

Written for: whoever is releasing this bot — including Claude in a future session.

Production is the DigitalOcean droplet behind <https://swingtrademl.com>. **Pushing
or merging to `main` does not deploy.** The owner starts every release by hand:
Actions, Deploy to production, Run workflow, branch `main`.
`.github/workflows/deploy.yml` re-runs the whole test suite (`test.yml`: backend,
frontend and browser tests) and only releases to the droplet if it passes, so a red
commit cannot reach production. It releases the tip of `main` at the moment the run
starts. Started from any other branch it runs the tests and deploys nothing.

If the "Run workflow" button is missing or `gh workflow run` is refused, the workflow
is switched off in GitHub (Actions, Deploy to production, Enable workflow); only the
owner decides that. While it is off, nothing deploys, and merging still changes nothing
on the server.

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

   The deploy's own gate (`test.yml`) is wider than these three: it also runs
   `npm test`, the browser tests (`npm run e2e:typecheck`, `npm run e2e`), the
   migrations-from-empty check (`backend/scripts/check_migrations.py`) and the
   money-code coverage floor. Ruff and `npm run lint` are advisory there. A branch
   can pass the three above and still fail the deploy.

   - The backend suite needs the Docker Postgres on port 5433. If it is down,
     DB tests hang for ~264s and then fail confusingly. A port check is not a
     liveness check — actually connect.
   - If the test DB schema is stale (errors like `column ... does not exist`),
     drop and recreate the schema of **`swing_trade_ml_test` only**.
   - `npm run lint` currently fails for lack of an eslint config. That is
     pre-existing; `typecheck` and `build` are the real gates.
   - Ruff has known pre-existing findings. Compare against `origin/main` (run the same
     command in a clean worktree of it, never a bare `git stash`) and only fix the ones you added.

4. **Rebase onto `origin/main` again before pushing.** It moves often.

   ```bash
   git fetch origin && git rebase origin/main
   ```

   Then re-run the suite — a clean rebase is not a passing one.

5. **Get it onto `main`, then the owner starts the deploy.**

   ```bash
   git push origin fix/<short-name>          # then a PR the owner merges
   ```

   `main` takes pull requests only (required checks: backend, frontend, e2e and gitleaks; admins
   are bound by the rule; no approval is required), so a direct `git push origin HEAD:main` is refused:
   use a pull request. These settings live in GitHub, not in the repo, so the owner confirms them.
   A merged commit has passed those checks, but the deploy tests the tip of `main` again, so it can
   still fail there.

   When the owner is ready to release, the owner runs Deploy to production on
   `main` (Actions page, or `gh workflow run deploy.yml --ref main`).
   It releases everything merged since the last deploy, and every merged commit must
   pass the tests together, so someone else's red commit blocks your deploy.

6. **Watch the release, don't assume it.**

   ```bash
   curl -s "https://api.github.com/repos/nareshgudiganti/swingtrademl/actions/runs?per_page=5"
   ```

   After the owner starts Deploy to production on `main` (a new run), wait for that run to reach
   `completed / success`. Merging alone starts no run, so if none appears, nothing was deployed.

   A red run does **not** always mean "nothing changed". `infra/deploy/release.sh` builds the
   new images, stops the worker, saves a database dump, runs the migrations, then starts the
   api, frontend and worker and waits up to 3 minutes for a fresh worker heartbeat. If a step
   fails after the worker was stopped, the script tries to put the previous images back and
   start them, but it cannot undo migrations ("Database remains migrated"), and if putting the
   old images back also fails, `release.sh` makes a last attempt with `docker start stml-worker`
   and says so in the run log if even that fails. A failure before the worker was stopped
   (tests, window, disk check, build) leaves the running site as it was, and the script puts
   `/root/app` back on the commit that is running, so the next deploy records the right previous
   commit. A failed or cancelled deploy job sends a Telegram message (the `deploy-failed` job).

   **Expect an uptime alert during a deploy.** The worker is stopped for the database dump and the
   migration, a few minutes, and `uptime.yml` now reads `scheduler_running` from the public
   `/ready` answer without needing the API key. If an uptime check happens to run in that window it
   messages Telegram that the scheduler is not running, and messages again when it is back. That is
   the deploy, not a fault: confirm the deploy run finished green and the next uptime run says all good.

7. **Confirm prod is actually serving it.**

   ```bash
   KEY=$(grep '^API_KEY=' .env | cut -d= -f2-)
   curl -s -H "X-API-Key: $KEY" https://swingtrademl.com/api/v1/status
   curl -s https://swingtrademl.com/api/v1/health
   ```

   `/status` does not expose the released commit, so a green deploy run plus a
   healthy `/health` is the available evidence. The deploy's `smoke` job does
   these checks automatically from outside, but it runs only after the deploy job
   succeeded and messages Telegram when its checks fail. A failed or cancelled deploy job is
   announced by the separate `deploy-failed` job; if that message cannot be delivered its step
   goes red, so open the run either way. The backstop is `uptime.yml`,
   which is scheduled every 10 minutes (GitHub can run it much later), checks the site and the scheduler, and messages Telegram
   (see `docs/QUALITY-CHECKS.md`, "After-deploy smoke test (qa2)"). Where the change is
   behavioural, name the observation that will confirm it and when it happens —
   for a scan change, that is the next 15:45 IST run.

8. **Clean up.** `git worktree remove <tmp-dir> --force && git worktree prune`.
   Leave the main checkout as you found it.

## Timing

The scan that trades runs at **15:45 IST, Mon–Fri**. A deploy restarts the worker,
so `deploy.yml` **refuses** to deploy on weekdays between **09:00 and 16:30 IST**
unless the run is started with "force" ticked (emergency fixes only). Start the
deploy as a NEW run after 16:30 IST, never by re-running an old run: a re-run
redeploys that run's old commit, not the current `main`.

## When the push is blocked

A push or merge to `main` no longer deploys, but Claude Code's auto mode still
classifies a push to `main` as a production change and blocks it unless the operator has granted permission. Claude **cannot grant
itself that permission** — writing the permission file is itself blocked as
self-modification, by design.

So either the operator merges/pushes (and then starts the deploy by hand), or they add the rules in
`.claude/settings.local.json` themselves (gitignored — never commit deploy
permissions to this public repo). See the "Letting Claude deploy" section of
whatever onboarding note the operator keeps; the rules needed are
`Bash(git push origin *)`, `Bash(git fetch *)` and `Bash(git rebase *)`, with
`Bash(git push --force*)` denied.

## Rollback

Revert the commit on a branch, merge the revert by pull request, then the owner starts a
NEW Deploy to production run on `main`. It is the same pipeline, and it re-runs the tests
on the way back, so a red test also blocks a rollback:

```bash
git fetch origin
git switch -c revert/<short-name> origin/main
git revert <bad-sha>                  # for a merge commit: git revert -m 1 <merge-sha>
git push origin revert/<short-name>   # then a pull request; main is protected
gh workflow run deploy.yml --ref main # the owner, after the revert is merged
```

- Never start the rollback by re-running the old good run: a re-run redeploys that run's
  own commit, which silently drops everything merged since.
- Weekdays 09:00 to 16:30 IST the run is refused unless "force" is ticked; tick it for an
  emergency rollback.
- A revert changes code only. Migrations that already ran stay applied (`release.sh` never
  downgrades), so check that the older code works on the newer schema first.
- Merging the revert does not change production. Until the new run succeeds, production is
  still running the bad commit.

Do not force-push `main`. It would skip the tested path and can silently drop
whatever else landed since.

## Database backups and restoring

Every deploy that gets as far as stopping the worker saves `pg_dumpall` output to
`/root/backups/release-<time>-<first 12 characters of the sha>/database.sql` on the droplet
(`release.sh` writes it after the build and before the migrations; same server, so it does
not survive losing the droplet). The nightly backup job keeps that dump for only the 5
newest releases; older release folders keep `rollback.json` and `previous-sha` only.

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
