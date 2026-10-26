# fd-protocol-v1 layer 1 — pre-run checklist (rev 2, 2026-10-26)

The 5D historical test is one-shot. **It has not been executed.** This lists what was checked, with evidence.

## Result: ready to run, waiting only for the owner's explicit go

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Tag `fd-protocol-v1` is the signed commit `271eb1c` | PASS | `git rev-parse fd-protocol-v1` = `271eb1cb1cc9b42cf0c9422712cd7a717f67ec8f`; same on origin; PR #71 merge |
| 2 | Tag is in `origin/main` history | PASS | `git merge-base --is-ancestor fd-protocol-v1 origin/main` true |
| 3 | Protocol, tool, label trainer and account replay at the tag are the signed versions | PASS | tag version reads "SIGNED 2026-10-24", D1–D5 and D7 ticked; tests at the tag: 53 passed (`test_brain_five_day.py`, `test_trial_freeze.py`) |
| 4 | Imported modules unchanged since the tag (`walk_forward`, `phase_b`, `replay_scoring`, `horizon_grid`, `exit_policy`) | PASS | `git log fd-protocol-v1..origin/main` on these paths is empty |
| 5 | No prior official 5D result | PASS | no `docs/brain/evidence/fd_v1/`; no `fd-protocol-v1 layer 1` row in `EXPOSURE-LEDGER.md` (checked at the tag) |
| 6 | Dates and settings are the signed ones | PASS | dry run: 2023-07-01 to 2025-01-31, 21 folds, "the confirmation sample (pass or fail)"; endpoint label 5 days +2%; trade +2% / −4%; confidence exit ≤ 0.35; time stop entry + 30 calendar days; buy rule 0.60, +0.10 bear, volume ≥ 100,000, volatility ≤ 6%, falling knife −8%, 260 bars |
| 7 | Database connection | PASS (cause found) | The failure was **not a wrong password**. A locally installed PostgreSQL (`postgres.exe`, Windows service) owns port **5432**; the project's Docker Postgres is published on **5433** (`docker-compose.yml` says so). The backend default URL points at 5432, so it reached the wrong server. With the port set to 5433 the backend connects. No credential was read, printed or changed |
| 8 | Candle coverage | PASS | Docker DB `swing_trade_ml`: 49 active+watchlisted stocks, all start 2021-08-05, minimum 1,262 daily bars each (≥ 471 before 2023-07-01, ≥ 416 inside the sample); `NIFTY 50` present, 1,261 bars, 2021-08-08 to 2026-09-06 |
| 9 | Docker services | PASS | `stml-postgres`, `stml-redis` Up and healthy |
| 10 | The guard allows the run **from the tagged commit** | PASS | dry run in a worktree at `271eb1c`: "A real run is allowed." |
| 11 | The guard allows the run from current `origin/main` (`396428a`) | **REFUSED — see finding F1** | dry run: "docs/superpowers/specs/2026-10-24-five-day-protocol.md differs from the tagged version" |
| 12 | Output preserved | PLAN | report `.md` + `.json` go to `docs/brain/evidence/fd_v1/`; ledger row written before scoring; console log saved beside them; all committed to a branch for your review |

## Finding F1 — the protocol file on `main` was edited after the tag

Commit `a25efa3` (26 Oct 10:06 IST, the tv22 change) edited `docs/superpowers/specs/2026-10-24-five-day-protocol.md`
after the tag: it records D6 as signed on 2026-10-25 (shared paper account, one reserved brain slot) and rewords the
layer 2 text and one known-limits bullet. It changes **nothing about layer 1** (no setting, date, rule or benchmark),
and the tool's guard correctly treats any change to a frozen file as a protocol change, so it refuses from `main`.

I did not bypass the guard and did not edit the guard or the tag. Options for you:

- **(a) Recommended: run from a checkout of the tagged commit `271eb1c`** (a worktree `fd-tag` is ready). This is
  exactly the signed, frozen version; the manifest will record `271eb1c`. The D6 wording change is layer 2 only
  and is disclosed in the report. Risk: the tag's code is older than `main` for unrelated files — the 53 tests
  pass there and the database is reachable, so I expect none; any failure appears before the ledger row.
- (b) Treat the D6 edit as `fd-protocol-v2` and re-sign/re-tag first. Cleaner paper trail, slower, and the
  layer 1 settings stay the same.
- (c) Do nothing yet.

## Other things to know before you say go

1. The run **writes to the local Docker database**: it registers trial models named `fd_h5_*` (never activated),
   as the tool's docstring says. It touches no live setting, order, or the brain's tables. (No `fd_h5_*` models exist
   yet.)
2. The local database is the development copy; its candles end 2026-09-06. The confirmation sample ends 2025-01-31,
   so this does not matter for the pass/fail, but the report must say the data came from the local copy, not prod.
3. If the process crashes **after** the ledger row is written, that window counts as run. I will not delete the row
   to retry without your decision.
4. Run once. No retries that alter the experiment. Any outcome (PASS, FAIL or INSUFFICIENT/INCONCLUSIVE) is
   committed as is. No tuning afterwards; any change is `fd-protocol-v2`.

## Command (not run)

From the tag worktree `.claude/worktrees/fd-tag` (database on port 5433, built from the configured URL without
printing it):

```
cd .claude/worktrees/fd-tag/backend
PYTHONPATH=$PWD/src DATABASE_URL=<configured URL with port 5433> \
  <backend venv>/python.exe -m swing_trade_ml.brain.five_day --from 2023-07-01 --to 2025-01-31
```

## What I need from you

Reply with: **go (a)**, or **(b)**, or **wait**.
