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

## Error watch (qa9): `backend/src/swing_trade_ml/core/error_watch.py` + `services/server_health.py`

- **When:** counting is always on (every ERROR log line, API and worker). The comparison runs in
  the brain daily check, trading days 16:20 IST, stored in `/brain/daily-checks`.
- **What:** each ERROR is counted in the existing Redis by a short "kind": logger name + event
  name (numbers replaced by `#`), the job name for `job.failed`, and the exception class. Only kind
  and count are stored, never the message, so no secret can land there. One Redis hash per day
  (`errwatch:day:YYYY-MM-DD`, kept 35 days). An "error day" ends at 16:20 IST, so errors after the
  check count toward the next one. The check reads every day since the previous stored check
  (Monday reads the weekend) and compares with the 14 days before.
- **Shows:** `Errors logged` (info: count and kinds); one `New kind of error` warning per kind not
  seen in those 14 days. Warnings reach Telegram through the daily check's message, e.g.
  `CHECK New kind of error: swing_trade_ml.brain.service: brain.run.failed (ValueError) (3 times)`.
- **Safe by design:** Redis down never breaks logging (swallowed; counting rests for a minute).
  If the check cannot read Redis it shows a warning instead. Off switch: `ERROR_WATCH_ENABLED=false`.
- **If it warns:** search the logs for the event name (`docker compose logs worker api | grep
  <event>`), find the cause. Once fixed, it stops counting; a kind already seen is not repeated
  unless it comes back after 14 quiet days. The first check after deploy lists every kind as new
  (there is no history yet).

## Disk and memory alarm (qa11): `backend/src/swing_trade_ml/services/server_health.py`

- **When:** in the brain daily check, trading days 16:20 IST (not weekends or holidays).
- **What is measured:** the code runs in the worker container. **Disk** = the filesystem holding
  `MODEL_ARTIFACT_DIR` (the `model_data` named volume). Docker keeps all named volumes, including
  `postgres_data`, under `/var/lib/docker` on the droplet's own disk, so on this single-disk server
  it is the disk Postgres writes to. **Memory** = `/proc/meminfo`, which in a container without a
  memory limit (none is set) shows the host. **Database size** = `pg_database_size(current_database())`.
- **Thresholds:** `Server disk` warns above 80% used, fails above 90% (Postgres stops when the
  disk is full). `Server memory` warns below 10% available; skipped where there is no
  `/proc/meminfo` (Windows dev). `Database size` is info only. Warn/fail reach Telegram through
  the daily check's message.
- **If disk warns:** check `docker system df`; prune old images (`docker image prune`), old
  backups, old logs (`docker` json logs grow without limit unless rotated). If the database
  itself is the bulk, look at the biggest tables before deleting anything.
- **If memory warns:** `free -m`, `docker stats`; a stuck training job or the frontend dev
  server are the usual suspects. Resize the droplet if it keeps happening.

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

## Request limits (qa7): `backend/src/swing_trade_ml/api/rate_limit.py`

- **What:** each visitor's address (IP) may make only so many requests a minute. Over the limit
  they get "Too many attempts from your connection. Please wait … and try again." (HTTP 429, with a
  `Retry-After` header saying how many seconds to wait).
- **Sign-in endpoints — 10 a minute per IP, one shared counter:** password sign-in
  (`/auth/login`), sign-up, password change, Google sign-in (`/auth/google/login`, `/callback`,
  `/exchange`) and Kite login (`/auth/kite/login`, `/auth/kite/callback`). A Google sign-in uses 3
  of the 10, a Kite login 2.
- **No-login endpoints — 60 a minute per IP:** `/auth/options` and `/`. `/health` and `/ready` are
  never limited: uptime and the after-deploy check call them, and a 429 there would look like an outage.
- **Works with the account lockout (P0), does not replace it:** the lockout pauses one account for
  15 minutes after 5 wrong passwords, whoever is guessing. The request limit stops one address
  trying many accounts, or flooding the public endpoints.
- **Where to change it:** `RATE_LIMIT_ENABLED`, `RATE_LIMIT_AUTH_PER_MINUTE`,
  `RATE_LIMIT_PUBLIC_PER_MINUTE`, `RATE_LIMIT_TRUSTED_PROXIES` in `core/config.py` (override in
  `.env`). A limit of 0 switches that group off.
- **How it counts:** one Redis key per (group, IP, minute), `INCR` + `EXPIRE`. No new service.
- **If Redis is down:** requests are **allowed** (fail open) and a warning
  `rate_limit.redis_unavailable_allowing` is logged; Redis is then left alone for 30 seconds. A
  broken counter must never stop the owner signing in.
- **Which IP:** prod traffic arrives through the host nginx and Docker, so every request looks like
  it comes from Docker's 172.x gateway. The real address is read from `X-Forwarded-For`, but only
  when the request came from one of our own proxies (loopback / private addresses). The right-most
  entry that is not our own proxy is used: nginx appends the address it saw to the end, while
  anything further left was written by the visitor and can be faked. `X-Real-IP` is used only when
  there is no `X-Forwarded-For`. This relies on the host nginx's `/api/` block sending
  `X-Forwarded-For $proxy_add_x_forwarded_for` (the standard `include proxy_params;` does).
- **Tests:** the suite runs with limits off (`tests/conftest.py`); `tests/test_rate_limit.py`
  switches them on with an in-memory Redis stand-in.
- **If users report "Too many attempts":** check the api log for `rate_limit.refused` (shows IP and
  count). If every user shares one IP there, nginx is not passing `X-Forwarded-For` — fix nginx,
  or raise `RATE_LIMIT_AUTH_PER_MINUTE` until it is fixed.
