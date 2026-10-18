# Quality checks: what runs automatically, and what to do when one fails

Tracker section `qa` (System Atlas). Each check below says when it runs, what it protects,
and what to do if it goes red.

## Secret scan (qa3): `.github/workflows/secret-scan.yml`

- **When:** every push to any branch, every pull request.
- **What:** gitleaks scans the whole git history for keys, tokens and passwords. Rules and the
  allowlist of known-fake values: `.gitleaks.toml`. Output is redacted.
- **If it fails:** the repo is public, so treat the secret as already stolen.
  1. Rotate it first (new Kite API secret, new Telegram bot token, new `JWT_SECRET_KEY`, …).
  2. Only then remove it from the code. Deleting the line does not remove it from history.
  3. If it is a fake value used in a test, add that exact value (never a path or whole rule) to
     the allowlist in `.gitleaks.toml`, with a comment saying why it is fake.

## Library audit (qa4): `.github/workflows/dependency-audit.yml` + `.github/dependabot.yml`

- **When:** Mondays 09:00 IST, and on pull requests that change dependencies.
- **What:** pip-audit on a fresh backend install (same as the Docker build); npm audit on the
  frontend lockfile. Dependabot opens weekly update PRs (never merged automatically).
- **Fails on:** any backend finding not on the ignore list; high/critical issues in frontend
  code that ships to the browser. Build/test-only tools are shown but do not fail the run.
- **Ignore list:** in the workflow header, each with a reason. Re-check monthly; remove an entry
  as soon as a fixed version exists.
- **Known, not yet fixed (2026-10-18):** vitest 3 (test runner only) needs vitest 5, which needs
  a Vite major upgrade; @capacitor/cli (phone build tool). Neither ships to prod.

## After-deploy smoke test (qa2): `smoke` job in `.github/workflows/deploy.yml` + `infra/deploy/smoke.py`

- **When:** right after every successful deploy to production (push to `main`).
- **What:** from outside the server, as a visitor would, with GET requests only (it never logs in,
  scans or places an order, and never prints response bodies):
  - `/api/v1/health` and `/api/v1/ready` answer 200;
  - `/api/v1/status` answers 200 and says **paper** trading. A live trading mode (or the live
    trading switch on) fails at once, without retries: going live is the owner's call only;
  - `/api/v1/brain/stage` and `/api/v1/risk/limits` answer 200;
  - the pages `/` and `/trademind` load (200, the app's HTML).

  Containers are still restarting just after a deploy, so failing checks are retried for about
  2.5 minutes (waits of 5, 10, 20, 30, 30, 30 seconds). `release.sh` already checks the release
  from inside the droplet (`verify.py`: database migrated, fresh worker heartbeat); this is the
  outside view.
- **Secrets:** `API_KEY` (repository secret) for the status, brain-stage and risk-limit checks;
  without it those are skipped with a warning and only the public checks run.
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for the alert (the same ones `uptime.yml` uses).
- **If it fails:** a Telegram message names what failed. Open Actions, Deploy to production, the
  `smoke` job. If the site is broken, revert the commit and push (see `docs/DEPLOY.md`, Rollback).
  If it says the bot is NOT in paper mode, check `TRADING_MODE` / `ALLOW_LIVE_TRADING` in the
  server's `.env` immediately.
- **Run by hand:** `python3 infra/deploy/smoke.py` (public checks only without `API_KEY` set).

## Database upgrade test (qa5): Restore drill workflow with "upgrade_check"

- **When:** by hand, **before deploying a branch that adds or changes a migration**
  (`backend/alembic/versions/`). Actions, Restore drill, Run workflow: tick `upgrade_check`, and
  put the branch name in `ref`. Outside 09:00-16:30 IST on weekdays.
- **What:** `infra/deploy/restore-drill.sh` restores the newest prod backup into a throwaway
  Postgres container, checks row counts, then runs that branch's `alembic upgrade head` on the
  restored copy and prints the database revision before and after (and the branch's head).
  Python and libraries come from the live API image; the code and migrations from `ref`.
- **Safety:** the migration can only reach the throwaway server: it runs inside the throwaway
  container's isolated network (no route to the live database), the script checks that network
  mode, and a guard refuses to migrate unless the server it reached carries a marker database
  created only in the throwaway copy. The live `.env` is never loaded. (The restored database has
  the same name as the live one, because the backup recreates it, so the guard is on the server,
  not the name.)
- **If it fails:** the output names the failing migration and the SQL error. Fix the migration on
  the branch and re-run before merging; do not deploy it. A branch that adds a new Python library
  fails at import here: that case can only be checked by a real build.
- **Note:** the drill script itself runs from the deployed code on the droplet, so this check
  exists only once this change is on `main`. Last result: `/root/backups/restore-drill-last.txt`.
