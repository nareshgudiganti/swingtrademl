# December runbook (testing phase, no new code)

Status: written 2026-11-07 for the owner. Development ends 2026-11-30. From then on the project only tests, reports and
fixes bugs. This file lists what to run, when, and what to do when something fails. Every command below was read from
code or from a committed doc; where a command could NOT be verified it is marked **[UNVERIFIED]**.

Rules that never change in December: paper trading only; production models are not retrained or replaced; the sealed
trial and signed evaluation rules are not edited; nothing is deployed before 16:30 IST on a weekday; no secret is ever
printed or committed (`.env`, Kite and API keys). Tags are never moved or deleted. A failed result stays on record.

Test environment (all local commands): from the repo root, Git Bash,
`env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=backend/src backend/.venv/Scripts/python.exe ...`
Docker Postgres must be up for any database command (they hang silently otherwise).

## Calendar

| Date | What | Who |
|---|---|---|
| by 2026-11-08 | Sign the Phase B protocol (`2026-11-05-phase-b-completion-protocol-FINAL-DRAFT.md`, package v2), merge after 16:30 IST, tag `phase-b-completion-v1` | owner |
| 2026-11-09 | Phase B may start (gates G1-G15 in the protocol, section 11) | owner |
| 2026-11-09 to 2026-12-04 | Phase B: B1, then B2, then B3, one run each | owner |
| by 2026-12-04 | Phase B record (`phase_b_finish --apply`), tag `phase-b-result` (and `wf-protocol-v2` only for a real survivor) | owner |
| 2026-12-04 or later | SX5 development run, only with the owner's separate written authorisation | owner |
| 2026-12-05 or later | 15D lab start, only after Phase B record, Amendment 3 signed and tagged | owner |
| weekly | Saturday 11:00 IST automatic brain health message (Telegram) | automatic |
| 2027-01-28 | h05 run 1 ends; runs 2 and 3 are started BY HAND | owner |

## 1. Phase B (details in `docs/brain/PHASE-B-FINISH.md` and protocol sections 7 to 9)

```
swingtrade brain phase-b --candidate B1 --dry-run     # plan only, reads no market data, writes nothing
swingtrade brain phase-b --candidate B1               # the one real run (from 2026-11-09)
python -m swing_trade_ml.brain.phase_b_finish --manifest B1            # dry run of the manifest
python -m swing_trade_ml.brain.phase_b_finish --manifest B1 --apply    # writes MANIFEST_B1.json
# then run the two git commands it prints (explicit files, one commit), check `git show --stat`, clean tree, then B2, then B3
python -m swing_trade_ml.brain.phase_b_finish                          # dry run of the final record
python -m swing_trade_ml.brain.phase_b_finish --apply                  # record + report + one ledger row
# then the git add / git commit / git tag -a phase-b-result commands it prints
```

If a run stops for any reason: do not re-run, do not open results, follow protocol section 9 (INTERRUPTION note first).

## 2. 15D selection lab (details in `docs/brain/SELECTION-LAB-START.md`)

Only through the wrapper. It refuses before 2026-12-05, without the `phase-b-result` record, without Amendment 3
(`sl-protocol-v1.1` tag and signed marker), with a dirty tree or changed frozen files.

```
python -m swing_trade_ml.brain.selection_lab_start S0 --check-only    # exit 0 = every check passes; 2 = refused, reasons printed
python -m swing_trade_ml.brain.selection_lab_start S0                 # real start; same for S1, S2, S0M, S1M, S2M, one run each
```

After a NO_SURVIVOR Phase B the lab is independent experimental research only; no failed Phase B model is promoted.
Never run `selection_lab_run` directly (it skips the date and Phase B checks).

## 3. SX5 development run (details in `docs/brain/SX5-RUN.md`)

Needs the owner's signed protocol, signing tag, approval file and a separate training authorisation (December 4 or later).
No holdout run is part of this script. SX10 is deferred and has no mode here.

