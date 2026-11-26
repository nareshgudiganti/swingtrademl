# #258 Inventory of data, signal, portfolio and execution interfaces

Parent: #237. Baseline: main `897da862`. Read-only inventory: no behaviour changed. Every `file:line` is the definition line as of the baseline and is not pinned by a test (the names, parameters and routes are).

## In plain English

- The app has four layers: data comes in, signals are produced, positions and equity are tracked, and orders are placed. This page lists every public door into each layer, who walks through it, and what it promises.
- **Orders can be placed from a small, fixed set of places.** All paper orders go through `get_broker().place_order` in `open_position` and `close_position`. The only code that talks to the real broker's order call is `_place_real_holding_order`, reached only from the owner-only real-holdings buy and sell routes. A test now fails if a new call to an order method appears anywhere else.
- **Manual positions do not place orders.** `manual_open_position` and `manual_close_position` only record what the owner did elsewhere.
- **Candles have one writer** (`_upsert_candles`), and the Brain reads candles only through `DatedReader`, bounded by the run's `as_of`.
- **Frozen files.** The `Frozen` column comes from `backend/tests/trial_freeze.json`: the scan engine, `DatedReader`, `run_brain`, risk and limits are frozen. Execution, brokers, ingestion, portfolio, ledger and records are not.
- **Things worth a look** are listed in the last section.

Column key: **Intended caller** says who the app means to serve. How each route is enforced is not published here (held back for the owner). "No (internal)" means it is not a route.

## 1. Data in

How prices and side data get into the database, and the one reader the Brain uses. Every candle is stamped IST midnight (18:30 UTC the day before); readers must convert with `.astimezone(IST).date()`.

