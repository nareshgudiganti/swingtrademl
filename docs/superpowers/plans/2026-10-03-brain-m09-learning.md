# M09 Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After ideas play out, compare what the brain decided with what happened (+8% before −4% within 15 trading days), report expected vs actual by confidence band and by word, spot feature drift, group stop-outs into patterns, and write proposals the owner accepts or rejects — nothing changes until Accept.

**Architecture:** Pure functions in `backend/src/swing_trade_ml/brain/modules/m09_learn/` (`outcomes.py`, `report.py`, `failures.py`, `drift.py`, `proposals.py`) plus thin DB services (`scoring.py`, `store.py`). Outcome columns on `brain_decisions`; a new `brain_proposals` table. A LEARN-step module `M09` (its mode switches the after-run scoring hook on/off), a weekly `brain_learn` job, `swingtrade brain learn`, API endpoints and a console "Learning" section.

**Tech Stack:** Python 3.12, pandas, numpy, SQLAlchemy 2, Alembic, FastAPI, pytest; React + TanStack Query (TypeScript).

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` (in the main checkout `D:/machine learning/swing-trade-bot/docs/superpowers/specs/`), module sheet "M09 Learning loop". Running notes: `docs/brain/BUILD_NOTES.md`.

## Global Constraints

- Work ONLY in the worktree `D:/machine learning/swing-trade-bot/.claude/worktrees/brain-m00` on branch `brain/m09-learn`. Never push. Never touch `main`.
- Locked trade rule: target +8%, stop −4%, horizon 15 trading days; entry at the decision day's close; a bar touching both barriers counts as the stop (same as `ml.features.build_label`).
- Only decisions from **live nightly** runs (`brain_runs.kind == "nightly"` and `brain_runs.live`) of kind `idea` are scored. Replays, why-runs and intraday runs are never scored.
- Only outcomes fully known by the scoring date count (no look-ahead). A decision whose 15 bars are not complete and that hit neither barrier stays unscored.
- A proposal NEVER changes behaviour until the owner accepts it (spec C9). Accepting a `buy_level` proposal makes the reader use that buy level; accepting a `module_mode` proposal calls `service.set_mode`.
- Plain English in every user-facing string (the owner has no finance background). R = the 4% risked (return ÷ 0.04).
- Tests: run with `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m pytest -q <files>`. DB tests need Docker Postgres on :5433 (already running).
- Lint/format ONLY brain paths and files you create: `"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m ruff format <paths>` and `ruff check <paths>`. NEVER run ruff format on `src/swing_trade_ml` as a whole (it rewrites 50+ unrelated v1 files). Never run prettier on existing frontend files (no repo config); match file style by hand; check with `npx tsc --noEmit -p .` in `frontend/`.
- After adding columns/tables, the test DB keeps old tables: run `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on database `swing_trade_ml_test` (postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_test) for new columns on existing tables; new tables are created automatically by the test setup.
- Commit after each green step with a message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A decision whose outcome is not yet known stays unscored (no look-ahead) — Task 1 `test_unresolved_decisions_stay_unscored`.
2. Several nightly runs on one day must count once per stock per day (latest run wins) — Task 2 `test_one_decision_per_stock_per_day`.
3. A proposal never changes the buy level until accepted, and a rejected one never does — Task 4 `test_buy_level_changes_only_after_accept`.
4. Too few scored ideas → no proposal and a plain "not enough yet" note rather than a noisy suggestion — Task 4 `test_too_few_cases_propose_nothing`.
5. Drift on a shifted synthetic feature is flagged; an unshifted one is not — Task 3 `test_a_shifted_feature_is_flagged`.

---

### Task 1: Outcome columns, proposals table, pure outcome scoring, scoring service

**Files:**
- Create: `backend/alembic/versions/20261003_0900_brain_learning.py` — revision `9f2a6c3e7d10`, down_revision `6e1b4d8a2c73`. Adds to `brain_decisions`: `outcome` String(8) nullable, `outcome_return` Float nullable, `outcome_days` Integer nullable, `max_up` Float nullable, `max_down` Float nullable, `resolved_on` Date nullable. Creates `brain_proposals`: `id` BigInteger PK, `kind` String(24) not null, `title` Text not null, `evidence` Text not null, `change` JSONB not null default `{}`, `status` String(12) not null default `open`, `decided_by` String(128) null, `decided_at` DateTime(tz) null, `decided_note` Text null, `created_at`/`updated_at` DateTime(tz) server_default now(). Index on `status`. Downgrade drops both.
- Modify: `backend/src/swing_trade_ml/db/models/brain.py` — the six columns on `BrainDecision`; new `BrainProposal(Base, TimestampMixin)` mirroring the table.
- Create: `backend/src/swing_trade_ml/brain/modules/m09_learn/__init__.py` (docstring `"""M09 · Learning loop."""`), `outcomes.py`, `scoring.py`.
- Test: `backend/tests/test_brain_m09_learning.py`.

**Interfaces — Produces:**
```python
# outcomes.py (pure)
@dataclass(frozen=True, slots=True)
class Outcome:
    outcome: str        # "target" | "stop" | "timeout"
    ret: float          # +0.08, -0.04, or close on bar 15 / entry - 1
    days: int           # bars until the hit, or 15
    max_up: float       # highest high / entry - 1 over the bars considered
    max_down: float     # lowest low / entry - 1 over the bars considered
    resolved_on: date   # the bar day the outcome became known

