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

- **Brain recorded no ideas, 2026-10-04 to 10-09 (root cause found 2026-10-09, fix on `develop`)**: the
  brain's own risk module (M07) asks version 1's `check_entry`; when it says no, M08 `_risk_check`
  (`brain/modules/m08_decide/rules.py`) lowers TRADE to WATCH ("Good idea, but the risk check said no").
  `strategies/brain.py` turned every non-TRADE into a HOLD with no stop/target, and the compare report and
  the "N of 30" gate only count BUYs with stop and target — so nothing was ever counted (74-108 such ideas
  a day on prod). The earlier note that "version 1 rejected 108" was wrong: these were brain-side
  downgrades, and the v1-side tag (`a139d9f`) never fired. **Fix:** in the practice stage only, such a
  WATCH (downgraded from TRADE purely by the risk check, levels present, no owner overrule) is emitted as
  a BUY tagged `features["blocked_by_risk_limit"]`, so it is scored to outcome, counted as
  `finished_blocked` (not toward the gate; switch `COUNT_BLOCKED_TOWARD_GATE` in `compare.py`), kept off
  `/signals/picks`, `/buy-list`, the suggestion list and the track record, and never made an approval.
  The brain strategy is advisory, so nothing is bought. Tests: `test_brain_risk_downgrade_evidence.py`.

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
