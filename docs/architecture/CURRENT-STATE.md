# Current state — 2026-10-05

## Completed

- **v1** live in production (DigitalOcean, swingtrademl.com). Rollback tag `v1` = `64fcb05`.
  Paper trial running from 2026-09-28.
- **Brain M00–M18** on GitHub `main`. TradeMind screens (`/trademind`) wired to live brain data.
  **Production: M18 practice (shadow)** since 2026-10-04 — no auto brain-driven live orders.
- **M18 go-live switch**: shadow strategy, brain-vs-v1 comparison, 30-idea gate, approvals path,
  rollback, console cards — see `docs/brain/GO_LIVE.md`.
- **Service 1 P0 (shipped `fcaef35`)**: split-check CLI; `watchlist_snapshots` + PIT replay universe;
  `candle_corrections` on ingest + M02 `feature_snapshots` invalidation from corrected bar;
  provisional **2027** holidays; `data_manifest` on brain runs;
  feed `connector_status` on `/brain/health`; `obv_slope` train/serve fix; nightly + ingest
  watchlist snapshot hooks in `workers/jobs.py`.
- **Phase 1 gate (local, 2026-10-05)**: `brain replay-week` + `brain rescore-learning` — evidence in
  `docs/brain/evidence/PHASE2_EVIDENCE_TEMPLATE.md`. B0 split-check clean → **gap #3 adjusted prices
  deferred**.
- **Plans manager** (Free/Plus/Pro) on a feature branch; off by default in prod.

## In progress / ops (not new feature code)

- **Production droplet**: after each `main` deploy, run checklist
  `docs/brain/evidence/prod_deploy_20261005.md` (rebuild api/worker, alembic head `m3r6e5p1s1v1`,
  snapshot, split-check). SSH is owner-side; CI deploy does not replace rebuild when backend changes.
- **M18 evidence**: collect **30 finished shadow ideas** before approval stage opens.
- **Weekly brain health**: `docs/brain/weekly_health_checklist.md` + `docs/brain/TESTING.md`.
- **Model artifacts**: primary dir `MODEL_ARTIFACT_DIR` (default `./data/models`); optional
  `MODEL_BACKUP_DIR` — runbook `docs/brain/evidence/model_artifact_backup.md`.

## Remains (approved roadmap)

| Area | What |
|------|------|
| Phase 0 ops | Prod ingest freshness on trading days; off-droplet model backup habit |
| Phase 2 | M06 meta-train + M09 before/after evidence doc |
| Phase 3 | Playbook candidates, M11 sector gate (config off), shadow comparison gate |
| Phase 4 | Live blockers (`docs/brain/LIVE_READINESS.md`); M18 approval trial after gates |
| Deferred | Gap **#3** adjusted layer unless split-check flags contamination; M19 / Pro |

## Next exact tasks

1. **Owner on droplet**: complete `prod_deploy_20261005.md` for commit `fcaef35` (or latest `main`).
2. **Owner weekly**: Level 1–2 in TESTING.md; track M18 “N of 30”.
3. **Dev (optional)**: Phase 2 evidence after meta-train; Phase 3 only in paper.

## Tests (reference)

- Service 1 P0 + replay-week tests added 2026-10-05 (`test_split_check`, `test_watchlist_snapshots`,
  `test_candle_corrections`, `test_brain_replay_week`, etc.).
- Full brain suite on `main` before deploy: use `backend/.venv` + Docker Postgres per `CLAUDE.md`.

## Known issues (still true)

- **M06 SHADOW**: meta-model below break-even; ideas often **WAIT** — expected until evidence improves.
- **Gap #3**: no adjusted price layer; B0 clean 2026-10-05 — monitor with periodic `brain split-check`.
- **M18 minors**: no v1 cash reservation on brain buys; paper “live” price can be prior close without Kite;
  approvals endpoint may wait on Telegram; `by` is client-set.
- **Local check DB** may show bad opening equity on some dates (v1 data quirk).

## Doc pointers

- Roadmap: `docs/brain/ROADMAP.md`
- Gaps: `docs/architecture/architecture-gaps.md`
- Testing: `docs/brain/TESTING.md`
