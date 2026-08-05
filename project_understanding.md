# Swing Trade ML — Project Understanding

A working reference for the whole system: what to install, how to start it, how
the pieces fit together, what business rules govern trading decisions, and
exactly which technical indicators the model reads. Written to be re-readable
months from now without needing this conversation for context.

---

## 1. Installations required

### 1.1 Required on your machine (host)

| Software | Version | Why | Check |
|---|---|---|---|
| **Docker Desktop** | Any recent | Runs Postgres, Redis, and (optionally) the API/frontend in containers | `docker --version` |
| **Python** | 3.11–3.13 | Backend, only needed if you run the API outside Docker | `python --version` |
| **Git** | Any | Version control | `git --version` |

### 1.2 Optional on your machine

| Software | Version | Why | Check |
|---|---|---|---|
| **Node.js** | 22 LTS | Only needed to run the React dashboard *outside* Docker. If skipped, the dashboard still runs via `docker compose up frontend` — Node then only exists inside the container. | `node --version` |
| **gh (GitHub CLI)** | Any | Convenient for repo operations from the terminal; not required, `git` alone is enough | `gh --version` |

Install Node if you want it locally:
```powershell
winget install OpenJS.NodeJS.LTS
```

### 1.3 Nothing else needs manual installation

Everything else — PostgreSQL, TimescaleDB, Redis, every Python package
(FastAPI, SQLAlchemy, scikit-learn, LightGBM, pandas, etc.), every npm package
— is pulled automatically by Docker or `pip`/`npm` the first time you build.
You do not install PostgreSQL yourself; it runs inside the `postgres`
container.

### 1.4 Accounts / external services needed

