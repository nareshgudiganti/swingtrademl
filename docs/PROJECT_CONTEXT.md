# Project context: Swing Trade ML

Reviewed 2026-09-15 against local commit `dd1f4c4`.

## Scope and evidence

This is a source-based orientation for follow-up questions, not a certification of production behavior or profitability. It covers the repository structure, core trading and ML implementations, API and UI organization, finance services, database models, scheduling, deployment configuration, and selected tests. Existing documentation was compared with code; some comments and documents are stale.

No production database, broker account, deployed website, or model artifact was inspected. Actual environment secrets were not opened. Configuration values below are code defaults, not confirmed operating settings. Application code was not changed during this review.

Repository inventory: 82 backend Python source files, 32 backend test modules, 15 migration files, and 21 frontend TSX files (plus TypeScript helpers, CSS, and native wrapper projects).

## 1. What the application does

A personal Indian-equities trading and finance platform with:

- ML swing signals and a moving-average crossover benchmark.
- Paper and live execution through interchangeable brokers.
- Advisory strategies for tracking trades entered manually, including real holdings while the automated broker remains in paper mode.
- Portfolio valuation, trade reports, confidence monitoring, and signal outcome tracking.
- Long-term stock suggestion scaffolding; an implementation mismatch currently affects evaluation (see gaps below).
- Personal finance statement imports, categorization, spending analytics, loans, recurring bills, and daily expenses.
- Mutual fund holdings, NAV tracking, and CAS statement import.
- Browser dashboard, installable PWA, and Capacitor Android/iOS wrappers.

## 2. Stack and navigation map

| Area | Implementation | Starting point |
|---|---|---|
| Backend | Python 3.11–3.13, FastAPI, Pydantic | `backend/src/swing_trade_ml/main.py` |
| API contracts | Pydantic schemas and versioned routers | `schemas/__init__.py`, `api/v1/router.py` |
| Database | SQLAlchemy, psycopg, PostgreSQL/TimescaleDB, Alembic | `db/models/`, `db/session.py`, `backend/alembic/` |
| Market data | Kite instrument master, candles, quotes | `services/ingestion.py`, `brokers/kite.py` |
| ML | pandas/numpy features, sklearn/LightGBM, joblib artifacts | `ml/features.py`, `dataset.py`, `train.py`, `predict.py`, `registry.py` |
| Decisions | Registered strategy implementations | `strategies/base.py`, `ml_swing.py`, `sma_crossover.py`, `long_term_value.py` |
| Trading | Scan, risk, execution, valuation | `services/engine.py`, `risk.py`, `execution.py`, `portfolio.py` |
| Historical simulation | In-memory strategy replay | `services/backtest.py` |
| Finance | Parsers, ingestion, calculations, CAS/NAV services | `services/finance/`, API `finance.py` and `mutual_funds.py` |
| Automation | APScheduler, Redis-backed worker visibility, Telegram | `workers/`, `notifications/telegram.py` |
| Frontend | React 19, TypeScript, Vite, React Query, Recharts | `frontend/src/App.tsx`, `api/client.ts`, `api/types.ts` |
| Operations | CLI, Compose, nginx, CI/deploy workflows | `cli.py`, root Compose files, `.github/workflows/` |

Backend paths in this document are relative to `backend/src/swing_trade_ml/` unless otherwise stated.

## 3. Main trading flow

1. Ingestion upserts instrument metadata and OHLCV candles; quote refresh supplies current prices.
2. `engine.run_all_active()` selects active strategies matching the broker mode, plus advisory strategies regardless of mode.
3. Each strategy uses its explicit symbol universe or the watchlist. The engine loads its minimum history plus 50 bars and calls `evaluate()`.
4. Strategies return `SignalDecision`: BUY, HOLD, EXIT/SELL, confidence, reason, price, optional stop/target/horizon, and diagnostic features.
5. The engine identifies BUY candidates outside the confidence-ranked slot budget. Execution records decisions and rejection reasons.
6. Entry risk checks account for existing positions, cooldown, position count, drawdown, cash, and sizing limits. Optional pyramiding requires a profitable existing position book.
7. Advisory decisions notify and record suggestions. Auto decisions write an Order before broker submission; synchronous paper fills create Positions immediately.
8. Pending live orders are polled by reconciliation, which finishes Position/Trade bookkeeping when fills complete.
9. Quote updates and exit checks maintain unrealized P&L, highest price, trailing stops, and exits. Closed trades feed portfolio statistics and reports.