def score(entry: float, bars_after: pd.DataFrame, horizon: int = 15,
          target: float = 0.08, stop: float = 0.04) -> Outcome | None:
    """bars_after: columns day, high, low, close — bars strictly after the decision day, ascending.
    Walk bars 1..horizon: stop if low <= entry*(1-stop) (checked first: a same-bar touch of both is a stop),
    else target if high >= entry*(1+target). No hit by bar `horizon` -> timeout with the bar-15 close.
    Fewer than `horizon` bars and no hit -> None (not known yet)."""

# scoring.py (DB)
def score_pending(db: Session, upto: date) -> int:
    """Score every unscored idea decision of a live nightly run whose outcome is known by `upto`
    (IST trading day). decision day = brain_runs.as_of in Asia/Kolkata as a date; entry = the stock's
    last daily close on or before that day (candles, interval 'day', ts read in IST); bars_after =
    daily bars with IST day > decision day and <= upto. Writes the six columns. Returns how many were scored."""
```
IST conversion: daily candles are stamped IST midnight (stored 18:30 UTC the day before) — always convert `ts` with `.astimezone(ZoneInfo("Asia/Kolkata")).date()`.

- [ ] Write tests: target hit (steady +1%/day rise, spread ±1% → target on bar 7), stop first, same-bar both → stop, timeout with bar-15 return, max_up/max_down, `None` when 10 bars and no hit; DB test inserting an instrument + daily candles + one live nightly run with an idea decision, one replay run (`live=False`) and one `why` run with idea decisions → only the nightly one is scored (`test_only_live_nightly_ideas_are_scored`); `test_unresolved_decisions_stay_unscored`.
- [ ] Run → fail. Implement. Run → pass. Apply `ALTER TABLE brain_decisions ADD COLUMN IF NOT EXISTS ...` for the six columns on `swing_trade_ml_test`. Commit.

### Task 2: Expected vs actual, by word and week; failure patterns

**Files:** Create `m09_learn/report.py`, `m09_learn/failures.py`; extend `backend/tests/test_brain_m09_learning.py`.

**Interfaces — Consumes:** Task 1 columns. **Produces:**
```python
# report.py (pure). rows: DataFrame with columns
#   run_started (datetime), decision_day (date), symbol, word, confidence (float|None), outcome, ret
BANDS = ((0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01))
def one_per_day(rows) -> DataFrame   # keep the latest run_started per (symbol, decision_day)
def by_band(rows) -> list[dict]      # per band with n>0: {"band": "50-60%", "n", "said": mean confidence,
                                     #   "hit": share outcome=="target", "avg_r": mean(ret)/0.04}; rows without confidence skipped
def by_word(rows) -> list[dict]      # per word present, order TRADE, WATCH, WAIT, AVOID: {"word","n","hit","avg_r"}
def by_week(rows) -> list[dict]      # per ISO week of decision_day, ascending: {"week": "2026-W40","n","hit","avg_r"}
# failures.py (pure). rows also carry "market" (market situation label or None) and "sector" (str or None)
def failure_patterns(rows, min_stops: int = 3, lift: float = 1.5) -> list[str]
    # among outcome=="stop": for each value of "market" then "sector", if stop count >= min_stops and its share of
    # stops >= lift x its share of all rows -> plain line, e.g.
    # "5 of 9 stop-outs came when the market was in a correction (correction was 30% of all ideas)."
    # sector line: "4 of 9 stop-outs were Banks stocks (Banks were 15% of all ideas)."  Most striking first.
```
The functions call `one_per_day` themselves (`test_one_decision_per_stock_per_day`). Plain names for sector buckets: `swing_trade_ml.brain.modules.m11_sector.ranking.plain_name(swing_trade_ml.ml.sector_map._SECTOR_INDEX[bucket])`.

- [ ] Tests (synthetic DataFrames): bands and their numbers; words in fixed order; weeks ascending; one-per-day; a failure pattern found when one market label is over-represented; none when stops are spread evenly; none below `min_stops`. Fail → implement → pass → commit.

### Task 3: Feature drift

**Files:** Create `m09_learn/drift.py`; extend tests.

**Produces:**
```python
def psi(reference: np.ndarray, recent: np.ndarray, bins: int = 10) -> float | None
    # population stability index; bin edges = reference quantiles (unique); eps 1e-4 in each share;
    # None if either side has fewer than 50 non-NaN values
