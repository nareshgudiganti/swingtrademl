# Current state — 2026-10-04

## Completed

- **v1** live in production (DigitalOcean, swingtrademl.com). Rollback tag `v1` = `64fcb05`.
  Paper trial running from 2026-09-28.
- **Brain M00–M17** on GitHub `main` (through `753e3e7`). TradeMind screens (`/trademind`) wired
  to live brain data. **Live in production since 2026-10-04 in M18 practice (shadow) mode.**
- **M18 go-live switch** on `main` (`10ae6d1` integration; stack through `753e3e7`):
  - shadow strategy, brain-vs-v1 comparison, owner stage switch with the 30-idea gate
  - approvals (valid until the next close, placed at the next open after a live-price re-check)
  - rollback, console cards, `docs/brain/GO_LIVE.md`
  - final-review fix round done (slot share, no confidence-decay on brain buys, no risk events
    from practice refusals, late-fill position link, switch-off resets stage)
- **Service 1 gap analysis** done: 13 NEW GAP items checked against the code. See
  `architecture-gaps.md` and `ADR-001-service-01-gaps.md`.
- **Plans manager** (Free/Plus/Pro) on local `feature/plans-manager`, off by default.

## Currently being implemented

- **M18**: merged to `main`. Nothing left to implement; collecting shadow evidence in production
  (practice stage).
- **Service 1 gaps**: none in progress. Waiting for the owner to approve a build list.

## Remains

- Collect 30 finished M18 shadow ideas before the approval stage can open.
- Owner decisions on Service 1: which gaps to build, and whether gap 3 goes before more M18 work.
- Service 1 must-do items (if approved): 3 corporate-action layer, 4 point-in-time universe,
  11 calendar 2027+, 13 correction log. Then 5/8 manifest, 10 readiness, 9 breakdown,
  2 security master lite, 7 `obv_slope` skew.
- M19 (plans and legal review) later. Further brain changes ship via `main` like any prod change;
  use `brain/*` branches only for work not yet merged.

## Next exact task

1. M18 is merged (`10ae6d1`), so this is the next task: with the owner's go-ahead and local Docker Postgres running, run the read-only
   **split-contamination check**: one-day close moves > 30% on known split/bonus dates in
   `candles`. Its result decides whether Service 1 gap 3 jumps ahead.

## Files changed

- This documentation pass (untracked, in the main checkout): `CLAUDE.md`,
  `docs/architecture/service-01-market-data.md`, `docs/architecture/architecture-gaps.md`,
  `docs/architecture/CURRENT-STATE.md`, `docs/decisions/ADR-001-service-01-gaps.md`.
- M18 (merged into `brain/integration`, last fix `fd77917`): `strategies/brain.py`, `services/brain_golive/`
  (shadow, compare, stage, approvals), `db/models/brain_golive.py`, migrations `d2a7c4e9f150`
  and `e8b3f1a6c247`, edits to v1 `services/risk.py`, `services/execution.py`,
  `strategies.py`, `core/strategy_policy.py`, `workers/jobs.py`, `cli.py`, frontend
  `components/BrainGoLive.tsx`, `pages/Brain.tsx`, `api/types.ts`; docs `docs/brain/GO_LIVE.md`,
  `docs/brain/BUILD_NOTES.md`.
- Service 1: no code changed.
- Main checkout has unrelated uncommitted edits: `frontend/src/App.tsx`,
  `components/icons.tsx`, `styles.css`.

## Tests completed

- M18 full backend suite after the fix round: **1103 passed**. Every new test was seen failing
  first.
- Final-review subset (`brain or strategy_policy or execution or engine or risk`): 689 passed.
- `npx tsc --noEmit`: clean.
- Real check on the local check DB: 49 brain signals, 0 TRADE ideas, orders 55 → 55 (nothing
  bought). The stage switch refuses with "Only 0 of 30…".
- Service 1: no tests (nothing built).

## Known issues

- **Calendar**: `core/holidays.py` has no 2027 dates. Deadlines and freshness break from 1 Jan 2027.
- **Replay universe** uses today's watchlist (hindsight bias in replays and evidence).
- **Candle corrections overwrite** history. No corporate-action adjustment.
- **M02 `obv_slope`** differs from the batch feature code.
- **M06 stays SHADOW**: its honest ceiling is 24.5% against the 41% break-even, so all ideas are WAIT.
- **M18 minors**:
  - No cash is reserved for v1 when the brain buys.
  - The late-fill position link is only filled on the approvals list or after the open job.
  - In paper mode without a Kite session, the "live" price can be yesterday's close.
  - `GET /brain/approvals` can wait on a Telegram send.
  - `by` is client-set.
- **Local check DB** has the wrong 28 Sep opening equity (Portfolio shows +435.6%). This is v1
  data, not a UI bug.
- Plans branch and brain branch have separate alembic heads, so a merge migration is needed.