Predictions, signals, and trades are different records: a model probability is not automatically a BUY; a BUY may be rejected or advisory; a recorded signal outcome is not realized trade P&L.

## 4. Modes, identity, and risk

- `get_broker()` returns Kite only when both `TRADING_MODE=live` and `ALLOW_LIVE_TRADING=true`; otherwise paper. Kite also checks the live latch before submission.
- Strategy `execution_mode` is independently `auto` or `advisory`. Advisory routing depends on this database field, not a free-form strategy parameter.
- Trading tables carry `mode`; many portfolio queries filter by mode. Strategy comparison endpoints also exist and should be checked individually before assuming universal mode separation.
- Auto strategies are bound to the broker mode when created. New strategies start inactive.
- Dashboard authentication uses bearer JWTs. Scripts may use `X-API-Key`. Username/password signup/login and an allowlisted Google OAuth flow are implemented.
- This is a shared personal application: trading and finance tables inspected do not implement per-user ownership. Authentication should not be mistaken for multi-tenant isolation.

Default risk settings: 1% equity risk per trade, 10% position allocation cap, 10 open positions, 20% drawdown entry breaker, 5-day stop-out cooldown. Fixed-amount sizing is also supported, defaulting to INR 10,000 when selected. Strategy overrides affect some limits; `capital_allocation` acts as a concentration ceiling in the sizer.

Runtime exits: stop, target, 60-calendar-day time stop, or strategy EXIT. Trailing stops ratchet upward using the original entry-to-stop rupee distance. Confidence-decay alerts and manual entry/exit recording are separate capabilities.

Paper costs share functions with backtests: 5 bps adverse slippage, zero delivery brokerage, 11.9 buy/10.4 sell tax bps, and INR 15.93 flat DP charge per sell by default. These are configured approximations. Paper pricing falls back from Kite LTP to stored quote to latest candle close.

## 5. ML and strategies

### Feature and training pipeline

- The current feature list contains **53** columns, rather than the older documented 37.
- Families: trend, momentum, volatility, volume/flow, candle structure, price-extreme recency, streaks, NIFTY relative strength/regime, sector context, INDIA VIX, and watchlist breadth.
- `build_features()` requires five frames: stock, benchmark, sector, VIX, and breadth. Context joins use backward `merge_asof`.
- Training pools symbols and sorts by timestamp. `chronological_split()` takes a row-based 80/20 split by default. The scaler is fitted on training rows only.
- Algorithms: LightGBM, random forest, gradient boosting, logistic regression. LightGBM has an import-failure fallback to gradient boosting.
- Artifacts store estimator, scaler, feature ordering, and label metadata; model rows store versions, training dates/symbols, metrics, and feature importance.
- New models are TRAINED unless activation is explicitly requested. Activation archives the previous active model of that name.

### Current label semantics

New training defaults ask: **does price reach +8% before -4%, within 15 trading bars?**

`build_label()` checks future high/low values. Same-bar target/stop ties count as stops. The final unresolved horizon is removed. New model/prediction rows retain `label_kind="barrier"`; legacy endpoint labels remain supported through the migration and evaluator branch.

Prediction outcome evaluation counts trading bars for barrier models. Signal outcome evaluation uses the signal's own stop/target and a calendar-day horizon. These metrics are not interchangeable.

### Strategy behavior

| Type | Behavior |
|---|---|
| `ml_swing` | Active model probability; default 60% entry and 35% exit thresholds; extra 10 percentage points required in a bearish NIFTY regime; liquidity, volatility, and falling-knife filters; stops/targets at 2x/4x ATR with a stop-width clamp. |
| `sma_crossover` | Moving-average crossing with trend, ADX, RSI, and volume filters; rule-based comparison strategy. |
| `long_term_value` | Intended long-horizon technical classifier: 250-day horizon, 30% target, 20% stop, 65% confidence; fundamentals are not implemented. See evaluation/advisory gaps below. |