KEY_FEATURES = ("rsi_14", "sma_50_ratio", "sma_200_ratio", "high_52w_dist", "relative_strength_20d",
                "vix_percentile_rank", "breadth_pct_above_sma50", "nifty_trend_regime")
def feature_drift(reference: pd.DataFrame, recent: pd.DataFrame, features=KEY_FEATURES) -> list[dict]
    # {"feature", "psi", "level"}; level "stable" (<0.1), "moderate" (<0.25), "major"; features missing on
    # either side skipped; sorted by psi descending
def drift_lines(drift: list[dict]) -> list[str]
    # plain lines for moderate/major only, e.g.
    # "high_52w_dist has shifted a lot from what the model learnt on (stability index 0.41)."
```
Service (same file, DB): `drift_report(db, model_name: str = "swing_classifier", recent_days: int = 20) -> list[dict]` — reference = `build_features(...)` rows for watch-listed instruments over the active model's `train_start..train_end` (use `swing_trade_ml.ml.dataset.load_candles`, `swing_trade_ml.ml.features.build_features` with the market-context loaders exactly as `brain/modules/m06_reason/dataset.py::build_dataset` does; at most 20,000 rows, sampled with a fixed seed); recent = `feature_snapshots` rows whose `bar_date` is within the last `recent_days` distinct bar dates (read the model to find the column holding the features; it is a JSON mapping or list of pairs). Returns `[]` when there is no active model or no snapshots.

- [ ] Tests: `psi` ≈ 0 for two samples of the same normal; > 0.25 for a mean shift of 1 SD (`test_a_shifted_feature_is_flagged`); `None` under 50 values; `feature_drift` levels and ordering; `drift_lines` wording. (No DB test for `drift_report`; it is exercised in the real check.) Fail → implement → pass → commit.

### Task 4: Proposals — generate, store, accept/reject; accepted buy level used by the reader

**Files:** Create `m09_learn/proposals.py` (pure), `m09_learn/store.py` (DB); modify `backend/src/swing_trade_ml/brain/reader.py` (`model_probability`); extend tests.

**Produces:**
```python
# proposals.py (pure)
@dataclass(frozen=True, slots=True)
class Draft:
    kind: str            # "buy_level"
    title: str
    evidence: str
    change: dict         # {"buy_level": 0.65}
def buy_level_proposal(rows: pd.DataFrame, current: float,
                       candidates=(0.55, 0.6, 0.65, 0.7, 0.75), min_cases: int = 20,
                       min_gain_r: float = 0.05) -> Draft | None
    # rows: one_per_day rows with confidence and ret. For each candidate t != current with >= min_cases rows at
    # confidence >= t: avg_r(t) = mean(ret)/0.04. Pick the best; propose only if avg_r(best) >= avg_r(current) + min_gain_r
    # and current itself has >= min_cases rows. Title: "Raise the buy level to 65%" / "Lower the buy level to 55%".
    # Evidence: "Among 48 past ideas scored 65% or more, the average result was +0.12 R per trade, against -0.03 R
    # for 120 ideas at the current 60%. It would have skipped 30 of 52 losing ideas and 6 of 14 winning ones."
    # (losing = outcome "stop", winning = outcome "target", counted among rows >= current but < best for a raise,
    #  or the extra rows gained for a lower). Returns None otherwise.
# store.py (DB)
def create(db, draft: Draft) -> BrainProposal | None   # None if an OPEN proposal with the same kind and change exists
def list_proposals(db, status: str | None = None) -> list[BrainProposal]   # newest first
def accept(db, proposal_id: int, by: str, note: str = "") -> BrainProposal   # status accepted + applies it:
    # kind "module_mode": service.set_mode(db, change["module"], change["mode"], by=by, note=...)
    # kind "buy_level": nothing else — the reader reads it (below)
def reject(db, proposal_id: int, by: str, note: str = "") -> BrainProposal
    # both raise ValueError if the proposal is not open
