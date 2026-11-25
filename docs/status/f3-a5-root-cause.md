# F3 / A5 root cause: idea list and plain answers read different runs (G3b)

Investigated 2026-11-25 (IST), read-only, from origin/main 36bb2830. Nothing run against prod or the DB; code reading only.

## Root cause
The idea list (Today, Discover, Stock Detail list, AI Analysis, all through `useLatestRun`) calls `GET /brain/runs/latest?kind=nightly`, which runs `service.latest_run` with no book filter and orders by `started_at`. Stock Detail's plain answers (`/beginner/stock/{symbol}`) use `beginner_views._latest_nightly`, which keeps only the PAPER book and orders by `as_of`, then `started_at`. Two helpers were written for the same idea ("the latest run"), with different book and ordering rules, so when a non-paper-book run (or a run with a later `started_at` but earlier `as_of`) exists, the two screens pick different runs. It is a bug (an unintended duplicate rule), not a deliberate separation: `_latest_nightly`'s own docstring says it mirrors `strategies.brain.todays_run`, which is paper-only by design, while the endpoint was never aligned.

## Query table
| Reader | File:line | Book | Order | Status / other |
|---|---|---|---|---|
| Frontend `useLatestRun` (Today, Discover, Stock Detail, AI Analysis, StockLink) | frontend/src/trademind/live.ts:46, api client.ts:794 | none (sends only `kind=nightly`) | server decides | server: done + live |
| `GET /brain/runs/latest` -> `service.latest_run` | api/v1/endpoints/brain.py:267-275; brain/service.py:426-435 | NONE | `started_at` desc | done, live (replays off), kind=nightly |
| `GET /brain/runs/{id}` | endpoints/brain.py:278 | n/a (by id) | n/a | none |
| Plain answers `_latest_nightly` | services/beginner_views.py:355-372 (used :419) | PAPER only | `as_of` desc, `started_at` desc | done, live, nightly |
| Bot/shadow `todays_run` | strategies/brain.py:42-58 | caller's book | `started_at` desc | done, live, nightly, IST day only |
| Daily check / weekly health | brain_daily_check.py:313, brain_weekly_health.py:130 | none (uses `latest_run`) | `started_at` | done, live |

The test `test_the_idea_list_and_the_plain_answers_use_the_same_run_when_a_live_book_run_is_newest` (backend/tests/test_verify_238_5d_ideas_screens.py:274-287, strict xfail) adds a `book="live"` run 5 minutes newer and asserts both run ids match. Its reason text says "for the owner"; the code shows the endpoint has no principal-based book rule at all (`_run_out` only hides holdings for non-owners), so the gap applies to everyone.

## Did #498 / #499 / #506 change it?
No. #498 (d59f32d9) touched `beginner_views.py` for plan percentages only; #499 and #506 did not touch `latest_run`, `_latest_nightly` or the endpoint (git log on the three files since 20 Nov shows only d59f32d9 and #413). The xfail is still strict, so it is still expected to fail.

## Frozen files (backend/tests/trial_freeze.json, `files` map)
- brain/service.py: FROZEN (holds `latest_run`).
- strategies/brain.py: FROZEN.
- api/v1/endpoints/brain.py: not frozen.
- services/beginner_views.py: not frozen.

## Proposed minimal fix (not implemented)
Make the endpoint use the same rule as the plain answers, without editing frozen `brain/service.py`:
1. endpoints/brain.py:267-275: when `kind == "nightly"` (the only kind the frontend sends), select via a small local query matching `_latest_nightly` (done, live, `book == PAPER`, order `as_of desc, started_at desc`); or better, move `_latest_nightly` to a shared unfrozen helper and call it from both places (beginner_views.py:355 and the endpoint). Other kinds keep `service.latest_run`.
2. Flip the test at line 274 from xfail to a normal test.
Trial behaviour: the trial writes runs and orders through frozen `service`/`strategies/brain.py`, which are untouched, so no trade or scoring behaviour changes. It is a read-path change: the idea list would stop showing a live-book run. In paper mode no live-book nightly run should exist, so on prod the screens likely already agree (not verified). Owner approval is still needed before main; no sizing/stop/limit code is touched.

## Not verified
- Did not run the test suite or the xfail (no DB/Docker started).
- Did not check whether any non-paper-book nightly run exists on prod or locally; so the real-world frequency of the mismatch is unknown.
- The `as_of` vs `started_at` ordering difference can also split the screens (e.g. a later re-run of an older as_of); not exercised by any test.
- `/brain/runs` list and observatory queries were not compared.
