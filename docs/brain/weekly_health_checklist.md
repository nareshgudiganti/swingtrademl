# Weekly brain health checklist (owner)

~15 minutes once per week on a trading day. Full detail: [TESTING.md](TESTING.md).

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
