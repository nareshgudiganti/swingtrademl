# Brain testing — step by step

Use this when you want a clear **yes/no**: is the brain **running and storing decisions correctly**?

This is **not** a test of whether the brain will make money. A healthy brain can still show mostly **WAIT** and banner **NO NEW TRADES** when data is stale or the market gate is careful.

---

## Before you start

| You need | Why |
|----------|-----|
| Logged in to the app (or `API_KEY` for read-only API checks) | Brain routes are protected |
| `BRAIN_ENABLED=true` in that environment | If false, `/api/v1/brain/*` returns **404** |
| Backend **worker** running (not API only) | Nightly job ~15:50 IST; “Run brain now” uses a queue |
| **TradeMind brain** strategy **active** (Strategies page) | If off, M18 stops recording shadow ideas |

---

## Test plan (four levels)

Do **Level 1** every day. Do **Level 2** after deploy or when something looks wrong. **Level 3** is on your PC. **Level 4** is for developers (automated tests).

---

### Level 1 — Five minutes in the app (owner)

**Goal:** Last night’s run exists and the page makes sense.

| Step | What to do | Pass | Fail |
|------|------------|------|------|
| 1.1 | Open **Brain** / TradeMind | Page loads, no “not found” | 404 or blank brain |
| 1.2 | Check **latest nightly** date | Last **trading day** (not a weekend/holiday) | No run for days |
| 1.3 | Read the **banner** (top) | One of NORMAL / DEFENSIVE / NO NEW TRADES with a plain sentence | Error text or empty |
| 1.4 | Open **one stock card** | Word (TRADE/WATCH/WAIT/AVOID) + reasons in English | Missing word or crash |
| 1.5 | **Trading stage** card | Shows **Practice (shadow)** and “N of 30 … finished” | Stage changed without you |
| 1.6 | **Strategies** → TradeMind brain | **Active** | Inactive (M18 ideas stop) |

**Practice stage:** you must **not** see **Approve** on ideas. That is correct, not a failure.

---

### Level 2 — API checks (confirm the database matches the UI)

Use your browser network tab, or curl with header `X-API-Key: <your key>` (never share the key).

Base URL: production `https://swingtrademl.com/api/v1` or local `http://localhost:8000/api/v1`.

| Step | Request | Pass | Fail |
|------|---------|------|------|
| 2.1 | `GET /brain/health` | `last_nightly_ok` within ~1 trading day; `failed_runs_7d` is 0 or small; `last_run.status` = `done` | `failed`, or no `last_nightly_ok` for days |
| 2.2 | `GET /brain/runs/latest?kind=nightly` | `live: true`, `status: done`, `counts` object present | `failed`, `live: false` for “today” |
| 2.3 | `GET /brain/modules` | M07 **mandatory** and **on**; M01, M02, M08 **on** | M07 off (should be impossible via API) |
| 2.4 | `GET /brain/stage` | `stage: shadow` until you change it | Unexpected `approval` / `auto` |
| 2.5 | `GET /brain/compare` | JSON with brain vs v1 comparison (after a few trading days) | Empty or error |

**How to read `health.data`:**

- `fresh: true` → M01 happy with market data.
- `fresh: false` → brain may still **run** but banner often **NO NEW TRADES** (safety working).

---

### Docker — rebuild after backend code changes

The **api** and **worker** images copy Python code at build time. Edits under `backend/` do not appear in running containers until you rebuild and recreate them.

From the **repo root** (with Docker Desktop running):

```powershell
docker compose build api worker
docker compose up -d api worker
docker exec stml-api alembic upgrade head
```

Then run Service 1 / brain checks **inside** the api container (same paths as production):

```powershell
docker exec stml-api python -m swing_trade_ml.cli brain split-check
docker exec stml-api python -c "from swing_trade_ml.db.session import session_scope; from swing_trade_ml.services.watchlist_snapshots import record_watchlist_snapshot; _s=session_scope(); _db=_s.__enter__(); _n=record_watchlist_snapshot(_db); _db.commit(); _s.__exit__(None,None,None); print('watchlist_snapshots:', _n)"
```

If `docker compose` or `docker exec` fails on your machine, run the same commands manually once Docker is healthy; the worker must be recreated after rebuild or it still runs the old scheduler code.

---

### Level 3 — Local command line (deep check on your machine)

From `backend/` with `.venv` and Docker Postgres up:

```powershell
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain modules
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain split-check
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain run --kind nightly --symbols RELIANCE,TCS --book paper
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain why RELIANCE --book paper
```

| Step | Pass | Fail |
|------|------|------|
| `brain modules` | Lists M01–M15 and modes | Command error |
| `brain run` | Prints `Run <run_id> …` and stock lines; ends without traceback | Exception or hang > 30 min |
| `brain why` | Full trace for one symbol | Exception |

**Validation week and the learning watchdog:**

```powershell
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain validate-week --days 5 [--out path.json]
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain rescore-learning
```

`validate-week` is `replay-week` plus a JSON evidence report (default `docs/brain/evidence/validation_week_<from>_<to>.json`: run ids, data manifest, word counts, safety-rule booleans, decision fingerprint, `/brain/compare` snapshot) and a short plain-English summary. The golden-day and WHY-integrity checks run in the test suite (`tests/test_brain_golden_day.py`, `tests/test_brain_validation.py`).

