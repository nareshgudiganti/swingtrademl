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

## Money-code coverage floor (qa8): `backend/scripts/check_money_coverage.py`

- **When:** every backend test run in CI (`test.yml`, after pytest writes `coverage.json`).
- **What:** fails the build if the share of tested lines drops below **95%** in any of the money
  files: `services/risk.py`, `services/limits.py`, `services/exit_policy.py`,
  `services/execution.py`, and `brokers/` (`__init__`, `base`, `paper`, `kite`).
- **Where it stood (2026-10-18):** risk 100%, limits 98.8%, exit policy 100%, execution 99.4%,
  brokers 98.7-100%. New tests: `tests/test_money_*.py` (77 tests; Kite is always a fake, nothing
  reaches Zerodha; "live" mode is switched on in memory only to prove the paper latch refuses).
- **If it fails:** a change to money code arrived without tests. Add tests for the uncovered lines
  (the CI log lists each file's figure). Never lower a floor to make a build pass.
