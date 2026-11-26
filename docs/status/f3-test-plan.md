# Feature 3 (#228) test plan, prepared 26 Nov 2026 (IST), base origin/main fa55809d

Nothing was run. This is a plan only.

## Blockers
1. **Test database.** Docker Postgres `stml-postgres` is up on port 5433, but no database named `swing_trade_ml_test` exists (only `swing_trade_ml_356_test`, `_batch_test`, `_candle_test`, `_dev1_groww_test`). Create one for Feature 3 (see DB below). The owner supplies the password.
2. **Full-suite slot.** The owner allows two heavy suites at once across Features 1-3, so Feature 3 must wait for a free slot.
3. **Implementation complete** (the suites run once, at the end).
4. **Real-backend browser run needs a seeded user and data.** I found no seed script (not confirmed absent). See Browser.

## DB requirement
- Postgres only. `backend/tests/conftest.py` forces safe env via `tests/_env_safety.py`: paper mode, scheduler and Telegram off, credentials blanked, DB_AUTO_MIGRATE off.
- Guard `core/db_guard.py::assert_local_test_database` refuses the run unless the host is localhost, there are no URL query parameters, and the database name **ends with `_test`** (stricter than "contains").
- Schema comes from `Base.metadata.create_all` once per session, not Alembic. Each test runs in a rolled-back transaction.
- Create: `docker exec stml-postgres psql -U swingtrade -d postgres -c "CREATE DATABASE swing_trade_ml_f3_test;"`
- Run: `DATABASE_URL='postgresql+psycopg://swingtrade:<PASSWORD>@localhost:5433/swing_trade_ml_f3_test' backend/.venv/Scripts/python.exe -m pytest ...`. Tests then run with `env -u API_KEY -u JWT_SECRET_KEY -u TRADING_MODE`. Never unset DATABASE_URL.

## Browser requirement
- Normal e2e (`frontend/playwright.config.ts`) needs **no backend, DB or Kite**. It builds into `dist-e2e` and serves via `vite preview` on port 4174. Every /api/v1 call is answered by `e2e/support/mockApi.ts`. Run in `frontend/`: `npx playwright install chromium` once, then `npm run e2e`.
- Real-backend integration is possible but not scripted. Steps: (1) start uvicorn locally on a free port such as 8020 (8000 and 5173 are held by the main-local containers, 5180/8010 by stable) with DATABASE_URL set to the f3 test database, TRADING_MODE=paper, ENABLE_SCHEDULER=false, DB_AUTO_MIGRATE=false, API_KEY and JWT_SECRET_KEY set to throwaway values, Kite and Telegram blank. (2) Create the tables with the test conftest's create_all. (3) Run vite with `VITE_API_BASE_URL=http://localhost:8020/api/v1` on a free port such as 5190. (4) Seed a user, an instrument with candles, and a brain run.
- Missing: the seeding script, and a login path that works without Google or Kite.

## Selected tests
Backend, DB-backed (about 175 tests): test_beginner_stock (18), test_display_gaps_474 (22), test_verify_238_5d_ideas_screens (14), test_admin_model_overview (6), test_stock_score_history (9), test_idea_report (16), test_brain_public_verdict (12), test_horizon_report (9), test_market_session (20), test_p0_sessions (8), test_p0_plan_audit (1), test_brain_m12_stock (27, mostly pure).
Backend, pure (about 28 tests): test_plan_percentages_from_brain_policy (5), test_brain_plan_gate (2), test_horizon_385_mixup (3, strict xfail), test_horizon_guard (3), test_model_card (8), test_stock_compare (7), plus the xfails in test_brain_evidence_verification.
Frontend vitest, all pure and fast (about 150 tests): AdminModels, IdeaCard, oneCard, StockBrief, StockSearch, fiveDayIdeaScreens, horizonLabels, horizons, HorizonSelector, IdeaExplain, IdeaReports, scoreVsPlan, stepDetails, stockLink, stockScoreToday, verify240 (chart, quote and dated-close states), whyNoTradeCard.
Playwright, mocked: journeys (18), score-wording (11), a11y, today, tour, deep-link, score-trail-models, horizon-report, manual-test.
Estimates: selected backend about 3-6 minutes, vitest about 1-2, e2e about 5-8 (including the build).

## Expected failures
| File:line | Cites | Issue status |
|---|---|---|
| test_verify_238_5d_ideas_screens.py:224 | #385 | open issue |
| test_verify_238_5d_ideas_screens.py:261 | #416 | open issue |
| test_verify_238_5d_ideas_screens.py:276 (idea list and plain answers use different runs, G3) | none | **no own issue**; described in #486 (From #238) |
| test_horizon_385_mixup.py:44 | #385 | open issue |
| test_brain_evidence_verification.py:497 and :509 | #385 | open issue |
| frontend/src/trademind/verify240.test.tsx:131 (it.fails, undated close, G4/G6) | none | **no own issue**; described in #486 (From #240) |
| fiveDayIdeaScreens.test.ts:60 (comment only: three word helpers) | none | **no own issue**; described in #486 (From #238) |

Skips in the selection are conditional on the environment only (no local candles, PowerShell or bash missing). They are not Feature 3 gaps.
Needing an issue with root-cause evidence: the three "none" rows. #486 is an umbrella defect list, so create one child issue per gap. #385 and #416 are broad feature or core issues, so confirm each cited xfail is listed in them. The 11 other repo xfails (5d flow scenarios, market context and others) belong to Features 1 and 2 or to Core and are out of scope.

## Resource schedule (max two heavy suites at once, across F1-F3)
1. Heavy 1: the F3 backend selection (DB, f3 test DB), run alone for its DB. Run it in parallel with the F3 vitest and mocked e2e, which are light and need no DB. Count the e2e build as one heavy slot.
2. The full backend suite (about 20 minutes for 143 non-DB files, plus the DB files) is one heavy slot and must not share a database with another run, so give each feature its own `_test` database. Run it serially after the selected tests pass.
3. The real-backend browser run goes last, after the suites. It uses its own ports and the f3 database, so stop the DB tests first.
