# Phase 2 evidence — M06 / M09 before vs after Service 1

Run after gap #4 universe and correction log are deployed and snapshots exist.

## Stub — 2026-10-05 (local ops only)

- P0 tables migrated (`m3r6e5p1s1v1`); `watchlist_snapshots` backfilled (49 symbols).
- B0 split-check: **0 suspicious** / 1 event — see [split_contamination_latest.md](split_contamination_latest.md).
- `brain meta-train` **not run** (skipped; too heavy for this pass).
- M06/M09 before/after table below still **empty** — fill after replay gate or a dedicated meta-train window.

## Commands (Docker Postgres up, from `backend/`)

```powershell
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain replay-week --days 5 --book paper
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain rescore-learning --since 2026-09-01
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain meta-train
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain learn
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain split-check --save
```

## Record

| Metric | Before PIT | After PIT |
|--------|------------|-----------|
| M06 ceiling on unseen months | | |
| M09 scored ideas (count) | | |
| Split contamination flagged | | |

**Decision:** Keep M06 SHADOW unless ceiling clears ~41% break-even after costs. Do not lower the margin without owner approval.

## Phase 1 gate — replay week + M09 rescore (2026-10-05, local Docker)

Host venv from `backend/` (env vars `API_KEY`, `DATABASE_URL`, `JWT_SECRET_KEY`, `TRADING_MODE` unset per CLAUDE.md):

```text
Replay week 2026-09-28 .. 2026-10-05 (paper)
  2026-09-28  nightly-20261005T154409-5031ea  NO_NEW_TRADES  WAIT=304  universe=304
  2026-09-29  nightly-20261005T154639-98a75a  NO_NEW_TRADES  WAIT=304  universe=304
  2026-09-30  nightly-20261005T154903-d90b18  NO_NEW_TRADES  WAIT=304  universe=304
  2026-10-01  nightly-20261005T155125-1b55df  NO_NEW_TRADES  WAIT=304  universe=304
  2026-10-05  nightly-20261005T155347-ed0d3c  NO_NEW_TRADES  WAIT=304  universe=304
Done — 5 trading day(s) replayed.
```

(Skip 2026-10-02..04: Gandhi Jayanti + weekend per NSE calendar.)

| Trading day | run_id | banner | counts (TRADE/WATCH/…) | universe |
|-------------|--------|--------|-------------------------|----------|
| 2026-09-28 | nightly-20261005T154409-5031ea | NO_NEW_TRADES | WAIT=304 | 304 |
| 2026-09-29 | nightly-20261005T154639-98a75a | NO_NEW_TRADES | WAIT=304 | 304 |
| 2026-09-30 | nightly-20261005T154903-d90b18 | NO_NEW_TRADES | WAIT=304 | 304 |
| 2026-10-01 | nightly-20261005T155125-1b55df | NO_NEW_TRADES | WAIT=304 | 304 |
| 2026-10-05 | nightly-20261005T155347-ed0d3c | NO_NEW_TRADES | WAIT=304 | 304 |

**M09 rescore-learning** (`--since 2026-09-01`):

```text
Scored 0 newly finished ideas (0 in total) since 2026-09-01.
Only 0 ideas have finished so far — too few to judge; keep collecting.
```

Exit code 0 for both commands (~12 min replay, ~22 s rescore). Sector-map unmapped warnings for a handful of symbols during replay (non-fatal).
