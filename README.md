# Swing Trade ML

ML-driven swing trading bot for Indian equities. Generates BUY/SELL suggestions
from a trained classifier plus rule-based strategies, sizes them against a risk
budget, executes them (simulated or real), and reports over Telegram.

**FastAPI · SQLAlchemy · PostgreSQL/TimescaleDB · scikit-learn/LightGBM · React · Zerodha Kite Connect**

---

## The core safety design

The system runs in **paper mode by default**. Placing a real order requires
*two* independent flags:

```env
TRADING_MODE=live
ALLOW_LIVE_TRADING=true
```

Either one alone resolves to the paper broker. This is checked at broker
selection *and* again inside the Kite client immediately before an order is
transmitted — an order that reaches the exchange cannot be un-sent.

Paper and live share one code path. `PaperBroker` and `KiteBroker` implement the
same `Broker` interface, so strategies, risk checks, and execution are identical
in both modes. Going live changes which object the factory returns, nothing else.

Every row in `signals`, `orders`, `positions`, `trades` and `portfolio_snapshots`
carries a `mode` column, so six months of paper results stay queryable — and
strictly separated from live P&L — after the switch.

---

## Architecture

```
                    ┌──────────────┐
   React dashboard  │   frontend   │  Vite · TypeScript · React Query
   (localhost:5173) └──────┬───────┘
                           │ REST + X-API-Key
                    ┌──────▼───────┐
                    │   FastAPI    │  api  — request handling only
                    └──────┬───────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼─────┐      ┌─────▼──────┐    ┌──────▼──────┐
   │ strategies│      │  services  │    │     ml      │
   │  sma_x    │      │  engine    │    │  features   │
   │  ml_swing │─────▶│  risk      │───▶│  train      │
   └───────────┘      │  execution │    │  predict    │
      decides what    │  portfolio │    │  registry   │
                      │  ingestion │    └─────────────┘
                      └─────┬──────┘
                            │
                    ┌───────▼────────┐
                    │    brokers     │  ◀── the paper/live switch
                    │  paper │ kite  │
                    └───────┬────────┘
                            │
        ┌───────────────────┼──────────────────┐
   ┌────▼─────┐      ┌──────▼──────┐   ┌───────▼──────┐
   │ Postgres │      │  Zerodha    │   │   Telegram   │
   │Timescale │      │    Kite     │   │     Bot      │
   └──────────┘      └─────────────┘   └──────────────┘
```

Separation of concerns is deliberate:

| Layer | Decides | Never does |
|---|---|---|
| `strategies/` | *what* to do with an instrument | place orders, size positions |
| `services/risk.py` | *how much* to buy | decide direction |
| `services/execution.py` | *whether and when* to execute | compute signals |
| `brokers/` | *how* the order is filled | know about strategies |

This is what makes the paper phase meaningful — results are attributable to the
strategy rather than to the plumbing.

---

## Project layout

```
SwingTradeML/
├── backend/
│   ├── src/swing_trade_ml/
│   │   ├── core/          config, logging, security, enums
│   │   ├── db/            SQLAlchemy models + session/bootstrap
│   │   ├── brokers/       Broker port · PaperBroker · KiteBroker
│   │   ├── strategies/    SMA crossover · ML swing (registry-based)
│   │   ├── ml/            features · dataset · train · predict · registry
│   │   ├── services/      ingestion · engine · risk · execution · portfolio
│   │   ├── notifications/ Telegram
│   │   ├── workers/       APScheduler jobs
│   │   ├── api/v1/        REST endpoints
│   │   ├── schemas/       Pydantic contracts
│   │   ├── cli.py         operational commands
│   │   └── main.py        FastAPI app
│   ├── alembic/           migrations (applied automatically at startup)
│   └── tests/
├── frontend/              React dashboard
├── infra/postgres/        DB init scripts
├── docker-compose.yml
└── .env                   your config (gitignored)
```

---

## Quick start

### 1. Configure

```bash
cp .env.example .env
```

Fill in at minimum:

| Key | How to get it |
|---|---|
| `KITE_API_KEY`, `KITE_API_SECRET` | [developers.kite.trade/apps](https://developers.kite.trade/apps) |
| `API_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `JWT_SECRET_KEY` | same command |
| `TELEGRAM_BOT_TOKEN` | message [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | message your bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` |

Set the Kite app's redirect URL to exactly:
`http://localhost:8000/api/v1/auth/kite/callback`

### 2. Start

```bash
docker compose up -d
```

That brings up Postgres/TimescaleDB, Redis, the API, the scheduler worker, and
the React dashboard. **Tables are created automatically on first start** —
`init_database()` runs Alembic migrations during app startup, so there is no DDL
step and no migration command to remember.

| Service | URL |
|---|---|
| API docs | http://localhost:8000/docs |
| Dashboard | http://localhost:5173 |
| Health | http://localhost:8000/api/v1/health |

### 3. Connect Zerodha

Open http://localhost:8000/api/v1/auth/kite/login, follow the URL it returns,
and log in. **Kite tokens expire daily at ~06:00 IST**, so this is a every-trading-morning
step — the app stores the token and reloads it on restart, but cannot renew it
unattended.

### 4. Load data and train

```bash
docker compose exec api swingtrade sync-instruments   # instrument master + watchlist
docker compose exec api swingtrade backfill           # 5 years of daily candles
docker compose exec api swingtrade train --activate   # train and promote a model
docker compose exec api swingtrade status             # verify
```

Backfill takes several minutes — Kite allows ~3 historical calls/second and the
ingestion layer paces itself accordingly.

### 5. Create a strategy

In the dashboard → **Strategies** → New strategy → pick `ml_swing` → Activate.

Then either wait for the 15:45 IST scan, or press **Run scan now**.

---

## Running without Docker

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Postgres still comes from Docker
docker compose up -d postgres redis

uvicorn swing_trade_ml.main:app --reload
```

Frontend (needs Node 22+, `winget install OpenJS.NodeJS.LTS`):

```powershell
cd frontend
npm install
npm run dev
```

---

## The daily cycle

All times IST, weekdays only.

| Time | Job | What happens |
|---|---|---|
| 09:15–15:30, every 60s | `refresh_quotes` | Poll live prices, mark positions to market |
| 09:15–15:30, every 60s | `check_exits` | Enforce stop-loss / target / time-stop |
| 15:40 | `daily_ingest` | Top up daily candles |
| 15:45 | `signal_scan` | Run every active strategy on completed bars |
| 16:00 | `daily_summary` | Snapshot equity curve, send Telegram digest |
| 16:15 | `evaluate_predictions` | Score predictions whose horizon has elapsed |
| Sunday 08:00 | `sync_instruments` | Refresh instrument master |

The scan runs **after** the close on purpose. Scanning intraday evaluates a
half-formed daily candle and produces signals that vanish by 15:30.

---

## The ML model

**Question it answers:** will this stock rise ≥2% within the next 5 trading days?

- **Features** (37): trend (SMA/EMA ratios, crossovers), momentum (RSI, MACD,
  Stochastic, Williams %R, ROC), volatility (ATR, Bollinger position/width),
  volume (relative volume, OBV slope, MFI), price structure (returns, distance
  from 20-day and 52-week extremes, candle anatomy), regime (ADX).
- **Everything is level-invariant** — ratios and percentages, never raw prices.
  A model trained on a ₹3,000 stock's absolute price learns nothing transferable
  to a ₹200 one, and breaks on a split.
- **Pooled across symbols.** A per-symbol model has a few thousand rows and
  overfits that symbol's recent regime.
- **Chronological split, never random.** With overlapping forward-return labels,
  a random split leaks the future into training and produces fictional accuracy.
- **`class_weight="balanced"`.** Only ~20–30% of bars precede a 2% move in five
  days; an unweighted fit converges to "never buy" — 75% accurate, useless.

The metric to judge it on is not training accuracy. It is
`GET /api/v1/ml/predictions/accuracy` — realised accuracy on predictions the bot
actually made, scored after each horizon elapsed. That is what the six-month
paper phase is for.

The SMA crossover strategy exists as a benchmark. **If the ML model cannot beat
a moving-average crossover over six months, it is not earning its complexity.**

---

## Risk controls

Configured in `.env`, enforced in `services/risk.py` on every entry:

| Control | Default | Why |
|---|---|---|
| `RISK_PER_TRADE_PCT` | 1% | Position size is derived from the distance to the stop, so every trade risks the same amount regardless of stop width. Highest-leverage control in the system. |
| `MAX_POSITION_PCT` | 10% | Caps single-name concentration when a tight stop would otherwise justify a huge position. |
| `MAX_OPEN_POSITIONS` | 10 | Bounds total exposure. |
| `MAX_PORTFOLIO_DRAWDOWN_PCT` | 20% | Circuit breaker — halts *new entries*; existing positions still exit normally so capital is never trapped. |
| `DEFAULT_STOP_LOSS_PCT` | 5% | Fallback when a strategy supplies no stop; prevents unbounded sizing. |

Paper fills are pessimistic by design: adverse slippage, brokerage, and
statutory charges are deducted on every fill, and buys are rejected when virtual
cash runs out. A cost-free simulation reliably overstates returns, and swing
strategies with modest edges are exactly where that illusion bites.

---

## Telegram notifications

Set `TELEGRAM_ENABLED=true` plus the token and chat id, then:

```bash
curl -X POST http://localhost:8000/api/v1/notifications/telegram/test \
  -H "X-API-Key: $API_KEY"
```

Events (`TELEGRAM_NOTIFY_ON`): `signal`, `order`, `fill`, `error`,
`daily_summary`, `system`.

Every trade message carries a **📝 PAPER** or **💰 LIVE** banner. The one thing
that must never be ambiguous is whether real money moved.

---

## Useful commands

```bash
# CLI (inside the container, or in the venv)
swingtrade status                     # system + portfolio overview
swingtrade sync-instruments           # refresh instrument master
swingtrade backfill --days 1825       # historical candles
swingtrade train --algorithm lightgbm --activate
swingtrade scan                       # run active strategies now
swingtrade create-user --username admin --password secret

# Tests
cd backend && pytest -v

# Migrations (only when you change a model — startup applies them automatically)
alembic revision --autogenerate -m "add xyz"
```

---

## Path to cloud

Already in place: 12-factor config, containerised services, versioned
migrations, structured JSON logging, separate liveness/readiness probes, no
local state except model artifacts.

Remaining when you deploy:

1. `ENVIRONMENT=production` — disables `/docs` (it is a full read/write control
   surface for the trading system).
2. `DB_AUTO_MIGRATE=false` — run migrations as a deploy step so concurrent API
   replicas cannot race on the same migration.
3. Move `MODEL_ARTIFACT_DIR` to S3/GCS.
4. Secrets from the platform's secret manager, not `.env`.
5. Keep exactly one worker replica — a second scheduler means duplicate trades.
6. Replace the `X-API-Key` dashboard auth with the JWT flow (`POST /auth/login`)
   before exposing the frontend on a public address.

---

## Honest limitations

- **Kite tokens cannot be renewed unattended.** A human must log in each trading
  morning. There is no way around this in Kite Connect's design.
- **Trading holidays are not modelled.** Ingestion on a holiday simply returns no
  bars; nothing breaks, but the calendar is weekday-only.
- **Live order reconciliation is polling-based.** Live fills are asynchronous and
  picked up by `POST /orders/sync`; there is no websocket order-update stream yet.
- **Sharpe over a six-month paper run is indicative, not significant.** The
  sample is too short to be a sound estimate.
- **Paper charges are approximated.** A single basis-point figure stands in for
  the full STT/exchange/SEBI/stamp-duty/GST stack. Directionally honest, not
  exact to the rupee.

---

## Warning

Trading involves substantial risk of loss. This software is provided as-is with
no warranty. Paper trade for a meaningful period, understand every strategy you
enable, and never deploy capital you cannot afford to lose. The six-month paper
phase is not a formality — it is the only evidence you will have that any of
this works.
