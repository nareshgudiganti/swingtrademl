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
