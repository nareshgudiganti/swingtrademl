# F3 test report (agent 4, QA)

Run: 2026-11-26 (IST), on origin/main `36bb2830` (PR #513 merge), detached worktree. No product code changed.

## Counts

| Suite | Result |
|---|---|
| Backend, non-DB subset (143 of 441 test files, 20 min 8 s) | **2475 passed, 34 skipped, 2 xfailed, 0 failed, 0 xpassed** |
| Backend, DB tests (the other ~298 files) | **NOT RUN** (see below) |
| Frontend `tsc --noEmit -p .` | clean (exit 0) |
| Frontend `vitest run` | **95 files, 1297 tests, all passed** |
| Browser (Playwright, mocked API) | **92 passed**: today, score-wording, score-trail-models, deep-link, a11y specs |

Backend summary line: `2475 passed, 34 skipped, 2 xfailed, 1 warning in 1208.37s (0:20:08)`.

## Failures, xfail, xpass

No failures, no xpass. Two xfails, both known gaps:

- (b) `backend/tests/test_horizon_385_mixup.py:44`: issue #385. The live run request never names the scoring model's horizon, so a 5-day score is stamped 15. Documented in the file header as a strict-xfail pin; it will flip to a failure when fixed.
- (b) `backend/tests/test_scoreboard_independent.py:931`: `h05_rules.random_k_distribution` returns 200 x 0.0 with no usable pool, so the report shows random_5 range [0.0, 0.0] instead of "not measured". Marked DEFECT in the xfail reason. No issue number is cited in the xfail reason. Strictness at line 931 not confirmed by me (only the first file's docstring says strict).

34 skips: reasons were not printed (`-rs` not used); not investigated.

## Why DB tests were not run

`DATABASE_URL` was not set in the process environment, and the brief forbids reading `.env`. Docker shows a Postgres on 5433 (`stml-postgres`) and the dev stack, but I did not point tests at them without an explicit test URL. The non-DB subset was chosen by grep: files that mention none of `db_session|client|db_engine|SessionLocal|get_db|sessionmaker|engine`. This is a heuristic, so a few DB-free tests that use `client` are also excluded. A first attempt with a 580 s timeout was killed and discarded; the numbers above are from the full re-run.

## Browser validation

Playwright's own config builds the app and serves it with `vite preview` on port 4174, with every `/api/v1` call answered by `e2e/support/mockApi.ts`. No backend, DB, login or Kite, and nothing can reach production. Covered: Today (owner, tester, member, phone width 390 px, no sideways scroll), stock page `/trademind/stock/ITC` and score trail for KEC, deep links, and the a11y spec. Console errors were not separately captured and no screenshot was taken: the config has screenshots off and I may write no spec files. The a11y spec passing is the closest check.

## NOT run

- Backend DB tests (about 298 files).
- Full Playwright suite: only 5 of the 17 spec files ran (journeys, saas-journey, deletion, tax-export, horizon-report, manual-test, tour, alerts-bell, order-safety, real-orders-badge, brain-no-run were not).
- Real-backend browser check (needs a DB and login).
- Stock-page screenshot.
