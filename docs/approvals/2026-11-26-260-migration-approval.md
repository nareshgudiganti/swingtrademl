# #260 approval request: two new history tables (scan_runs, horizon_ranks)

Date: 2026-11-26 (IST). Status: REQUEST FOR APPROVAL. No migration file exists, nothing was applied anywhere.
Design: `docs/superpowers/specs/2026-11-26-260-scan-record-and-rankings-design.md` (PR #539).
Checked against `origin/main` `897da862`.

## What this is, in plain English

Today a stock with no score gets an explicit "no decision" row, but the scan as a whole leaves no record: how many stocks
were expected, how many scored, how many had old prices, which were skipped, which models ran. Nor do we store where a
stock ranked on a day ("3rd of 40").

Two new tables fix that. Both are add-only (the database refuses edits and deletes, like `horizon_records`). Neither
changes any existing table. Start with the 5-day horizon.

## Verified facts

- Alembic head is `signalkey01` (`backend/alembic/versions/20261126_1200_signal_key.py`), one head. Re-checked on `897da862`.
- `securities.id` and `horizon_records.id` are both BIGINT (checked in the models, the migration, and the local test DB).
- Neither new table name exists anywhere in `backend/src` or `backend/alembic`.
- TimescaleDB: only `candles` is a hypertable (`20260101_0000_initial_schema.py`). `horizon_records`, `score_ledger` and
  `securities` are plain tables. **Neither new table should be a hypertable**: they get tens of rows a day, are
  referenced by foreign keys (hypertables handle those poorly), and need no time partitioning.

## Revisions (recommended: two, so each can be approved and rolled back alone)

| File (not created) | revision | down_revision | creates |
|---|---|---|---|
| `backend/alembic/versions/20261127_1200_scan_runs.py` | `scanrank01` | `signalkey01` | `scan_runs` |
| `backend/alembic/versions/20261127_1210_horizon_ranks.py` | `scanrank02` | `scanrank01` | `horizon_ranks` |

If the head moves before build, `down_revision` is re-pointed to the head at that time.

## Table 1: `scan_runs` (one row per nightly pass)

```sql
-- UPGRADE scanrank01
CREATE TABLE scan_runs (
    id             BIGSERIAL PRIMARY KEY,
    scan_key       VARCHAR(64)  NOT NULL,            -- same format as horizon_records.scan_key, e.g. 'h5:2026-11-26'
    session_date   DATE         NOT NULL,            -- market session scored (IST date)
    horizon_days   SMALLINT     NOT NULL,
    pass_no        SMALLINT     NOT NULL DEFAULT 1,  -- nightly job runs 3 times a day
    is_final       BOOLEAN      NOT NULL DEFAULT false,
    universe_count INTEGER      NOT NULL,            -- stocks expected
    scored_count   INTEGER      NOT NULL,
    stale_count    INTEGER      NOT NULL DEFAULT 0,  -- newest candle older than the session
    missing_count  INTEGER      NOT NULL DEFAULT 0,  -- active model did not score the stock
    skipped_count  INTEGER      NOT NULL DEFAULT 0,  -- identity refused or unresolved
    skipped_symbols TEXT,                            -- JSON text, sorted list
    model_versions  TEXT,                            -- JSON text, sorted "<model_id>:<name>:<version>"
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_scan_runs_horizon CHECK (horizon_days IN (5, 10, 15)),
    CONSTRAINT ck_scan_runs_pass    CHECK (pass_no >= 1),
    CONSTRAINT ck_scan_runs_counts  CHECK (
        universe_count >= 0 AND scored_count >= 0 AND stale_count >= 0
        AND missing_count >= 0 AND skipped_count >= 0
        AND scored_count + stale_count + missing_count + skipped_count <= universe_count)
);
CREATE INDEX ix_scan_runs_session ON scan_runs (session_date, horizon_days);
CREATE UNIQUE INDEX uq_scan_runs_key ON scan_runs (scan_key, horizon_days, pass_no);

CREATE OR REPLACE FUNCTION scan_runs_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_scan_runs_no_update   BEFORE UPDATE   ON scan_runs FOR EACH ROW       EXECUTE FUNCTION scan_runs_append_only();
CREATE TRIGGER trg_scan_runs_no_delete   BEFORE DELETE   ON scan_runs FOR EACH ROW       EXECUTE FUNCTION scan_runs_append_only();
CREATE TRIGGER trg_scan_runs_no_truncate BEFORE TRUNCATE ON scan_runs FOR EACH STATEMENT EXECUTE FUNCTION scan_runs_append_only();

-- DOWNGRADE scanrank01 (to signalkey01)
DROP TRIGGER IF EXISTS trg_scan_runs_no_truncate ON scan_runs;
DROP TRIGGER IF EXISTS trg_scan_runs_no_delete   ON scan_runs;
DROP TRIGGER IF EXISTS trg_scan_runs_no_update   ON scan_runs;
DROP TABLE scan_runs;
DROP FUNCTION IF EXISTS scan_runs_append_only();
```

## Table 2: `horizon_ranks` (one row per stock per day per horizon per rank revision)

It points at `horizon_records` by id, so score, model and version are not copied. A separate table is needed because
`horizon_records` refuses every update, and a rank can change when a later pass adds stocks (new revision, old row stays).

```sql
-- UPGRADE scanrank02
CREATE TABLE horizon_ranks (
    id                BIGSERIAL PRIMARY KEY,
    horizon_record_id BIGINT      NOT NULL REFERENCES horizon_records (id) ON DELETE RESTRICT,
    security_id       BIGINT      NOT NULL REFERENCES securities (id)      ON DELETE RESTRICT,
    session_date      DATE        NOT NULL,
    horizon_days      SMALLINT    NOT NULL,
    model_id          INTEGER,                       -- plain id, same as horizon_records.model_id
    rank_no           INTEGER     NOT NULL,          -- 1 = best score; ties share a rank
    cohort_size       INTEGER     NOT NULL,          -- how many stocks were ranked
    rank_revision     INTEGER     NOT NULL DEFAULT 1,
    scan_run_id       BIGINT      REFERENCES scan_runs (id) ON DELETE RESTRICT,
    source            VARCHAR(12) NOT NULL DEFAULT 'live',
    ranked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_horizon_ranks_horizon  CHECK (horizon_days IN (5, 10, 15)),
    CONSTRAINT ck_horizon_ranks_rank     CHECK (rank_no >= 1 AND rank_no <= cohort_size),
    CONSTRAINT ck_horizon_ranks_revision CHECK (rank_revision >= 1),
    CONSTRAINT ck_horizon_ranks_source   CHECK (source IN ('live', 'backfill'))
);
CREATE INDEX ix_horizon_ranks_security_id ON horizon_ranks (security_id);
CREATE INDEX ix_horizon_ranks_session     ON horizon_ranks (session_date, horizon_days, rank_no);
CREATE UNIQUE INDEX uq_horizon_ranks_key  ON horizon_ranks (horizon_record_id, rank_revision);

CREATE OR REPLACE FUNCTION horizon_ranks_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_horizon_ranks_no_update   BEFORE UPDATE   ON horizon_ranks FOR EACH ROW       EXECUTE FUNCTION horizon_ranks_append_only();
CREATE TRIGGER trg_horizon_ranks_no_delete   BEFORE DELETE   ON horizon_ranks FOR EACH ROW       EXECUTE FUNCTION horizon_ranks_append_only();
CREATE TRIGGER trg_horizon_ranks_no_truncate BEFORE TRUNCATE ON horizon_ranks FOR EACH STATEMENT EXECUTE FUNCTION horizon_ranks_append_only();

-- DOWNGRADE scanrank02 (to scanrank01)
DROP TRIGGER IF EXISTS trg_horizon_ranks_no_truncate ON horizon_ranks;
DROP TRIGGER IF EXISTS trg_horizon_ranks_no_delete   ON horizon_ranks;
DROP TRIGGER IF EXISTS trg_horizon_ranks_no_update   ON horizon_ranks;
DROP TABLE horizon_ranks;
DROP FUNCTION IF EXISTS horizon_ranks_append_only();
```

Rank rule (fixed in code, not SQL): within one (session_date, horizon_days, model_id), over the latest revision of each
record that has a score and is not NO_DECISION, `rank_no = RANK() OVER (ORDER BY score DESC)`. A record with no score gets
no row: absent means "unranked", never rank 0 or last.

## Write path

- Writer: the existing nightly horizon job (`job_horizon_nightly`, Mon-Fri 17:30, 19:30, 21:30 IST), which only runs
  when `HORIZON_NIGHTLY_ENABLED` is true (default false). No new job or infrastructure.
- `scan_runs`: one row at the end of each pass, built from the counts the job already computes (today they only reach a
  log line). The 21:30 pass sets `is_final`. `horizon_ranks`: written on the final pass only.
- Idempotency key per session: `scan_runs` = (`scan_key`, `horizon_days`, `pass_no`); `horizon_ranks` =
  (`horizon_record_id`, `rank_revision`). A repeat insert fails and the writer treats that as "already recorded".
- Both writes run in their own savepoint, so a failure can never block the evidence write to `horizon_records`.
  New writer switch, default off, separate from `HORIZON_NIGHTLY_ENABLED`. Depends on #316 landing first.

## Read path

- Admin-only, read-only endpoint and screen: recent sessions with counts and skipped stocks; a stock's rank history.
  A session with no `scan_runs` row shows "not recorded", never "0 scanned". A record with no rank shows "unranked".
- Brain: if it ever reads ranks, only through `DatedReader`, bounded by `as_of` (a rank written after `as_of` is invisible).
  Not needed for the admin view; a later build. Service 1 stores, the Brain decides.

## Decisions still open (recommendation first)

1. **Approve both tables as written above (A1 + A2)?** Recommend yes. (D1 new table not a column, D2 add-only, D3 ties
   share a rank, D6 keep rows forever are folded in: all recommended yes.)
2. **One migration or two (D7)?** Options: one file, or two revisions. Recommend two (`scanrank01`, `scanrank02`), so each
   table is approved and rolled back alone.
3. **Should the 15:45 signal scan also go in `scan_runs` (D8)?** Options: now (needs a `scan_kind` column and a
   nullable horizon, changes the SQL above) or later. Recommend later; keep `.last_scan.json` for now.
4. **Ranks on the final 21:30 pass only (D5)?** Options: final pass only, or every pass. Recommend final only: fewer
   rows, no mid-day ranks that change.
5. **Rank backfill for history (D4, A6)?** Options: backfill from `horizon_records` scores marked `source='backfill'`
   after a dry run, or never. Recommend yes, later, as a separate script and a separate approval; leave past
   `scan_runs` empty (unknown stays unknown, it cannot be rebuilt honestly).

Later gates, each asked separately when reached: merge of the migration PR (a merge does not deploy), the deploy that
runs `alembic upgrade head`, switching the writers on (A3, A4, A5).

## Explicitly NOT being done now

- No migration file is written and no production (or local main) migration is run.
- No writer is switched on; no new setting is added.
- No backfill, no admin screen, no `DatedReader` method.
- No change to any existing table, to frozen trial files, or to #353 / #360.

## Validation

SQL was run inside a throwaway transaction (BEGIN ... ROLLBACK) on the local TEST database only
(`swing_trade_ml_test`): upgrade 1, upgrade 2, downgrade 2, downgrade 1, in order. Result is in the PR description.