Large/mid/small-cap labels derive from model-name suffixes, not a real-time market-cap classification service.

Strategy recommendations use closed-trade statistics: active automatic ML strategies need at least 10 all-time closed trades; ranking uses the last 90 days when that window has at least 3 trades, otherwise all-time, with win rate, profit factor, and net P&L as the ordering.

## 6. Data model

- Market: Instrument -> Candle history and latest Quote.
- Strategy -> Signal -> Order, with Position and Trade attribution. Positions retain entry/exit levels, confidence, unrealized P&L, and trailing-stop state.
- PortfolioSnapshot stores equity history and peak/drawdown inputs.
- MLModel -> Prediction; unique prediction key is `(model_id, instrument_id, ts)` with database upsert.
- User and BrokerSession separate application login from broker token persistence.
- FinanceIngestedFile -> FinanceTransaction; supplementary tables cover loans, recurring bills/payments, daily categories, and custom categorization rules.
- MutualFund -> MutualFundNav and MutualFundHolding; holdings include source metadata for manual versus CAS imports.
- Candle identity is instrument/interval/timestamp. Alembic versions track schema changes, including the latest barrier-label metadata migration.

## 7. Frontend and finance

Main routes: `/dashboard`, `/strategies`, `/holdings`, `/portfolio`, `/reports`, `/scans`, `/finance`. `/models` and `/settings` remain routed but are omitted from the main navigation.

- Dashboard: portfolio overview, ranked ideas, market context, tiered strategy signals, and status.
- Strategies: configuration, activation, scan actions, performance comparisons.
- My Holdings: real Kite holdings and links to tracked advisory positions.
- Portfolio: tracked positions and position actions; Reports: closed trades and grouped results.
- Scan Results: signal track record and outcome details.
- Models: model training/management; Settings: watchlist, ingestion, coverage, scheduler and notification configuration.
- Finance tabs: Statement, Transactions, Calculation, Analysis, Loans, Mutual Funds, Monthly, Daily.

Finance ingestion supports CSV, PhonePe PDFs, and ICICI-style bank PDFs. It hashes files, normalizes transactions, applies keyword rules, and upserts deduplicated rows. Custom rules are merged with bundled CSV rules. Manual overrides, soft deletion/restoration, permanent deletion routes, and bank-versus-PhonePe source reconciliation are present. Internal transfers are excluded from income/expense analytics.

CAS import reconstructs remaining mutual-fund purchase lots using FIFO and rebuilds CAS-sourced holdings for imported scheme/folio pairs while preserving manual holdings. AMFI NAV snapshots populate scheme metadata and append tracked-fund NAV history. This is holdings tracking, not a mutual-fund order execution system.

## 8. Schedule and deployment

Default scheduled times are IST:

| Time | Work |
|---|---|
| Every 60s | Worker heartbeat and broker-session confirmation |
| Weekdays 06:10 | Optional Kite credential/TOTP auto-login |
| Weekdays 06:15–15:45 at :15/:45 | Missing-session reminders, gated by session state |
| Market session, polling interval | Quotes, exits, pending-order reconciliation |
| 15:40 | Daily candle ingestion |
| 15:42 | Watchlist predictions |
| 15:45 | Strategy scan (configurable) |
| 16:00 | Portfolio snapshot and daily summary |
| 16:15 / 16:17 | Prediction / signal outcome evaluation |
| 21:30 weekdays | Mutual fund NAV sync |
| Sunday 08:00 | Instrument sync |

Market checks include known NSE holidays. Jobs have error handling and session checks; schedule presence alone does not prove a job completed.

Compose runs Postgres/TimescaleDB, Redis, API, worker, and frontend. Only the worker enables scheduling. API and worker share model storage. Local Postgres is published on **5433**, whereas the bare code database default uses **5432**.

