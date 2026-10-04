# CLAUDE.md — Swing Trade Bot / TradeMind

Read this first in every session. Then read `docs/architecture/CURRENT-STATE.md`.

## What this repo is

- **Production** runs from GitHub `main` (latest on origin: `8ea5e63`, “One market clock”). Push to
  `main` deploys to swingtrademl.com (DigitalOcean droplet). Git tag `v1` = `64fcb05` is a **frozen
  rollback reference only** — prod does not run from that tag.
- **Version 1 (v1)**: the swing-trading app stack (FastAPI + Postgres/TimescaleDB + Redis +
  APScheduler, React/Vite frontend). Still the core runtime; brain modules plug into it.
- **TradeMind Brain**: decision layer under `backend/src/swing_trade_ml/brain/`. The full stack
  (including `753e3e7`) is on `main` and **live in production since 2026-10-04 in practice mode**
  (M18 shadow / practice stage — no auto brain-driven orders yet). Use local `brain/*` branches
  (e.g. worktree `.claude/worktrees/brain-m00`) for brain work that has **not** shipped to `main`.
  `BRAIN_ENABLED` can still gate scheduling/API exposure in some environments; in prod the brain
  code is present and runs in practice mode — it is not “off by default” there.

## TradeMind architecture principles (settled — do not change without the owner)

1. **One backend, logical modules — no new microservices or infrastructure.** No Kafka, Airflow,
   S3, vector DB, alt-data. Reuse Postgres/TimescaleDB, Redis, APScheduler.
2. **"Service 1" (Market Data & Input Processing) is a logical layer, not a deployed service.**
   It is v1 ingestion + side feeds + the brain's `DatedReader` + M01 quality + M02 snapshots.
   See `docs/architecture/service-01-market-data.md`.
3. **Service 1 prepares trustworthy, point-in-time data. The Brain makes every decision.**
   No ranking, selection, risk or decision logic in the data layer.
4. **Modules are pure**: `run(view) -> Contribution`; no DB writes, no orders. Storage happens in
   `brain/service._store`. All brain DB reads go through `brain/reader.py` (`DatedReader`),
   bounded by the run's `as_of` (no look-ahead).
5. **Decisions only move toward caution.** Bad/stale data never makes a decision more aggressive.
   Missing M07 risk gate → NO NEW TRADES. Every module has a safe fallback.
6. **Vocabulary (Option A)**: ideas TRADE/WATCH/WAIT/AVOID; holdings HOLD/MONITOR/REDUCE/EXIT;
   banner NORMAL/DEFENSIVE/NO_NEW_TRADES.
7. **Trading rules**: horizon ≤ 15 trading days, +8% target / −4% stop, half out at +5%.
8. **v1 data and v1 trading path stay untouched.** New data layers (e.g. adjusted prices) sit
   *next to* v1 tables and are read only by the brain.
9. **Keep it understandable for a single developer.**

## Current implementation status (2026-10-04)

- Brain modules M00–M17 on `main`, folded into `brain/integration`.
- **M18 (shadow → manual approval → auto)** on `main` (`10ae6d1` integration; brain stack through
  `753e3e7`). **Production is in M18 practice mode** (shadow): brain runs and records ideas; stage
  advances after 30 finished brain ideas, then manual approval, then auto — per `docs/brain/GO_LIVE.md`.
- **Service 1 gap integration (13 "NEW GAP" items): analysed only. Nothing implemented. Owner has
  not yet approved a build list.** See `docs/architecture/architecture-gaps.md`.

## Risk rules (settled 2026-09-14 — never loosen without the owner)

- **Paper first.** `TRADING_MODE=paper`. Never set `TRADING_MODE=live` or
  `ALLOW_LIVE_TRADING=true`, locally or in prod. Going live is the owner's call only, after a
  manual-approval trial (M18).
- Per trade: +8% target / −4% stop, sell half at +5%, exit within 15 trading days. The 30-day
  time stop in v1 is *calendar* days and already agrees with this — do not "fix" it to 15.
- **15% portfolio drawdown from peak → halt all new entries** (`MAX_PORTFOLIO_DRAWDOWN_PCT`).
- **25% max of the account in one sector** (smallest account tier: one stock per sector) —
  `services/limits.py`. Limits scale with account size (₹10K → ₹1Cr ladder).
- Any change that touches order placement, sizing, stops or limits needs a test and the
  owner's approval before it reaches `main` (= prod).

## Secrets and API keys — never read, print, log or commit

- `.env` (root) holds real credentials; it is gitignored. Do not `cat` it or echo its values.
  If you need to know which settings exist, read `.env.example` or print names only.
- Never commit, paste into docs/chat, or send anywhere: `KITE_API_KEY`, `KITE_API_SECRET`,
  `KITE_PASSWORD`, `KITE_TOTP_SECRET`, `KITE_USER_ID`, Kite access tokens, `API_KEY`,
  `JWT_SECRET_KEY`, `GOOGLE_CLIENT_SECRET`, `POSTGRES_PASSWORD`, `DATABASE_URL`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Using `API_KEY` from `.env` in a header to query the prod REST API is allowed (read-only
  checks); never write it into a file or command output.
- Never place real orders through Kite from a session, and never trigger a Kite login against
  local — Kite logins go to prod.

## Important constraints

- **`brain/*` branches** are for in-progress brain work not yet on `main`. Ship brain changes via
  `main` (deploys to prod). Do not push experimental `brain/*` branches or open brain PRs without
  the owner’s go-ahead; trading-sensitive merges still need owner approval before `main`.
- Never `ruff format` the whole package (rewrites ~50 v1 files) — format only files you touched.
  No prettier on existing frontend files; check with `npx tsc --noEmit -p .`.
- Run tests with `backend/.venv/Scripts/python.exe` and
  `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE`. DB tests need Docker
  Postgres up (they hang silently otherwise).
- Daily candles are stamped IST midnight (18:30 UTC previous day) → always `.astimezone(IST).date()`.
- Never use bare `git stash` (stack is shared across worktrees).
- Owner is not a finance/ML expert: plain English in UI and summaries.

## Where things are

| What | Where |
|---|---|
| Current state, next task | `docs/architecture/CURRENT-STATE.md` |
| Service 1 architecture | `docs/architecture/service-01-market-data.md` |
| Gap list + status | `docs/architecture/architecture-gaps.md` |
| Why Service 1 gaps / Brain split | `docs/decisions/ADR-001-service-01-gaps.md` |
| Brain build notes, lessons | `docs/brain/BUILD_NOTES.md` (brain worktree) |
| M18 go-live guide | `docs/brain/GO_LIVE.md` (brain worktree) |
| Brain build book (spec) | `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` |
| v1 status | `docs/ROADMAP_TRACKER.md`, deploy: `docs/DEPLOY.md` |
