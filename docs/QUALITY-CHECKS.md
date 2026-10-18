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