Startup configures logging, initializes schema, restores broker session, attempts initial watchlist seeding, then starts scheduling when enabled. Migration failure falls back to `create_all()`, which cannot upgrade existing columns.

Production Compose uses the frontend's nginx build. The checked-in GitHub deployment workflow targets an SSH host on pushes to `main`, backs up the database, builds images, migrates, and restarts containers. CI tests pushes to `develop` and PRs; Ruff is advisory and frontend checking uses TypeScript. A separate Render blueprint remains, with database-extension and shared-artifact caveats. These files do not establish which deployment is currently running.

## 9. Observed gaps to retain for follow-up

These are source observations, not fixes made in this review:

1. **Long-term evaluation has an incompatible call.** `long_term_value.py` calls `build_features(d, index_df)`, but the function requires sector, VIX, and breadth frames too. With enough history and an active model, that path will raise a missing-arguments TypeError. Existing selected long-term tests do not exercise this full evaluation path.
2. **Long-term advisory-only is not enforced by its parameter.** `advisory_only=True` in the strategy defaults does not control execution. The API schema defaults `execution_mode` to `auto`; callers must set the database field to advisory. The common 60-day exit/alert rule also conflicts with a 250-day intended holding horizon.
3. **The label/exit alignment is incomplete.** New labels use fixed +8%/-4%/15 trading bars; ML swing still supplies ATR-based stops/targets, has confidence exits, trailing stops, and a 60-day time stop. Signal scoring additionally uses calendar days.
4. **Chronological splitting has no horizon purge.** The row split can separate symbols from the same timestamp across train/test and lets training labels span the test boundary. There is no walk-forward retraining or probability calibration in the inspected training pipeline.
5. **Historical replay is not full runtime parity.** The backtest shares sizing/cost functions but does not apply runtime trailing-stop and cooldown behavior. It uses the currently selected active model, without verifying that training predates the replay window, and fills entries at signal close plus slippage.
6. **Ranking is not strict execution ordering.** The live engine excludes lower-ranked candidates but processes survivors in evaluation order. It estimates capacity before exits; advisory ranking uses the broker mode while execution uses strategy mode. `max_daily_buys` is applied per scan rather than through an all-day purchase ledger.
7. **Live fill edge cases need focused review.** Reconciliation is implemented, but partial fills, crash windows around submission/commit, and concurrent manual/scheduled scans are not proven safe by this orientation. Reconciled sell completion records `ExitReason.MANUAL`, losing the original automated exit cause.
8. **After-close execution needs scrutiny.** The scheduled scan submits regular market orders through Kite; the inspected path does not queue them for the next open or select AMO. Paper can fill from cached prices outside the session. Live behavior should not be inferred from paper success here.
9. **Portfolio diversification controls are limited.** No sector exposure ceiling, correlation cap, or cash-reserve floor appears in entry risk checks. Existing controls focus on positions, cash, and drawdown.
10. **Documentation drift is material.** README/project_understanding still describe older features, targets, authentication or operational limitations. Auto-login, holiday handling, scheduled reconciliation, and the expanded feature pipeline now exist. Some research notes also describe earlier code or unverified production state.

## 10. Verification performed

- Selected backend suite: **54 passed, 1 deselected**. Files: `test_features.py`, `test_risk.py`, `test_safety.py`, `test_backtest.py`, and `test_long_term_strategy.py`; the database-dependent long-term signal test was excluded.
- Frontend: `npm.cmd run typecheck` passed.
- First backend attempt hit an inherited `DEBUG=release` value incompatible with Pydantic's boolean setting. Rerun used a process-local `DEBUG=false`, paper mode, disabled live trading/scheduler/Telegram, and disabled pytest caching. No persistent environment file was changed.
- PowerShell blocked `npm.ps1`; invoking `npm.cmd` completed the check.
- Full integration tests, migrations, browser interaction, native builds, deployment, model training, and broker execution were not run.

For follow-up answers, start with the relevant implementation above and distinguish code defaults, persisted configuration, actual runtime state, model metrics, signal outcomes, and realized trading results.
