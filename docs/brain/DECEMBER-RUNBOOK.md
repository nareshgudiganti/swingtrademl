# December runbook (testing phase, no new code)

Status: written 2026-11-07 for the owner. Development ends 2026-11-30. From then on the project only tests, reports and
fixes bugs. This file lists what to run, when, and what to do when something fails. Every command below was read from
code or from a committed doc; where a command could NOT be verified it is marked **[UNVERIFIED]**.

Rules that never change in December: paper trading only; production models are not retrained or replaced; the sealed
trial and signed evaluation rules are not edited; nothing is deployed before 16:30 IST on a weekday; no secret is ever
printed or committed (`.env`, Kite and API keys). Tags are never moved or deleted. A failed result stays on record.

Test environment (all local commands): from the repo root, Git Bash,
`env -u API_KEY -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=backend/src backend/.venv/Scripts/python.exe ...`
Docker Postgres must be up for any database command (they hang silently otherwise).

**Database address (corrected 2026-11-07).** The app's own default is port 5432, which does NOT match the Docker setup. The local
Docker Postgres with the data is `localhost:5433`, database `swing_trade_ml` (the same local-only credential the repo's test
configuration already commits). For any typed command that reads the database, set
`DATABASE_URL=postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml` (never a production address, and a
fresh worktree has no `.env`). The helper scripts below do this for you and refuse any non-local address.

**Two traps found while verifying these commands (both fail closed, nothing is written):**
- `python -m swing_trade_ml.cli ...` and `swingtrade ...` fail with a circular import. Import the brain service first (the typed Phase B
  form in section 1 shows how).
- `python -m swing_trade_ml.brain.phase_b_finish` uses a wrong default repository root (it looks one folder above the repo, so it reports
  every tag as missing). Always pass `--root .` from the repo root. (Fixing it would change a code file whose blob id is bound by the
  Phase B protocol, so it is left as it is.)

## 0. Helper scripts (`scripts/december/`, Windows PowerShell)

Thin wrappers that run only checks and dry runs. Each prints in plain English what it will do first, stops on the first error, never
prints secrets, never pushes, tags, commits or trains, and has NO helper for any live step (the real Phase B run, the lab start, the SX5
`--run`, every commit and tag stay typed commands). Run from the repo root:
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\december\<script> [options]` (if a policy blocks the file, this form works).

| Script | Does | Writes |
|---|---|---|
| `01-preflight.ps1` | branch, clean tree, tags, `phase_b.py` equals its tag, reserved tags not early, a real `select 1` on the local database, India date | nothing |
| `02-phase-b-dry-run.ps1 -Candidate B1` | prints one candidate's plan (no market data, no scoring) | nothing |
| `03-phase-b-manifest.ps1 -Candidate B1 [-Apply]` | manifest dry run; `-Apply` writes `MANIFEST_B1.json` only | only with `-Apply` |
| `04-phase-b-finish.ps1 [-Apply]` | final record dry run; `-Apply` writes the record, report and one ledger row | only with `-Apply` |
| `05-lab-check.ps1 -Candidate S0` | lab start wrapper in `--check-only` mode (can never start the lab) | one audit line (git-ignored) |
| `06-sx5-dry-run.ps1 [-WithData]` | SX5 plan and checks; `-WithData` also counts rows (SELECT only) | nothing |
| `07-h05-daily-check.ps1` | one read-only GET of the h05 report, prints sessions, missed sessions, events, verdicts; flags anything off | nothing |
| `08-weekly-scoreboard.ps1 -Report s1 -From YYYY-MM-DD -To YYYY-MM-DD` | the research scoreboard (working import form) | one report file under `docs/brain/evidence/scoreboard/` |

Start every working session with `01-preflight.ps1`. A FAIL on "clean tree" is normal while you have uncommitted edits.

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

Routine steps have helpers (`02`, `03`, `04` above). The typed forms, for reference:

```
# plan only (helper 02); reads no market data, writes nothing
python -c "import swing_trade_ml.brain.service; from swing_trade_ml.brain import phase_b as pb; print(pb.dry_run_plan('B1'))"
# THE ONE REAL RUN (typed by you, from 2026-11-09, from the signed branch, DATABASE_URL = the local Docker address above):
python -c "import sys, swing_trade_ml.brain.service; from swing_trade_ml.cli import main; sys.argv=['swingtrade','brain','phase-b','--candidate','B1']; raise SystemExit(main())"
python -m swing_trade_ml.brain.phase_b_finish --root . --manifest B1            # dry run of the manifest (helper 03)
python -m swing_trade_ml.brain.phase_b_finish --root . --manifest B1 --apply    # writes MANIFEST_B1.json
# then run the git commands it prints (explicit files, one commit), check the commit contents, clean tree, then B2, then B3
python -m swing_trade_ml.brain.phase_b_finish --root .                          # dry run of the final record (helper 04)
python -m swing_trade_ml.brain.phase_b_finish --root . --apply                  # record + report + one ledger row
# then the commit and annotated-tag commands it prints (typed by you)
```

If a run stops for any reason: do not re-run, do not open results, follow protocol section 9 (INTERRUPTION note first).

**Before each Phase B run (run safety, added 2026-11-09).** A run that stops after its outputs start is closed as exposed with no recovery
(protocol section 9, I2), so a sleeping laptop is the most likely way to lose a candidate. Each run: plug the laptop into power; turn
sleep and hibernate off (Windows: Settings > System > Power > Screen and sleep > "Never" while plugged in); keep the terminal open and do not
close the lid; close heavy programs (the full test suite and Phase B on one database at the same time can fail); confirm Docker Postgres answers
a real `select 1` (helper `01-preflight.ps1`); do not run a Windows update restart. Note the start time. The length of a real run is not yet
known (nothing has run on real data), so after B1 write down how long it took and check that B2 and B3 still fit before 2026-12-04.

## 2. 15D selection lab (details in `docs/brain/SELECTION-LAB-START.md`)

Only through the wrapper. It refuses before 2026-12-05, without the `phase-b-result` record, without Amendment 3
(`sl-protocol-v1.1` tag and signed marker), with a dirty tree or changed frozen files.

```
python -m swing_trade_ml.brain.selection_lab_start S0 --check-only    # exit 0 = every check passes; 2 = refused, reasons printed
python -m swing_trade_ml.brain.selection_lab_start S0                 # real start; same for S1, S2, S0M, S1M, S2M, one run each
```

After a NO_SURVIVOR Phase B the lab is independent experimental research only; no failed Phase B model is promoted.
Use the wrapper; running `selection_lab_run` directly is also refused (it repeats the date, Phase B and tag checks) but is not the supervised way.

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
- Known and understood: `TMCV` shows "not scored: invalid_features" every day. It is a new post-demerger listing with fewer than
  the 252 bars the `high_52w_dist` input needs; it is skipped, never imputed, and should become scorable around 17-18 Nov (see
  `docs/superpowers/specs/h05-tmcv-and-obv-slope-note.md`). Production-path parity fails on `obv_slope` only (known incident;
  training-basis parity is OK, and the h05 primary score is unaffected).
- The daily check is helper `07-h05-daily-check.ps1` (reads `API_KEY` from `.env` inside the script, never prints it).
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