def accepted_buy_level(db) -> float | None   # change["buy_level"] of the most recently ACCEPTED buy_level proposal
```
Reader: in `DatedReader.model_probability`, return `accepted_buy_level(self.db)` when not None instead of `settings.ML_MIN_CONFIDENCE` (look it up once per reader; cache on the instance).

- [ ] Tests: raise and lower proposals with exact wording on synthetic rows; `test_too_few_cases_propose_nothing`; no proposal when the gain is below `min_gain_r`; `create` de-duplicates open ones; `test_buy_level_changes_only_after_accept` (create → `accepted_buy_level` is None → reject another → still None → accept → returns the value); accepting twice raises; a `module_mode` proposal accepted calls set_mode (check `service.load_modes`). Fail → implement → pass → commit.

### Task 5: The module, the after-run hook, the weekly job, the CLI and the API

**Files:**
- Create `m09_learn/module.py`: `@register_module class Learning(BrainModule)` — `Manifest(id="M09", name="Learning loop", step=Step.LEARN, kind="step", version="1.0.0", reads=(), writes=(), budget_s=5.0, default_mode=Mode.ON)`; `run` returns `c.Contribution()` (learning happens after the run and weekly, never inside a decision run). Register in `backend/src/swing_trade_ml/brain/modules/__init__.py`.
- Modify `backend/src/swing_trade_ml/brain/service.py::_sync_episodes`: add job `("M09", (Mode.ON,), <m09 scoring module>, "score_pending_from_reader")` — add `def score_pending_from_reader(db, reader) -> int` in `scoring.py` that calls `score_pending(db, reader.as_of.astimezone(IST).date())`.
- Create `m09_learn/learn.py`: `def learning_report(db, since: date | None = None) -> dict` → `{"since", "n_scored", "by_band", "by_word", "by_week", "failures", "drift", "drift_lines", "note"}` reading scored rows (join runs for `run_started`=`BrainRun.started_at`, decision_day from `as_of`; market label from `BrainRun.context["situations"]` market entry; sector from `get_sector_bucket(symbol)`); `note` = "Only N ideas have finished so far — too few to judge; keep collecting." when fewer than 30 scored. `def run_learning(db, since=None) -> dict` = `score_pending(today)` + report + `create(buy_level_proposal(rows, current))` where current = `accepted_buy_level(db) or settings.ML_MIN_CONFIDENCE`; returns the report plus `"new_proposals"`.
- Job: `backend/src/swing_trade_ml/workers/jobs.py` add `job_brain_learn()` (session_scope → `run_learning`, errors via `_report_error`, like `_run_brain_job`); `backend/src/swing_trade_ml/workers/scheduler.py::add_brain_jobs` add `CronTrigger(day_of_week="sat", hour=10, minute=0, timezone=IST)` id `brain_learn`.
- CLI `backend/src/swing_trade_ml/cli.py`: `swingtrade brain learn [--since YYYY-MM-DD]` prints n scored, the band table, the word table, failure lines, drift lines, new proposals (follow the existing `brain` subcommands' style).
- API `backend/src/swing_trade_ml/api/v1/endpoints/brain.py` (all behind the existing brain gate): `GET /brain/learning?since=` → `learning_report`; `GET /brain/proposals?status=` → list of `{id, kind, title, evidence, change, status, created_at, decided_by, decided_at, decided_note}`; `POST /brain/proposals/{id}/accept` and `/reject` with body `{"note": str = ""}`, `by` = the owner identity the overrule endpoint uses; 409 when not open; 404 when missing.
- Update the module-list expectation in `backend/tests/test_brain_api.py` to include `M09` (sorted ids).

- [ ] Tests: M09 is the LEARN step module and starts ON; the after-run hook scores only on live nightly runs (monkeypatch `scoring.score_pending_from_reader`, as `test_only_live_nightly_runs_rebuild_the_memory` does in `tests/test_brain_m05_memory.py`); API: learning report shape on an empty DB with the "too few" note; proposals list/accept/reject incl. 409 and 404. Fail → implement → pass → full brain suite `tests/test_brain*.py` passes → commit.

### Task 6: Console "Learning" section

**Files:** Modify `frontend/src/api/types.ts`, `frontend/src/api/client.ts` (`brainLearning(since?)`, `brainProposals()`, `brainProposalDecide(id, 'accept'|'reject', note)`), `frontend/src/pages/Brain.tsx`.

A card "Learning from results" placed after "Market history": the `note` when present; a table "Expected vs actual" (band · ideas · it said · it happened · average result in R); a table by word; failure lines and drift lines as plain bullet lists; "Proposals" list: title, evidence, status; for `open` ones an optional note input and Accept / Reject buttons (mutations invalidate the proposals and learning queries). Plain wording: column heads "The brain said", "What happened". Match the existing file's style (single quotes, no semicolons, 2-space indent); `npx tsc --noEmit -p .` must pass.

- [ ] Implement, type-check, commit.

### Task 7: Real check, notes, memory (controller)

Upgrade the check DB (`brain_m00_check`), run `swingtrade brain learn`, verify the report and a proposal on real stored runs, full suite + lint, update `docs/brain/BUILD_NOTES.md` and memory, restart :8001.
