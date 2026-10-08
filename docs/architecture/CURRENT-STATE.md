# Current state — 2026-10-08

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
- **Plans manager** (Free / Pro) is on `main` and live since the 2026-10-06 deploy; the owner switch is
  OFF, so the owner sees everything and nobody is limited.
- **Deploy gate fixed 2026-10-06 (`f69134a`)**: every push to `main` from 2026-10-04 to 2026-10-05 failed
  the backend test gate (M08 read sector data without declaring `SectorState@1`; one stale replay test)
  and nothing deployed; then a migration ran in the wrong order on the server and rolled back. Both
  fixed. A red "Deploy to production" run in GitHub Actions means nothing was deployed.
- **Login / Testing tab (`19d3cb0`)**: login page hides "Sign up" when sign-up is closed
  (`GET /auth/options`); the Testing tab explains it is switched off (`PAPER_TESTER_ENABLED=false`).

## In progress / ops (not new feature code)

- **Production droplet**: the deploy script (`infra/deploy/release.sh`) builds api/worker/frontend,
  takes a database dump (server-side only), runs alembic, verifies a worker heartbeat and rolls back to
  the previous images on failure. After a deploy, still do the split-check/snapshot items in
  `docs/brain/evidence/prod_deploy_20261005.md`. SSH is owner-side.
- **Built 2026-10-08, ships with the next `main` deploy**: Saturday 11:00 IST brain health report
  (Telegram + `GET /brain/weekly-health`, alembic head `w7h3a1t5h0c1`); `swingtrade brain validate-week`,
  golden-day test, WHY integrity check and rescore watchdog (validation steps 1-5); authenticated model
  zip `GET /ml/backup/models.zip` + `scripts/backup-models-from-prod.ps1` for an off-server copy
  (database dumps are still only on the server).
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

- **Brain records no ideas while the market is stressed (diagnosed 2026-10-08)**: the brain reaches TRADE
  for ~119 stocks, then version 1's market-stress rule (`services/risk.py`, max 10% invested) rejects
  108 of them because the two open paper positions already use the cap. So "N of 30" stays 0. Not caused
  by the DEFENSIVE rule or by M06. **Owner chose option B (2026-10-09); implemented on a worktree branch,
  not yet on `main`.** In practice mode only, a brain idea refused by a v1 risk limit (market-stress cap,
  slots, cash, sector...) is tagged `features["blocked_by_risk_limit"]` and its reason is prefixed
  "Blocked by a risk limit (practice evidence only)". It is scored to outcome like any idea but is NOT a
  risk event, and no limit or order path changed. **Counting (conservative):** the "N of 30" gate counts
  only ideas that could really have been placed; blocked ones are reported separately
  (`finished_blocked` on `/brain/stage`, `brain_finished_blocked` on the compare report) and excluded
  from the brain-vs-v1 hit rate. One switch, `COUNT_BLOCKED_TOWARD_GATE` in
  `services/brain_golive/compare.py`, lets the owner count them toward the gate too. Note: rejected brain
  signals were already being saved and scored before this change (untagged), so those older ones still
  count as before; a 0 may also simply mean 15-day horizons have not finished yet. The frontend does not
  show the new blocked number yet.

- **M06 SHADOW**: meta-model below break-even; ideas often **WAIT** — expected until evidence improves.
- **Gap #3**: no adjusted price layer; B0 clean 2026-10-05 — monitor with periodic `brain split-check`.
- **M18 minors**: no v1 cash reservation on brain buys; paper “live” price can be prior close without Kite;
  approvals endpoint may wait on Telegram; `by` is client-set.
- **Local check DB** may show bad opening equity on some dates (v1 data quirk).

## Doc pointers

- **Solution vision (diagram → code → gaps):** `docs/architecture/TRADEMIND-SOLUTION-OVERVIEW.md`
- Roadmap: `docs/brain/ROADMAP.md`
- Gaps: `docs/architecture/architecture-gaps.md`
- Testing: `docs/brain/TESTING.md`
