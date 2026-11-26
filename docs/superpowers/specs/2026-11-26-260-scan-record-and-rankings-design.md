# #260 Daily scan record and horizon rankings: design (for owner approval)

Date: 2026-11-26 (IST). Status: DESIGN ONLY. No migration file exists, no code was changed, nothing was applied.
Base checked: `origin/main` at `2f0696d7`. Related design: `2026-11-26-316-candle-readiness-design.md`.

## 1. Purpose, in plain English

Today the system can tell you, stock by stock, that a score is missing (an explicit "no decision" row). It cannot tell
you about the scan as a whole: how many stocks were expected, how many were scored, how many had old prices, which were
skipped, and which model versions ran. It also does not store where each stock ranked on a given day, so a later
review cannot say "this stock was 3rd of 40 on that day".

This design adds two small history tables:

- `scan_runs`: one row per scan pass, with the counts and the skipped stocks.
- `horizon_ranks`: one row per stock per day per horizon, with its rank among that day's scored stocks.

Both are append-only (nothing is edited or deleted), and neither changes any existing table. Start with the 5-session
horizon, as #260 says.

Unverified: whether the owner wants the 15:45 signal scan (the #316 record) in `scan_runs` as well as the nightly
horizon passes. See decision D8.

## 2. Alembic position (verified)

- Head on `origin/main` (2f0696d7): `signalkey01`, file `backend/alembic/versions/20261126_1200_signal_key.py:20-21`
  (`down_revision = "simulation02"`). Chain: `horizon01` -> `simulation01` -> `modswitch01` -> `simulation02` ->
  `signalkey01`. I read every `revision` / `down_revision` in that folder: exactly one head, `signalkey01`.
- One new file would hold both changes, named `backend/alembic/versions/20261127_1200_scan_runs_ranks.py`,
  `revision = "scanrank01"`, `down_revision = "signalkey01"` (but see D7: the owner may prefer two revisions).
- Neither table name exists anywhere in `backend/src` or `backend/alembic` today (searched).
- If the head moves before this is built, re-point `down_revision` to the head at that time.

## 3. Tables

Style copied from `20261124_1200_horizon_records.py`: explicit constraint names, BigInteger ids, foreign keys with
`ondelete=RESTRICT`, append-only triggers (update, delete, truncate refused), additive only.

### 3.1 Migration A: `scan_runs`

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| scan_key | VARCHAR(64) NOT NULL | same format as `horizon_records.scan_key` (`h5:<session>`, `services/horizon_nightly.py:166`), so the tables join |
| session_date | DATE NOT NULL | market session whose candles were scored (IST date) |
| horizon_days | SMALLINT NOT NULL | 5, 10 or 15 |
| pass_no | SMALLINT NOT NULL default 1 | the nightly job runs 3 times a day; one row per pass |
| is_final | BOOLEAN NOT NULL default false | true on the last pass of the day |
| universe_count | INTEGER NOT NULL | stocks expected |
| scored_count | INTEGER NOT NULL | stocks scored |
| stale_count | INTEGER NOT NULL default 0 | newest candle older than the session |
| missing_count | INTEGER NOT NULL default 0 | active model did not score the stock |
| skipped_count | INTEGER NOT NULL default 0 | identity refused or unresolved |
| skipped_symbols | TEXT NULL | JSON text, sorted list |
| model_versions | TEXT NULL | JSON text, sorted `"<model_id>:<name>:<version>"` |
| started_at | TIMESTAMPTZ NULL | |
| finished_at | TIMESTAMPTZ NOT NULL default now() | |

Constraints: `ck_scan_runs_horizon` (horizon_days IN (5,10,15)); `ck_scan_runs_pass` (pass_no >= 1);
`ck_scan_runs_counts` (every count >= 0 and scored + stale + missing + skipped <= universe).
Indexes: `ix_scan_runs_session (session_date, horizon_days)`; unique `uq_scan_runs_key (scan_key, horizon_days, pass_no)`.
Triggers: `trg_scan_runs_no_update`, `_no_delete`, `_no_truncate`, using function `scan_runs_append_only`.

The numbers already exist: `DaySummary` (`services/horizon_nightly.py:71-97`) holds predictions, recorded, refused,
unresolved, no_data and skipped, but they only reach a log line (`log.info("horizon5.nightly", ...)` in
`job_horizon_nightly`). The stale versus missing split follows `_no_data_reason` (`horizon_nightly.py:189-192`).

### 3.2 Migration B: `horizon_ranks`

One row per (horizon record, rank revision). It points at `horizon_records` by id, so score, model and version are not
copied.

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| horizon_record_id | BIGINT NOT NULL, FK horizon_records(id) RESTRICT | |
| security_id | BIGINT NOT NULL, FK securities(id) RESTRICT | |
| session_date | DATE NOT NULL | |
| horizon_days | SMALLINT NOT NULL | |
| model_id | INTEGER NULL | plain id, same reason as `horizon_records.model_id` |
| rank_no | INTEGER NOT NULL | 1 = best score |
| cohort_size | INTEGER NOT NULL | how many stocks were ranked |
| rank_revision | INTEGER NOT NULL default 1 | a later pass can change a rank: new revision, old row stays |
| scan_run_id | BIGINT NULL, FK scan_runs(id) RESTRICT | which pass produced it |
| source | VARCHAR(12) NOT NULL default 'live' | 'live' or 'backfill' |
| ranked_at | TIMESTAMPTZ NOT NULL default now() | |

Constraints: `ck_horizon_ranks_horizon`, `ck_horizon_ranks_rank` (1 <= rank_no <= cohort_size),
`ck_horizon_ranks_revision` (>= 1), `ck_horizon_ranks_source`. Indexes: `ix_horizon_ranks_security_id`,
`ix_horizon_ranks_session (session_date, horizon_days, rank_no)`, unique `uq_horizon_ranks_key (horizon_record_id, rank_revision)`.
Triggers as above (function `horizon_ranks_append_only`).

Why a new table and not a column on `horizon_records`: that table refuses every update, so a rank column could only be
written at insert time and could never be corrected. A rank depends on the day's other stocks and can change when a
later pass adds stocks. A separate table also leaves the evidence table untouched. Existing columns it relies on
(`session_date`, `horizon_days`, `model_id`, `score`, `decision`, `revision`, `scan_key`) are in
`db/models/horizon.py:39-74`.

Rank rule (fixed in code, not in SQL): within one (session_date, horizon_days, model_id), over the latest revision of
each record with a score that is not NO_DECISION, `rank_no = RANK() OVER (ORDER BY score DESC)`; ties share a rank.
Records without a score get no row (absent = unranked, never rank 0).

The exact SQL and Alembic text for both tables is in the earlier proposal (scratchpad `260-migrations.md`). Its content
is unchanged by this check, because the revision chain did not move (section 11). It will be restated in the migration
file itself at build time.

## 4. Write path

- Writer: the existing nightly horizon job (`job_horizon_nightly`, `services/horizon_nightly.py`; schedule
  `{"day_of_week": "mon-fri", "hour": "17,19,21", "minute": 30}` at line 50), registered only when
  `HORIZON_NIGHTLY_ENABLED` is true (default false, `ENABLED: bool = False`, line 63; `register` near line 310).
  No new job and no new infrastructure.
- `scan_runs`: one row at the end of each pass, built from the `DaySummary`. The 21:30 IST pass sets `is_final`
  (`_is_final_pass`, near line 290).
- `horizon_ranks`: written on the final pass only (recommended), after that day's records exist.
- Idempotent per session: the unique keys make a repeat insert fail; the writer treats that as "already recorded".
- Safety: both writes run in their own savepoint (`begin_nested`) so a failure to write them can never block the
  evidence write in `horizon_records`.
- A new switch for the writers, default off, separate from `HORIZON_NIGHTLY_ENABLED`.
- Depends on #316 landing first, so that "the session's candles are in" is a known fact before ranks are written.

## 5. Read path

- Admin view: a read-only endpoint and screen listing recent sessions with counts and skipped stocks, and a stock's
  rank history. Owner-only, gated like the other research screens. A session with no `scan_runs` row shows as
  "not recorded", never as zero stocks scanned. A record with no rank row shows as "unranked", never as last.
- Brain: if the Brain ever reads ranks, it goes through `DatedReader` (`brain/reader.py:45`), bounded by the run's
  `as_of`, so a rank written after `as_of` is invisible (no look-ahead). No `DatedReader` method exists for these
  tables yet; adding one belongs to a later build and is not needed for the admin view. Service 1 only stores; the
  Brain decides.

## 6. Retention

Keep everything: the volume is tens of rows a day per horizon. `horizon_records` and `score_ledger` are also kept
forever by design. Unverified: any owner retention preference.

## 7. Rollback

- Before the writers are switched on: `alembic downgrade signalkey01` drops both tables (empty), triggers and
  functions. Nothing is lost.
- After they are on: switch the writers off, export `scan_runs` first (it cannot be rebuilt, because past passes were
  only logged). `horizon_ranks` can be rebuilt from `horizon_records` scores. Then downgrade. The running code must
  not read the dropped tables.
- The downgrade drops `horizon_ranks` first because it references `scan_runs`.
- No existing table is altered, so there is nothing else to undo.

## 8. Test plan (each criterion pass or fail)

The criteria come from #260's body: record coverage, stale data, skipped symbols, score and rank; start with 5D.
The tests are written at build time (none exist now).

| # | Criterion | Pass when |
|---|---|---|
| 1 | Migration up and down | `upgrade` then `downgrade` leaves `alembic current = signalkey01`; both tables, triggers and functions are gone |
| 2 | Append-only | UPDATE, DELETE and TRUNCATE on both tables raise |
| 3 | Counts add up | a pass with known inputs writes the exact universe, scored, stale, missing and skipped counts; the CHECK rejects a sum above universe |
| 4 | Skipped symbols named | refused and unresolved stocks appear in `skipped_symbols` |
| 5 | Rank rule | known scores give the expected `rank_no`; ties share a rank; no-score and NO_DECISION rows get no rank |
| 6 | Idempotent | running the same session twice leaves one set of rows |
| 7 | Evidence never blocked | forcing the rank or scan write to fail still saves the `horizon_records` row |
| 8 | Unknown stays unknown | a session with no scan row reads as "not recorded" |
| 9 | No look-ahead | a `DatedReader` read with `as_of` before `ranked_at` returns nothing |
| 10 | Frozen files untouched | `tests/test_trial_freeze.py` still passes |
| 11 | Writers off by default | with the new switch unset, no row is written |

## 9. Dependencies and gates

1. #316 first (owner approval pending).
2. #353 (no score from a stale or missing candle) and #360 (no duplicate signals on re-run) stay gated until after the
   trial; this design does not touch them. `stale_count` records staleness; it does not fix it.
3. Later items in #260's plan (versioned inputs, out-of-sample comparison, 5D rankings using model evidence) depend on
   #219/#226 and the model-card work (PR #496, #328 slice 1). Not covered here.
4. Frozen files: the earlier proposal searched `backend/tests/trial_freeze.json` for horizon, identity, alembic and
   score_ledger and found no match. I did not repeat that search on `2f0696d7`: unverified, re-run the freeze test at
   build time.

## 10. Owner approvals needed (each separately)

- A1. Migration A: `scan_runs`.
- A2. Migration B: `horizon_ranks`.
- A3. Merge of the migration PR (a merge does not deploy).
- A4. The deploy that runs `alembic upgrade head` (a separate manual run).
- A5. Switching the new writers on.
- A6. Running the rank backfill (after a dry run).

Decisions, recommended answer first:

- D1. New table `horizon_ranks` rather than a column: yes.
- D2. Append-only for both: yes.
- D3. Ties: shared rank (RANK), not strict order.
- D4. Backfill ranks for history, marked `source='backfill'`: yes. Leave past `scan_runs` empty (unknown stays unknown).
- D5. Ranks only on the final pass (21:30 IST): yes.
- D6. Retention: keep everything.
- D7. One migration file holding both tables (one approval, one rollback), or two revisions (`scanrank01` for A,
  `scanrank02` for B) so each can be approved and rolled back alone. Recommended: two revisions, because A1 and A2
  are approved separately.
- D8. Should the 15:45 signal-scan session record from #316 also go into `scan_runs`? Today that record is the file
  `.last_scan.json` (`workers/heartbeat.py:68-80`) and holds only the current session. The schema above is built for the
  nightly horizon passes. Storing the signal scan too needs a `scan_kind` column and a nullable horizon, which changes
  this proposal. Recommended: not now; keep the file and add a table later if scan history is wanted (the same
  recommendation #316 makes).

## 11. Differences from the earlier proposal

- Alembic head: unchanged. The earlier note said `signalkey01`; verified the same on `2f0696d7`.
  `simulation02` (`20261126_1200_simulation_rule_ref.py`) sits just below it in the one chain.
- Scope is now explicit: the earlier `scan_runs` records the nightly horizon passes, not the 15:45 signal scan that
  #316 changes. That is now decision D8 instead of an unstated assumption.
- Deploy-order and backfill detail from the earlier proposal still stand (switch writers on only after the tables are
  verified; backfill is a separate script, never inside the migration).
