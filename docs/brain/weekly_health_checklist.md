# Weekly brain health checklist (owner)

~15 minutes once per week on a trading day. Full detail: [TESTING.md](TESTING.md).

## Automatic check (runs for you)

A worker job runs **every Saturday at 11:00 IST** (an hour after the weekly learning run). It only
reads and reports: it places no orders and changes nothing. It stores the result and sends **one**
Telegram message (if Telegram is on; if not, the result is still stored). Read the last result any
time with `GET /brain/weekly-health` (needs `X-API-Key`; says "not run yet" before the first run).

Each line starts with **OK** (fine) or **CHECK** (look at this). Lines marked for information
never fail.

| Line | What it means |
|------|---------------|
| Nightly run | The last finished nightly brain run is from the latest trading day (weekends and NSE holidays do not count against it). |
| Failed runs | No brain runs failed in the last 7 days. |
| Data freshness | The data check from the last nightly run says prices are fresh. |
| Feed: delivery / bulk and block deals / FII/DII flows | Each side feed has data from within the last 3 trading days. |
| Key modules | M01, M02, M07 and M08 are all on. |
| Trading stage | Still Practice (shadow). CHECK if the stage changed. |
| Finished ideas | "N of 30" finished brain ideas. Information only. |
| Banner | The current banner (NORMAL, DEFENSIVE or NO NEW TRADES). Information only. |
| Learning and drift | This Saturday's learning/drift result, or "Not checked yet". Information only. |
| Model backup | Date of the newest file in the model backup folder. CHECK (warning) if no backup folder is set up or it is empty: backup runs are not recorded anywhere, so nothing is guessed. |

If the message says all good, you can skip the manual steps below. They stay as a fallback (for
example if no message arrives, which itself means the worker or Telegram needs a look).

## Quick UI (Level 1)

- [ ] Brain / TradeMind loads; latest **nightly** is the last trading day.
- [ ] Banner is NORMAL, DEFENSIVE, or NO NEW TRADES (not an error).
- [ ] One stock card shows a word + reasons in plain English.
- [ ] M18 stage still **Practice (shadow)**; note **N of 30** finished ideas.
- [ ] Strategies → **TradeMind brain** is **Active**.

## API (Level 2 — needs `X-API-Key`)

Base: `https://swingtrademl.com/api/v1`

| Check | Endpoint | Look for |
|-------|----------|----------|
| Brain health | `GET /brain/health` | `last_nightly_ok` recent; `failed_runs_7d` low |
| Latest run | `GET /brain/runs/latest?kind=nightly` | `status: done`, `live: true` |
| Modules | `GET /brain/modules` | M07 on; M01, M02, M08 on |
| Stage | `GET /brain/stage` | `shadow` until you change it |
| Compare | `GET /brain/compare` | Present after a few trading days |

Public (no key): `GET /api/v1/health` → `status: ok`.

## Optional CLI on droplet

```bash
docker exec stml-api python -m swing_trade_ml.cli brain split-check
```

## When something fails

- Stale data → banner often NO NEW TRADES (safety). Check ingest / Kite session on prod.
- No nightly for days → worker scheduler, `BRAIN_ENABLED`, brain strategy active.
- See [TESTING.md](TESTING.md) Level 3–4 and [LIVE_READINESS.md](LIVE_READINESS.md) for live blockers.

Record the date and N-of-30 in your notes; update [ROADMAP.md](ROADMAP.md) Phase 0 checkboxes when
you complete a week.