| Interface | file:line | Inputs | Outputs | Called by | Calls | Point-in-time and idempotency | Intended caller | Frozen |
|---|---|---|---|---|---|---|---|---|
| `services/ingestion.py::sync_instruments(db, exchange, equity_only)` | services/ingestion.py:143 | db, exchange, equity_only | count of instruments | POST /instruments/sync (background), startup (main.py), job_sync_instruments, CLI | Kite instrument dump; writes `instruments` | Re-runnable upsert. No point-in-time notion (a master list). | Owner | no |
| `services/ingestion.py::set_watchlist(db, symbols, exchange)` | services/ingestion.py:208 | db, symbols, exchange | matched symbols | PUT /instruments/watchlist, POST /instruments/watchlist/reset, startup, job_sync_instruments, CLI | writes `instruments.is_watchlisted` | Replaces the whole set each call. Stores the symbol text, not the stock ID (known gap, #249). | Owner | no |
| `services/ingestion.py::backfill_instrument(db, instrument, interval, days, incremental)` | services/ingestion.py:438 | db, instrument, interval, days, incremental | bars written | backfill_watchlist, backfill_symbols, backfill_index, POST /market-data/backfill | Kite history; `_upsert_candles` | Idempotent (overlap is by design). Incremental asks only for the gap since the newest stored bar. | Owner | no |
| `services/ingestion.py::backfill_watchlist(db, interval, days, incremental)` | services/ingestion.py:502 | db, interval, days, incremental | bars per symbol | job_daily_ingest, POST /market-data/backfill, CLI | backfill_instrument | Same as above. Long-running; job use only. | Owner | no |
| `services/ingestion.py::backfill_symbols(db, symbols, interval, days, incremental)` | services/ingestion.py:518 | db, symbols, interval, days, incremental | bars per symbol | job_daily_ingest (strategy-owned symbols) | backfill_instrument | Same as above, independent of the watchlist flag. | No (internal) | no |
| `services/ingestion.py::_upsert_candles(db, instrument_id, interval, bars)` | services/ingestion.py:344 | db, instrument, interval, bars | bars written | backfill_instrument only | writes `candles`, `candle_corrections`, `candle_arrivals` | The only writer of `candles` in the package. Idempotent upsert; a changed bar is logged as a correction, a first sighting as an arrival. | No (internal) | no |
| `services/ingestion.py::refresh_quotes(db)` | services/ingestion.py:557 | db | count of quotes updated | job_refresh_quotes, POST /market-data/refresh-quotes | broker quote call; writes `quotes` (one row per stock, updated in place) | Latest-only table: no history, no as-of. Open positions are polled too. | Owner | no |
| `services/market_feeds.py::run_daily_feeds(db, today)` | services/market_feeds.py:343 | db, today | FeedRun | daily market feeds job (3 passes), POST /market-data/feeds/refresh | NSE bhavcopy, deals, FII/DII, events, restrictions loaders | Each feed isolated; a missing bhavcopy for a trading day is left for the retry. Rows carry their own dates. | Owner | no |
| `services/market_feeds.py::load_bhavcopy(db, day)` | services/market_feeds.py:135 | db, day | rows added or None | run_daily_feeds, backfill_bhavcopy | fetch, parse_bhavcopy; writes delivery rows | Keyed by day; re-run adds nothing. | No (internal) | no |
| `services/market_feeds.py::backfill_bhavcopy(db, start, end)` | services/market_feeds.py:385 | db, start, end | counts by day | POST /market-data/feeds/backfill (background) | load_bhavcopy | Same as above. | Owner | no |
| `services/market_feeds.py::backfill_history_step(db, today, lookback_days, max_fetches)` | services/market_feeds.py:406 | db | step result | daily feeds job | load_bhavcopy | One bounded step per run. | No (internal) | no |
| `services/market_feeds.py::feed_status(db)` | services/market_feeds.py:431 | db | latest date and count per feed | GET /market-data/feeds/status | reads feed tables | Read only. | No (internal) | no |
| `services/quote_snapshot.py::build_snapshot(now, quote, candles)` | services/quote_snapshot.py:172 | now, quote, candles | Snapshot (state, price, price time) | GET /market-data/snapshot/{symbol} | none (pure) | Pure; the clock is passed in. States are fresh, stale, closed, missing. | No (internal) | no |
| `services/quote_snapshot.py::candle_points(rows, tz)` | services/quote_snapshot.py:77 | rows, tz | list of CandlePoint | GET /market-data/snapshot/{symbol} | none (pure) | Converts to IST dates. | No (internal) | no |
| `GET /market-data/quote/{symbol}` | api/v1/endpoints/market_data.py:72 | symbol, exchange | latest quote row | frontend | reads `quotes` | Latest only; no as-of. | Owner | no |
| `GET /market-data/snapshot/{symbol}` | api/v1/endpoints/market_data.py:87 | symbol, exchange | price snapshot | frontend | build_snapshot | As of the request time. | Owner | no |
| `GET /market-data/ltp` | api/v1/endpoints/market_data.py:120 | symbols | symbol to price map | frontend | get_broker().get_ltp | Live broker call (paper broker asks Kite for the price). | Owner | no |
| `GET /market-data/candles/{symbol}` | api/v1/endpoints/market_data.py:49 | symbol, interval, range | candles | frontend | reads `candles` | No as-of: returns what is stored. | Owner | no |
| `POST /market-data/refresh-quotes` | api/v1/endpoints/market_data.py:157 | none | message | frontend / scripts | refresh_quotes | Writes quotes. | Owner | no |
| `POST /market-data/backfill` | api/v1/endpoints/market_data.py:163 | symbols, interval, days | 202 message | frontend / scripts | backfill_instrument or backfill_watchlist (background) | Idempotent. | Owner | no |
| `POST /market-data/feeds/refresh` | api/v1/endpoints/market_data.py:135 | none | feed run result | frontend / scripts | run_daily_feeds | Idempotent per day. | Owner | no |
| `POST /market-data/feeds/backfill` | api/v1/endpoints/market_data.py:141 | days | 202 message | frontend / scripts | backfill_bhavcopy (background) | Idempotent. | Owner | no |
| `POST /instruments/sync` | api/v1/endpoints/instruments.py:59 | none | message | frontend / scripts | sync_instruments (background) | Re-runnable. | Owner | no |
| `PUT /instruments/watchlist` | api/v1/endpoints/instruments.py:91 | symbols, exchange | instruments | frontend | set_watchlist | Replaces the whole watchlist. | Owner | no |
| `POST /instruments/watchlist/reset` | api/v1/endpoints/instruments.py:111 | none | message | frontend | set_watchlist(default list from settings) | Replaces the whole watchlist. | Owner | no |
| `brain/reader.py::DatedReader(self, db, as_of, live, asof_model)` | brain/reader.py:45 | db, as_of, live, asof_model | reader bound to as_of | brain.service.run_brain, pit_replay, market_mode_history, GET /brain endpoints (last_close), CLI | all Brain database reads | Every candle read is bounded by `Candle.ts <= as_of`. Live-only inputs are refused when `live` is false. | No (internal) | yes |
| `brain/reader.py::DatedReader.universe(self)` | brain/reader.py:59 | none | tuple of symbols | brain modules, run_brain | reads instruments | Universe at run time. | No (internal) | yes |
| `brain/reader.py::DatedReader.instrument_id(self, symbol)` | brain/reader.py:73 | symbol | id or None | brain modules | reads instruments | Symbol text lookup. | No (internal) | yes |
| `brain/reader.py::DatedReader.last_close(self, symbol)` | brain/reader.py:77 | symbol | (date, close) or None | brain modules, GET /brain price check | reads candles | Bounded by as_of; IST date. | No (internal) | yes |
| `brain/reader.py::DatedReader.ohlcv(self, symbol, n)` | brain/reader.py:89 | symbol, n | DataFrame | brain modules | reads candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.context_frames(self, symbol)` | brain/reader.py:113 | symbol | dict of DataFrames | brain modules | reads index and sector candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.refresh_context_if_stale(self)` | brain/reader.py:143 | none | None | run_brain (live runs) | ensure_context_index and backfill | Live runs only; the one write-capable path in the reader. | No (internal) | yes |
| `brain/reader.py::DatedReader.recent_bars(self, symbol, n)` | brain/reader.py:163 | symbol, n | DataFrame | brain modules | reads candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.action_days(self)` | brain/reader.py:189 | none | dict symbol to set of days | brain modules | reads corporate actions | Dated. | No (internal) | yes |
| `brain/reader.py::DatedReader.event_rows(self, symbols)` | brain/reader.py:202 | symbols | rows | brain modules | reads events | Dated by event date, bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.restriction_rows(self, symbols)` | brain/reader.py:214 | symbols | rows | brain modules | reads restrictions | Dated. | No (internal) | yes |
| `brain/reader.py::DatedReader.delivery_rows(self, symbols, days)` | brain/reader.py:229 | symbols, days | dict of rows | brain modules | reads delivery rows | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.deal_rows(self, symbols, days)` | brain/reader.py:250 | symbols, days | rows | brain modules | reads bulk deals | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.feed_latest(self)` | brain/reader.py:273 | none | dict of latest feed dates | M01 quality | reads feed tables | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.dated_closes(self, symbol)` | brain/reader.py:291 | symbol | Series | brain modules | reads candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.dated_bars(self, symbol)` | brain/reader.py:305 | symbol | DataFrame | brain modules | reads candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.experience(self)` | brain/reader.py:314 | none | DataFrame | brain modules | reads stored outcomes | Dated. | No (internal) | yes |
| `brain/reader.py::DatedReader.index_closes(self)` | brain/reader.py:320 | none | Series | brain modules | reads index candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.sector_closes(self)` | brain/reader.py:323 | none | dict of Series | brain modules | reads sector candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.vix_closes(self)` | brain/reader.py:335 | none | Series | brain modules | reads volatility index candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.breadth_series(self)` | brain/reader.py:338 | none | Series | brain modules | reads candles | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.fii_net(self, days)` | brain/reader.py:347 | days | list of floats | brain modules | reads FII/DII rows | Bounded by as_of. | No (internal) | yes |
| `brain/reader.py::DatedReader.portfolio_numbers(self, book)` | brain/reader.py:362 | book | dict or None | brain modules | reads positions and snapshots | Live state; replays use PointInTimeReader instead. | No (internal) | yes |
| `brain/reader.py::DatedReader.system_state(self)` | brain/reader.py:380 | none | SystemState | brain modules | reads system state | Live state. | No (internal) | yes |
| `brain/reader.py::DatedReader.holdings(self, book)` | brain/reader.py:388 | book | tuple of Holding | brain modules | reads open positions | Live state; replays use PointInTimeReader. | No (internal) | yes |
| `brain/reader.py::DatedReader.model_bundle(self, name, version)` | brain/reader.py:418 | name, version | dict or None | brain modules | reads stored model files | Version-pinned. | No (internal) | yes |
| `brain/reader.py::DatedReader.model_probability(self, symbol)` | brain/reader.py:460 | symbol | (probability, confidence, source) or None | brain modules (M06) | model bundle, candles | Uses candles bounded by as_of. | No (internal) | yes |

## 2. Signals

Where an idea or a score is produced and where it is recorded. The v1 scan and the Brain are separate producers; the horizon records and the score ledger are append-only evidence tables.

| Interface | file:line | Inputs | Outputs | Called by | Calls | Point-in-time and idempotency | Intended caller | Frozen |
|---|---|---|---|---|---|---|---|---|
| `services/engine.py::run_strategy(db, strategy, interval)` | services/engine.py:115 | db, strategy, interval | ScanResult | run_all_active, POST /strategies/{strategy_id}/scan, brain_golive shadow scan | load_candles, strategy.evaluate, execution.process_decision, score_history.record_stock_scores | Reads whatever candles are stored (no age check). Records every decision, including rejected ones. | Owner | yes |
| `services/engine.py::run_all_active(db, interval)` | services/engine.py:230 | db, interval | ScanResult | job_signal_scan, POST /strategies/scan-all, CLI | run_strategy for each active strategy | Skips strategies of the wrong mode; advisory strategies never place orders. | Owner | yes |
| `services/engine.py::eligible_instruments(db, strategy)` | services/engine.py:39 | db, strategy | list of instruments | run_strategy | reads instruments | Universe at scan time. | No (internal) | yes |
| `strategies/base.py::BaseStrategy.evaluate(self, df, instrument, db)` | strategies/base.py:51 | df, instrument, db | SignalDecision or None | run_strategy, backtest | strategy-specific | Pure over the frame it is given. | No (internal) | yes |
| `strategies/ml_swing.py::MLSwingStrategy.evaluate(self, df, instrument, db)` | strategies/ml_swing.py:90 | df, instrument, db | SignalDecision or None | run_strategy | model prediction | Uses the frame it is given. | No (internal) | yes |
| `strategies/brain.py::BrainStrategy.evaluate(self, df, instrument, db)` | strategies/brain.py:187 | df, instrument, db | SignalDecision or None | run_strategy | reads today's Brain decision (todays_decisions) | Reads a stored Brain run; places nothing itself. | No (internal) | yes |
| `strategies/brain.py::to_signal(d, run, price, practice)` | strategies/brain.py:116 | decision, ... | SignalDecision | BrainStrategy.evaluate | none (pure) | Maps a Brain word to a signal; blocked-by-risk ideas never become a BUY. | No (internal) | yes |
| `brain/service.py::run_brain(db, kind, as_of, symbols, book, registry, run_id, on_step, asof_model)` | brain/service.py:86 | db, kind, as_of, symbols, book, registry, run_id, on_step, asof_model | (context, run_id) | job_brain_nightly, job_brain_intraday, job_brain_strategy, brain queue, replay_week, validation, GET /brain/why, CLI | DatedReader, module registry, `_store` | Past `as_of` makes it a replay with no live-only inputs. The only writer of brain runs and decisions. | Owner | yes |
| `brain/service.py::latest_run(db, kind, include_replays)` | brain/service.py:426 | db, kind, include_replays | BrainRun or None | brain endpoints, strategies/brain | reads brain_runs | Read only. | No (internal) | yes |
| `brain/service.py::decisions_for(db, run_id)` | brain/service.py:437 | db, run_id | list of decisions | brain endpoints | reads brain_decisions | Read only. | No (internal) | yes |
| `brain/service.py::overrule(db, decision_id, word, reason, by)` | brain/service.py:484 | db, decision_id, word, reason, by | BrainDecision | brain endpoint | writes the decision's overrule fields | Only toward caution (refused otherwise). | Owner | yes |
| `brain/service.py::set_mode(db, module_id, mode, by, note, known_ids, mandatory_ids)` | brain/service.py:54 | db, module, mode, ... | module state | brain endpoints | writes module state | Mode changes are recorded. | Owner | yes |
| `brain/service.py::health(db)` | brain/service.py:511 | db | dict | GET /brain/health | reads runs | Read only. | No (internal) | yes |
| `brain/horizons/workflow.py::run_horizon(horizon, outputs, session, sessions, symbol, policies, research_caller)` | brain/horizons/workflow.py:91 | horizon, outputs, session, sessions, symbol | HorizonRecord | services/horizon_nightly.py | none (pure) | One horizon per call; only a matching, approved model is used; no made-up stock. | No (internal) | no |
| `brain/horizons/workflow.py::run_all_horizons(session, outputs, sessions, store, symbol, policies, research_caller)` | brain/horizons/workflow.py:163 | outputs, session, sessions, symbol | three HorizonRecords | none in the package (tests only) | run_horizon x3 | 5D, 10D and 15D run independently and are never joined. | No (internal) | no |
| `services/horizon_nightly.py::record_day(db, session, policies, finalize)` | services/horizon_nightly.py:247 | db, session, policies, finalize | DaySummary | job_horizon_nightly, tests | record_prediction, horizon_records.save_record | Safe to run again; ACTIVE models only. Does not commit. | No (internal) | no |
| `services/horizon_nightly.py::job_horizon_nightly(now)` | services/horizon_nightly.py:294 | now | dict or None | scheduler (via register) | record_day | Never raises into the worker; off unless enabled. | No (internal) | no |
| `services/horizon_records.py::save_record(db, record, security_id, model_id, scan_key, run_ref, input_cutoff, config_version)` | services/horizon_records.py:98 | db, record, security_id, ... | SaveResult | horizon_nightly, save_for_symbol | writes `horizon_records` | A retry is a no-op; a changed result becomes the next revision. Append-only. | No (internal) | no |
| `services/horizon_records.py::save_for_symbol(db, record, **kwargs)` | services/horizon_records.py:151 | db, record, **kwargs | SaveResult | horizon_nightly (no-data path), tests | identity resolve, save_record | Unknown stock refused; nothing written. | No (internal) | no |
| `services/horizon_records.py::records_for(db, security_id, view, horizon_days, since, until, product_only)` | services/horizon_records.py:160 | db, security_id, view, ... | list of rows | screens, simulation source | reads `horizon_records` | Views: latest, first (the evidence), all. | No (internal) | no |
| `services/horizon_records.py::product_records(db, security_id, **kwargs)` | services/horizon_records.py:196 | db, security_id, **kwargs | list of rows | customer screens | records_for(product_only) | Leaves out research-only rows. | No (internal) | no |
| `services/identity/ledger.py::append_score(db, security_id, session_date, source, score, horizon_days, model_name, model_version, status, model_id, scan_key, input_cutoff, run_ref, note)` | services/identity/ledger.py:76 | db, security_id, session, horizon, model, score, status, ... | LedgerResult | append_missing, append_from_brain_run, score_history.append_to_ledger | writes `score_ledger` | A retry is a no-op; a changed value is the next revision. Append-only. | No (internal) | no |
| `services/identity/ledger.py::append_missing(db, security_id, session_date, source, reason, horizon_days, model_name, model_version, scan_key, status)` | services/identity/ledger.py:130 | db, security_id, session, ... | LedgerResult | append_missing_for_universe | append_score(status=missing) | A gap is a row, never a 0. | No (internal) | no |
| `services/identity/ledger.py::append_missing_for_universe(db, session_date, universe_security_ids, scored_security_ids, source, reason, horizon_days, model_name, model_version, scan_key)` | services/identity/ledger.py:159 | db, sessions, ... | rows written | score_history.append_to_ledger | append_missing | Same. | No (internal) | no |
| `services/identity/ledger.py::history(db, security_id, view, horizon_days, source, since, until)` | services/identity/ledger.py:191 | db, security_id, view, ... | list of rows | screens | reads `score_ledger` | Views: latest, first, all. | No (internal) | no |
| `services/identity/ledger.py::session_state(db, security_ids, session_date, horizon_days, source, model_name)` | services/identity/ledger.py:227 | db, security_ids, session | dict | screens | reads `score_ledger` | None means not in any scan; missing/stale rows are gaps. | No (internal) | no |
| `services/identity/ledger.py::append_from_brain_run(db, run_id)` | services/identity/ledger.py:263 | db, run_id | rows written | none in the package (tests only) | append_score | A re-run of the same run is a no-op; on-demand why runs skipped. | No (internal) | no |
| `services/identity/ledger.py::backfill_from_stock_scores(db, since)` | services/identity/ledger.py:309 | db, since | rows written | none in the package (tests only) | append_score | Manual backfill from the older table. | No (internal) | no |
| `services/score_history.py::record_stock_scores(db, scores, exit_confidence, today, universe)` | services/score_history.py:174 | db, scores, exit_confidence | rows written | engine.run_strategy, held_read | writes `stock_scores`, then append_to_ledger | One row per stock, day and model; same model replaces, other model adds. Never raises (own savepoint). | No (internal) | no |
| `services/score_history.py::append_to_ledger(db, sessions, latest, universe)` | services/score_history.py:256 | db, sessions, latest, universe | rows written | record_stock_scores | ledger.append_score, append_missing_for_universe | Never raises; old table untouched. | No (internal) | no |
| `services/score_history.py::record_score(db, position_id, score, exit_confidence, model_version, today, entry_score)` | services/score_history.py:70 | db, position, score, ... | ScoreRecord | execution._check_confidence_decay, held_read, brain_position_score | writes `position_scores` | Replaces the same day's row; worsening compared to the last earlier day. | No (internal) | no |
| `services/execution.py::record_signal(db, strategy, instrument, decision, mode, quantity)` | services/execution.py:123 | db, strategy, instrument, decision, ... | Signal | process_decision | writes `signals` | Every decision is recorded, accepted or rejected, with the reason. | No (internal) | no |
| `services/execution.py::make_signal_key(strategy, instrument, decision, mode, now)` | services/execution.py:65 | strategy, instrument, decision, mode, now | key text | record_signal, process_decision (retry paths) | none (pure) | One scan decision is one key: strategy, stock, mode, type, horizon and trading session. The session is the last closed trading day of `now`, so a retry after midnight maps to the session it belongs to. | No (internal) | no |
| `services/beginner_views.py::latest_nightly(db)` | services/beginner_views.py:355 | db | BrainRun or None | GET /brain/runs/latest, idea screens | reads `brain_runs` | The newest finished live nightly run of the paper book, whoever asks; replays, why-runs, intraday and failed runs never count. | No (internal) | no |
| `api/v1/endpoints/signals.py::buy_fresh_since(now)` | api/v1/endpoints/signals.py:142 | now | datetime (UTC) | GET /signals/top-picks, GET /signals/buy-list | market calendar | A BUY is fresh for at most 4 completed trading sessions; the cutoff counts back from the last closed session and skips weekends and holidays. | No (internal) | no |
| `POST /strategies/{strategy_id}/scan` | api/v1/endpoints/strategies.py:283 | strategy_id, interval | ScanResponse | frontend / scripts | engine.run_strategy | Synchronous; may place paper orders for auto strategies. | Owner | no |
| `POST /strategies/scan-all` | api/v1/endpoints/strategies.py:300 | interval | ScanResponse | frontend / scripts | engine.run_all_active | Same. | Owner | no |

## 3. Portfolio

Positions, trades, equity points and the simulation store. Paper and real books share the tables; the book is told apart by strategy (see `exclude_hand_books`).

| Interface | file:line | Inputs | Outputs | Called by | Calls | Point-in-time and idempotency | Intended caller | Frozen |
|---|---|---|---|---|---|---|---|---|
| `services/portfolio.py::mark_to_market(db, mode)` | services/portfolio.py:149 | db, mode | positions marked | job_refresh_quotes, job_daily_summary, POST /portfolio/snapshot, POST /portfolio/capital-added | reads `quotes`; writes position prices | Reads the cached quote, not the broker. A stale quote is used as it is (no age check; see #240). | No (internal) | no |
| `services/portfolio.py::take_snapshot(db, mode)` | services/portfolio.py:200 | db, mode | PortfolioSnapshot | job_daily_summary, POST /portfolio/snapshot, POST /portfolio/capital-added | writes `portfolio_snapshots` | Upsert on the calendar date: a re-run replaces the day's row. | No (internal) | no |
| `services/portfolio.py::portfolio_value_and_cash(db, mode, bot_book_only)` | services/portfolio.py:77 | db, mode, ... | (value, cash) | execution, risk, screens | reads positions | Read only. | No (internal) | no |
| `services/portfolio.py::equity_curve(db, mode, days, all_time)` | services/portfolio.py:716 | db, mode, days, all_time | points | GET /portfolio/equity-curve | reads snapshots | Clipped to the current paper trial unless all_time. | No (internal) | no |
| `services/portfolio.py::drawdown_peak(db, mode)` | services/portfolio.py:372 | db, mode | float or None | risk checks | reads snapshots | Peak since trial start. | No (internal) | no |
| `services/portfolio.py::performance_stats(db, mode, bot_book_only, all_time)` | services/portfolio.py:404 | db, mode, ... | dict | screens, weekly report | reads trades and positions | Read only. | No (internal) | no |
| `services/portfolio.py::strategy_performance_stats(db, strategy_id, since)` | services/portfolio.py:621 | db, strategy_id, ... | dict | screens | reads trades | Read only. | No (internal) | no |
| `services/portfolio.py::trial_start(mode)` | services/portfolio.py:306 | mode | datetime or None | equity_curve, stats | settings | Config only. | No (internal) | no |
| `services/portfolio.py::open_positions_by_book(db)` | services/portfolio.py:55 | db | dict of counts (bot, testing, real) | GET /status, ops digest | reads positions and strategies | Read only. The three books never mix. | No (internal) | no |
| `services/holdings_sync.py::close_positions_no_longer_held(db, strategy, held_symbols)` | services/holdings_sync.py:46 | db, holdings, ... | positions closed | sync_real_holdings job | execution.manual_close_position | Closes tracked rows the broker no longer shows; never sends an order. | No (internal) | no |
| `services/tester_paper.py::paper_buy(db, symbol, quantity, cap_tier, exchange)` | services/tester_paper.py:234 | db, instrument, quantity, ... | Position | POST /portfolio/tester/buy | execution.open_position (paper broker, tester book) | Paper only; own starting capital; never part of Brain results. | Owner or tester | no |
| `services/tester_paper.py::portfolio_value(db)` | services/tester_paper.py:135 | db | (value, cash, invested) | screens | reads positions | Read only. | No (internal) | no |
| `simulation/store.py::persist_run(db, run_key, ledgers, rules, momentum_universe, momentum_not_ranked)` | simulation/store.py:159 | db, run_key, ledgers, rules, momentum_universe, momentum_not_ranked | persist result | simulation/runner.py::run_and_persist | writes `sim_*` tables | Writes only what is not stored yet; checks what is. Keyed by run_key. | No (internal) | no |
| `simulation/store.py::performance_by_policy(db, run_key)` | simulation/store.py:578 | db, run_key | dict | none in the package (tests and manual use) | reads `sim_*` | Validation portfolio is in no denominator. | No (internal) | no |
| `simulation/store.py::trace_fills(db, run_key)` | simulation/store.py:635 | db, run_key | list of TraceRow | none in the package (tests and manual use) | reads `sim_*`, horizon records service | Every fill joined to its stock and record. | No (internal) | no |
| `simulation/store.py::universe_fingerprint(ids)` | simulation/store.py:148 | ids | (JSON text, sha256) or (None, None) | simulation/store.py::persist_run | none (pure) | Fingerprint of the declared momentum universe, stored with the run. | No (internal) | no |
| `simulation/runner.py::run_and_persist(db, run_key, sessions, models, momentum_universe, rule_version, allow_research, bars, momentum, sectors, specs)` | simulation/runner.py:171 | db, spec, ... | report | simulation/runner.py::main (command line) | store.persist_run | Does not commit. Reads stored records and candles only. | No (internal) | no |
| `simulation/runner.py::declared_universe(ids)` | simulation/runner.py:95 | ids | sorted tuple of security ids | simulation/runner.py::run_and_persist, resolve_universe | none (pure) | Refuses a missing, empty, repeated or non-integer universe; nothing is guessed. | No (internal) | no |
| `simulation/runner.py::resolve_universe(db, spec, on)` | simulation/runner.py:107 | db, spec, on | tuple of security ids | simulation/runner.py::main (command line) | identity service via simulation/source.py | Resolved on the given trading day; an unknown or ambiguous symbol refuses the run. | No (internal) | no |
| `simulation/source.py::closes_from_candles(db, security_ids, first_session, last_session, lookback_days)` | simulation/source.py:252 | db, security_ids, first_session, last_session, lookback_days | security id to IST date to close | simulation/runner.py::run_and_persist | reads `candles` | Nothing after the last session is read; IST dates. | No (internal) | no |
| `simulation/momentum.py::rule_ref()` | simulation/momentum.py:38 | none | rule name and version text | simulation/runner.py::run_and_persist, momentum_result | brain baseline constants | Pure. | No (internal) | no |
| `simulation/momentum.py::momentum_result(closes, sessions, symbols, universe)` | simulation/momentum.py:67 | closes, sessions, symbols, universe | MomentumResult (decisions, ranked, not ranked) | simulation/runner.py::run_and_persist, momentum_decisions | none (pure; brain momentum scores) | A pick at the close of session D uses only closes up to D. A declared stock with no price is reported, not dropped silently. | No (internal) | no |
| `simulation/momentum.py::momentum_decisions(closes, sessions, symbols, universe)` | simulation/momentum.py:122 | closes, sessions, symbols, universe | decisions by session | none in the package (tests only) | momentum_result | Same as above. | No (internal) | no |
| `simulation/runner.py::main(argv, database_url)` | simulation/runner.py:354 | argv, database_url | exit code | command line only | run_and_persist | Never run by the app; writes only simulation tables. | No (internal) | no |
| `POST /portfolio/snapshot` | api/v1/endpoints/portfolio.py:1165 | none | message | frontend / scripts | mark_to_market, take_snapshot | Idempotent per day. | Owner | no |
| `POST /portfolio/capital-added` | api/v1/endpoints/portfolio.py:1145 | amount, note | ledger row | frontend | records money added, take_snapshot | Paper only (refused otherwise). | Owner | no |
| `GET /portfolio/positions/detailed` | api/v1/endpoints/portfolio.py:177 | book, ... | position rows | frontend | position_action, reads quotes | Read only; the plan rule lets the bot book through for plan users. | Plan feature bot_portfolio (bot book); otherwise owner | no |

## 4. Execution

Everything that can place, cancel or record an order or a manual position, plus alerts. The execution entry points table at the end is pinned exactly by a test.

| Interface | file:line | Inputs | Outputs | Called by | Calls | Point-in-time and idempotency | Intended caller | Frozen |
|---|---|---|---|---|---|---|---|---|
| `brokers/__init__.py::get_broker()` | brokers/__init__.py:25 | none | Broker (paper unless live is enabled) | execution, engine, endpoints | settings | The only way trading code gets a broker (one documented exception below). | No (internal) | no |
| `brokers/__init__.py::current_mode()` | brokers/__init__.py:37 | none | mode string | approvals, screens | get_broker | Read only. | No (internal) | no |
| `brokers/base.py::Broker.place_order(self, request, db)` | brokers/base.py:142 | request, db | OrderResult | execution.open_position, execution.close_position | paper or Kite implementation | Abstract. | No (internal) | no |
| `brokers/base.py::Broker.cancel_order(self, broker_order_id, db)` | brokers/base.py:146 | broker_order_id, db | bool | POST /orders/{order_id}/cancel | paper or Kite implementation | Abstract. | No (internal) | no |
| `brokers/base.py::Broker.get_order_status(self, broker_order_id, db)` | brokers/base.py:149 | broker_order_id, db | OrderResult or None | reconcile_pending_orders | implementation | Abstract. | No (internal) | no |
| `brokers/base.py::Broker.get_ltp(self, symbols, db)` | brokers/base.py:158 | symbols, db | price map | check_exits, approvals, GET /market-data/ltp | implementation | Abstract. | No (internal) | no |
| `brokers/paper.py::PaperBroker.place_order(self, request, db)` | brokers/paper.py:235 | request, db | OrderResult (filled or rejected) | via get_broker | reads `quotes` (reference price); never calls Kite orders | Fills at the stored quote; a missing quote is a rejection. | No (internal) | no |
| `brokers/paper.py::PaperBroker.cancel_order(self, broker_order_id, db)` | brokers/paper.py:314 | broker_order_id, db | bool | via get_broker | paper orders table | Paper orders are already final. | No (internal) | no |
| `brokers/paper.py::PaperBroker.get_order_status(self, broker_order_id, db)` | brokers/paper.py:328 | broker_order_id, db | OrderResult or None | via get_broker | paper orders table | Read only. | No (internal) | no |
| `brokers/paper.py::PaperBroker.get_ltp(self, symbols, db)` | brokers/paper.py:398 | symbols, db | price map | via get_broker | Kite price call (read only) | Read only. | No (internal) | no |
| `brokers/kite.py::KiteBroker.place_order(self, request, db)` | brokers/kite.py:388 | request, db | OrderResult (always PENDING) | only execution._place_real_holding_order | Kite REST order call | Real money path. Always PENDING until reconciled. | No (internal) | no |
| `brokers/kite.py::KiteBroker.cancel_order(self, broker_order_id, db)` | brokers/kite.py:443 | broker_order_id, db | bool | none in the package (the live broker is never returned by get_broker while paper) | Kite REST cancel | Real money path. | No (internal) | no |
| `brokers/kite.py::KiteBroker.get_ltp(self, symbols, db)` | brokers/kite.py:540 | symbols, db | price map | PaperBroker.get_ltp, PaperBroker price lookup, real_orders.quote | Kite price call (read only) | Read only. | No (internal) | no |
| `brokers/kite.py::KiteBroker.get_order_status(self, broker_order_id, db)` | brokers/kite.py:452 | broker_order_id, db | OrderResult or None | reconcile_pending_orders (live orders) | Kite order book | Read only. | No (internal) | no |
| `services/execution.py::open_position(db, strategy, instrument, signal, quantity)` | services/execution.py:246 | db, strategy, instrument, signal, quantity | Position or None | process_decision, tester_paper.paper_buy, approvals._order | get_broker().place_order; writes Order, Position | Order row written before submission so a crash leaves a record. Paper fills at once; live waits for reconcile. | No (internal) | no |
| `services/execution.py::close_position(db, position, exit_price, reason, note, quantity)` | services/execution.py:592 | db, position, price, reason, note, quantity | Trade | process_decision, check_exits, POST /portfolio/positions/{position_id}/close | get_broker().place_order; writes Trade | Immutable Trade per sale; partial exits leave the rest OPEN. | No (internal) | no |
| `services/execution.py::manual_open_position(db, strategy, instrument, quantity, entry_price, stop_loss, take_profit, brokerage, taxes, signal)` | services/execution.py:356 | db, strategy, instrument, quantity, price, ... | Position | POST /portfolio/positions/manual, POST /portfolio/positions/import-holdings | writes Position only | Records a position bought elsewhere. No broker call, no order. | No (internal) | no |
| `services/execution.py::manual_close_position(db, position, exit_price, reason, brokerage, taxes)` | services/execution.py:710 | db, position, price, reason, ... | Trade | POST /portfolio/positions/{position_id}/manual-close, holdings_sync | writes Trade only | Records a sale made elsewhere. No broker call, no order. | No (internal) | no |
| `services/execution.py::place_real_holding_buy(db, strategy, instrument, quantity, reference_price)` | services/execution.py:864 | db, strategy, instrument, quantity, price | Order | services/real_orders.buy | _place_real_holding_order (KiteBroker directly) | Real money path; bypasses get_broker on purpose. | No (internal) | no |
| `services/execution.py::place_real_holding_sell(db, position, quantity)` | services/execution.py:873 | db, position, quantity | Order | services/real_orders.sell | _place_real_holding_order (KiteBroker directly) | Real money path; bypasses get_broker on purpose. | No (internal) | no |
| `services/execution.py::_place_real_holding_order(db, strategy_id, instrument, side, quantity, reference_price, position_id, exit_reason)` | services/execution.py:758 | db, ... | Order | place_real_holding_buy, place_real_holding_sell | KiteBroker.place_order | The only place outside get_broker that calls a broker order method. | No (internal) | no |
| `services/execution.py::process_decision(db, strategy, instrument, decision, ranked_out_reason)` | services/execution.py:1170 | db, strategy, instrument, decision, ... | Signal | engine.run_strategy, backtest | record_signal, risk checks, open_position, close_position | Always records the signal. Advisory strategies never reach the broker. | No (internal) | no |
| `services/execution.py::check_exits(db)` | services/execution.py:1572 | db | list of Trade | job_check_exits | broker prices, close_position | Stop, target and time-stop. Advisory positions only get an alert flag (advisory_alert_sent_at), never an order. | No (internal) | no |
| `services/execution.py::reconcile_pending_orders(db)` | services/execution.py:1729 | db | counts | job_reconcile_orders, POST /orders/sync | broker get_order_status; creates Position or Trade on fill | Safe to repeat; each order resolves once. | No (internal) | no |
| `services/execution.py::trail_stop(position)` | services/execution.py:1466 | position | None (moves the stored stop up) | check_exits, corporate_action_accounting | writes position.stop_loss in memory | Never moves the stop down. A stop change, so it needs a test and owner approval before any edit. | No (internal) | no |
| `services/execution.py::position_action(entry_confidence, last_confidence, alert_sent, holding_days, horizon_days, exit_confidence, exit_signal_pending, min_confidence, exit_alert_sent)` | services/execution.py:984 | position, ... | (action_code, label) | GET /portfolio/positions/detailed | none (pure) | Maps flags to a screen word. | No (internal) | no |
| `services/execution.py::confidence_decay_status(entry_confidence, current_confidence, exit_confidence, already_alerted, min_confidence, drop_threshold)` | services/execution.py:884 | ... | status | execution._check_confidence_decay, held_read | none (pure) | Read only. | No (internal) | no |
| `services/real_orders.py::buy(db, strategy, instrument, quantity)` | services/real_orders.py:103 | db, strategy, instrument, quantity | Order | POST /portfolio/real/buy | place_real_holding_buy | Refusal checks live here (RealOrderRefused). Real account only. | Real-account owner | no |
| `services/real_orders.py::sell(db, position, quantity)` | services/real_orders.py:130 | db, position, quantity | Order | POST /portfolio/real/positions/{position_id}/sell | place_real_holding_sell | Same. | Real-account owner | no |
| `services/real_orders.py::quote(db, instrument)` | services/real_orders.py:66 | db, instrument | price | POST real routes, GET /portfolio/real/quote | broker price | Read only. | Real-account owner | no |
| `services/real_orders.py::spent_today(db, strategy_id, now)` | services/real_orders.py:78 | db, strategy_id, now | rupees spent today | real_orders.buy (daily limit check), real_orders.status | reads orders | Read only. | No (internal) | no |
| `services/real_orders.py::status(db, strategy)` | services/real_orders.py:157 | db, strategy | dict | GET /portfolio/real/orders-status | reads orders | Read only. | Real-account owner | no |
| `services/brain_golive/approvals.py::approve(db, approval_id, by, note)` | services/brain_golive/approvals.py:579 | db, approval_id, by, note | BrainApproval | POST /brain/approvals/{approval_id}/approve | _order -> open_position | Claims the row first, so one order per idea; only while the market is open. | Owner | no |
| `services/brain_golive/approvals.py::execute_waiting(db)` | services/brain_golive/approvals.py:668 | db | list of approvals | job_brain_approvals_open | _order -> open_position | Re-checks every rule at the open. | No (internal) | no |
| `services/brain_golive/approvals.py::_order(db, a, ready)` | services/brain_golive/approvals.py:366 | db, approval, ready | BrainApproval | approve, execute_waiting | execution.open_position | Refuses outside market hours. | No (internal) | no |
| `services/entry_lock.py::entry_lock(mode, timeout)` | services/entry_lock.py:49 | mode, timeout | context manager | buy paths | advisory lock | One entry at a time per mode. | No (internal) | no |
| `notifications/telegram.py::TelegramNotifier.send_sync(self, text, event, kind)` | notifications/telegram.py:237 | text, kind, ... | bool | execution alerts, jobs | alert_settings.gate, Telegram | Gate decides send, hold or drop; safety alerts are never mutable through the API. | No (internal) | no |
| `notifications/telegram.py::TelegramNotifier.deliver_sync(self, text)` | notifications/telegram.py:226 | text | bool | alert_settings.flush | Telegram | One configured chat; a failure returns False. | No (internal) | no |
| `notifications/alert_policy.py::route(kind, prefs, now)` | notifications/alert_policy.py:168 | kind, prefs, now | Route | alert_settings.gate | none (pure) | Quiet hours hold ideas; stop-losses are sent. | No (internal) | no |
| `notifications/alert_policy.py::compose_digest(items, digest)` | notifications/alert_policy.py:205 | ... | text | alert_settings.flush | none (pure) | Pure. | No (internal) | no |
| `services/alert_settings.py::load(db, scope)` | services/alert_settings.py:58 | db, scope | AlertPrefs | gate, screens | reads one settings row | One shared row today (see #251). | No (internal) | no |
| `services/alert_settings.py::save(db, prefs, by, scope)` | services/alert_settings.py:79 | db, prefs, by, scope | AlertPrefs | PUT /notifications/alert-settings | writes the settings row | Validated; safety kinds cannot be muted. | Owner | no |
| `services/alert_settings.py::gate(kind, text, now, sessions, scope)` | services/alert_settings.py:134 | db, ... | decision | send_sync | alert_policy.route, holds rows | Held alerts survive a failed delivery. | No (internal) | no |
| `services/alert_settings.py::flush(db, now, deliver, scope)` | services/alert_settings.py:162 | db, now, deliver, scope | dict | job_flush_alerts | deliver callback | Sends held alerts when due. | No (internal) | no |
| `workers/jobs.py::job_flush_alerts()` | workers/jobs.py:177 | none | None | scheduler (flush_alerts) | alert_settings.flush | Never raises into the worker. | No (internal) | no |
| `services/trading_rules.py::trading_rules(as_of, include_research)` | services/trading_rules.py:24 | as_of, include_research | dict of rules, risk limit, brain plan, trial count, holidays | GET /config/trading-rules | research config, brain plan settings, NSE calendar | Read only; changes nothing. Research-only horizons are left out unless asked for. | No (internal) | no |
| `services/trading_rules.py::trial_sessions_so_far(as_of)` | services/trading_rules.py:69 | as_of | int | trading_rules | market calendar | Counts trading sessions from the trial start up to as_of. | No (internal) | no |
| `core/modules.py::require_module(module_id)` | core/modules.py:412 | module_id | route guard | api/v1/router.py (every optional module router, including the Brain approval routes) | module switch state | While a module is off its routes answer "switched off"; on (the default) it does nothing. | No (internal) | no |
| `core/modules.py::apply_to_scheduler(scheduler, state)` | core/modules.py:430 | scheduler, state | ids of jobs removed | workers/scheduler.py | scheduler | Removes the scheduled jobs of modules that are off; with every module on it removes nothing. | No (internal) | no |
| `core/modules.py::guard_scheduler_jobs(scheduler, state)` | core/modules.py:442 | scheduler, state | ids of jobs wrapped | workers/scheduler.py | scheduler | Makes each module job re-read the switch before every run and skip while the module is off. | No (internal) | no |
| `POST /orders/{order_id}/cancel` | api/v1/endpoints/orders.py:49 | order_id | message | frontend | get_broker().cancel_order | Cancels one order of the current mode. | Owner | no |
| `POST /orders/sync` | api/v1/endpoints/orders.py:68 | none | message | frontend / scripts | reconcile_pending_orders | Safe to repeat. | Owner | no |
| `POST /portfolio/positions/manual` | api/v1/endpoints/portfolio.py:736 | payload | PositionOut | frontend | manual_open_position | Record only. | Owner | no |
| `POST /portfolio/positions/import-holdings` | api/v1/endpoints/portfolio.py:535 | strategy_id | list | frontend | broker holdings, manual_open_position | Record only. | Real-account owner | no |
| `POST /portfolio/positions/{position_id}/manual-close` | api/v1/endpoints/portfolio.py:767 | position_id, payload | TradeOut | frontend | manual_close_position | Record only. | Owner | no |
| `POST /portfolio/positions/{position_id}/close` | api/v1/endpoints/portfolio.py:936 | position_id, payload | message | frontend | close_position | Places a paper exit through the broker. | Owner | no |
| `POST /portfolio/tester/buy` | api/v1/endpoints/portfolio.py:702 | payload | dict | frontend | tester_paper.paper_buy | Paper tester book only. | Owner or tester | no |
| `POST /portfolio/real/buy` | api/v1/endpoints/portfolio.py:904 | payload | dict | frontend | real_orders.buy | Real order (real account owners only). | Real-account owner | no |
| `POST /portfolio/real/positions/{position_id}/sell` | api/v1/endpoints/portfolio.py:919 | position_id, payload | dict | frontend | real_orders.sell | Real order (real account owners only). | Real-account owner | no |
| `PUT /brain/stage` | api/v1/endpoints/brain_golive.py:71 | stage, reason | dict | frontend | stage.set_stage | Back to practice is always allowed. | Owner | no |
| `POST /brain/approvals/{approval_id}/approve` | api/v1/endpoints/brain_golive.py:118 | approval_id, note | dict | frontend | approvals.approve | See approve. | Owner | no |
| `POST /brain/approvals/{approval_id}/reject` | api/v1/endpoints/brain_golive.py:126 | approval_id, reason | dict | frontend | approvals.reject | No order. | Owner | no |
| `GET /config/trading-rules` | api/v1/endpoints/system.py:237 | none | trading rules | frontend | trading_rules | Read only; the numbers are the app's published rules, no account data. | Any signed-in caller | no |
| `PUT /admin/modules/{module_id}` | api/v1/endpoints/admin_modules.py:56 | module_id, enabled, reason | module row | frontend (admin) | core/modules.py switches.set_enabled | Switches an optional module off or on; a core module is refused; every request is audited; no data is changed. | Owner | no |

## 5. Execution entry points (pinned exactly by a test)

Every call in the package to `place_order`, `cancel_order`, `open_position`, `close_position`, `manual_open_position`, `manual_close_position`, `place_real_holding_buy` or `place_real_holding_sell`, as (file, enclosing function, name called). A new call site, or one that disappears, fails the test until this table is updated.

| Site | What it is |
|---|---|
| `api/v1/endpoints/orders.py::cancel_order->cancel_order` | POST /orders/{order_id}/cancel |
| `api/v1/endpoints/portfolio.py::close->close_position` | POST /portfolio/positions/{position_id}/close |
| `api/v1/endpoints/portfolio.py::close_manual_position->manual_close_position` | POST /portfolio/positions/{position_id}/manual-close |
| `api/v1/endpoints/portfolio.py::create_manual_position->manual_open_position` | POST /portfolio/positions/manual |
| `api/v1/endpoints/portfolio.py::import_real_holdings->manual_open_position` | POST /portfolio/positions/import-holdings |
| `brokers/kite.py::KiteBroker.cancel_order->cancel_order` | Kite SDK cancel (inside the broker) |
| `services/brain_golive/approvals.py::_order->open_position` | Brain approval (owner OK or waiting at the open) |
| `services/execution.py::_place_real_holding_order->place_order` | real holdings buy/sell (KiteBroker directly) |
| `services/execution.py::_process_buy->open_position` | bot scan BUY |
| `services/execution.py::check_exits->close_position` | stop, target, time stop, scale-out |
| `services/execution.py::close_position->place_order` | exit through get_broker() |
| `services/execution.py::open_position->place_order` | entry through get_broker() |
| `services/execution.py::process_decision->close_position` | strategy SELL decision |
| `services/holdings_sync.py::close_positions_no_longer_held->manual_close_position` | sync of real holdings (record only) |
| `services/real_orders.py::buy->place_real_holding_buy` | POST /portfolio/real/buy |
| `services/real_orders.py::sell->place_real_holding_sell` | POST /portfolio/real/positions/{position_id}/sell |
| `services/tester_paper.py::paper_buy->open_position` | POST /portfolio/tester/buy |

## 6. Other mutating routes (pinned)

Every POST, PUT, PATCH or DELETE route in `orders.py`, `portfolio.py`, `strategies.py`, `brain_golive.py`, `real_report.py`, `instruments.py`, `market_data.py` and `notifications.py` must be in section 4 above or here. A new one fails the test until it is added.

| Route | What it does |
|---|---|
| `POST /strategies` | create a strategy |
| `PATCH /strategies/{strategy_id}` | edit a strategy |
| `DELETE /strategies/{strategy_id}` | delete a strategy |
| `POST /strategies/{strategy_id}/activate` | activate a strategy |
| `POST /strategies/{strategy_id}/deactivate` | deactivate a strategy |
| `PUT /notifications/alert-settings` | save the alert settings row |
| `POST /notifications/telegram/daily-summary` | send the daily summary to the one configured chat |
| `POST /notifications/telegram/test` | send a test message to the one configured chat |
| `POST /real-report/sync` | pull real holdings into the report |
| `POST /real-report/import-tradebook` | import a trade book file |

## 7. Findings and things that look odd

Facts, not defects unless said so. None changes behaviour here.

1. **Interfaces with no caller inside the app** (only tests or manual use): `run_all_horizons`, `append_from_brain_run`, `backfill_from_stock_scores`, `performance_by_policy`, `trace_fills`, and `KiteBroker.cancel_order` (while the bot is on paper `get_broker` never returns the live broker, so the cancel route cannot reach it). The simulation package runs only from its own command line.
2. **One deliberate bypass of `get_broker()`:** `_place_real_holding_order` builds on `KiteBroker` directly so the owner can buy or sell a real holding while the bot stays on paper. It is reachable only from the two owner-only real-account routes and refusals live in `services/real_orders.py`. It is the only non-paper order path.
3. **`DatedReader` is not read-only in one place:** `refresh_context_if_stale` can backfill index candles on a live run. Replays (`live=False`) do not call it.
4. **Latest-only tables have no as-of:** `quotes` (one row per stock), and the scan reads stored candles with no age check. Both are recorded in #240 and #246; this inventory adds no new defect.
5. **Two alert routes into one chat** (`send_sync`, `deliver_sync`) share one settings row (#251).

