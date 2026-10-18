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

## Bad-data drills (qa6): `backend/tests/test_bad_data_drills.py`

- **When:** with the backend test suite (CI and local; the database drills need Postgres).
- **What:** each drill runs the same day twice, once with clean data and once with one fault,
  and checks the faulty run is **never bolder**: no stock's word goes up
  (AVOID < WAIT < WATCH < TRADE), no TRADE gets bigger, no extra TRADEs, the banner is at least
  as careful (NO_NEW_TRADES < DEFENSIVE < NORMAL), and the run still finishes.
  The database drills use the real M01 data gateway, M07 risk gate and M08 decision engine.

| Drill | Fault | What it proves |
|---|---|---|
| Missing prices | one stock / every stock has no price; no NIFTY history; a stock with no candles; today's bar missing for one stock, for everyone; NIFTY missing; a 5-day gap | the stock is WAIT or refused (`DATA`); market-wide gaps give NO NEW TRADES |
| Stale data | ingest did not run for a week; only NIFTY stale; 2 of 6 stocks stale; Monday run with Friday bars | NO NEW TRADES, banner says the data is not reliable |
| Kite down | margins/LTP calls raise during a live-book brain run; LTP raises at the market open and when approving | no stock approved (cash counts as 0); an approved idea expires, nothing is bought |
| Module crash | M01, M07, M08, a reasoning plug-in raise; each of the 15 installed modules raises in turn in a full run; modules over their time budget | the run completes, the module is marked dropped, fallbacks answer |
| Risk gate missing | M07 not installed, crashes, too slow, bad output, stored as OFF/SHADOW, an impostor plug-in writes verdicts | NO NEW TRADES, no TRADE, the brain strategy gets no buyable signal |
| Reader/DB fails | the database reader raises mid-run | the run is stored as failed; no run today means the strategy says HOLD |
| Garbage | NaN / out-of-range opinion and quality values, decisions with no reason or the wrong vocabulary, NaN or zero close in the database | dropped as bad output or treated as no data |

- **Known bugs (xfail, strict; not fixed because the trial is frozen):**
  1. **M10 crash makes the run bolder.** The fallback judges the market from the NIFTY trend
     only and ignores breadth: DEFENSIVE becomes NORMAL, M07 drops its defensive limits
     (2 ideas, half size) and approves every liked stock at full size.
  2. **Probability above 1 is accepted.** `contracts.validate_record` checks stance and
     confidence but not `probability`; 7.0 counts as liked and a WAIT becomes a TRADE.
  3. **A decide module's TRADE is not sanity-checked.** NaN stop/target and a huge quantity pass
     the constitution when the verdict is allowed and the data is fresh.
  4. **NaN model score with M08 down.** The decide fallback's `p < threshold` is False for NaN,
     so it drafts a TRADE; the constitution lowers it only to WATCH (no-score baseline: WAIT).
- **If a drill fails:** the brain got bolder (or crashed) on bad data. Do not loosen the test.
  Fix the fallback so it stays careful, with the owner's approval (trial freeze). When a known
  bug is fixed, its xfail turns into an unexpected pass: remove the xfail mark.

## Browser and accessibility tests (qa1, qa10): `frontend/e2e/` + job `e2e` in `.github/workflows/test.yml`

- **When:** every push to `develop` and every pull request (same triggers as the other test jobs).
- **How it runs:** Playwright builds the app into `frontend/dist-e2e/`, serves it with `vite preview`
  and drives Chromium. There is **no backend**: every `/api/v1/...` call is answered by
  `frontend/e2e/support/mockApi.ts` from the JSON in `frontend/e2e/fixtures/` (paper mode, made-up
  values). Anything not in the fixtures gets a 404, and every change request (buy, sell, halt, …)
  gets a 403, so a test can never place or change anything, and nothing can reach production.
- **Journeys (qa1, `journeys.spec.ts`):**
  1. Sign in with username and password (and a wrong password, and logging out).
  2. Today: market mode, idea counts, holdings needing attention, top ideas, insights.
  3. Stock page: opened by tapping a top idea; chart, brain decision, tabs.
  4. Portfolio: all four tabs open, each with the right Paper / Real strip.
  5. Admin: the owner opens all six Admin pages; a non-owner sees no Admin, no Testing and no
     real-money tab, and owner addresses send them back.
  6. Phone width (390 x 844): no sideways scrolling on the main pages; the menu and page tabs
     work by tapping.
  Any uncaught JavaScript error on a page fails the test.
- **Accessibility (qa10, `a11y.spec.ts`):** axe (WCAG 2.0/2.1 A and AA, plus 2.2 AA) scans sign-in,
  Today, a stock page, the four Portfolio tabs and Admin (Control), once with the browser in light
  mode and once in dark. It **fails on serious or critical problems** (for example poor contrast or
  a button with no name). At phone width, the section menu, page tabs and top-bar buttons must be at
  least 24 x 24 px (WCAG 2.2 target size), and the icon-only account button must have a name a
  screen reader can read. The TradeMind screens have one dark theme whatever the browser setting,
  so the light and dark scans differ only where the browser's own colours apply.
- **Known debt:** `frontend/e2e/a11y-allowlist.json` lists problems that exist today, each with the
  rule, the page and a TODO. Listed problems do not fail the check; anything new does. When the run
  prints an `allowlist-entry-now-passes` note, delete that entry. Today (2026-10-18) it holds two
  colour-contrast items (the blue Sign in button, and grey table headings), left for the owner to
  approve because fixing them changes how the app looks.
- **Run it locally** (in `frontend/`): `npx playwright install chromium` once, then `npm run e2e`.
  `npm run e2e:typecheck` checks the test code's types. One spec: `npx playwright test e2e/a11y.spec.ts`.
- **If it fails:** the list output names the step and the missing text, or the axe rule, element
  and contrast numbers. If a screen changed on purpose, update the text the test looks for (or the
  fixture). If the screen now calls a new endpoint, add it to `mockApi.ts` with a fixture. Do not
  add a new axe problem to the allowlist to make CI green; fix it, or ask the owner first.
  Nothing (traces, screenshots, reports) is uploaded from CI: the repo is public.
- **Known issue found while writing these tests (not fixed here, app behaviour):** for the owner,
  loading a `/trademind/...` address directly (bookmark, refresh) lands on Today instead of that
  page, because the app decides before the account status has arrived. The tests therefore load
  Today first and then move inside the app (`openPage` in `e2e/support/test.ts`).
