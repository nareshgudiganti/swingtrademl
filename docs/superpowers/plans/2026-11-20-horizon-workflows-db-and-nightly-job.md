# Horizon Workflows: Database Tables and Nightly Job — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**In plain English (for the owner):** today the 5D / 10D / 15D workflows (#387) only exist in memory during
tests. This plan adds three new database tables to keep every result permanently, and one evening job that,
after the day's scan, runs the three workflows on the scores the scan saved and later checks each result on
its own due day. The job is **off by default** behind its own switch, never places orders, and does not touch
the nightly Brain run or any frozen trial file.

**Goal:** Persist #387's per-horizon records, runs and evaluations, and run the three workflows once per
trading session from a separate, switchable scheduler job.

**Architecture:** The pure package `brain/horizons/` (built in #387) stays pure. A new package
`swing_trade_ml/horizon_workflows/` does all database work: it reads the scan's saved `predictions` joined to
`ml_models`, turns them into `ModelOutput`s, calls `run_horizon` per stock and horizon, writes the results to
three new tables, and evaluates unfinished records against daily candles. A scheduler hook registers its job
only when `HORIZON_WORKFLOWS_ENABLED=true`, copying the shadow-lane job pattern
(`shadow_lanes/lane_job.py`: advisory lock, one savepoint per unit of work, never raises).

**Tech Stack:** Python 3.12, SQLAlchemy 2 (typed `Mapped`), Alembic, Postgres/TimescaleDB, APScheduler, pytest.

**Spec:** #387 (requirement + acceptance test) and the pure contract in
`backend/src/swing_trade_ml/brain/horizons/` (`HorizonRecord`, `Evaluation`, `HorizonStore` docstring:
"this class is the contract such a table must keep"). Owner decisions 2026-11-20: thresholds 0.80/0.60;
starting price = next-session open.

## Owner approvals needed before Task 2 starts

1. **Schema migration** (three new tables, nothing existing altered). AGENTS.md: migrations need approval.
2. **D1 — which model roles may decide.** #387 accepts only role `final`. The 5D model the Brain already uses
   (model 2) may be marked `prod` or not marked at all; if so the 5D workflow will record "No decision" every
   day. Recommendation: 5D accepts `final` or `prod`; 10D and 15D accept `final` only (same rule the shadow
   lanes use). Whether model 2 is marked `prod` is **unknown** until someone checks Admin → Models.
   **Status correction (Codex #387 round 5):** D1 is **pending**, not decided. The `brain/horizons` code on this
   branch accepts only role `final` for every horizon, including 5D, until the owner approves the
   recommendation. Any wording elsewhere that 5D already accepts `prod` is false.
3. **D2 — job time.** Recommendation: weekdays 17:30, 19:30 and 21:30 IST. The candle-readiness work (#316)
   can retry the scan until 17:00, so 17:30 is the first safe slot; later slots fill in only what is missing.

## Global Constraints

- Paper only. Never import order placement, brokers, `services/risk.py`, `services/limits.py` or Kite code.
- Do not edit any file listed in `backend/tests/trial_freeze.json` (includes `brain/service.py`,
  `brain/runner.py`, `brain/reader.py`, `ml/predict.py`). `tests/test_trial_freeze*.py` must stay green.
- Nothing outside `brain/lanes/` may mention `brain.lanes` (enforced by `tests/test_h05_service.py`).
- `brain/horizons/` stays pure: it imports only `swing_trade_ml.brain.horizons` (enforced by
  `test_package_imports_no_database_broker_or_order_code`).
- Migration: new tables only, "safe to run twice" (check `inspect(...).get_table_names()` first, as in
  `alembic/versions/20261111_1400_admin_mfa.py`), working `downgrade()`.
- Dates: every candle/prediction timestamp becomes a session date via `.astimezone(IST).date()`. Daily
  candles are `Candle.interval == "day"`, stamped at IST midnight. The index is the instrument named by
  `settings.BENCHMARK_INDEX_SYMBOL` ("NIFTY 50", exchange `INDICES`).
- Switch `HORIZON_WORKFLOWS_ENABLED: bool = False` in `core/config.py`; off = no job, no import of the package.
- Format only touched files (`ruff format <file>`); never the whole package.
- Tests: `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src
  backend/.venv/Scripts/python.exe -m pytest ...` from `backend/`; Docker Postgres must be up.
- No push, merge or deploy without the owner.

## Review Focus

1. **The scan's prediction is changed or re-written after the workflow recorded it** → the stored record keeps
   its own copy of score, close and model version; it never changes. (Test in Task 4.)
2. **The job runs twice on one day, or crashes half-way** → one run per horizon per session; a horizon that
   failed is retried by the next slot, the ones that succeeded are not duplicated. (Tests in Task 5.)
3. **Late December, next year's holiday list not yet added** → due session unknown → "No decision for this
   horizon" with a calendar reason, never a guessed date or a crash. (Test in Task 3.)
4. **Today's candles arrive late** → evaluation stays "pending"; it must not be marked "unmeasurable" just
   because ingestion is slow. Evaluate only up to the latest session that has a NIFTY 50 daily candle.
   (Test in Task 5.)
5. **The scan was re-run, so one model has two predictions for one stock on one day** → use the latest one
   that day, record its prediction id, and do not treat it as "two eligible models". (Test in Task 3.)

---

### Task 1: Per-horizon eligible roles in the pure policy (decision D1)

**Files:**
- Modify: `backend/src/swing_trade_ml/brain/horizons/policy.py` (add field), `workflow.py` (`_refusal`)
- Test: `backend/tests/test_brain_horizon_workflows.py`

**Interfaces:**
- Produces: `HorizonPolicy.eligible_roles: frozenset[str]`; defaults `{"final", "prod"}` for 5D,
  `{"final"}` for 10D and 15D (or all `{"final"}` if the owner rejects D1). `_refusal(out, policy, session)`.
  `ELIGIBLE_ROLE` is removed.

- [ ] **Step 1: Write the failing tests**

```python
def test_5d_accepts_a_prod_model():
    assert run_horizon(5, [output(5, role="prod")], SIGNAL, SESSIONS).decision == "TRADE"

@pytest.mark.parametrize("h", [10, 15])
def test_10d_and_15d_refuse_a_prod_model(h):
    record = run_horizon(h, [output(h, role="prod")], SIGNAL, SESSIONS)
    assert record.decision == NO_DECISION
    assert "not approved for decisions" in record.reason
```

- [ ] **Step 2: Run them** — expect `test_5d_accepts_a_prod_model` to FAIL (role refused).
- [ ] **Step 3: Add `eligible_roles` to `HorizonPolicy` and check `out.role in policy.eligible_roles` in `_refusal`.**
- [ ] **Step 4: Run `tests/test_brain_horizon_workflows.py`** — all pass.
- [ ] **Step 5: Commit** `feat(brain): per-horizon eligible model roles (#387)`

### Task 2: Migration and ORM models for the three tables

**Files:**
- Create: `backend/alembic/versions/20261121_1000_horizon_workflows.py` (revision `horizonwf01`,
  `down_revision` = the single current head from `alembic heads`; if there are two heads, stop and ask)
- Create: `backend/src/swing_trade_ml/db/models/horizon_workflows.py`; register it in `db/models/__init__.py`
- Test: `backend/tests/test_horizon_workflow_tables.py`

**Interfaces:**
- Produces ORM classes:
  - `HorizonRun` → `horizon_workflow_runs`: `id` BigInteger PK; `horizon` int (CHECK in 5,10,15);
    `input_session` date; `status` str(16) (`recorded` | `no_decision` | `no_inputs` | `error`);
    `reason` Text null; `n_records` int; `policy_code` str(32); `started_at`, `finished_at` timestamptz.
    UNIQUE(`horizon`, `input_session`).
  - `HorizonRecordRow` → `horizon_workflow_records`: `id` BigInteger PK; `run_id` FK runs RESTRICT;
    `horizon` int; `symbol` str(32); `instrument_id` FK instruments null; `input_session` date;
    `evaluation_due_session` date null; `decision` str(12) (CHECK in TRADE, WATCH, WAIT, NO_DECISION);
    `reason` Text; `model_id` FK ml_models RESTRICT null; `model_name` str(128) null; `model_version`
    str(32) null; `prediction_id` BigInteger null (no FK: predictions may be re-written); `score`,
    `input_close`, `target_pct`, `stop_pct`, `half_out_pct` float null; `policy_code` str(32) null;
    `created_at` timestamptz. UNIQUE(`run_id`, `symbol`); UNIQUE(`id`, `horizon`);
    **Correction (Codex #387 round 7, P2):** as drafted, a 15D record can reference a 5D run and still pass,
    so a report grouped by run could count 15D evidence under 5D. The record's `horizon` and `input_session`
    must be tied to the parent run: add UNIQUE(`id`, `horizon`, `input_session`) on the runs table and make the
    record's foreign key the composite (`run_id`, `horizon`, `input_session`) -> runs(`id`, `horizon`,
    `input_session`), with a test that a mismatching record is refused by the database;
    CHECK(`decision` = 'NO_DECISION' OR (`model_id` IS NOT NULL AND `model_version` IS NOT NULL AND
    `score` IS NOT NULL AND `evaluation_due_session` IS NOT NULL)).
  - `HorizonEvaluationRow` → `horizon_workflow_evaluations`: `record_id` BigInteger PK; `horizon` int;
    composite FK (`record_id`, `horizon`) → records(`id`, `horizon`) RESTRICT (so a label can never be
    filed under another horizon); `status` str(16) (CHECK in complete, unmeasurable); `exit_reason`
    str(8) null; `exit_session` date null; `label` smallint null; `entry_session` date null;
    `entry_price` float null; `note` Text; `evaluated_at` timestamptz.
- "Pending" is never stored: no evaluation row = still pending.

- [ ] **Step 1: Write failing tests** (use `db_session`):
  `test_tables_exist_after_upgrade`; `test_second_run_for_same_horizon_and_session_is_refused`
  (IntegrityError); `test_three_horizons_same_session_are_all_kept`;
  `test_decided_record_without_model_is_refused` (IntegrityError from the CHECK);
  `test_evaluation_cannot_be_filed_under_another_horizon` (record horizon 5, evaluation horizon 15 →
  IntegrityError); `test_migration_chain_shape` (load the migration module as
  `tests/test_owner_private_migration.py::test_migration_chain_and_downgrade_shape` does: revision
  `horizonwf01`, `down_revision` = the head found in Step 3; `upgrade()` guards every `create_table` with
  the table-name check, so it is safe to run twice).
- [ ] **Step 2: Run them** — expect FAIL (tables/models missing).
- [ ] **Step 3: Write the ORM models and the migration** (constraint names prefixed `ck_hwf_`, `uq_hwf_`, `fk_hwf_`).
- [ ] **Step 4: Run the new tests and `tests/test_check_migrations_script.py`** — all pass;
  `alembic heads` shows one head (`horizonwf01`).
- [ ] **Step 5: Commit** `feat(db): horizon workflow tables (migration, owner-approved) (#387)`

### Task 3: Inputs — scan predictions to `ModelOutput`s, and the exchange calendar

**Files:**
- Create: `backend/src/swing_trade_ml/horizon_workflows/__init__.py`, `inputs.py`, `calendar.py`
- Test: `backend/tests/test_horizon_workflow_inputs.py`

**Interfaces:**
- Consumes: `brain.horizons.ModelOutput`; `services.model_registry.role_of(model)["role"]`;
  `core.market_session.is_trading_day`, `core.holidays.NSE_HOLIDAYS`.
- Produces:
  - `@dataclass(frozen=True) class ScoredOutput: output: ModelOutput; model_id: int; prediction_id: int;
    instrument_id: int`
  - `load_outputs(db: Session, input_session: date) -> dict[str, list[ScoredOutput]]` — key = symbol.
    One entry per (model, instrument): the latest `Prediction.ts` whose IST date is `input_session`.
    **Correction (Codex #387 round 3, P2):** that rule is not safe. `Prediction` rows also hold intraday
    (for example 15-minute) predictions, and one of those sorts after the daily candle stamped at IST midnight,
    so "latest ts of the day" can pick an intraday score as the session's closing decision. The loader must
    select only the daily scan's score for the session (how the scan marks its rows has to be verified in the
    code before building; do not infer it from the timestamp) and must never fall back to an intraday row.
    `forecast_horizon_sessions = MLModel.prediction_horizon_days`; `score = Prediction.probability`;
    `input_close = Prediction.price_at_prediction`; `role = role_of(model)["role"]`.
  - `exchange_sessions(start: date, count: int) -> list[date] | None` — `start` plus the next `count`
    trading days; None when any needed year is missing from `NSE_HOLIDAYS`.
    **Correction (Codex #387 round 3, P2):** `core.market_session.is_trading_day` is weekday-only
    (`d.weekday() < 5` and not a listed holiday), so it omits a special weekend exchange session. If a Friday
    signal is followed by a Saturday session, the calendar would enter on Monday and count the due session one
    session late. The calendar must come from a source that lists special sessions, or the helper must return
    None for any window it cannot prove is complete; the weekday-only helper alone is not enough.

- [ ] **Step 1: Write failing tests:** `test_latest_prediction_of_the_day_wins` (two predictions, same model,
  same stock, 15:45 and 16:30 IST → one output, the later prediction id; Review Focus 5. **Superseded by the
  round-3 correction above:** add a test where a later intraday prediction exists and the daily scan's score is
  still the one used);
  `test_prediction_ts_is_read_in_ist` (a prediction at 18:45 UTC belongs to the next IST date);
  `test_model_horizon_and_role_are_carried`; `test_other_sessions_are_ignored`;
  `test_calendar_skips_weekends_and_holidays`; `test_calendar_without_next_years_holidays_is_none`
  (monkeypatch `NSE_HOLIDAYS` to drop next year; start 2026-12-28, count 15 → None; Review Focus 3).
- [ ] **Step 2: Run** — FAIL (module missing).
- [ ] **Step 3: Implement `load_outputs` and `exchange_sessions`.**
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `feat(horizons): load scan predictions and exchange sessions (#387)`

### Task 4: Repository — write runs and records, read unfinished records, write evaluations

**Files:**
- Create: `backend/src/swing_trade_ml/horizon_workflows/repository.py`
- Test: `backend/tests/test_horizon_workflow_repository.py`

**Interfaces:**
- Consumes: Task 2 ORM classes; `brain.horizons.HorizonRecord`, `Evaluation`, `NO_DECISION`; Task 3 `ScoredOutput`.
- Produces:
  - `run_exists(db, horizon: int, input_session: date) -> bool`
  - `save_run(db, horizon: int, input_session: date, records: list[tuple[HorizonRecord, ScoredOutput | None]],
    *, status: str, reason: str | None, policy_code: str) -> HorizonRun` — one run row plus one record row
    per tuple; `model_id`/`prediction_id`/`instrument_id` come from the `ScoredOutput` whose
    `output.model_version` and `output.model_name` match the record (None for NO_DECISION).
  - `unfinished_records(db) -> list[HorizonRecordRow]` — decided records with no evaluation row.
  - `to_contract(row: HorizonRecordRow) -> HorizonRecord`
  - `save_evaluation(db, row: HorizonRecordRow, ev: Evaluation) -> bool` — writes only `complete` or
    `unmeasurable`; returns False (writes nothing) for `pending`; never updates an existing row.

- [ ] **Step 1: Write failing tests:** `test_saved_record_round_trips_to_the_contract` (every field of
  `HorizonRecord` equal after `to_contract`); `test_record_keeps_its_copy_when_the_prediction_changes`
  (update `Prediction.probability` after `save_run` → stored `score` unchanged; Review Focus 1);
  `test_pending_is_not_written`; `test_finished_evaluation_is_never_rewritten` (second `save_evaluation`
  for the same record → False, row unchanged); `test_no_decision_records_are_never_unfinished`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `feat(horizons): repository for runs, records and evaluations (#387)`

### Task 5: The daily job, the switch and the scheduler hook

**Files:**
- Create: `backend/src/swing_trade_ml/horizon_workflows/job.py`
- Modify: `backend/src/swing_trade_ml/core/config.py` (add `HORIZON_WORKFLOWS_ENABLED: bool = False` next
  to `LANE_SHADOW_ENABLED`), `backend/src/swing_trade_ml/workers/scheduler.py` (add
  `add_horizon_workflow_job(target) -> bool` beside `add_lane_job`, called after it), `.env.example`
  (name only, value `false`)
- Test: `backend/tests/test_horizon_workflow_job.py`

**Interfaces:**
- Consumes: Tasks 1–4; `brain.horizons.run_horizon`, `evaluate_record`, `DEFAULT_POLICIES`, `HORIZONS`;
  `core.market_session.last_closed_trading_day`.
- Produces:
  - `LOCK_KEY = 7_300_145_003`; `JOB_ID = "horizon_workflows_daily"`;
    `SCHEDULE = {"day_of_week": "mon-fri", "hour": "17,19,21", "minute": 30}` (decision D2)
  - `run_daily(db: Session, now: datetime | None = None) -> dict` — returns
    `{"input_session": str, "horizons": {5: str, 10: str, 15: str}, "evaluated": int}` or
    `{"skipped": "another_run_active"}`.
  - `job_horizon_workflows() -> None` (own `session_scope`, commits, logs, never raises)
  - `register(target) -> bool`

`run_daily` order (the part the tests do not fully determine):
1. `pg_try_advisory_xact_lock(LOCK_KEY)`; if taken → skipped.
2. `input_session = last_closed_trading_day(now)`; `outputs = load_outputs(db, input_session)`;
   **Correction (Codex #387 round 5, P2):** a decision must be saved only while its simulated entry is still in
   the future. The entry is the open of the session after `input_session` (09:15 IST). A Monday 10:00 IST
   retry that picks Friday would save a decision after Monday's open has happened and later evaluate it from
   that open, which is hindsight. The job must refuse (skip, never save) when the entry session has already
   opened, and the test list must include that case.
   **Correction (Codex #387 round 5, P2):** `SCHEDULE` is `mon-fri` and `last_closed_trading_day` is
   weekday-based, so a special Saturday exchange session gets no run and a manual Saturday-evening run selects
   Friday even if the evaluation calendar contains Saturday. The schedule and the input-session selector must
   be driven by the same exchange calendar as the evaluation (including special sessions), or the job must
   refuse when it cannot show the calendar is complete.
   `sessions = exchange_sessions(input_session, 15)`.
   **Correction (Codex #387 round 1, P2):** this calendar is built from the current input session, so it
   omits earlier sessions. Evaluating a stored record needs a calendar that covers *that record's* own input
   session (for example a Monday 5D record evaluated on Tuesday). Build the evaluation calendar to start at
   or before the oldest unfinished record's `input_session`; otherwise such a record cannot be placed on the
   calendar. (Since round 7 the evaluator leaves a record "pending", not "unmeasurable", when the calendar
   stops before a needed session; it still cannot be evaluated until the calendar covers it.)
3. For each horizon in `HORIZONS`, inside its own `db.begin_nested()` savepoint; a horizon that raises is
   logged and reported as `"error: <ExceptionType>"` and does not stop the others:
   - `run_exists` → `"already_recorded"`.
     **Correction (Codex #387 round 7, P2):** this is wrong for a partly filled run. If one stock's score exists
     at 17:30 and another arrives by 19:30, the first slot saves the run and `run_exists` then makes the later
     slot skip the second stock for good. A run is not final after one slot: a later slot must add records for
     the stocks that have no record yet (UNIQUE(`run_id`, `symbol`) already makes that safe) and skip only
     stocks that already have one. Skipping the whole run is allowed only when every expected stock has a record
     (or the last slot of the day has run). The test list must include "score arrives at the second slot".
   - no outputs at all → do **not** save (so a later slot can retry) → `"no_inputs"`.
   - no eligible model for this horizon in any stock (every `run_horizon` result is NO_DECISION for the same
     model-level reason, or no output has this forecast horizon) → `save_run(status="no_decision",
     reason=<the reason>, records=[])` → one run row instead of hundreds of identical rows.
   - otherwise one `run_horizon(...)` per symbol (calendar None → pass the short session list so the
     record says the calendar reason) → `save_run(status="recorded")`.
4. Evaluate: `as_of` = latest session ≤ `input_session` that has a NIFTY 50 `day` candle (Review Focus 4);
   **Correction (Codex #387 round 1, P2):** a NIFTY 50 candle does not prove that each stock's own candle
   exists. Decide readiness per stock: a record is only evaluated up to the sessions for which *that stock*
   has a `day` candle, and a missing stock candle leaves the record pending, never saved as a final
   "unmeasurable" (a terminal result is never retried, so a late stock candle would be ignored);
   for each `unfinished_records(db)` row, load that instrument's `day` candles from its input session to
   `as_of` as `{ist_date: (open, high, low, close)}`, `evaluate_record`, `save_evaluation`.

- [ ] **Step 1: Write failing tests:**
  - `test_acceptance_three_horizons_one_day_all_stored` — seed one stock with predictions from a 5-, a 10-
    and a 15-session model (role `final`) on one session; `run_daily` → three run rows, three records
    with the right model versions and due sessions.
  - `test_acceptance_5d_completes_on_session_5_while_others_pend` — seed flat candles through session 5
    (plus NIFTY candles); `run_daily` with `now` on session 5 → one evaluation row (5D, `time`); 10D/15D
    have none. Repeat with candles through 10 and 15.
  - `test_5d_model_alone_gives_15d_a_no_decision_run`.
  - `test_running_twice_does_not_duplicate` (Review Focus 2).
  - `test_one_horizon_failing_keeps_the_others` (monkeypatch `run_horizon` to raise for 10 only → 5D and
    15D rows committed, result shows `error: RuntimeError` for 10; next `run_daily` records 10).
  - `test_no_predictions_yet_saves_nothing_so_a_later_slot_retries`.
  - `test_late_candles_leave_evaluation_pending` (no NIFTY candle for the due session → no evaluation row;
    Review Focus 4).
  - `test_switch_off_registers_no_job_and_imports_nothing` (scheduler with the default settings: no
    `horizon_workflows_daily` job; `"swing_trade_ml.horizon_workflows" not in sys.modules` after
    `add_horizon_workflow_job`, following `tests/test_lane_job_wiring.py::test_wiring_is_a_noop_when_disabled`).
  - `test_job_never_raises` (`session_scope` patched to raise → logged, no exception).
  - `test_package_imports_no_order_or_broker_code` (AST scan of `horizon_workflows/`: no `brokers`,
    `kiteconnect`, `services.risk`, `services.limits`, `services.engine`, `brain.lanes`).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement `job.py`, the config field, the scheduler hook and the `.env.example` line.**
- [ ] **Step 4: Run the new tests, then `tests/test_trial_freeze*.py`, `tests/test_h05_service.py`,
  `tests/test_lane_job_wiring.py`, `tests/test_brain_horizon_workflows.py`** — all pass.
- [ ] **Step 5: Run the full backend suite** — record the exact summary line; name every failure.
- [ ] **Step 6: Commit** `feat(horizons): switchable daily job for the three horizon workflows (#387)`

### Task 6: Hand-off

- [ ] Update `docs/ai/HANDOFF.md` (branch, base, commits, test lines, open decisions) and post status on
  #387 with the `update-tickets` skill. Stop for Codex review. Turning the switch on in production is a
  separate owner step after merge and deploy.

## Not in this plan (later, each needs its own go-ahead)

- A screen or API to read these results (Admin → Jobs already shows the job's last run via `job_runs`).
- Backfilling past sessions; costs and slippage in the evaluator; feeding these results into the Brain's
  live decisions or the sealed trial.
