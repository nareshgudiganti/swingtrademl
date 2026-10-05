# Brain and Service 1 roadmap

Living tracker for the approved brain/gaps plan (`.cursor/plans/brain_and_gaps_roadmap_80009dda.plan.md` on the dev machine). Operational checks: [TESTING.md](TESTING.md).

**Owner sign-off:** P0 Service 1 build list and M18 gating defaults approved for implementation (2026-10-05).

## Brain validation phase (baseline `0bdaa76`)

**Freeze:** no new trading features; prove the brain, then build only what evidence demands.

Inspection (read-only, sections A–H): [VALIDATION_PHASE_INSPECTION.md](VALIDATION_PHASE_INSPECTION.md). **Await owner approval** before implementing the phased sequence in §F of that doc.

## Phase 0 — Evidence and ops

- [x] Split-contamination check CLI (`swingtrade brain split-check`)
- [ ] Weekly brain health per [weekly_health_checklist.md](weekly_health_checklist.md) / TESTING.md (owner)
- [ ] Prod ingest freshness on trading days (ops)
- [ ] Model artifact off-droplet backup (dev) — [model_artifact_backup.md](evidence/model_artifact_backup.md)
- [ ] M18: progress toward 30 finished shadow ideas (owner)

## Phase 1 — Service 1 P0

- [x] **#11** NSE calendar 2027+ (`core/holidays.py`)
- [x] **#4** Point-in-time universe (`watchlist_snapshots`, `DatedReader` replay)
- [x] **#13** Candle correction log + M02 snapshot invalidation (`candle_corrections`, `feature_snapshots` hook)
- [x] **#1 lite** `known_at` via `candle_corrections.corrected_at` (no `candles.ingested_at` yet)
- [x] **Ops (local Docker, 2026-10-05):** `alembic upgrade head` → `m3r6e5p1s1v1` (needed extra `alembic_version` row `p1a2n3s4f5r6` before merge; [alembic_local_20261005.md](evidence/alembic_local_20261005.md))
- [x] **Ops (local Docker, 2026-10-05):** initial `watchlist_snapshots` backfill (49 symbols)
- [x] **Ops (local Docker, 2026-10-05):** B0 split-check — 0 suspicious / 1 event (`evidence/split_check_20261005.md`)
- [x] **Ops (local Docker, 2026-10-05):** rebuild `api` + `worker` after backend changes ([TESTING.md](TESTING.md) Docker section)
- [x] **Gate (local Docker, 2026-10-05):** replay week (5 IST days) + M09 rescore — [evidence/PHASE2_EVIDENCE_TEMPLATE.md](evidence/PHASE2_EVIDENCE_TEMPLATE.md)
  - Replay: `swingtrade brain replay-week --days 5 --book paper` — all days `NO_NEW_TRADES`, WAIT=304, universe=304
  - Rescore: `swingtrade brain rescore-learning --since 2026-09-01` — 0 finished ideas (expected until shadow ideas complete)

## Phase 2 — Service 1 P1

- [ ] **#3** Adjusted price layer (B0 clean 2026-10-05 — **deferred**, low urgency; no build unless contamination returns)
- [x] **#7** `obv_slope` train/serve denominator fix (`ml/features.py`)
- [x] **#5/#8** Run `data_manifest` on `brain_runs.context`
- [x] **#10** Feed readiness on `/brain/health` (`brain/connectors.py` `connector_status`)
- [ ] M06 meta-train + M09 before/after evidence doc

## Phase 3 — Entry edge

- [ ] Playbook candidates → M08
- [ ] M11 sector gate
- [ ] Shadow comparison gate

## Phase 4 — Live / M18

- [ ] Phase 0 live blockers (AMO, GTT, etc.)
- [ ] M18 approval trial after gates

## Phase 5–6

- [ ] Exit model, M13 filings, challengers
- [ ] M19 / Pro product (deferred)