| Service | For | Where to get it |
|---|---|---|
| **Zerodha Kite Connect** app | Market data + order placement | [developers.kite.trade/apps](https://developers.kite.trade/apps) — gives you `KITE_API_KEY` and `KITE_API_SECRET` |
| **Telegram bot** | Trade/error notifications | Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → gives you `TELEGRAM_BOT_TOKEN`; then message your own bot once and read your chat id from `https://api.telegram.org/bot<TOKEN>/getUpdates` |

Both are optional to get the system running — the API boots and paper trading
works with neither configured — but Kite is required for real market data and
Telegram is required to receive notifications.

---

## 2. Steps to start the application

### 2.1 One-time setup

```powershell
# 1. Copy the environment template and fill in real values
cp .env.example .env
```

Edit `.env` and set at minimum:
- `KITE_API_KEY`, `KITE_API_SECRET` — from your Kite Connect app
- `API_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `JWT_SECRET_KEY` — generate the same way
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — if you want notifications now (can be added later)

Set your Kite app's redirect URL to exactly:
`http://localhost:8000/api/v1/auth/kite/callback`

**Important — port 5433, not 5432.** If you already have a local PostgreSQL
installation, it very likely owns port 5432 on Windows. This project's
Postgres container publishes on **5433** instead, specifically to avoid that
collision. `DATABASE_URL` in `.env.example` already points at 5433 — don't
change it back to 5432 unless you've confirmed nothing else is listening
there.

### 2.2 Start everything (recommended path — Docker only)

```powershell
docker compose up -d
```

This single command builds and starts five containers:

| Container | What it runs | Port |
|---|---|---|
| `stml-postgres` | PostgreSQL 17 + TimescaleDB | 5433 → 5432 |
| `stml-redis` | Redis 7 | 6379 |
| `stml-api` | FastAPI, no scheduler | 8000 |
| `stml-worker` | Same app, scheduler **on** | (internal 8001) |
| `stml-frontend` | Vite dev server (React) | 5173 |

Tables are created automatically — `init_database()` runs the Alembic
migration during the API container's startup. No manual DDL, no migration
command to remember.

Check it worked:
```powershell
curl http://localhost:8000/api/v1/health
# {"status":"ok","app":"Swing Trade ML","environment":"local","version":"0.1.0"}
```

Open:
- **Dashboard:** http://localhost:5173
- **API docs (Swagger):** http://localhost:8000/docs
- **Health:** http://localhost:8000/api/v1/health

### 2.3 Alternative: backend outside Docker (faster iteration while coding)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Postgres and Redis still come from Docker
docker compose up -d postgres redis

uvicorn swing_trade_ml.main:app --reload
```

Frontend (needs Node installed locally):
```powershell
cd frontend
npm install
npm run dev
```

**Don't run the backend both ways at once** — a locally-run `uvicorn` and the
`stml-api` Docker container both try to bind host port 8000, and whichever
started second will either fail or silently not receive traffic. Pick one.

### 2.4 First-run data setup (after the stack is up)

```powershell
# 1. Log in to Zerodha (opens a browser flow) — required before any of the below
#    Visit: http://localhost:8000/api/v1/auth/kite/login

# 2. Pull the instrument master and set your watchlist
docker compose exec api swingtrade sync-instruments

# 3. Backfill historical candles (takes several minutes — Kite rate-limits to ~3 req/s)
docker compose exec api swingtrade backfill --days 1825

# 4. Train the first model
docker compose exec api swingtrade train --algorithm lightgbm --activate

# 5. Verify
docker compose exec api swingtrade status
```

**Kite tokens expire daily at ~06:00 IST.** Step 1 must be repeated every
trading morning — there is no way around this in Kite Connect's design. The
token is stored in the database and reloaded automatically on restart, but it
cannot renew itself unattended.

### 2.5 Daily use

Once set up, you generally only need:
```powershell
docker compose up -d          # if not already running
# open http://localhost:8000/api/v1/auth/kite/login once each morning
```
Everything else — quote polling, the post-close scan, exit checks, the daily
Telegram summary — runs automatically on the schedule in §4.6.

### 2.6 Stopping / resetting

```powershell
docker compose down           # stop everything, keep data
docker compose down -v        # stop everything AND delete all data (careful)
```

---

## 3. Repository layout

```
SwingTradeML/
├── backend/
│   ├── src/swing_trade_ml/
│   │   ├── core/          config, logging, security, enums
│   │   ├── db/             SQLAlchemy models + session/bootstrap
│   │   ├── brokers/        Broker port · PaperBroker · KiteBroker
│   │   ├── strategies/     SMA crossover · ML swing (registry-based)
│   │   ├── ml/              features · dataset · train · predict · registry
│   │   ├── services/       ingestion · engine · risk · execution · portfolio
│   │   ├── notifications/  Telegram
│   │   ├── workers/        APScheduler jobs
│   │   ├── api/v1/         REST endpoints
│   │   ├── schemas/        Pydantic contracts
│   │   ├── cli.py          operational commands (swingtrade ...)
│   │   └── main.py         FastAPI app + startup sequence
│   ├── alembic/            migrations (applied automatically at startup)
│   └── tests/
├── frontend/                React dashboard (7 pages)
├── infra/postgres/          DB init scripts (extensions)
├── docker-compose.yml
├── .env                     your config (gitignored, never committed)
└── README.md                setup-focused quick reference (this file goes deeper)
```

---

## 4. Functional architecture

### 4.1 The core design principle: one code path for paper and live

Every piece of trading logic — strategies, risk sizing, execution, portfolio
accounting — talks to a `Broker` interface, never directly to `kiteconnect`.
Two implementations exist:

- **`PaperBroker`** — simulates fills against real, live market prices. Applies
  slippage, brokerage, and statutory-charge estimates on every fill. Rejects
  orders when virtual cash runs out. Limit orders that the market hasn't
  reached don't fill (many toy backtests get this wrong).
- **`KiteBroker`** — the real Zerodha Kite Connect client. Places real orders
  for real money.

Because both implement the identical interface, **strategies cannot tell which
one they're talking to.** The only thing that changes when going live is which
object a factory function returns — nothing about strategy logic, risk checks,
or execution flow changes. This is what makes six months of paper results
mean anything: they were produced by the exact code that would run live.

### 4.2 The safety latch — how "live" is gated

Real orders require **two independent conditions**, both read fresh on every
call (never cached):

```
TRADING_MODE=live        AND        ALLOW_LIVE_TRADING=true
```

Either alone resolves to the paper broker. The check happens twice: once when
selecting which broker to use, and again inside `KiteBroker.place_order()`
immediately before transmission — because an order that reaches the exchange
cannot be un-sent, that second check is not redundant.

Every row in `signals`, `orders`, `positions`, `trades`, and
`portfolio_snapshots` carries a `mode` column (`"paper"` or `"live"`), so paper
results stay queryable and strictly separated from live P&L even after the
switch is eventually flipped.

### 4.3 Request flow, end to end

```
1. Scheduler (or manual trigger) calls services/engine.run_all_active()
2. For each active Strategy, for each instrument in its watchlist:
     a. Load recent candles from the database
     b. strategy.evaluate(candles) -> SignalDecision (BUY/SELL/HOLD/EXIT,
        price, confidence, stop_loss, take_profit, reason)
3. services/execution.process_decision() takes that decision:
     a. Always records it as a Signal row — including rejections, with why
     b. If BUY: ask services/risk.check_entry() — position limits, drawdown
        circuit breaker, position sizing off distance-to-stop
     c. If allowed: get_broker().place_order() — simulated or real
     d. On fill: create/close a Position, write a Trade on exit
4. services/portfolio computes P&L, drawdown, Sharpe/Sortino, equity curve
5. notifications/telegram pushes a message for the outcome (if enabled)
```

### 4.4 Layer responsibilities (strict separation)

| Layer | Decides | Never does |
|---|---|---|
| `strategies/` | *what* to do with an instrument | place orders, size positions |
| `services/risk.py` | *how much* to buy | decide direction |
| `services/execution.py` | *whether and when* to execute | compute signals |
| `brokers/` | *how* the order is filled | know about strategies |

This separation is why results are attributable to the strategy, not the
plumbing — a bad backtest number can only mean the strategy is bad, not that
sizing or execution silently helped/hurt it.

### 4.5 Data model (what's stored and why)

| Table | Holds | Key point |
|---|---|---|
| `instruments` | The tradable universe | `is_watchlisted` flags which ones get data ingested |
| `candles` | OHLCV bars | TimescaleDB hypertable, keyed on `(instrument_id, interval, ts)` — no surrogate id, because the partitioning column must be in every unique index |
| `quotes` | Latest live price per instrument | One row each, updated in place — fast "what's it worth now" reads |
| `strategies` | Configured strategy instances | `params` JSON holds strategy-specific tunables; `mode` binds it to paper or live at creation time |
| `signals` | Every decision a strategy made | Rejected signals are kept too — a rejection is as informative as an execution |
| `orders` | Every order request and its lifecycle | Paper orders get synthetic `PAPER-...` ids |
| `positions` | Open/closed holdings | Mark-to-market fields refreshed by the intraday job |
| `trades` | Completed round trips | Written once, immutable — the stable source for performance stats |
| `portfolio_snapshots` | Daily equity-curve point | Needed for drawdown/Sharpe, which can't be reconstructed from trades alone (days with no trade still need a value) |
| `ml_models` | Trained model registry | Exactly one `ACTIVE` row per model name at a time |
| `predictions` | Every prediction the active model made | `was_correct` backfilled once each prediction's horizon elapses — this is the real accuracy measure, not the training-time metric |
| `broker_sessions` | Daily Kite access tokens | Append-only log; newest active row loaded at startup |
| `users` | Dashboard logins | Separate from the Kite session — the dashboard should work even without a Kite login today |

### 4.6 The daily schedule (all times IST, weekdays only)

| Time | Job | What happens |
|---|---|---|
| 09:15–15:30, every 60s | `refresh_quotes` | Poll live prices, mark positions to market |
| 09:15–15:30, every 60s | `check_exits` | Enforce stop-loss / target / time-stop against live prices |
| 15:40 | `daily_ingest` | Top up daily candles for the watchlist |
| 15:45 | `signal_scan` | Run every active strategy against completed daily bars |
| 16:00 | `daily_summary` | Snapshot the equity curve, send the Telegram digest |
| 16:15 | `evaluate_predictions` | Score predictions whose horizon has now elapsed |
| Sunday 08:00 | `sync_instruments` | Refresh the instrument master (tokens change on corporate actions) |

The scan runs **after** the close deliberately — scanning intraday would
evaluate a half-formed daily candle and produce signals that vanish by 15:30.

Only the `worker` container runs the scheduler (`ENABLE_SCHEDULER=true`); the
`api` container does not. Running it in both would mean two schedulers racing
to place the same trade.

### 4.7 Backtesting (`services/backtest.py`)

Replays a strategy against candles already sitting in the `candles` table —
years of history in seconds, instead of waiting out the six-month paper
phase to get six months of evidence.

```powershell
swingtrade backtest --strategy ml_swing --symbols RELIANCE,TCS,INFY \
  --start 2023-01-01 --end 2025-01-01
```

Also available as `POST /api/v1/backtest` (same parameters, JSON body) for
anything that wants the trade log and equity curve programmatically rather
than printed to a terminal. It's synchronous, unlike `/ml/train` — a
backtest writes nothing to persist, so there's no natural resource to poll
afterward. A handful of symbols over a few years returns in seconds over
HTTP; a full-watchlist, multi-year sweep can take minutes and belongs on the
CLI, which has no HTTP timeout to race against.

`symbols` defaults to the watchlist either way. Requires `swingtrade
backfill` to have already ingested history for the requested range and
warm-up window.

Design point: it reuses the exact cost formulas (slippage bps, brokerage per
order, tax bps) and the exact `calculate_quantity` sizing function that
`PaperBroker` and `services/risk.py` use — so a backtest number and a paper
number mean the same thing, not two different accounting conventions.
Deliberately **not** shared: nothing is written to `signals`/`orders`/
`positions`/`trades`. Portfolio state lives in memory for the duration of one
run and is discarded after printing the summary — a five-year run across 50
symbols would otherwise flood those tables with rows unrelated to actual
paper trading.

Two approximations worth knowing when reading a result:
- Exits are checked once per day against that day's high/low (stop takes
  priority over target if both fall inside the same day's range), rather
  than the live system's continuous intraday check.
- An entry fills at that day's close plus slippage, mirroring the live
  system's post-close scan filling near-immediately at the live quote.

---

## 5. Business rules

### 5.1 Trading mode

- **Default: paper.** Nothing reaches a real exchange without both
  `TRADING_MODE=live` and `ALLOW_LIVE_TRADING=true` set explicitly.
- **Plan: paper for the first 6 months** before considering live capital,
  per the original project brief.

### 5.2 Risk controls (enforced on every entry, `services/risk.py`)

| Rule | Default (`.env`) | Rationale |
|---|---|---|
| Risk per trade | `RISK_PER_TRADE_PCT = 1%` | Position size is derived from the **distance to the stop**, not a fixed rupee amount — a 10% stop gets a smaller position than a 3% stop, so every trade risks the same fraction of the portfolio. This is the single highest-leverage control in the system. |
| Max position concentration | `MAX_POSITION_PCT = 10%` | Caps single-name exposure — otherwise a very tight stop could justify an oversized position under the risk-per-trade rule alone. |
| Max open positions | `MAX_OPEN_POSITIONS = 10` | Bounds total number of simultaneous bets. |
| Drawdown circuit breaker | `MAX_PORTFOLIO_DRAWDOWN_PCT = 20%` | Halts **new entries** once drawdown from the equity peak exceeds this. Existing positions still exit normally — capital is never trapped, only new risk is blocked. |
| Default stop-loss | `DEFAULT_STOP_LOSS_PCT = 5%` | Fallback when a strategy supplies no explicit stop; prevents unbounded position sizing. |
| Default take-profit | `DEFAULT_TAKE_PROFIT_PCT = 15%` | Fallback target when a strategy supplies none. |
| Time stop | 60 days | A swing position still open after 60 days is closed regardless of P&L — capital tied up that long in a "swing" trade is treated as a failed thesis. |

Every entry passes these checks *before* an order is placed. A blocked entry
is recorded as a `Signal` with a `rejection_reason` — never silently dropped.

### 5.3 Paper simulation rules (`brokers/paper.py`)

- **Prices are real, only fills are simulated** — the paper broker consumes
  the same live Kite quotes the live broker would; it never invents prices.
- **Costs are charged on every fill:** slippage (`PAPER_SLIPPAGE_BPS`,
  default 5bps against you), brokerage (`PAPER_BROKERAGE_PER_ORDER`, ₹20),
  and an approximated tax/statutory-charge stack
  (`PAPER_TAX_BPS`, 12bps of turnover). A cost-free simulation reliably
  overstates returns.
- **Fills are pessimistic by construction** — buys fill above the reference
  price, sells below, never in your favour.
- **Cash is finite.** Virtual capital starts at `PAPER_STARTING_CAPITAL`
  (₹10,00,000 default) and buys are rejected once it's exhausted — position
  sizing gets genuinely tested, not just assumed correct.
- **Limit orders respect the market.** A limit buy above the current price (or
  limit sell below it) does not fill just because an order exists — it stays
  `OPEN` until the market reaches it, exactly like reality.

### 5.4 Order/product defaults

- **Product type: CNC** (delivery / overnight), not MIS (intraday). A swing
  trade is meant to be held for days; MIS positions get auto-squared-off by
  the broker at the same day's close, which would silently break the strategy.
- **Order type: MARKET** by default for both entries and exits generated by
  the automated engine.

### 5.5 Exit rules (checked intraday, every 60s while the market is open)

A position closes automatically when any of these trigger, in this priority
order:
1. **Stop-loss hit** — current price ≤ position's stop.
2. **Take-profit hit** — current price ≥ position's target.
3. **Time stop** — held ≥ 60 days.
4. **Signal exit** — the strategy itself emits an `EXIT` (e.g. a death cross,
   or the ML model's confidence dropping below its exit threshold).

### 5.6 Model promotion rules

- A newly trained model is `TRAINED`, never automatically `ACTIVE`, unless
  `--activate`/`auto_activate` is explicitly passed. Promotion is a
  deliberate act — a new model should be reviewed before it starts generating
  real signals, especially during the paper phase.
- Exactly one model per `name` may be `ACTIVE` at a time. Activating a new
  version automatically archives whatever it replaces — rollback is a single
  API call, not a redeploy.
- The metric that matters is **not** the training-time held-out accuracy. It's
  `GET /api/v1/ml/predictions/accuracy` — realised accuracy on predictions the
  bot actually made, scored once each prediction's horizon has elapsed. This
  is what the six-month paper phase exists to accumulate.

### 5.7 Data retention and separation

- Paper and live data are never mixed in aggregate queries — every query
  filters on `mode`.
- Historical candles are kept indefinitely (no automatic pruning) — training
  data quality depends on having a long, unbroken history.

---

## 6. Technical indicators — parameters used for market understanding

All 37 features are computed directly with pandas/numpy in
`backend/src/swing_trade_ml/ml/features.py` (no external TA library, so every
formula is visible and pinned). **Every feature is level-invariant** — a ratio
or a percentage, never a raw price — so the model generalises across a ₹200
stock and a ₹3,000 stock instead of learning symbol-specific price levels.

### 6.1 Trend

| Feature | Formula | Parameter |
|---|---|---|
| `sma_{10,20,50,200}_ratio` | `close / SMA(close, n) - 1` | n = 10, 20, 50, 200 days |
| `ema_{12,26}_ratio` | `close / EMA(close, n) - 1` | n = 12, 26 days |
| `sma_10_50_cross` | `SMA(10) / SMA(50) - 1` | — |
| `sma_50_200_cross` | `SMA(50) / SMA(200) - 1` | — |

### 6.2 Momentum

| Feature | Formula | Parameter |
|---|---|---|
| `rsi_14` | Wilder's RSI | 14-period, Wilder smoothing (not a plain rolling mean — matches standard charting platforms) |
| `macd`, `macd_signal`, `macd_hist` | Standard MACD, normalised by price | fast=12, slow=26, signal=9 |
| `stoch_k`, `stoch_d` | Stochastic oscillator | k=14, d=3 |
| `williams_r` | `-100 × (highest_14 - close) / (highest_14 - lowest_14)` | 14-period |
| `roc_10`, `roc_20` | Rate of change | 10-day, 20-day |

### 6.3 Volatility

| Feature | Formula | Parameter |
|---|---|---|
| `atr_14_pct` | ATR(14) / close | Wilder smoothing, 14-period |
| `bb_position` | Position within Bollinger Bands | 20-period, ±2 standard deviations |
| `bb_width` | Band width relative to midline | 20-period, ±2σ |
| `volatility_20` | Annualised std of daily returns | 20-day window, ×√252 |

### 6.4 Volume

| Feature | Formula | Parameter |
|---|---|---|
| `volume_ratio_20` | Today's volume / 20-day average volume | 20-day |
| `obv_slope` | 10-bar change in On-Balance Volume, scaled by its own 20-bar average | 10-day slope, 20-day scale |
| `mfi_14` | Money Flow Index (volume-weighted RSI) | 14-period |

### 6.5 Price structure

| Feature | Formula | Parameter |
|---|---|---|
| `return_{1,5,10,20}d` | Simple percentage return | 1, 5, 10, 20 trading days |
| `high_20_dist` | `close / rolling_high(20) - 1` | 20-day |
| `low_20_dist` | `close / rolling_low(20) - 1` | 20-day |
| `high_52w_dist` | `close / rolling_high(252) - 1` | 252 trading days (~52 weeks) |
| `gap_pct` | Overnight gap from prior close to today's open | — |
| `body_pct` | Candle body size relative to its full range | — |
| `upper_wick_pct`, `lower_wick_pct` | Wick size relative to candle range | — |

### 6.6 Regime

| Feature | Formula | Parameter |
|---|---|---|
| `adx_14` | Average Directional Index (trend strength, direction-agnostic) | 14-period |
| `trend_strength` | `ADX × sign(SMA10/SMA50 cross)` | derived |

### 6.7 The prediction target

The model answers one question:

> **Will this stock rise by ≥2% within the next 5 trading days?**

- `ML_PREDICTION_HORIZON_DAYS = 5` — the forward window
- `ML_TARGET_RETURN_PCT = 0.02` — the return threshold that defines a positive label
- `ML_MIN_CONFIDENCE = 0.60` — minimum predicted probability required before the strategy will act on it
- `ML_TRAIN_TEST_SPLIT = 0.2` — held out **chronologically** (never randomly — a
  random split on overlapping forward-return labels leaks the future into
  training and produces a fictional accuracy score)
- Training pools data **across all watchlisted symbols** rather than one
  model per symbol — a per-symbol model has only a few thousand rows and
  overfits that symbol's recent regime.
- `class_weight="balanced"` on every algorithm — only ~20–30% of bars precede
  a 2% move in 5 days, and an unweighted fit converges to "never buy" (75%
  accurate, useless).

### 6.8 Algorithms available (selectable per training run)

- **LightGBM** (default) — gradient-boosted trees, `min_child_samples=50` to
  stop it fitting noise in a handful of coincidental bars
- **Random Forest**
- **Gradient Boosting** (scikit-learn)
- **Logistic Regression** — the simplest baseline

### 6.9 The rule-based benchmark

A **SMA crossover strategy** (20/50-day, filtered by ADX ≥ 20 and RSI ≤ 70) is
included specifically as a benchmark. **If the ML model cannot beat this
simple crossover over six months of paper trading, it is not earning its
added complexity** — this comparison is the whole point of running both
strategies side by side during the paper phase.

---

## 7. What's not yet built (as of this document)

- **Live order reconciliation** is polling-based (`POST /orders/sync`), not a
  websocket order-update stream. This is a genuinely bigger lift than the
  other items here — persistent connection management, reconnect/backoff
  logic, and wiring Kite's postback/ticker stream into the existing
  order-status flow — not attempted yet.
- **Backtest results have no dashboard page.** Both the CLI
  (`swingtrade backtest`, §4.7) and `POST /api/v1/backtest` return the full
  trade log and equity curve, but there's nowhere in the React app to browse
  one without calling the API directly.

---

## 8. Honest limitations worth remembering

- Kite tokens genuinely cannot be renewed unattended — a human logs in every
  trading morning, permanently, by Kite Connect's design.
- Paper transaction costs are a reasonable approximation of Zerodha's real
  cost stack, not exact to the rupee.
- Sharpe/Sortino computed over a six-month paper run are indicative, not
  statistically significant — the sample is too short.