```
cd backend
scripts/sx5_run.py                 # dry run (default): plan and every check
scripts/sx5_run.py --with-data     # also reads the local database (SELECT only) and prints data hashes
scripts/sx5_run.py --run --approval <file> --authorisation <file>   # the real development run
```
(prefix with the environment rules above and use `.venv/Scripts/python.exe`). Exit 0 = verdict written, 2 = refused.
Copy the run folder into the evidence folder and commit small text files only. PENDING_HOLDOUT ends the script: the
holdout steps are the owner's, per protocol section 10.

## 4. Daily and weekly checks (5D h05 lane, prod, read-only)

The h05 daily job runs by itself (Mon-Sat 07:30, 08:30, 18:30, 20:30, 22:30 IST). Check once a day after about 19:00 IST:

- `GET /api/v1/research/h05/report` (header `X-API-Key`, owner account): expect `sessions recorded` = trading days since
  2 Nov, `missed sessions` 0, no events. INCONCLUSIVE verdicts are normal until about 40 matured days (late December or later).
- `GET /brain/daily-checks/latest` and `GET /brain/weekly-health`: lines should say OK; a CHECK line needs a look.
- Telegram: the Saturday 11:00 IST health message must arrive; no message means the worker or Telegram needs a look.
- Known and understood: `TMCV` shows "not scored: invalid_features" every day (one stock, still to be explained);
  production-path parity fails on `obv_slope` only (known incident; training-basis parity is OK).
- Read-only local helpers: `python -m swing_trade_ml.brain.lanes.h05_cli report [--run-no N]`, `... protocol`, `... check`, `... parity`
  (database-backed; for prod run them inside the api container, for example `docker exec stml-api python -m swing_trade_ml.brain.lanes.h05_cli report` **[UNVERIFIED on the droplet]**).

Weekly scoreboard (research only, development data, needs the database). `python -m swing_trade_ml.brain.scoreboard ...` FAILS with a
circular-import error (found 2026-11-07, also on `origin/main`; not fixed because of the development freeze). Use this form, which works:
`python -c "import swing_trade_ml.brain.service; from swing_trade_ml.brain.scoreboard import main; main(['s1','--from','YYYY-MM-DD','--to','YYYY-MM-DD'])"`
(`s1` or `s2`; it writes under `docs/brain/evidence/scoreboard/`).
Never combine backtest, forward-research and paper P&L into one profit figure.

## 5. h05 runs 2 and 3 (after 2027-01-28)

Started by hand, once each: `python -m swing_trade_ml.brain.lanes.h05_cli start-run --run-no 2 --start <YYYY-MM-DD> --end <YYYY-MM-DD>`
(then run 3 the same way). The protocol hash must stay accepted; do not change the h05 rules. Set a calendar reminder for 2027-01-25.

## 6. Shadow lanes for 10D and 15D stay OFF

`LANE_SHADOW_ENABLED=false`. No 10D slot (10D is deferred; the model failed its test and no td-protocol-v2 exists). The 15D
lane needs a passed lab, a frozen model and the owner's `LANE_SHADOW_MODELS` choice, so it is not part of December.

## 7. When something breaks

| Symptom | First action |
|---|---|
| A tool exits 2 ("refused") | Read the printed reasons; they name the missing tag, file, date or clean tree. Fix the cause outside the result; never edit a result file. |
| A command hangs | Docker Postgres is down. Start it; a port check is not a liveness check. |
| Windows test fails with exit status 3221225794 | Process launch failure under load; re-run that file alone. It is environment, not code. |
| Deploy refused | The weekday 09:00-16:30 IST window; re-run after 16:30. Never force. |
| h05 report shows missed sessions | Do not backfill or change rules. Note it; the protocol says missed sessions are never made up. |
| Prod disk or memory alert | `docs/DEPLOY.md`, the server-watch notes; prune Docker builder cache first (owner on the droplet). |
| Anything touching orders, sizing, stops or limits | Stop. Needs a test and the owner's approval; paper mode only. |

## 8. Where things live

Protocols and amendments: `docs/superpowers/specs/`. Evidence: `docs/brain/evidence/`. Exposure ledger: `docs/brain/EXPOSURE-LEDGER.md`.
Deploy: `docs/DEPLOY.md`. Quality checks: `docs/QUALITY-CHECKS.md`. Completion report: `docs/brain/NOVEMBER-COMPLETION-REPORT.md`.