Exit codes for `rescore-learning`, `learn` and `validate-week` (use them in cron or a watchdog):

| Code | Meaning |
|------|---------|
| 0 | Finished. For `validate-week`: every safety rule held on every replayed day. |
| 1 | Failed (error logged at error level). `rescore-learning` / `learn` also send one Telegram alert through the normal notifier. Also used for bad `--days/--from/--to` and a busy run lock. |
| 2 | Bad command-line arguments (argparse). |
| 3 | `validate-week` only: the replay ran and the report was written, but a safety rule was broken on some day. Read the report. |

The weekly scheduled learning job (`brain_learn`) never raises; on failure it logs `job.failed` at error level and sends the same single "Job failed" alert.

**Optional M18:**

```powershell
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain strategy-create
.\.venv\Scripts\python.exe -m swing_trade_ml.cli brain shadow-scan
```

Pass: commands finish; shadow-scan reports signals recorded (stage must stay shadow for no buys).

**Known local gotchas (not always “brain broken”):**

- Warning `brain.reader.model_unavailable` if model files point at `/app/data/models/...` on Windows — use Docker API/worker paths or fix `MODEL_ARTIFACT_DIR`.
- First run after memory reset can take **several minutes** (M05 rebuild).
- Stale candle DB → banner **NO_NEW_TRADES** (M01 doing its job).

---

### Level 4 — Automated tests (developers)

Docker Postgres must be running.

```powershell
cd backend
$env:API_KEY=''; $env:DATABASE_URL=''; $env:JWT_SECRET_KEY=''; $env:TRADING_MODE='paper'
.\.venv\Scripts\python.exe -m pytest tests/test_brain_api.py tests/test_brain_m18_shadow.py -q
```

Pass: all tests green. This proves **code behaviour**, not your production data freshness.

---

## Finalise — one signing-off checklist

Copy this and tick when true:

```
[ ] Level 1: Brain UI — latest nightly, banner, cards OK
[ ] Level 1: Stage = Practice; brain strategy Active
[ ] Level 2: /brain/health — last nightly done, failures low
[ ] Level 2: /brain/runs/latest — live nightly done
[ ] (If testing M18) /brain/compare returns data; 30-idea counter moves over weeks
[ ] I understand: WAIT / NO NEW TRADES can mean "working safely", not "broken"
```

**Sign-off meanings:**

| Outcome | Meaning |
|---------|---------|
| **Brain operational** | Levels 1–2 pass; runs complete; decisions stored |
| **Brain cautious** | Operational but banner NO NEW TRADES or mostly WAIT — check data ingest (candles, holidays) |
| **Brain broken** | Repeated `failed` runs, 404 with BRAIN_ENABLED true, or UI empty while health says failed |

---

## Example: real run on this project (2026-10-05, local CLI)

This is what a **successful run** looks like when data is **stale** (brain still works; it refuses to be aggressive).

**Command:** `brain run --kind nightly --symbols RELIANCE,TCS --book paper`

| Check | Result |
|-------|--------|
| Run finished? | **Pass** — `run_id` `nightly-20261005T111323-d31a36`, ~56 s |
| Status | **Pass** — `done`, no error |
| Banner | **Expected caution** — `NO_NEW_TRADES` (NIFTY last price 07 Sep 2026, 18 trading days old) |
| RELIANCE | **Pass (logic)** — `WAIT`, “No opinion … (no model score …)” — model file missing on host + no M06 answer |
| TCS | **Pass (logic)** — `AVOID`, results on 08 Oct (M13 landmine) |
| Holdings | **Pass** — GMRAIRPORT `HOLD`, others `MONITOR` with reasons |
| Fallbacks | **Pass** — “Steps answered by their fallback: remember, reason” when model/M06 unavailable |
| `/brain/health` (same DB) | `failed_runs_7d: 0`, `fresh: false`, `stale_count: 5` |

**Automated tests same day:** `test_brain_api.py` + `test_brain_m18_shadow.py` → **18 passed**.

**What would have been a failure:** traceback, `status: failed`, or health showing repeated failures with no new `done` nightly.

---

## When something fails — quick map

| Symptom | Likely cause | What to do |
|---------|----------------|------------|
| `/brain/*` 404 | `BRAIN_ENABLED=false` | Set true in env; restart API/worker |
| No nightly after 16:00 IST | Worker down or job not registered | Check worker logs for `job.brain.done` |
| `failed` in health | Exception during run | Read `last_run.error` in health or run row in DB |
| Always NO NEW TRADES | Stale NIFTY/candles or bad holiday calendar | Run data refresh; check `core/holidays.py` after 2026 |
| All WAIT, “no model score” | Model files missing or wrong path | Confirm models in worker container `/app/data/models` |
| 30-idea gate stuck at 0 | Brain strategy off or no finished shadow ideas | Activate strategy; wait for scored signals |

---

## Related docs

- `GO_LIVE.md` — practice / approval / automatic stages  
- `BUILD_NOTES.md` — what each module does and SHADOW modules  
- `docs/architecture/CURRENT-STATE.md` — known issues and next ops tasks  
