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
