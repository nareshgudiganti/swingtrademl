# Brain Observatory Phase 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status: plan revision 2, for build approval. Not approved to build or deploy.** Deployment is a separate approval (spec P-1).

**Goal:** an owner-only, read-only Brain Observatory: pick a date, a run and a stock, and see what the brain
**already stored** about it. Health, recording and effectiveness are shown separately. Anything the
records cannot show is labelled honestly.

**Architecture:**
- One new backend package, `services/brain_observatory/`, of pure helpers and bounded read queries.
- One new GET-only router at `/api/v1/brain/observatory`. It runs every request in its **own
  Postgres `READ ONLY` transaction** with a statement timeout.
- One new TradeMind page.
- No change to `brain/`, strategies, execution, workers, the database schema or settings.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy 2 (psycopg 3), Postgres 17 + TimescaleDB, pytest; React +
TypeScript + React Query (Vite).

**Spec:** `docs/superpowers/specs/2026-10-15-brain-observatory-design.md` (rev 4, addendum 12 = rev 4a,
addendum 13 = four questions and one source of truth). This plan adds rev 4b requirements R1–R9, listed
below; the spec gets a pointer to them as section 14 in Task 0. The evidence plan
(`docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md`, tasks A2/A3) is met for 1A by Task 7.

## Global Constraints

- **Paper only.** Never set `TRADING_MODE=live` or `ALLOW_LIVE_TRADING=true`.
- **Must not touch:** `backend/src/swing_trade_ml/brain/`, `strategies/`, `workers/`, `db/`, `alembic/`,
  `infra/`, the existing `services/*` files, `.env*`, or
  `docs/superpowers/specs/2026-10-12-walk-forward-protocol.md` (the frozen protocol).
- No migration, no scheduled job, no new setting, no Phase 1B or Phase 2 instrumentation.
- **Allowed edits outside the new package:**
  - `api/v1/router.py` (one include line)
  - `frontend/src/api/client.ts`, `frontend/src/api/types.ts`
  - `frontend/src/trademind/TradeMindApp.tsx`
  - `.github/workflows/test.yml` (checkout `fetch-depth: 0`; **scope addition, needs the owner's OK**,
    see R6)
- **Endpoints:** owner-only (`require_owner`), GET only. Every request uses its own session whose first
  statement is `SET TRANSACTION READ ONLY`, then `SET LOCAL statement_timeout = '5s'`.
- **Limits:**
  - date range at most 92 days → 422 otherwise
  - list pages at most 500 rows, with typed cursors
  - at most 12 SQL statements per request, except `/outcomes` (at most 12 own statements plus the trial
    journal's, at most 20 in total)
- **Status words (exact text):**
  - "Not observed"
  - "Before recording began"
  - "Not recorded in Phase 1A"
  - "Not recorded — decision-path recording deferred during trial"
  - "Switched off"
  - "Not applicable"
  - "Unknown"
  - "Conflicting records"
  - "Not due yet"
- **Recording card text (exact):** "Existing records only — partial visibility."
- **Verdict words (exact), in precedence order:**
  1. "Verdict record invalid"
  2. "No frozen protocol yet"
  3. "Insufficient evidence"
  4. "Not proven"
  5. "Passed, not proven: independence not established"
  6. "Proven"
- **Day of a run** = `as_of.astimezone(IST).date()` (`IST = ZoneInfo("Asia/Kolkata")`).
- **Running backend tests:**

  ```
  cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE ./.venv/Scripts/python.exe -m pytest <path> -q
  ```

  Docker Postgres must be up first (`docker compose up -d postgres`; DB tests hang silently otherwise).
- Format only the files you touched: `ruff format <file>` (never the whole package). Frontend check:
  `cd frontend && npx tsc --noEmit -p .`. No prettier on existing files.
- **Git:** work on branch `feature/brain-observatory-1a` off `develop`. Never bare `git stash`. Commits
  end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do **not** push or merge without the
  owner.

## Rev 4b requirements (owner review, 2026-10-15) and where each is closed

| # | Requirement | Task / tests |
|---|---|---|
| R1 | Independent module-health **flags** and per-flag **counts**. A module may carry several flags (executed + valid + used); counts are per flag, not "one state per module" | Task 3: `test_flags_are_independent`, `test_counts_are_per_flag` |
| R2 | **Missing corroboration ≠ conflict.** Only one source present → `single_source`; neither → `no_record`; two sources that disagree → `conflicting`; identical repeated lines → `duplicate` (not conflict) | Task 3: four corroboration tests |
| R3 | Recording card reads exactly "Existing records only — partial visibility." and lists what is not recorded | Task 8 (`recording` block) + Task 10 page + `test_run_detail_recording_card` |
| R4 | Outcomes, costs, benchmarks: each figure carries its verified **source** and **assumptions**; missing data is shown as `available: false` with a reason, never as zero | Task 7: `SOURCES`, unavailable-state tests |
| R5 | **Numerical verdict** and **independence status** kept separate, with a fixed precedence. Covers unaudited results and an uncommitted audit | Task 5: precedence table tests |
| R6 | Effectiveness integrity checks run **in CI** against git objects (tags and blobs), not trust | Task 6 + test.yml `fetch-depth: 0` |
| R7 | Missing-run checks use **trading holidays and the scheduled deadline**: before the deadline → "Not due yet"; holiday or weekend → "Not applicable" | Task 4 |
| R8 | **Database-enforced** read-only transaction plus **isolated write-attempt tests**. Postgres counters are supplementary only | Task 1: write refused in session; write refused through a route; counters as an extra check |
| R9 | **Redaction preserves typed identifiers and pagination cursors**: only named free-text keys are redacted | Task 2: `test_ids_and_cursors_are_never_altered` |

Deferred decisions and how 1A stays honest without them:

| Decision | How 1A behaves |
|---|---|
| Audit location | The registry records `independence = "audit_uncommitted"`. The page says so; "Proven" is impossible for that entry. When the owner commits the audit, the registry entry changes by commit and CI re-checks it (Task 6) |
| Policy document | Not needed by any 1A code path. The page's "trial" wording cites no policy file |

## Review Focus

The five inputs most likely to bite a real user that the spec does not spell out. Each has a test in its
owning task.

1. **Old runs stored before the `context` column existed, or with `modules = {}`**. Expected: the page
   loads, shows "Not observed" or `single_source`, and never errors. *Test:* Task 3
   `test_empty_modules_and_trace_do_not_crash`; Task 8 `test_old_run_without_context`.
2. **A date with no runs at all (holiday, or a future date)**. Expected: day shows "Not applicable" or
   "Not due yet", empty lists, 200 OK. *Test:* Task 8 `test_day_with_no_runs`.
3. **The same symbol on two exchanges in the current instrument master**. Expected: both are listed as
   "current instrument", with no silent pick. *Test:* Task 8 `test_symbol_on_two_exchanges`.
4. **A run still `running` or `queued`, or `failed` with an error message holding a connection string**.
   Expected: headline shows the run's own status; the error is shown redacted. *Test:* Task 8
   `test_failed_run_error_is_redacted`.
5. **Trial journal raising, for example no candles locally**. Expected: `/outcomes` still returns stored
   M09 grades; the journal-derived figures read `available: false` with the redacted reason. *Test:*
   Task 7 `test_journal_failure_is_honest`.

---

## Plan revision 2: corrections (owner review, 2026-10-15). Binding

These corrections **replace** the task code they name. Where a task step and a correction disagree, the
correction wins. Each affected task starts with a "Plan rev 2" note pointing here.

### Scope additions that need explicit approval

Both are inside this build request, but neither is a read-only view of stored records, so each is named
separately:

| # | Addition | Why it is needed | What it touches |
|---|---|---|---|
| S1 | **View-time outcome calculations** (spec addendum 13): net-after-costs, every stock, momentum, NIFTY and the forward gate, computed when the page asks, from stored prices, using existing pure scoring code | the owner's four questions ("what happened", "compared with what") cannot be answered from stored records alone; only M09's gross grade is stored | new code in `services/brain_observatory/` only; calls existing pure functions (`build_journal`, `gate`, `summarise`, `momentum_scores`, `outcomes_for`, `blocked_by_risk`); no writes |
| S2 | **CI checkout `fetch-depth: 0`** in `.github/workflows/test.yml` | the verdict integrity checks read git tags and blobs | one CI line; no app code |

If either is refused: without S1, the Results tab shows stored M09 grades only, and every computed figure
reads "Not available in this build". Without S2, Task 6's tests fail in CI by design, so the verdict
registry cannot be deployed. Drop Task 6, and `/effectiveness` then shows "Verdict record invalid" for
every claim (Task 5 gets a `REGISTRY_VERIFIED_IN_CI = False` switch).

### Verified invariants these corrections rely on (checked 2026-10-15)

| Invariant | Where |
|---|---|
| Every stored run's `modules` lists **all modules installed when it ran** (with the mode used); failed runs store `{}` | `brain/service.py` `_store`: `used_modes = {… for cls in registry.all()}`; the failure path does not set `modules` |
| A queued run has status `queued` and is not started; `started_at` is reset when it really starts | `brain/queue.py:105`, `:186` |
| `live = False` means a replay | `brain/contracts.py:79` |
| The trial cohort: live, `status = done`, nightly, `book == TRADING_MODE`, one run per IST day (the latest by `started_at`), from `TRIAL_START = 2026-10-14` | `brain/trial_journal.py` `load_sessions`, `TRIAL_START` |
| M18 stage with no recorded change = `shadow` (practice), fail-closed | `services/brain_golive/stage.py:98` |
| Tracker rows carry `book`; orders and signals carry `mode` | `BrainTrack.book`; `Order.mode`, `Signal.mode` |
| Momentum looks back 20 trading bars | `walk_forward.MOMENTUM_BARS = 20` |

### C1. Claims bound by code; frozen minimums from code; audits checked against committed blobs

**Replaces:** Task 5 `_entry_problems`, `evaluate` and its tests; adds to Task 6.

A registry entry can only feed the claims that **this code** binds to its protocol. A claim name written in
the JSON is checked, never trusted. Minimums come from code, not JSON.

In `verdicts.py`, add after `CLAIMS`:

```python
# Frozen protocols known to this code. Only these can produce a verdict, only for the claims listed, and
# only with these minimums. Changing a claim name or a minimum in the JSON makes the record invalid; it can
# never move a model-ranking result onto the full-brain claim.
FROZEN_PROTOCOLS = {
    "wf-protocol-v1": {
        "tag": "wf-protocol-v1",
        "parts": {"predictive": "model_ranking_predictive", "economic": "model_ranking_economic"},
        "minimums": {"eligible_folds": 12, "finished_ideas": 100, "share": 0.6},
    },
}
```

Replace `_entry_problems` and `evaluate` with:

```python
def _entry_problems(entry: dict, frozen: dict) -> list[str]:
    problems = []
    if entry.get("tag") != frozen["tag"]:
        problems.append("tag differs from the frozen protocol's tag")
    if entry.get("minimums") != frozen["minimums"]:
        problems.append("minimums differ from the frozen protocol's")
    if set(entry.get("parts", {})) != set(frozen["parts"]):
        problems.append("parts differ from the frozen protocol's")
    for name, part in entry.get("parts", {}).items():
        if frozen["parts"].get(name) != part.get("claim"):
            problems.append(f"part '{name}' is bound to a claim the protocol does not test")
    sample = entry.get("sample", {})
    if sample.get("kind") != "confirmation":
        problems.append("sample is not the protocol's confirmation sample")
    if sample.get("independence") in ("untouched", "exposure_disclosed") and not (
        sample.get("audit_path") and sample.get("audit_sha256")
    ):
        problems.append("independence is claimed without a committed audit (path and hash)")
    return problems


def evaluate(registry: dict) -> list[dict]:
    found: dict[str, dict] = {}
    rejected: list[dict] = []
    for entry in registry.get("entries", []):
        frozen = FROZEN_PROTOCOLS.get(entry.get("protocol_id"))
        if frozen is None:
            rejected.append({"protocol_id": entry.get("protocol_id"), "why": "not a frozen protocol known to this code"})
            continue
        problems = _entry_problems(entry, frozen)
        independence = entry.get("sample", {}).get("independence")
        for name, claim in frozen["parts"].items():  # the claim comes from code, never from the JSON
            part = entry.get("parts", {}).get(name)
            if problems or part is None:
                numeric, why = "invalid", problems or [f"part '{name}' is missing"]
            else:
                numeric, why = numeric_verdict(part, frozen["minimums"])
            found[claim] = {
                "word": display_word(numeric, independence),
                "numeric": numeric,
                "independence": independence,
                "independence_note": entry.get("sample", {}).get("independence_note", ""),
                "protocol_id": entry["protocol_id"],
                "tested_subject": entry.get("tested_subject"),
                "numbers": None if part is None else {
                    k: part.get(k) for k in ("eligible_folds", "folds_won", "share", "finished_ideas", "extra_check", "extra_check_value")
                },
                "problems": why,
            }
    out = []
    for claim, label in CLAIMS:
        item = found.get(claim) or {
            "word": NO_PROTOCOL, "numeric": None, "independence": None, "independence_note": "",
            "protocol_id": None, "tested_subject": None, "numbers": None, "problems": [],
        }
        out.append({"claim": claim, "label": label, **item})
    return out


def rejected_entries(registry: dict) -> list[dict]:
    return [
        {"protocol_id": e.get("protocol_id"), "why": "not a frozen protocol known to this code"}
        for e in registry.get("entries", [])
        if e.get("protocol_id") not in FROZEN_PROTOCOLS
    ]
```

`/effectiveness` returns `{"claims": evaluate(reg), "rejected_entries": rejected_entries(reg)}`.

Registry JSON: add `"audit_sha256": null` to `sample`.

**Tests**, added to `test_brain_observatory_verdicts.py`:

```python
def test_renaming_a_claim_cannot_create_full_brain_proof():
    reg = copy.deepcopy(v.load_registry())
    e = reg["entries"][0]
    e["sample"].update(independence="untouched", audit_path="docs/x.md", audit_sha256="0" * 64)
    e["parts"]["predictive"].update(claim="full_brain", recorded_word="pass", folds_won=14, share=14 / 21, extra_check_value=0.001)
    out = {c["claim"]: c for c in v.evaluate(reg)}
    assert out["full_brain"]["word"] == v.NO_PROTOCOL
    assert out["model_ranking_predictive"]["word"] == v.INVALID


def test_minimums_come_from_code_not_json():
    reg = copy.deepcopy(v.load_registry())
    reg["entries"][0]["minimums"] = {"eligible_folds": 1, "finished_ideas": 1, "share": 0.1}
    out = {c["claim"]: c for c in v.evaluate(reg)}
    assert out["model_ranking_predictive"]["word"] == v.INVALID


def test_an_unknown_protocol_binds_nothing():
    reg = copy.deepcopy(v.load_registry())
    reg["entries"][0]["protocol_id"] = "my-own-protocol"
    out = {c["claim"]: c for c in v.evaluate(reg)}
    assert all(c["word"] == v.NO_PROTOCOL for c in out.values())
    assert v.rejected_entries(reg)[0]["protocol_id"] == "my-own-protocol"
```

In `test_a_passing_entry_shows_proven_only_for_its_own_claim` and `test_untouched_requires_an_audit_path`,
set `audit_sha256` alongside `audit_path` where the test means "a committed audit".

**Task 6 additions** (CI, against git objects):

```python
def test_e0_frozen_minimums_match_the_protocol_text():
    for pid, frozen in v.FROZEN_PROTOCOLS.items():
        entry = next(e for e in ENTRIES if e["protocol_id"] == pid)
        text = git("show", f"{frozen['tag']}:{entry['protocol_file']}").decode()
        m = frozen["minimums"]
        assert f"at least {m['eligible_folds']} eligible folds and {m['finished_ideas']} finished model ideas" in text
        assert f"at least {round(m['share'] * 100)}% of eligible folds" in text


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e4b_audit_is_the_committed_blob(entry):
    s = entry["sample"]
    if s.get("audit_path"):
        assert sha("HEAD", s["audit_path"]) == s["audit_sha256"], "audit differs from the committed blob"
```

Today `audit_path` is null (`audit_uncommitted`), so `e4b` checks nothing and says so via the parametrized
id. When the owner commits the audit, the registry gains its path and hash in the same commit, and CI
verifies it.

### C2. Official forward gate from the established trial cohort, independent of the page range

**Replaces:** Task 7 `forward_trial` use inside `build`; adds a route in Task 8 and a card in Task 10.

The forward gate is computed only over the established cohort: `trial_journal.TRIAL_START` to today
(IST), live, `book == TRADING_MODE`. It never depends on the page's `from` / `to`.

In `outcomes.py`, add:

```python
def official_forward_gate(db, today: date) -> dict:
    """The forward gate (layer-2 draft 5a) over the established trial cohort only: TRIAL_START to today,
    the same cohort definition as brain/trial_journal.journal_for. Never uses the page's date range."""
    from swing_trade_ml.brain.trial_journal import TRIAL_START

    journal, _momentum, error = _journal(db, TRIAL_START, today, live=True, book=settings.TRADING_MODE, stage_filter=None)
    out = forward_trial(journal, error)
    out.update(cohort_from=TRIAL_START.isoformat(), cohort_to=today.isoformat(),
               cohort="live nightly brain runs, book = TRADING_MODE, from TRIAL_START (brain/trial_journal.py)")
    if journal is not None:
        out["gate"] = journal["gate"]
    return out
```

`build()` no longer returns `forward_trial`. The route `GET /forward-gate` (owner, read-only) returns
`official_forward_gate(db, get_now().date())`.

**Test** (in `test_brain_observatory_outcomes.py`, using `db_session` and the realistic fixture from C7):

```python
def test_forward_gate_ignores_the_page_range(db_session, realistic_cohort):
    today = realistic_cohort.today
    a = o.official_forward_gate(db_session, today)
    b = o.official_forward_gate(db_session, today)  # the route takes no range at all
    assert a == b and a["cohort_from"] == "2026-10-14"


def test_forward_gate_equals_the_trial_journal(db_session, realistic_cohort):
    from swing_trade_ml.brain.trial_journal import TRIAL_START, journal_for

    official = journal_for(db_session, TRIAL_START, realistic_cohort.today)["gate"]
    assert o.official_forward_gate(db_session, realistic_cohort.today)["gate"] == official
```

### C3. Correct cursor comparison; nightly status from the whole day

**Replaces:** Task 8 `queries.runs_on`, the `/runs` route's `nightly`.

```python
from sqlalchemy import literal, tuple_


def runs_on(db: Session, day: date, after: tuple[datetime, str] | None, limit: int) -> list[BrainRun]:
    lo, hi = day_window(day)
    q = select(BrainRun).where(BrainRun.as_of >= lo, BrainRun.as_of < hi)
    if after is not None:
        q = q.where(tuple_(BrainRun.started_at, BrainRun.id) > tuple_(literal(after[0]), literal(after[1])))
    return list(db.scalars(q.order_by(BrainRun.started_at, BrainRun.id).limit(limit + 1)))


def nightly_runs_on(db: Session, day: date) -> list[dict]:
    """Every nightly run of the day (brief columns), so the day's nightly status never depends on a page."""
    lo, hi = day_window(day)
    rows = db.execute(select(BrainRun.id, BrainRun.kind, BrainRun.live, BrainRun.status)
                      .where(BrainRun.kind == "nightly", BrainRun.as_of >= lo, BrainRun.as_of < hi)).all()
    return [{"id": r.id, "kind": r.kind, "live": r.live, "status": r.status} for r in rows]
```

In `/runs`, set `"nightly": schedule.nightly_state(day, now, queries.nightly_runs_on(db, day))`.

**Tests:**

```python
def test_cursor_pages_runs_with_equal_start_times(client, obs_ns, now_after_deadline):
    same = AS_OF
    rows = [make_run(f"p{i}", as_of=same, kind="intraday", started_at=same) for i in range(3)]
    with committed(*rows):
        seen, cursor = [], None
        for _ in range(4):
            q = f"{BASE}/runs?date=2026-10-15&limit=1" + (
                f"&after_started_at={cursor['after_started_at']}&after_id={cursor['after_id']}" if cursor else "")
            body = client.get(q, headers=OWNER).json()
            seen += [i["id"] for i in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
    assert len(seen) == 3 and len(set(seen)) == 3


def test_nightly_state_is_for_the_whole_day_not_the_page(client, obs_ns, now_after_deadline):
    early = make_run("i0", as_of=AS_OF, kind="intraday", started_at=AS_OF - timedelta(hours=6))
    nightly = make_run("n9", as_of=AS_OF, started_at=AS_OF)
    with committed(early, nightly):
        body = client.get(f"{BASE}/runs?date=2026-10-15&limit=1", headers=OWNER).json()
    assert [i["kind"] for i in body["items"]] == ["intraday"]
    assert body["nightly"]["state"] == "observed"
```

### C4. Historical runs: no missing modules that did not exist yet; queued runs are not executed

**Replaces:** Task 3 `module_rows` flag logic, `outside_rows` M00 and M16, and the affected tests.

Rules, based on the verified invariant that a stored run's `modules` is its installed list:

| Case | Result |
|---|---|
| `modules` non-empty, module absent, no trace line | **"Not installed when this run happened"** (`not_installed_then`). Never "Not observed" |
| `modules` empty (failed or very old run), no trace line | **Unknown** ("this run stored no module list"). Never "Not observed" |
| "Not observed" | only when the run lists the module (mode on or shadow), its step is in the run kind, and there is no trace line |

In `module_rows`, replace the flag block with:

```python
        installed_known = bool(modules)
        not_installed = installed_known and mid not in modules and not lines
        list_unknown = not installed_known and not lines
        flags = {
            "expected": bool(applicable) and installed_known and mid in modules and not off,
            "executed": bool(seen & EXECUTED),
            "valid_output": bool(seen & VALID),
            "used": "used" in seen,
            "shadow": "shadow" in seen,
            "switched_off": off,
            "failed": bool(seen & FAILED),
            "not_observed": bool(applicable) and installed_known and mid in modules and not lines and not off,
            "not_applicable": applicable is False,
            "not_installed_then": not_installed,
            "unknown": list_unknown,
            "unknown_module": mid not in step_map,
            "duplicate": len(lines) > 1 and len(seen) == 1,
            "conflicting": bool(conflicts),
        }
```

Then make these changes:
- Set `corroboration = "not_installed"` when `not_installed`.
- Add `"not_installed_then"` and `"unknown"` to `FLAGS`, and `"not_installed"` to `CORROBORATION`.
- Leave `headline` unchanged; `unknown` is counted, never merged into OK.

Replace the M00 and M16 lines in `outside_rows`:

```python
M00_STATES = {
    "queued": ("not_started", "queued; not started yet"),
    "running": ("in_progress", "running now"),
    "failed": ("executed_failed", "started and failed; see the error"),
    "done": ("executed", "finished"),
    "superseded": ("executed", "finished; replaced by a later run of the same day"),
}
...
    state, detail = M00_STATES.get(status, ("unknown", f"unrecognised run status '{status}'"))
    m00 = {"module_id": "M00", "state": state, "detail": detail}
    if status not in ("done", "superseded"):
        m16 = {"state": "not_applicable", "detail": "alerts are checked only after a finished run"}
    elif live and kind in ALERTING_KINDS:
        m16 = (
            {"state": "executed", "detail": f"alert check recorded; {alerts_sent} alerts sent"}
            if alerts_checked_at is not None
            else {"state": "unknown", "detail": "Not observed or send failed: no alert check was recorded"}
        )
    else:
        m16 = {"state": "not_applicable", "detail": "alerts run only after live nightly and intraday runs"}
    return [
        m00,
        {"module_id": "M16", **m16},
        {"module_id": "M17", "state": "not_applicable", "detail": "the console is a screen, not a step of a run"},
        {"module_id": "M18", "state": "not_applicable",
         "detail": "go-live is not part of a single run; the day's stage is shown as day context"},
    ]
```

**Tests** (replace `test_no_record_is_not_a_conflict_and_is_inferred`; add the others):

```python
def test_listed_module_without_a_line_is_not_observed():
    rows = health.module_rows("nightly", {"M08": "on"}, [], STEP_MAP)
    r = row(rows, "M08")
    assert r["flags"]["not_observed"] and r["inferred"]["not_observed"]


def test_module_added_after_the_run_is_not_missing():
    rows = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used")], STEP_MAP)
    r = row(rows, "M08")
    assert r["flags"]["not_installed_then"] and not r["flags"]["not_observed"] and not r["flags"]["expected"]


def test_run_without_a_module_list_is_unknown_not_missing():
    rows = health.module_rows("nightly", {}, [], STEP_MAP)
    r = row(rows, "M08")
    assert r["flags"]["unknown"] and not r["flags"]["not_observed"] and r["corroboration"] == "no_record"


@pytest.mark.parametrize(("status", "state"), [("queued", "not_started"), ("running", "in_progress"),
                                               ("failed", "executed_failed"), ("done", "executed")])
def test_m00_follows_the_run_status(status, state):
    rows = {r["module_id"]: r for r in health.outside_rows("nightly", True, status, None, 0)}
    assert rows["M00"]["state"] == state
    if status in ("queued", "running", "failed"):
        assert rows["M16"]["state"] == "not_applicable"
```

### C5. Promised views implemented, not reduced

**Replaces / extends:** Task 10 page; Task 8 routes (add `/forward-gate`; `/runs/{id}/stocks` paging is
already there).

No scope reduction. The page adds the following:

1. **Daily counts:** the selected day plus the 13 trading days before it, from `/days`:
   - universe size, idea and holding decisions, TRADE/WATCH/WAIT/AVOID
   - tracked holdings by book
   - signals and paper orders by mode
   - nightly state and intraday due/recorded

   One table, one row per day.
2. **Learning view:** `/learning` for the selected month. It shows results collected, changes proposed by
   status, learning checks, and the "proven improvement" word. The line "Only M09 activity counts as
   learning" is shown.
3. **Pagination:** stocks use `useInfiniteQuery` with `next_cursor.after_id` and a "Load more" button; runs
   use `next_cursor` the same way. Nothing is silently capped.
4. **Module failure messages:** the module table shows `failure_messages` (already redacted) under each
   failed module, plus `conflicts` and the new `not_installed_then` / `unknown` states.
5. **Explicit request-error states:** every query shows one of these, never a blank card:
   - Loading
   - an error with the server's message and status (`ApiError.status`): 403 → "Owner only", 404 → "Not
     found", 422 → the message, otherwise "Could not load: …"
   - Empty ("No runs on this day")

Helper used by every card:

```tsx
import { ApiError } from '../../api/client'

function QueryState({ q, empty }: { q: { isLoading: boolean; isError: boolean; error: unknown }; empty?: string }) {
  if (q.isLoading) return <p className="tm-muted">Loading…</p>
  if (q.isError) {
    const e = q.error
    const status = e instanceof ApiError ? e.status : undefined
    const label = status === 403 ? 'Owner only' : status === 404 ? 'Not found' : 'Could not load'
    return <p className="tm-bad" role="alert">{label}{status ? ` (${status})` : ''}: {e instanceof Error ? e.message : String(e)}</p>
  }
  return empty ? <p className="tm-muted">{empty}</p> : null
}
```

(`ApiError` is exported from `frontend/src/api/client.ts`; if it is not, export it there. That is the
only change to that file beyond the new calls.)

Paged stocks:

```tsx
const stocks = useInfiniteQuery({
  queryKey: ['obs-stocks', chosenRun, symbol],
  queryFn: ({ pageParam }) => api.obsStocks(chosenRun, symbol || undefined, pageParam),
  initialPageParam: undefined as number | undefined,
  getNextPageParam: (last) => last.next_cursor?.after_id,
  enabled: !!chosenRun,
})
const stockItems = stocks.data?.pages.flatMap((p) => p.items) ?? []
// …
{stocks.hasNextPage && <button type="button" onClick={() => stocks.fetchNextPage()}>Load more</button>}
```

New client calls (`client.ts`):

```ts
  obsDays: (from: string, to: string) => get<ObsDays>(`/brain/observatory/days?from=${from}&to=${to}`),
  obsLearning: (from: string, to: string) => get<ObsLearning>(`/brain/observatory/learning?from=${from}&to=${to}`),
  obsForwardGate: () => get<ObsForwardGate>('/brain/observatory/forward-gate'),
  obsRunsPage: (date: string, afterStartedAt?: string, afterId?: string) =>
    get<ObsRuns>(`/brain/observatory/runs?date=${date}` +
      (afterStartedAt && afterId ? `&after_started_at=${encodeURIComponent(afterStartedAt)}&after_id=${encodeURIComponent(afterId)}` : '')),
```

Types, appended to `types.ts`:

```ts
export interface ObsByKey { [key: string]: number }
export interface ObsDay {
  day: string; nightly: ObsNightly
  counts: { idea: ObsByKey; holding: ObsByKey; ideas_total: number; holdings_total: number } | null
  universe: number | null
  intraday: Record<string, number | boolean>
  tracked: { by_book: ObsByKey; label: string }
  signals: { by_mode: ObsByKey; label: string }
  paper_orders: { by_mode: ObsByKey; label: string }
  other_runs: { id: string; kind: string; live: boolean; status: string }[]
}
export interface ObsDays { days: ObsDay[]; redacted_fields: string[] }
export interface ObsLearning {
  results_collected: number; changes_proposed: ObsByKey; learning_checks: number
  proven_improvement: ObsClaim; note: string; redacted_fields: string[]
}
export interface ObsForwardGate {
  word: string; why: string; cohort_from: string; cohort_to: string; cohort: string
  gate?: { sessions: number; finished: number; word: string }
}
```

**Browser checks** are in the acceptance list below (B1–B9).

### C6. Book and category kept separate; categories only from verified invariants

**Replaces:** Task 8 `track_rows`, `tracked_by_day`, `brain_signals_by_day`, `brain_orders_by_day`,
`stored_grade_rows`; Task 7 `build` and `_journal`.

- **Tracker records:**
  - per stock: `track_rows(db, symbol, day, book)` filters `BrainTrack.book == run.book`
  - per day: `tracked_by_day` returns `{day: {book: n}}`

  Books are never summed.
- **Signals and orders:** grouped by `(day, mode)` and returned as `by_mode`, never summed across modes.
  Label: "not linked to a specific run".
- **Outcome categories:** the only rules, each from a verified invariant:

  | Category | Rule |
  |---|---|
  | `practice` | nightly, `status = done`, `live = true`, `book = "paper"`, **and** the M18 stage at the end of that IST day is `shadow`. Stage comes from `brain_stage_changes` (latest change at or before the day's end), or `shadow` when none, as `current_stage` fails closed |
  | `backtest` | nightly, `status = done`, `live = false` (replay), `book = "paper"` |
  | `paper` | v1 paper trades; not brain decisions, so in 1A it returns `available: false` and is never mixed in |

  Anything else is **excluded and counted** in the response, never moved into a category:

  ```
  "excluded": {"other_stage_days": n, "other_book_runs": m}
  ```

  The live book and approval or auto stage days fall here.

Queries:

```python
def stage_history(db: Session) -> list[tuple[datetime, str]]:
    return [(r.changed_at, r.stage) for r in db.execute(
        select(BrainStageChange.changed_at, BrainStageChange.stage).order_by(BrainStageChange.changed_at))]


def stored_grade_rows(db: Session, start: date, end: date, live: bool) -> list[tuple[str, float | None, datetime, str]]:
    lo, _ = day_window(start)
    _, hi = day_window(end)
    return list(db.execute(select(BrainDecision.outcome, BrainDecision.outcome_return, BrainRun.as_of, BrainRun.book)
                           .join(BrainRun, BrainRun.id == BrainDecision.run_id)
                           .where(BrainDecision.kind == "idea", BrainDecision.outcome.is_not(None),
                                  BrainRun.kind == "nightly", BrainRun.live.is_(live), BrainRun.status == "done",
                                  BrainRun.as_of >= lo, BrainRun.as_of < hi)).all())


def nightly_sessions(db: Session, start: date, end: date, *, live: bool, book: str):
    """The trial journal's session rule (latest done nightly run per IST day) in two statements, not one
    per day. A test proves it equals trial_journal.load_sessions on the same data."""
    from swing_trade_ml.brain.trial_journal import Idea, Session as JSession
    from swing_trade_ml.strategies.brain import blocked_by_risk

    lo, _ = day_window(start)
    _, hi = day_window(end)
    runs = db.execute(select(BrainRun.id, BrainRun.as_of, BrainRun.banner_mode)
                      .where(BrainRun.kind == "nightly", BrainRun.live.is_(live), BrainRun.status == "done",
                             BrainRun.book == book, BrainRun.as_of >= lo, BrainRun.as_of < hi)
                      .order_by(BrainRun.started_at.asc())).all()
    latest = {}
    for r in runs:
        latest[run_day(r.as_of)] = r
    ids = [r.id for r in latest.values()]
    by_run: dict[str, list] = {i: [] for i in ids}
    if ids:
        for d in db.scalars(select(BrainDecision).where(BrainDecision.run_id.in_(ids), BrainDecision.kind == "idea")
                            .order_by(BrainDecision.id)):
            by_run[d.run_id].append(Idea(d.symbol, d.overruled_word or d.word,
                                         d.confidence if d.score_source else None, blocked=blocked_by_risk(d)))
    return [JSession(day, latest[day].banner_mode, tuple(by_run[latest[day].id])) for day in sorted(latest)]


def daily_bars(db: Session, symbols: list[str], lo: date, hi: date) -> dict:
    """Daily bars from lo to hi (IST days) for the given symbols, one statement, same shape as
    replay_score.load_bars. Bounded on both sides, unlike load_bars."""
    import pandas as pd

    from swing_trade_ml.db.models.market import Candle

    if not symbols:
        return {}
    lo_ts, _ = day_window(lo)
    _, hi_ts = day_window(hi)
    rows = db.execute(select(Instrument.tradingsymbol, Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close)
                      .join(Instrument, Instrument.id == Candle.instrument_id)
                      .where(Instrument.tradingsymbol.in_(symbols), Candle.interval == "day",
                             Candle.ts >= lo_ts, Candle.ts < hi_ts)
                      .order_by(Instrument.tradingsymbol, Candle.ts)).all()
    grouped: dict[str, list[dict]] = {}
    for sym, ts, o, h, low, c in rows:
        grouped.setdefault(sym, []).append({"day": run_day(ts), "open": float(o), "high": float(h),
                                            "low": float(low), "close": float(c)})
    return {s: pd.DataFrame(r, columns=["day", "open", "high", "low", "close"]) for s, r in grouped.items()}
```

`run_day` is imported from `schedule`. Check `replay_score._BAR_COLUMNS` and use the same column list.

`outcomes._journal` becomes:

```python
def _journal(db, start: date, end: date, *, live: bool, book: str, stage_filter: str | None):
    from swing_trade_ml.brain.trial_journal import build_journal, gate
    from swing_trade_ml.brain.walk_forward import MOMENTUM_BARS

    try:
        sessions = queries.nightly_sessions(db, start, end, live=live, book=book)
        excluded_days = 0
        if stage_filter is not None:
            history = queries.stage_history(db)
            kept = [s for s in sessions if stage_on_day(history, s.day) == stage_filter]
            excluded_days, sessions = len(sessions) - len(kept), kept
        symbols = sorted({i.symbol for s in sessions for i in s.ideas})
        lo = start - timedelta(days=MOMENTUM_BARS * 2 + 10)  # at least 20 trading bars before the first day
        hi = end + timedelta(days=60)  # ideas from the last session need about 15 more sessions
        bars = queries.daily_bars(db, symbols, lo, hi)
        index = settings.BENCHMARK_INDEX_SYMBOL
        journal = build_journal(sessions, bars, {}, index_bars=queries.daily_bars(db, [index], lo, hi).get(index))
        journal["gate"] = gate(journal)
        journal["excluded_other_stage_days"] = excluded_days
        return journal, momentum_summary(sessions, bars), None
    except Exception as exc:  # noqa: BLE001 — shown to the owner as 'not available', never hidden
        return None, None, f"{type(exc).__name__}: {exc}"


def stage_on_day(history: list[tuple], day: date) -> str:
    from swing_trade_ml.services.brain_observatory.schedule import day_window

    _, end = day_window(day)
    stage = "shadow"  # no recorded change = practice, as services/brain_golive/stage.current_stage fails closed
    for changed_at, s in history:
        if changed_at < end:
            stage = s
    return stage
```

In `build`:
- `practice` calls `_journal(..., live=True, book="paper", stage_filter="shadow")`.
- `backtest` calls `_journal(..., live=False, book="paper", stage_filter=None)`.
- Stored grades are filtered the same way in Python: same `book` and, for practice, the same stage rule.
  Count `excluded`.

**Tests:**

```python
def test_sessions_loader_equals_the_trial_journal(db_session, realistic_cohort):
    from swing_trade_ml.brain.trial_journal import load_sessions

    start, end = realistic_cohort.start, realistic_cohort.today
    assert o.queries.nightly_sessions(db_session, start, end, live=True, book="paper") == load_sessions(db_session, start, end, live=True)


def test_bounded_bars_give_the_same_journal(db_session, realistic_cohort):
    from swing_trade_ml.brain.trial_journal import journal_for

    start, end = realistic_cohort.start, realistic_cohort.today
    mine, _, err = o._journal(db_session, start, end, live=True, book="paper", stage_filter=None)
    assert err is None
    assert mine["summaries"]["brain_trade"] == journal_for(db_session, start, end)["summaries"]["brain_trade"]


def test_live_book_and_approval_days_are_excluded_not_mixed(db_session, realistic_cohort):
    realistic_cohort.add_live_book_run(db_session)
    realistic_cohort.add_stage_change(db_session, "approval", realistic_cohort.days[5])
    out = o.build(db_session, realistic_cohort.start, realistic_cohort.today, "practice")
    assert out["excluded"]["other_stage_days"] > 0 and out["excluded"]["other_book_runs"] == 1


def test_tracker_rows_follow_the_run_book(client, obs_ns):
    sym = f"{SYM_PREFIX}H"
    run = make_run("t1", as_of=AS_OF, modules={"M15": "on"})
    holding = make_decision("t1", sym, kind="holding", word="HOLD")
    paper_row = BrainTrack(book="paper", symbol=sym, opened_on=date(2026, 10, 1), day=THU, day_n=10, ret=0.02,
                           status="on_track", reason="", stop=None, band=[])
    live_row = BrainTrack(book="live", symbol=sym, opened_on=date(2026, 10, 1), day=THU, day_n=10, ret=-0.03,
                          status="watch", reason="", stop=None, band=[])
    with committed(run, holding, paper_row, live_row):
        did = client.get(f"{BASE}/runs/{RUN_PREFIX}t1/stocks", headers=OWNER).json()["items"][0]["id"]
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}t1/stocks/{did}", headers=OWNER).json()
        days = client.get(f"{BASE}/days?from=2026-10-15&to=2026-10-15", headers=OWNER).json()["days"][0]
    assert [r["ret"] for r in body["tracker"]["rows"]] == [0.02]
    assert body["tracker"]["book"] == "paper"
    assert days["tracked"]["by_book"] == {"paper": 1, "live": 1}
```

`stock_detail` returns `"tracker": {"book": r.book, "label": …, "rows": …}` using
`queries.track_rows(db, d.symbol, run_day, r.book)`. `make_run` gains a `book: str = "paper"` parameter.
Add `BrainTrack` and `SYM_PREFIX` to the test's imports.

### C7. No silent truncation; realistic bounds tested

**Replaces:** Task 8 `runs_between` (remove `.limit(...)`, select brief columns only) and the `/days`
aggregation.

- `runs_between` returns every run in the range (at most 92 days, about 30 runs a day), with columns
  `id, kind, live, status, as_of, started_at`. No `LIMIT`.
- Every per-day number is a `GROUP BY` result. No list in any response is cut without a `next_cursor`.

**Realistic-size fixture** `realistic_cohort` (in `observatory_fixtures.py`; uses `db_session`, rolled
back). Sized like prod or larger:
- 92 IST days
- per trading day: 1 nightly run (49 ideas, 3 holdings) and 28 intraday runs
- 49 symbols plus NIFTY 50, each with 260 daily candles

It exposes `.start`, `.today`, `.days` and helpers `add_live_book_run`, `add_stage_change`.

Fixture code, added to `observatory_fixtures.py`:

```python
from dataclasses import dataclass, field
from datetime import UTC, date, time, timedelta
from zoneinfo import ZoneInfo

from swing_trade_ml.core.market_session import is_trading_day
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.market import Candle

IST = ZoneInfo("Asia/Kolkata")
N_SYMBOLS, N_HOLDINGS, N_INTRADAY = 49, 3, 28


def trading_days(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def nightly_as_of(day: date) -> datetime:
    return datetime.combine(day, time(15, 50), tzinfo=IST).astimezone(UTC)


@dataclass
class Cohort:
    start: date
    today: date
    days: list[date]
    symbols: list[str] = field(default_factory=list)

    def add_live_book_run(self, db) -> None:
        db.add(make_run("livebook", as_of=nightly_as_of(self.days[3]), book="live"))
        db.flush()

    def add_stage_change(self, db, stage: str, day: date) -> None:
        db.add(BrainStageChange(stage=stage, previous_stage="shadow", changed_by="owner", reason="test",
                                changed_at=datetime.combine(day, time(9, 0), tzinfo=IST)))
        db.flush()


def count_statements(session):
    class Counter:
        n = 0

    def bump(*_a, **_k):
        Counter.n += 1

    event.listen(session.connection(), "before_cursor_execute", bump)
    return Counter


@pytest.fixture()
def realistic_cohort(db_session) -> Cohort:
    """Prod-sized or larger, in the rolled-back db_session: 92 IST days from TRIAL_START, one nightly
    run per trading day with 49 ideas and 3 holdings, 49 symbols plus NIFTY 50 with about 260 daily
    candles each (from 130 days before the start to 60 days after the end)."""
    from swing_trade_ml.brain.trial_journal import TRIAL_START
    from swing_trade_ml.core.config import settings

    start, today = TRIAL_START, TRIAL_START + timedelta(days=91)
    days = trading_days(start, today)
    symbols = [f"{SYM_PREFIX}{i:02d}" for i in range(N_SYMBOLS)]
    for n, sym in enumerate([*symbols, settings.BENCHMARK_INDEX_SYMBOL]):
        inst = Instrument(instrument_token=TOKEN_BASE + n, tradingsymbol=sym, exchange="NSE")
        db_session.add(inst)
        db_session.flush()
        price = 100.0 + n
        for i, d in enumerate(trading_days(start - timedelta(days=130), today + timedelta(days=60))):
            price *= 1 + ((n % 7) - 3) / 1000 + (0.01 if i % 11 == 0 else 0)
            db_session.add(Candle(instrument_id=inst.id, interval="day",
                                  ts=datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC),
                                  open=price, high=price * 1.02, low=price * 0.98, close=price, volume=100_000))
    for k, d in enumerate(days):
        run = make_run(f"rc{k}", as_of=nightly_as_of(d))
        db_session.add(run)
        db_session.flush()
        for j, sym in enumerate(symbols):
            db_session.add(make_decision(f"rc{k}", sym, word="TRADE" if j == k % N_SYMBOLS else "WAIT",
                                         confidence=0.5 + j / 200, score_source="model"))
        for sym in symbols[:N_HOLDINGS]:
            db_session.add(make_decision(f"rc{k}", sym, kind="holding", word="HOLD"))
    db_session.flush()
    return Cohort(start=start, today=today, days=days, symbols=symbols)


@dataclass
class CommittedRuns:
    start: date
    end: date
    intraday_total: int
    ideas_total: int


@pytest.fixture()
def committed_realistic_runs(obs_ns) -> CommittedRuns:
    """Runs and decisions only (no candles), committed in this session's namespace, for /days: 92 days,
    one nightly with 49 ideas and 28 intraday runs per trading day."""
    from swing_trade_ml.brain.trial_journal import TRIAL_START

    start, end = TRIAL_START, TRIAL_START + timedelta(days=91)
    rows, ideas, intraday = [], 0, 0
    for k, d in enumerate(trading_days(start, end)):
        rows.append(make_run(f"cn{k}", as_of=nightly_as_of(d)))
        rows += [make_decision(f"cn{k}", f"{SYM_PREFIX}{j:02d}", word="WAIT") for j in range(N_SYMBOLS)]
        ideas += N_SYMBOLS
        for s in range(N_INTRADAY):
            at = datetime.combine(d, time(9, 0), tzinfo=IST) + timedelta(minutes=15 * s)
            rows.append(make_run(f"ci{k}-{s}", as_of=at.astimezone(UTC), kind="intraday"))
            intraday += 1
    with committed(*rows):
        yield CommittedRuns(start=start, end=end, intraday_total=intraday, ideas_total=ideas)
```

(`event` comes from `sqlalchemy`; `make_run` gains `book: str = "paper"`. If committing about 7,000 rows one
flush at a time is slow, use `s.add_all` with one flush per run; the content stays the same.)

**Tests:**

```python
def test_days_over_92_days_counts_everything(client, obs_ns, now_after_deadline, committed_realistic_runs):
    body = client.get(f"{BASE}/days?from={committed_realistic_runs.start}&to={committed_realistic_runs.end}", headers=OWNER).json()
    assert sum(d["intraday"]["recorded"] for d in body["days"]) == committed_realistic_runs.intraday_total
    assert sum((d["counts"] or {}).get("ideas_total", 0) for d in body["days"]) == committed_realistic_runs.ideas_total


def test_outcomes_processing_is_bounded(db_session, realistic_cohort):
    import time as _t

    counter = count_statements(db_session)
    t0 = _t.perf_counter()
    o.build(db_session, realistic_cohort.start, realistic_cohort.today, "practice")
    o.official_forward_gate(db_session, realistic_cohort.today)
    assert counter.n <= 12, counter.n
    assert _t.perf_counter() - t0 < 4.0  # under the 5 s per-statement timeout with room
```

`committed_realistic_runs` commits only `brain_runs` and `brain_decisions` (no candles) in the test
namespace (C8), because `/days` reads through the read-only session. `count_statements` is a helper in
`observatory_fixtures.py` that attaches a `before_cursor_execute` listener to the session's connection.

### C8. Committed fixtures only in a verified test database, in a per-run namespace

**Replaces:** Task 1 `observatory_fixtures.py` constants, `committed`, `cleanup`, and the `obs_clean`
fixture (renamed `obs_ns`).

```python
import uuid

from sqlalchemy import text

_RUN_TAG = uuid.uuid4().hex[:8]
RUN_PREFIX = f"obs-{_RUN_TAG}-"            # unique per test session; cleanup touches only this prefix
SYM_PREFIX = f"OX{_RUN_TAG[:6].upper()}"   # distinct symbols per session
TOKEN_BASE = 9_000_000_000 + int(_RUN_TAG[:6], 16)  # distinct instrument tokens per session


def assert_dedicated_test_database() -> None:
    """Refuse to commit anything unless this is the dedicated local or CI test database."""
    url = engine.url
    if url.database != "swing_trade_ml_test" or url.host not in ("localhost", "127.0.0.1"):
        pytest.fail(f"refusing to commit fixture rows to database '{url.database}' on '{url.host}'")
    with engine.connect() as c:
        if c.execute(text("SELECT current_database()")).scalar() != "swing_trade_ml_test":
            pytest.fail("connected database is not swing_trade_ml_test")


@pytest.fixture()
def obs_ns():
    assert_dedicated_test_database()
    cleanup()
    yield
    cleanup()
```

`committed()` calls `assert_dedicated_test_database()` first. `cleanup()` keeps the same deletes, using
`RUN_PREFIX` / `SYM_PREFIX` (now per session), plus
`delete(Instrument).where(Instrument.instrument_token >= TOKEN_BASE, Instrument.instrument_token < TOKEN_BASE + 1000)`.
Tests build symbols as `f"{SYM_PREFIX}A"` and tokens as `TOKEN_BASE + n`.

**Test:**

```python
def test_fixture_refuses_a_non_test_database(monkeypatch):
    from sqlalchemy.engine import make_url

    import observatory_fixtures as fx

    monkeypatch.setattr(fx.engine, "url", make_url("postgresql+psycopg://u:p@db.example.com/swing_trade_ml"))
    with pytest.raises(pytest.fail.Exception):
        fx.assert_dedicated_test_database()
```

### C9. Two shipping facts found by the evidence-plan session (verified 2026-10-15)

**C9a. A JSON registry would not ship.** The prod image installs the backend as a wheel, which only
carries the data files listed in `backend/pyproject.toml` `[tool.setuptools.package-data]` (today:
`category_rules.csv` and `score_evidence_barrier.json`).

Fix without touching `pyproject.toml`: the registry becomes a Python module,
`services/brain_observatory/validation_verdicts.py`, which defines `REGISTRY: dict` with the same content
as the Task 5 JSON (plus `audit_sha256: None`). `verdicts.load_registry()` returns `copy.deepcopy(REGISTRY)`.
Tests that loaded the JSON use `load_registry()` unchanged.

Add a test that the deployed artifact really carries the registry:
`importlib.resources.files("swing_trade_ml.services.brain_observatory").joinpath("validation_verdicts.py").is_file()`,
plus `from swing_trade_ml.services.brain_observatory.validation_verdicts import REGISTRY` in a test that
builds the wheel (`python -m build --wheel` in a temp dir) and lists its contents. If building a wheel in CI
is too slow, check with `zipfile` on the wheel built by `pip install .` in a temp venv. Choose one; both
are read-only.

**C9b. The frozen tags exist only locally.**
- `git ls-remote --tags origin` shows neither `wf-protocol-v1` nor `evidence-defs-v1`.
- The frozen commits themselves (`7b97291`, `e160276`) **are** on `origin/develop` and `origin/main`.

So in CI:
- E1's blob check uses `git show <tag_commit>:<path>` (works today with `fetch-depth: 0`).
- The **tag → commit** check (`git rev-parse <tag>^{commit} == tag_commit`) runs only when the tag
  exists. Under `CI=true` a missing tag is reported as an **explicit failure**:
  "frozen tag not on origin: owner to push", never a silent skip.

Pushing tags is an outward action, so it is **the owner's call**:

```bash
git push origin wf-protocol-v1 evidence-defs-v1
```

Until then, CI is red on that one check by design.

### C10. Coordination with branch `feature/evidence-phase-a` (another session, not pushed)

That branch (commits `d9974ee`, `3686a1c`) already adds files with the same names as this plan:
- `services/brain_observatory/{__init__,verdicts}.py`, a read-only session, `endpoints/brain_observatory.py`
  (all marked interim and superseded by this plan)
- `baselines.py`, `defs.py`, `evidence.py`, `pack.py`
- the `test.yml` fetch-tags change

It also tags `evidence-defs-v1` on `d9974ee`, which **locks evidence-plan section 3a**. So the A4 baselines
are no longer "later".

Recommendation (owner decides who builds, and the merge order):
1. This plan stays the master for A2. Build it **on top of `feature/evidence-phase-a`**: branch from its
   tip, not from `develop`, then replace that branch's interim `verdicts.py`, endpoint and read-only
   session with Tasks 1, 5 and 8.
2. Task 7 calls `baselines.trade_level` (evidence-defs-v1: matched every stock, Random 5, momentum, NIFTY
   per idea with costs, cash) instead of the trial-journal approximations. Labels then say
   "evidence-defs-v1". C6's category rules still apply, and C2's forward gate is unchanged.
3. S2 is already on that branch; this plan does not add it twice.
4. If the owner prefers to build A2 independently from `develop`, the plan as written works, but the two
   branches will conflict on those files and one set must be dropped at merge.

Task 0 Step 1 changes to `git switch -c feature/brain-observatory-1a feature/evidence-phase-a` if
option 1 is chosen.

### Updated acceptance checks

These replace Task 11 Steps 4–5 and add to the matrix. Each row says what closes it.

**Backend (CI and local)**

| ID | Check | Closes |
|---|---|---|
| A1 | All Task 1–9 tests, including C1–C8 tests, pass locally (Docker Postgres up) and in CI | all |
| A2 | Verdict CI tests E0–E4b pass in CI with `fetch-depth: 0`; each fails when its registry value is altered (Task 6 Step 3, now also for a claim rename and a minimum change) | C1 |
| A3 | **Before/after baseline:** on `develop` (a `git worktree add ../obs-baseline develop`, never a stash) and on the branch, run `tests/test_brain_golden_day.py tests/test_brain_service.py tests/test_brain_runner.py tests/test_brain_m08_engine.py tests/test_brain_m18_strategy.py tests/test_brain_trial_journal.py tests/test_brain_trial_journal_api.py`. Both runs pass with the same test ids, and the golden-day fingerprint is identical. In a scratch script, also dump the golden day's stored decisions (symbol, kind, word, qty, entry_low, entry_high, target, stop, reasons) on both commits and `diff` them: no differences | spec T1A-2 |
| A4 | Scope guard: `git diff --name-only develop...HEAD` lists only the section 10 files, plus S1's package code and S2's workflow line if approved | T1A-1 |
| A5 | Real local nightly run: API values equal SQL (words, decision count, module flags vs raw trace, one stock's fields, tracker rows by book) | T1A-3 |

**Browser** (browser-automation skill, local, owner signed in; each check is a DOM assertion, not only a
screenshot)

| ID | Check |
|---|---|
| B1 | Card 2 text equals "Existing records only — partial visibility." |
| B2 | Module table: the count of rows with "used" ticked equals the API `counts.used`; each failed module shows its failure message |
| B3 | Daily counts table: the selected day's TRADE / WATCH / WAIT / AVOID equal `/days` |
| B4 | "Load more" appears when the API returns `next_cursor` and, after clicking, the list length equals the sum of both pages (tested with `limit` lowered via a query parameter on a dev build, or a run with more than 500 decisions in the local data) |
| B5 | The decision-path and "Why no TRADE?" panels show "Not recorded — decision-path recording deferred during trial" |
| B6 | Card 3 shows the frozen verdicts and the forward gate with its cohort dates "from 2026-10-14", unchanged when the date picker moves |
| B7 | Error states: stop the API → each card shows "Could not load"; pick a run id that does not exist → "Not found (404)" |
| B8 | Non-owner session: the Brain Logs menu has no "Observatory"; visiting `/trademind/observatory` redirects; the API answers 403 |
| B9 | No console errors and no failed network requests other than the deliberate ones in B7 |

Screenshots of each tab are kept as a record, in addition to B1–B9.

Out of this approval: Phase 1B and Phase 2, production deployment, pushes and merges.

---

## File map

| File | Responsibility |
|---|---|
| `backend/src/swing_trade_ml/services/brain_observatory/__init__.py` | package docstring only |
| `.../brain_observatory/db.py` | read-only session dependency (R8) |
| `.../brain_observatory/redact.py` | free-text redaction over a JSON payload (R9) |
| `.../brain_observatory/health.py` | module-health flags, corroboration and counts; M00, M16–M18 rows (R1, R2) |
| `.../brain_observatory/schedule.py` | expected runs per day: holidays, deadlines, intraday slots (R7) |
| `.../brain_observatory/verdicts.py` | registry loading, numerical verdict, independence, precedence (R5) |
| `.../brain_observatory/validation_verdicts.json` | the reviewed verdict registry |
| `.../brain_observatory/counts.py` | universe / idea / holding relation; word counts |
| `.../brain_observatory/queries.py` | every database read (bounded, batched) |
| `.../brain_observatory/outcomes.py` | stored grades + trial-journal figures with sources and assumptions (R4) |
| `backend/src/swing_trade_ml/api/v1/endpoints/brain_observatory.py` | GET routes, limits, response shapes, recording card (R3) |
| `backend/src/swing_trade_ml/api/v1/router.py` | +1 include line |
| `backend/tests/observatory_fixtures.py` | committed test rows and cleanup (the read-only session cannot see a rolled-back test transaction) |
| `backend/tests/test_brain_observatory_*.py` | tests per task |
| `.github/workflows/test.yml` | checkout `fetch-depth: 0` so tag checks run (R6) |
| `frontend/src/api/types.ts`, `frontend/src/api/client.ts` | types and calls |
| `frontend/src/trademind/pages/Observatory.tsx` | the page |
| `frontend/src/trademind/TradeMindApp.tsx` | owner-only menu entry and route |

---

### Task 0: Branch and spec pointer

> **Plan rev 2:** apply C10 (branch base, if option 1); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Modify: `docs/superpowers/specs/2026-10-15-brain-observatory-design.md` (append section 14; section 13, the four questions and one source of truth, already exists and Task 7 implements it)

- [ ] **Step 1: Create the branch**

```bash
cd "D:/machine learning/swing-trade-bot"
git switch develop
git switch -c feature/brain-observatory-1a
```

- [ ] **Step 2: Append the rev 4b pointer to the spec**

Append at the end of the spec:

```markdown

## 14. Rev 4b (owner review of the plan, 2026-10-15)

Requirements R1–R9 in `docs/superpowers/plans/2026-10-15-brain-observatory-phase-1a.md` are part of this spec:
independent health flags and counts; single-source vs conflicting records; the recording card text "Existing
records only — partial visibility."; sourced outcome, cost and benchmark figures with honest unavailable
states; numerical verdict separate from independence with fixed precedence; CI integrity checks against git
objects; missing-run checks using holidays and deadlines; database-enforced read-only transactions with
isolated write tests; redaction that never alters ids or cursors.

Two corrections to earlier sections:
- 3.3 `/outcomes`: the figures are **computed at view time from stored prices** (section 13's one function,
  category required) and labelled so; only the M09 grades are stored records.
- 6.3 learning changes: "No frozen protocol yet", by the precedence rule, since no protocol exists for them.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-15-brain-observatory-design.md
git commit -m "Brain Observatory spec: rev 4b pointer to the Phase 1A plan requirements

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Read-only session (R8)

> **Plan rev 2:** apply C8 (verified test database, per-session namespace; `obs_clean` becomes `obs_ns`); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_observatory/__init__.py`
- Create: `backend/src/swing_trade_ml/services/brain_observatory/db.py`
- Create: `backend/tests/observatory_fixtures.py`
- Test: `backend/tests/test_brain_observatory_readonly.py`

**Interfaces:**
- Produces: `get_readonly_db() -> Generator[Session, None, None]` (FastAPI dependency);
  `STATEMENT_TIMEOUT = "5s"`.
- Produces (tests): `observatory_fixtures.committed(*rows)` context manager; `cleanup()`;
  `make_run(...) -> BrainRun`; `make_decision(...) -> BrainDecision`; constants `RUN_PREFIX = "obs-test-"`,
  `SYM_PREFIX = "OBSX"`; pytest fixture `obs_clean` (in the test modules, via the import below).

- [ ] **Step 1: Write the package docstring**

`backend/src/swing_trade_ml/services/brain_observatory/__init__.py`:

```python
"""Brain Observatory, Phase 1A: read-only views over what the brain already stored.

Spec: docs/superpowers/specs/2026-10-15-brain-observatory-design.md. Nothing here writes, runs the brain,
sends a message or talks to a broker; the API reads through its own READ ONLY transaction (db.py).
"""
```

- [ ] **Step 2: Write the committed-rows test helper**

`backend/tests/observatory_fixtures.py`:

```python
"""Committed rows for Brain Observatory tests.

The Observatory reads through its own READ ONLY transaction (services/brain_observatory/db.py), so it
cannot see rows a test added inside the rolled-back `db_session`. These helpers commit marked rows and
delete them again: run ids start with RUN_PREFIX, symbols with SYM_PREFIX.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import BrainAlert, BrainDecision, BrainRun, BrainTrack, FeatureSnapshot
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.session import engine

RUN_PREFIX = "obs-test-"
SYM_PREFIX = "OBSX"


def make_run(
    suffix: str,
    *,
    as_of: datetime,
    kind: str = "nightly",
    status: str = "done",
    live: bool = True,
    modules: dict | None = None,
    trace: list | None = None,
    error: str | None = None,
    alerts_checked_at: datetime | None = None,
    context: dict | None = None,
    quality: dict | None = None,
    started_at: datetime | None = None,
) -> BrainRun:
    return BrainRun(
        id=f"{RUN_PREFIX}{suffix}",
        kind=kind,
        as_of=as_of,
        book="paper",
        live=live,
        started_at=started_at or as_of,
        finished_at=as_of,
        ms=41000,
        status=status,
        error=error,
        modules=modules if modules is not None else {},
        trace=trace if trace is not None else [],
        quality=quality if quality is not None else {},
        alerts_checked_at=alerts_checked_at,
        context=context,
    )


def make_decision(run_suffix: str, symbol: str, *, kind: str = "idea", word: str = "WAIT", **kw) -> BrainDecision:
    return BrainDecision(run_id=f"{RUN_PREFIX}{run_suffix}", symbol=symbol, kind=kind, word=word, **kw)


def cleanup() -> None:
    with Session(engine) as s:
        s.execute(delete(FeatureSnapshot).where(FeatureSnapshot.symbol.like(f"{SYM_PREFIX}%")))
        s.execute(delete(BrainTrack).where(BrainTrack.symbol.like(f"{SYM_PREFIX}%")))
        s.execute(delete(BrainAlert).where(BrainAlert.run_id.like(f"{RUN_PREFIX}%")))
        s.execute(delete(BrainDecision).where(BrainDecision.run_id.like(f"{RUN_PREFIX}%")))
        s.execute(delete(BrainRun).where(BrainRun.id.like(f"{RUN_PREFIX}%")))
        s.execute(delete(Instrument).where(Instrument.tradingsymbol.like(f"{SYM_PREFIX}%")))
        s.commit()


@contextmanager
def committed(*rows) -> Iterator[None]:
    """Commit `rows` in order (parents first); always clean up afterwards."""
    cleanup()
    try:
        with Session(engine) as s:
            for row in rows:
                s.add(row)
                s.flush()
            s.commit()
        yield
    finally:
        cleanup()


@pytest.fixture()
def obs_clean():
    cleanup()
    yield
    cleanup()
```

- [ ] **Step 3: Write the failing tests**

`backend/tests/test_brain_observatory_readonly.py`:

```python
"""R8: the Observatory's session is READ ONLY in Postgres itself; a write is refused by the database."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from observatory_fixtures import obs_clean  # noqa: F401 — pytest fixture
from swing_trade_ml.db.models.brain import BrainModuleSetting
from swing_trade_ml.db.session import engine
from swing_trade_ml.services.brain_observatory.db import STATEMENT_TIMEOUT, get_readonly_db


def _open():
    gen = get_readonly_db()
    return gen, next(gen)


def test_the_transaction_is_read_only_and_time_limited(obs_clean):
    gen, s = _open()
    try:
        assert s.execute(text("SHOW transaction_read_only")).scalar() == "on"
        assert s.execute(text("SHOW statement_timeout")).scalar() == STATEMENT_TIMEOUT
    finally:
        gen.close()


def test_a_write_in_the_session_is_refused_by_postgres(obs_clean):
    gen, s = _open()
    try:
        with pytest.raises(DBAPIError) as exc:
            s.execute(text("INSERT INTO brain_modules (module_id, mode) VALUES ('OBSW', 'on')"))
        assert "read-only transaction" in str(exc.value).lower()
    finally:
        gen.close()
    with Session(engine) as check:
        assert check.get(BrainModuleSetting, "OBSW") is None


def test_the_session_is_rolled_back_and_closed_never_committed(obs_clean, monkeypatch):
    calls = []
    gen, s = _open()
    monkeypatch.setattr(s, "commit", lambda: calls.append("commit"))
    gen.close()
    assert calls == []
```

`backend/tests/conftest.py` already puts `backend/tests` on the path for helper imports such as
`brain_fakes`. If `from observatory_fixtures import ...` fails, use the same import style that
`test_brain_m18_*` uses for `brain_m18_fixtures` (check with
`grep -n "brain_m18_fixtures" backend/tests/test_brain_m18_stage.py`).

- [ ] **Step 4: Run and verify they fail**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE ./.venv/Scripts/python.exe -m pytest tests/test_brain_observatory_readonly.py -q`
Expected: FAIL, `ModuleNotFoundError: swing_trade_ml.services.brain_observatory.db`.

- [ ] **Step 5: Implement `db.py`**

```python
"""The Observatory's own database session: READ ONLY in Postgres, time-limited, never committed (R8).

It is a separate session from the request's `get_db` one (used by auth), so the read-only setting is the
first statement of its own transaction, as Postgres requires.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import text
from sqlalchemy.orm import Session

from swing_trade_ml.db.session import SessionLocal

STATEMENT_TIMEOUT = "5s"


def get_readonly_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        yield db
    finally:
        db.rollback()
        db.close()
```

- [ ] **Step 6: Run and verify they pass**

Run: same command. Expected: 3 passed.

- [ ] **Step 7: Format and commit**

```bash
cd backend && ./.venv/Scripts/ruff.exe format src/swing_trade_ml/services/brain_observatory tests/observatory_fixtures.py tests/test_brain_observatory_readonly.py
cd .. && git add backend/src/swing_trade_ml/services/brain_observatory backend/tests/observatory_fixtures.py backend/tests/test_brain_observatory_readonly.py
git commit -m "Brain Observatory: read-only, time-limited database session (Postgres-enforced)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Redaction that keeps ids and cursors (R9, spec 3.4)

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_observatory/redact.py`
- Test: `backend/tests/test_brain_observatory_redact.py`

**Interfaces:**
- Produces: `FREE_TEXT_KEYS: frozenset[str]`; `redact_text(s: str) -> str`;
  `redact_response(payload: dict) -> dict`. The last returns a new dict with every free-text value
  redacted and a top-level `"redacted_fields": list[str]` of JSON paths that changed.

- [ ] **Step 1: Write the failing tests**

```python
"""Spec 3.4 and R9: redact secrets in free text only; ids, symbols, numbers and cursors are never altered."""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.brain_observatory.redact import FREE_TEXT_KEYS, redact_response, redact_text

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvd25lciJ9.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
HEX40 = "0123456789abcdef0123456789abcdef01234567"


def test_each_secret_kind_in_free_text_is_replaced(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:obs-telegram-token-value", raising=False)
    text = (
        "boom postgresql://swing:hunter2@db:5432/x mail naresh@example.com jwt "
        f"{JWT} api_key=abcd1234 token: zzz999 blob {HEX40} tg 123456:obs-telegram-token-value end"
    )
    out = redact_text(text)
    for secret in ("hunter2", "naresh@example.com", JWT, "abcd1234", "zzz999", HEX40, "obs-telegram-token-value"):
        assert secret not in out
    assert out.startswith("boom ") and out.endswith(" end")
    assert "postgresql://[redacted]@db:5432/x" in out


def test_text_without_secrets_is_byte_identical():
    s = "Model score 41% is below the buy level 60%. Results on 08 Oct."
    assert redact_text(s) == s


def test_ids_and_cursors_are_never_altered():
    payload = {
        "run_id": "nightly-20261015T155000-ab12cd",
        "decision_id": 912345,
        "symbol": "BAJAJ-AUTO",
        "next_cursor": {"after_id": 912345, "after_started_at": "2026-10-15T10:20:00+00:00"},
        "word": "WAIT",
        "error": f"failed with {HEX40}",
    }
    out = redact_response(payload)
    for key in ("run_id", "decision_id", "symbol", "next_cursor", "word"):
        assert out[key] == payload[key]
    assert HEX40 not in out["error"]
    assert out["redacted_fields"] == ["error"]


def test_a_run_id_inside_free_text_is_kept():
    s = "superseded by nightly-20261015T155000-ab12cd at 15:52"
    assert redact_text(s) == s


def test_nested_lists_and_paths_are_reported():
    payload = {"runs": [{"id": "x", "trace": [{"module_id": "M06", "reason": "error: token=abc123"}]}]}
    out = redact_response(payload)
    assert "abc123" not in out["runs"][0]["trace"][0]["reason"]
    assert out["redacted_fields"] == ["runs[0].trace[0].reason"]


def test_only_named_keys_are_free_text():
    assert {"error", "reason", "reasons", "evidence_text", "downgrade_reason", "overrule_reason"} <= FREE_TEXT_KEYS
    assert not {"id", "run_id", "decision_id", "symbol", "next_cursor", "after_id", "word"} & FREE_TEXT_KEYS
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`)

Run: `... -m pytest tests/test_brain_observatory_redact.py -q`

- [ ] **Step 3: Implement `redact.py`**

```python
"""Remove secrets from stored free text before the Observatory shows it (spec 3.4, R9).

Only values under FREE_TEXT_KEYS are touched. Ids, symbols, words, numbers, timestamps and pagination
cursors are typed fields and pass through unchanged. Text is never parsed for meaning, only redacted.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from swing_trade_ml.core.config import settings

FREE_TEXT_KEYS = frozenset(
    {
        "error", "reason", "reasons", "evidence_text", "downgrade_reason", "overrule_reason",
        "banner_headline", "headline", "text", "detail", "issues", "note", "title", "evidence",
        "decided_note", "drift_note", "drift_lines", "message", "failure_messages", "why",
    }
)
SECRET_SETTINGS = (
    "KITE_API_KEY", "KITE_API_SECRET", "KITE_PASSWORD", "KITE_TOTP_SECRET", "KITE_USER_ID", "API_KEY",
    "JWT_SECRET_KEY", "GOOGLE_CLIENT_SECRET", "POSTGRES_PASSWORD", "DATABASE_URL", "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)
MASK = "[redacted]"
_RUN_ID = re.compile(r"^(nightly|intraday|why)-\d{8}T\d{6}-[0-9a-f]{6}$")
_URL_CRED = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_KV = re.compile(r"(?i)\b(access_token|api[_-]?key|secret|password|token)(\s*[=:]\s*)([^\s,;'\"]+)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LONG = re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}")


def _secret_values() -> list[str]:
    values: set[str] = set()
    for name in SECRET_SETTINGS:
        for raw in (getattr(settings, name, None), os.environ.get(name)):
            if raw is None:
                continue
            value = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
            if len(value) >= 4:
                values.add(value)
            if name == "DATABASE_URL" and value:
                password = urlsplit(value).password
                if password and len(password) >= 4:
                    values.add(password)
    return sorted(values, key=len, reverse=True)


def _long(match: re.Match) -> str:
    token = match.group(0)
    return token if _RUN_ID.match(token) else MASK


def redact_text(s: str) -> str:
    out = s
    for value in _secret_values():
        out = out.replace(value, MASK)
    out = _URL_CRED.sub(lambda m: f"{m.group(1)}{MASK}@", out)
    out = _JWT.sub(MASK, out)
    out = _KV.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", out)
    out = _EMAIL.sub(MASK, out)
    out = _LONG.sub(_long, out)
    return out


def _walk(value, path: str, free: bool, changed: list[str]):
    if isinstance(value, dict):
        return {k: _walk(v, f"{path}.{k}" if path else k, k in FREE_TEXT_KEYS, changed) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, f"{path}[{i}]", free, changed) for i, v in enumerate(value)]
    if free and isinstance(value, str):
        cleaned = redact_text(value)
        if cleaned != value:
            changed.append(path)
        return cleaned
    return value


def redact_response(payload: dict) -> dict:
    changed: list[str] = []
    out = _walk(payload, "", False, changed)
    out["redacted_fields"] = changed
    return out
```

Note on `_walk`: a list under a free-text key (`reasons`) keeps `free=True` for its strings. A dict inside
a list under a non-free key (`trace[0]`) re-decides per key.

- [ ] **Step 4: Run, expect PASS** (6 passed)

- [ ] **Step 5: Format, commit**

```bash
git add backend/src/swing_trade_ml/services/brain_observatory/redact.py backend/tests/test_brain_observatory_redact.py
git commit -m "Brain Observatory: redact secrets in free text only; ids and cursors untouched

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Module health: independent flags, corroboration, counts (R1, R2, spec 3.2)

> **Plan rev 2:** apply C4 (historical module lists, M00 and M16 by run status); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_observatory/health.py`
- Test: `backend/tests/test_brain_observatory_health.py`

**Interfaces:**
- Produces:
  - `FLAGS: tuple[str, ...]`
  - `current_step_map() -> dict[str, str]` (module id → step value; cached; **inferred**)
  - `module_rows(kind: str, modules: dict | None, trace: list | None, step_map: dict[str, str]) -> list[dict]`
  - `step_fallbacks(trace: list | None) -> list[dict]`
  - `flag_counts(rows: list[dict]) -> dict`
  - `outside_rows(kind: str, live: bool, status: str, alerts_checked_at, alerts_sent: int) -> list[dict]`
  - `headline(status: str, rows: list[dict], fallbacks: list[dict]) -> str` (`"completed" | "degraded" | <run status>`)
- Row shape:

  ```
  {module_id, step, step_source: "step log" | "current code (inferred)" | None,
   mode_recorded, statuses, flags: {flag: bool}, inferred: {flag: bool},
   corroboration: "corroborated" | "single_source" | "no_record" | "conflicting",
   conflicts: [str], failure_messages: [str]}
  ```

- [ ] **Step 1: Write the failing tests**

```python
"""R1, R2 and spec 3.2: per-module health from stored records only; flags independent, conflicts explicit."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.services.brain_observatory import health

STEP_MAP = {"M01": "perceive", "M06": "reason", "M07": "risk", "M08": "decide", "M09": "learn"}


def line(mid, status, step="perceive", reason=""):
    return {"step": step, "module_id": mid, "status": status, "reason": reason, "ms": 5, "version": "1"}


def row(rows, mid):
    return next(r for r in rows if r["module_id"] == mid)


def test_flags_are_independent():
    rows = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used")], STEP_MAP)
    f = row(rows, "M01")["flags"]
    assert f["executed"] and f["valid_output"] and f["used"] and f["expected"]
    assert not (f["failed"] or f["shadow"] or f["switched_off"] or f["not_observed"])


def test_executed_never_implies_used():
    trace = [line("M06", "shadow", "reason"), line("M01", "fallback", reason="error: x")]
    rows = health.module_rows("nightly", {"M06": "shadow", "M01": "on"}, trace, STEP_MAP)
    assert row(rows, "M06")["flags"]["executed"] and not row(rows, "M06")["flags"]["used"]
    m01 = row(rows, "M01")
    assert m01["flags"]["executed"] and m01["flags"]["failed"] and not m01["flags"]["used"]
    assert m01["failure_messages"] == ["error: x"]


def test_counts_are_per_flag():
    trace = [line("M01", "used"), line("M06", "shadow", "reason")]
    rows = health.module_rows("nightly", {"M01": "on", "M06": "shadow"}, trace, STEP_MAP)
    c = health.flag_counts(rows)
    assert c["executed"] == 2 and c["valid_output"] == 2 and c["used"] == 1 and c["shadow"] == 1


def test_single_source_is_not_a_conflict():
    rows = health.module_rows("nightly", {}, [line("M01", "used")], STEP_MAP)
    assert row(rows, "M01")["corroboration"] == "single_source"
    assert not row(rows, "M01")["flags"]["conflicting"]


def test_no_record_is_not_a_conflict_and_is_inferred():
    rows = health.module_rows("nightly", {}, [], STEP_MAP)
    r = row(rows, "M08")
    assert r["corroboration"] == "no_record" and r["flags"]["not_observed"] and r["inferred"]["not_observed"]
    assert r["step_source"] == "current code (inferred)"


def test_disagreeing_sources_conflict():
    rows = health.module_rows("nightly", {"M01": "off"}, [line("M01", "used")], STEP_MAP)
    r = row(rows, "M01")
    assert r["corroboration"] == "conflicting" and r["flags"]["conflicting"]
    assert "mode 'off'" in r["conflicts"][0]


def test_identical_repeated_lines_are_duplicate_not_conflict():
    rows = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used"), line("M01", "used")], STEP_MAP)
    r = row(rows, "M01")
    assert r["flags"]["duplicate"] and not r["flags"]["conflicting"]


def test_different_repeated_lines_conflict():
    rows = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used"), line("M01", "fallback")], STEP_MAP)
    assert row(rows, "M01")["flags"]["conflicting"]


def test_switched_off_is_corroborated_when_both_say_off():
    rows = health.module_rows("nightly", {"M01": "off"}, [line("M01", "skipped", reason="switched off")], STEP_MAP)
    r = row(rows, "M01")
    assert r["flags"]["switched_off"] and not r["flags"]["expected"] and r["corroboration"] == "corroborated"


def test_not_applicable_for_the_run_kind():
    rows = health.module_rows("intraday", {"M09": "on"}, [], STEP_MAP)
    r = row(rows, "M09")
    assert r["flags"]["not_applicable"] and not r["flags"]["not_observed"]


def test_unknown_module_is_flagged():
    rows = health.module_rows("nightly", {"M99": "on"}, [line("M99", "used")], STEP_MAP)
    assert row(rows, "M99")["flags"]["unknown_module"]


def test_empty_modules_and_trace_do_not_crash():
    rows = health.module_rows("nightly", None, None, STEP_MAP)
    assert {r["module_id"] for r in rows} == set(STEP_MAP)


def test_step_fallbacks_listed():
    assert health.step_fallbacks([line("fallback", "fallback", "decide", "no module answered")]) == [
        {"step": "decide", "reason": "no module answered"}
    ]


def test_headline():
    ok = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used")], {"M01": "perceive"})
    assert health.headline("done", ok, []) == "completed"
    assert health.headline("done", ok, [{"step": "decide", "reason": "x"}]) == "degraded"
    assert health.headline("failed", ok, []) == "failed"


def test_m16_m17_m18_rows():
    stamp = datetime(2026, 10, 15, 10, 22, tzinfo=UTC)
    rows = {r["module_id"]: r for r in health.outside_rows("intraday", True, "done", stamp, 0)}
    assert rows["M16"]["state"] == "executed" and "0 alerts" in rows["M16"]["detail"]
    rows = {r["module_id"]: r for r in health.outside_rows("nightly", True, "done", None, 0)}
    assert rows["M16"]["state"] == "unknown"
    rows = {r["module_id"]: r for r in health.outside_rows("why", True, "done", None, 0)}
    assert rows["M16"]["state"] == "not_applicable"
    assert rows["M17"]["state"] == "not_applicable" and rows["M18"]["state"] == "not_applicable"


def test_alerting_kinds_mirror_the_alert_service():
    from swing_trade_ml.brain.alerts.service import ALERTING_KINDS

    assert health.ALERTING_KINDS == frozenset(ALERTING_KINDS)


def test_current_step_map_reads_the_registry():
    m = health.current_step_map()
    assert m["M08"] == "decide" and m["M07"] == "risk"
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `health.py`**

```python
"""Module health for one stored brain run (spec 3.2; R1 independent flags, R2 corroboration).

Pure functions over what the run stored: `brain_runs.modules` (module id -> mode used) and
`brain_runs.trace` (one line per module and step). The module -> step map comes from the current code's
module list and is marked inferred wherever it decides anything.
"""

from __future__ import annotations

from functools import lru_cache

from swing_trade_ml.brain.module import STEPS_FOR

EXECUTED = frozenset({"used", "shadow", "fallback", "rejected"})
VALID = frozenset({"used", "shadow"})
FAILED = frozenset({"fallback", "rejected"})
CONSISTENT = {"off": {"skipped"}, "on": {"used", "fallback", "rejected"}, "shadow": {"shadow", "fallback", "rejected"}}
ALERTING_KINDS = frozenset({"nightly", "intraday"})  # mirrors brain/alerts/service.py; a test keeps them equal
FLAGS = (
    "expected", "executed", "valid_output", "used", "shadow", "switched_off", "failed",
    "not_observed", "not_applicable", "unknown_module", "duplicate", "conflicting",
)
CORROBORATION = ("corroborated", "single_source", "no_record", "conflicting")


@lru_cache(maxsize=1)
def current_step_map() -> dict[str, str]:
    import swing_trade_ml.brain.modules  # noqa: F401 — registers the installed modules
    from swing_trade_ml.brain.module import REGISTRY

    return {cls.manifest.id: cls.manifest.step.value for cls in REGISTRY.all()}


def module_rows(kind: str, modules: dict | None, trace: list | None, step_map: dict[str, str]) -> list[dict]:
    modules = modules or {}
    by_id: dict[str, list[dict]] = {}
    for item in trace or []:
        mid = item.get("module_id")
        if mid and mid != "fallback":
            by_id.setdefault(mid, []).append(item)
    steps_in_kind = {s.value for s in STEPS_FOR.get(kind, ())}
    rows = []
    for mid in sorted(set(step_map) | set(modules) | set(by_id)):
        lines = by_id.get(mid, [])
        mode = modules.get(mid)
        statuses = [item.get("status") for item in lines]
        seen = set(statuses)
        recorded_step = lines[0].get("step") if lines else None
        step = recorded_step or step_map.get(mid)
        inferred_step = recorded_step is None
        applicable = None if step is None else step in steps_in_kind
        conflicts = []
        if len(seen) > 1:
            conflicts.append(f"step log has different results for one module: {sorted(seen)}")
        if mode is not None and seen and not seen <= CONSISTENT.get(mode, set()):
            conflicts.append(f"mode '{mode}' but the step log says {sorted(seen)}")
        if conflicts:
            corroboration = "conflicting"
        elif mode is not None and lines:
            corroboration = "corroborated"
        elif mode is not None or lines:
            corroboration = "single_source"
        else:
            corroboration = "no_record"
        off = "skipped" in seen or mode == "off"
        flags = {
            "expected": bool(applicable) and not off,
            "executed": bool(seen & EXECUTED),
            "valid_output": bool(seen & VALID),
            "used": "used" in seen,
            "shadow": "shadow" in seen,
            "switched_off": off,
            "failed": bool(seen & FAILED),
            "not_observed": bool(applicable) and not lines and not off,
            "not_applicable": applicable is False,
            "unknown_module": mid not in step_map,
            "duplicate": len(lines) > 1 and len(seen) == 1,
            "conflicting": bool(conflicts),
        }
        rows.append(
            {
                "module_id": mid,
                "step": step,
                "step_source": None if step is None else ("current code (inferred)" if inferred_step else "step log"),
                "mode_recorded": mode,
                "statuses": statuses,
                "flags": flags,
                "inferred": {k: inferred_step for k in ("expected", "not_observed", "not_applicable")},
                "corroboration": corroboration,
                "conflicts": conflicts,
                "failure_messages": [item.get("reason", "") for item in lines if item.get("status") in FAILED],
            }
        )
    return rows


def step_fallbacks(trace: list | None) -> list[dict]:
    return [
        {"step": item.get("step"), "reason": item.get("reason", "")}
        for item in trace or []
        if item.get("module_id") == "fallback"
    ]


def flag_counts(rows: list[dict]) -> dict:
    counts = {flag: sum(1 for r in rows if r["flags"][flag]) for flag in FLAGS}
    counts["corroboration"] = {c: sum(1 for r in rows if r["corroboration"] == c) for c in CORROBORATION}
    counts["inferred_flags"] = ["expected", "not_observed", "not_applicable"]
    return counts


def headline(status: str, rows: list[dict], fallbacks: list[dict]) -> str:
    if status != "done":
        return status
    bad = any(r["flags"]["failed"] or r["flags"]["not_observed"] or r["flags"]["conflicting"] for r in rows)
    return "degraded" if bad or fallbacks else "completed"


def outside_rows(kind: str, live: bool, status: str, alerts_checked_at, alerts_sent: int) -> list[dict]:
    if live and kind in ALERTING_KINDS:
        m16 = (
            {"state": "executed", "detail": f"alert check recorded; {alerts_sent} alerts sent"}
            if alerts_checked_at is not None
            else {"state": "unknown", "detail": "Not observed or send failed: no alert check was recorded"}
        )
    else:
        m16 = {"state": "not_applicable", "detail": "alerts run only after live nightly and intraday runs"}
    return [
        {"module_id": "M00", "state": "executed", "detail": f"run status: {status}"},
        {"module_id": "M16", **m16},
        {"module_id": "M17", "state": "not_applicable", "detail": "the console is a screen, not a step of a run"},
        {
            "module_id": "M18",
            "state": "not_applicable",
            "detail": "go-live is not part of a single run; the day's stage is shown as day context",
        },
    ]
```

- [ ] **Step 4: Run, expect PASS** (17 passed)

- [ ] **Step 5: Format, commit** (`git add` the two files; message: "Brain Observatory: module health
  flags, corroboration and counts from stored runs")

---

### Task 4: Expected runs, holidays and deadlines (R7)

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_observatory/schedule.py`
- Test: `backend/tests/test_brain_observatory_schedule.py`

**Interfaces:**
- Produces:
  - `IST`, `NIGHTLY_AT = time(15, 50)`, `NIGHTLY_DUE_BY = time(16, 20)`,
    `INTRADAY_SLOTS: tuple[time, ...]` (28), `INTRADAY_GRACE = timedelta(minutes=10)`
  - `run_day(as_of: datetime) -> date`
  - `day_window(day: date) -> tuple[datetime, datetime]`
  - `nightly_expectation(day: date, now: datetime) -> str` (`"not_applicable" | "not_due" | "due"`)
  - `intraday_expectation(day: date, now: datetime) -> dict` (`{"slots": 28, "due": n, "not_due": m}`, or
    `{"not_applicable": True}`)
  - `nightly_state(day, now, runs: list[dict]) -> dict` (`runs` items carry `id, kind, live, status`)

- [ ] **Step 1: Write the failing tests**

```python
"""R7: a missing run is 'Not observed' only on a trading day after its deadline."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from swing_trade_ml.services.brain_observatory import schedule as sch

IST = sch.IST
THU = date(2026, 10, 15)


def at(d, h, m):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


def test_weekend_and_listed_holiday_are_not_applicable(monkeypatch):
    assert sch.nightly_expectation(date(2026, 10, 17), at(date(2026, 10, 17), 20, 0)) == "not_applicable"
    monkeypatch.setattr(sch, "is_trading_day", lambda d: False)
    assert sch.nightly_expectation(THU, at(THU, 20, 0)) == "not_applicable"


def test_before_the_deadline_is_not_due():
    assert sch.nightly_expectation(THU, at(THU, 16, 0)) == "not_due"
    assert sch.nightly_expectation(THU, at(THU, 16, 20)) == "due"


def test_missing_after_deadline_is_not_observed():
    assert sch.nightly_state(THU, at(THU, 17, 0), [])["state"] == "not_observed"
    assert sch.nightly_state(THU, at(THU, 16, 5), [])["state"] == "not_due"


def test_superseded_runs_are_ignored_and_two_live_runs_conflict():
    runs = [
        {"id": "a", "kind": "nightly", "live": True, "status": "superseded"},
        {"id": "b", "kind": "nightly", "live": True, "status": "done"},
    ]
    assert sch.nightly_state(THU, at(THU, 17, 0), runs) == {"state": "observed", "run_id": "b", "expectation": "due"}
    runs.append({"id": "c", "kind": "nightly", "live": True, "status": "done"})
    assert sch.nightly_state(THU, at(THU, 17, 0), runs)["state"] == "conflicting"


def test_intraday_slots_due_by_time():
    assert len(sch.INTRADAY_SLOTS) == 28
    e = sch.intraday_expectation(THU, at(THU, 9, 20))
    assert e == {"slots": 28, "due": 1, "not_due": 27}  # 09:00 is due at 09:10; 09:15 at 09:25


def test_run_day_uses_ist_not_utc():
    utc_evening = datetime(2026, 10, 14, 19, 0, tzinfo=sch.UTC)  # 00:30 IST on 15 Oct
    assert sch.run_day(utc_evening) == THU


def test_schedule_constants_match_the_scheduler_source():
    src = (Path(sch.__file__).resolve().parents[2] / "workers" / "scheduler.py").read_text(encoding="utf-8")
    assert "jobs.job_brain_nightly,\n        CronTrigger(day_of_week=WEEKDAYS, hour=15, minute=50" in src
    assert 'hour="9-15", minute="0,15,30,45"' in src
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `schedule.py`**

```python
"""Which brain runs were due on a day (R7): trading days only, and only after their deadline.

Times mirror workers/scheduler.py (nightly 15:50 IST; intraday every 15 minutes 09:00-15:45), checked by a
test. The nightly deadline is 16:20 IST, when the daily check runs. Holidays come from the listed NSE
holidays (core/market_session.is_trading_day); an unlisted closure would show as Not observed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from swing_trade_ml.core.market_session import is_trading_day

IST = ZoneInfo("Asia/Kolkata")
__all__ = ["IST", "UTC", "is_trading_day"]
NIGHTLY_AT = time(15, 50)
NIGHTLY_DUE_BY = time(16, 20)
INTRADAY_SLOTS = tuple(time(h, m) for h in range(9, 16) for m in (0, 15, 30, 45))
INTRADAY_GRACE = timedelta(minutes=10)


def run_day(as_of: datetime) -> date:
    return as_of.astimezone(IST).date()


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=IST)
    return start, start + timedelta(days=1)


def nightly_expectation(day: date, now: datetime) -> str:
    if not is_trading_day(day):
        return "not_applicable"
    return "due" if now >= datetime.combine(day, NIGHTLY_DUE_BY, tzinfo=IST) else "not_due"


def intraday_expectation(day: date, now: datetime) -> dict:
    if not is_trading_day(day):
        return {"not_applicable": True}
    due = sum(1 for t in INTRADAY_SLOTS if now >= datetime.combine(day, t, tzinfo=IST) + INTRADAY_GRACE)
    return {"slots": len(INTRADAY_SLOTS), "due": due, "not_due": len(INTRADAY_SLOTS) - due}


def nightly_state(day: date, now: datetime, runs: list[dict]) -> dict:
    expectation = nightly_expectation(day, now)
    live = [r for r in runs if r["kind"] == "nightly" and r["live"] and r["status"] != "superseded"]
    if len(live) > 1:
        return {"state": "conflicting", "run_ids": [r["id"] for r in live], "expectation": expectation}
    if live:
        return {"state": "observed", "run_id": live[0]["id"], "expectation": expectation}
    if expectation == "due":
        return {"state": "not_observed", "expectation": expectation}
    return {"state": expectation, "expectation": expectation}
```

- [ ] **Step 4: Run, expect PASS** (7 passed). If `test_weekend…` fails because 17 Oct 2026 is listed
  differently, check `core/holidays.py`; 17 Oct 2026 is a Saturday.

- [ ] **Step 5: Format, commit** ("Brain Observatory: expected runs by trading day and deadline")

---

### Task 5: Verdicts: numbers, independence, precedence (R5, spec 6)

> **Plan rev 2:** apply C1 (claims and minimums bound by code) and C9a (registry as a Python module); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_observatory/validation_verdicts.json`
- Create: `backend/src/swing_trade_ml/services/brain_observatory/verdicts.py`
- Test: `backend/tests/test_brain_observatory_verdicts.py`

**Interfaces:**
- Produces:
  - word constants `INVALID, NO_PROTOCOL, INSUFFICIENT, NOT_PROVEN, PASSED_NOT_PROVEN, PROVEN`
  - `INDEPENDENCE = ("untouched", "exposure_disclosed", "audit_uncommitted", "unaudited")`
  - `CLAIMS: tuple[tuple[str, str], ...]`
  - `load_registry(path: Path = REGISTRY_PATH) -> dict`
  - `numeric_verdict(part: dict, minimums: dict) -> tuple[str, list[str]]` (`"pass" | "fail" | "insufficient" | "invalid"`)
  - `display_word(numeric: str, independence: str) -> str`
  - `evaluate(registry: dict) -> list[dict]`. One item per claim:
    `{claim, label, word, numeric, independence, protocol_id, tested_subject, independence_note, numbers, problems}`

- [ ] **Step 1: Write the registry file** (values verified 2026-10-15 from git objects; see spec 6.2 and 11)

```json
{
  "schema": "validation-verdicts@1",
  "entries": [
    {
      "protocol_id": "wf-protocol-v1",
      "protocol_file": "docs/superpowers/specs/2026-10-12-walk-forward-protocol.md",
      "protocol_sha256": "63c71d054a27390b9dbb03123d48c4f9102f8c1de51a661314dd24de90e6e70e",
      "tag": "wf-protocol-v1",
      "tag_commit": "7b972916b1510676f05cd4ef7941003e7013ff6e",
      "evidence_commit": "e1602761c9fc3a2a609d6229bb59605b432d7a67",
      "tested_subject": "Model top-5 ranking only (layer 1): a model retrained per 28-day fold by brain/walk_forward.py, next-day open entry, +8% / -4%, half out at +5%, 15 trading days, after costs. Not the exact production model and not the full brain.",
      "sample": {
        "from": "2023-07-01",
        "to": "2025-01-31",
        "folds": 21,
        "kind": "confirmation",
        "independence": "audit_uncommitted",
        "audit_path": null,
        "independence_note": "An independence audit dated 2026-10-12 exists only as an uncommitted edit. It reports that 2024-08-01 to 2025-01-31 was exposed to a feature-selection decision."
      },
      "report_files": {
        "md": {"path": "docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.md", "sha256": "f656da864d89f3aca246c1861020b94c0aa4d350238a70d2290e883966608e37"},
        "json": {"path": "docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.json", "sha256": "5ff084939bdc7af14f99db7404636c10fba9438998a2ca3139f62eaa10dd3ceb"}
      },
      "minimums": {"eligible_folds": 12, "finished_ideas": 100, "share": 0.6},
      "parts": {
        "predictive": {
          "claim": "model_ranking_predictive",
          "recorded_word": "fail",
          "eligible_folds": 21,
          "folds_won": 7,
          "share": 0.3333333333333333,
          "finished_ideas": 1980,
          "extra_check": "lower bound of the daily edge over every-stock is above zero",
          "extra_check_value": -0.00513018427018618
        },
        "economic": {
          "claim": "model_ranking_economic",
          "recorded_word": "fail",
          "eligible_folds": 21,
          "folds_won": 9,
          "share": 0.42857142857142855,
          "finished_ideas": 1980,
          "extra_check": "average result per trade after costs is above zero overall",
          "extra_check_value": -0.002038939548709073
        }
      }
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

```python
"""R5 and spec 6: the numerical verdict and the independence status are separate, combined by a fixed
precedence. Nothing can show Proven without passing numbers AND an untouched, committed audit."""

from __future__ import annotations

import copy

import pytest

from swing_trade_ml.services.brain_observatory import verdicts as v

MIN = {"eligible_folds": 12, "finished_ideas": 100, "share": 0.6}


def part(**kw):
    p = {"claim": "x", "recorded_word": "pass", "eligible_folds": 20, "folds_won": 14, "share": 0.7,
         "finished_ideas": 500, "extra_check": "e", "extra_check_value": 0.01}
    p.update(kw)
    return p


def test_both_halves_of_the_pass_rule_are_required():
    assert v.numeric_verdict(part(), MIN) == ("pass", [])
    assert v.numeric_verdict(part(recorded_word="fail", extra_check_value=-0.01), MIN)[0] == "fail"
    assert v.numeric_verdict(part(recorded_word="fail", folds_won=11, share=0.55), MIN)[0] == "fail"


def test_below_minimums_is_insufficient():
    assert v.numeric_verdict(part(eligible_folds=11, folds_won=8, share=8 / 11), MIN)[0] == "insufficient"
    assert v.numeric_verdict(part(finished_ideas=99), MIN)[0] == "insufficient"


def test_inconsistent_numbers_are_invalid():
    assert v.numeric_verdict(part(share=0.9), MIN)[0] == "invalid"
    assert v.numeric_verdict(part(folds_won=30), MIN)[0] == "invalid"
    assert v.numeric_verdict(part(recorded_word="fail"), MIN)[0] == "invalid"


@pytest.mark.parametrize(
    ("numeric", "independence", "word"),
    [
        ("invalid", "untouched", v.INVALID),
        ("pass", "nonsense", v.INVALID),
        ("insufficient", "untouched", v.INSUFFICIENT),
        ("fail", "untouched", v.NOT_PROVEN),
        ("fail", "unaudited", v.NOT_PROVEN),
        ("pass", "unaudited", v.PASSED_NOT_PROVEN),
        ("pass", "audit_uncommitted", v.PASSED_NOT_PROVEN),
        ("pass", "exposure_disclosed", v.PASSED_NOT_PROVEN),
        ("pass", "untouched", v.PROVEN),
    ],
)
def test_precedence(numeric, independence, word):
    assert v.display_word(numeric, independence) == word


def test_real_registry_gives_not_proven_with_uncommitted_audit():
    out = {c["claim"]: c for c in v.evaluate(v.load_registry())}
    for claim in ("model_ranking_predictive", "model_ranking_economic"):
        assert out[claim]["word"] == v.NOT_PROVEN
        assert out[claim]["numeric"] == "fail"
        assert out[claim]["independence"] == "audit_uncommitted"
    assert out["model_ranking_predictive"]["numbers"]["folds_won"] == 7
    assert out["model_ranking_economic"]["numbers"]["folds_won"] == 9


def test_claims_without_a_protocol():
    out = {c["claim"]: c for c in v.evaluate(v.load_registry())}
    assert out["full_brain"]["word"] == v.NO_PROTOCOL
    assert out["learning_changes"]["word"] == v.NO_PROTOCOL


def test_untouched_requires_an_audit_path():
    reg = copy.deepcopy(v.load_registry())
    reg["entries"][0]["sample"]["independence"] = "untouched"
    out = {c["claim"]: c for c in v.evaluate(reg)}
    assert out["model_ranking_predictive"]["word"] == v.INVALID


def test_a_passing_entry_shows_proven_only_for_its_own_claim():
    reg = copy.deepcopy(v.load_registry())
    e = reg["entries"][0]
    e["sample"].update(independence="untouched", audit_path="docs/x.md")
    e["parts"]["predictive"].update(recorded_word="pass", folds_won=14, share=14 / 21, extra_check_value=0.001)
    out = {c["claim"]: c for c in v.evaluate(reg)}
    assert out["model_ranking_predictive"]["word"] == v.PROVEN
    assert out["model_ranking_economic"]["word"] == v.NOT_PROVEN
    assert out["full_brain"]["word"] == v.NO_PROTOCOL


def test_a_seen_sample_is_invalid():
    reg = copy.deepcopy(v.load_registry())
    reg["entries"][0]["sample"]["kind"] = "seen"
    out = {c["claim"]: c for c in v.evaluate(reg)}
    assert out["model_ranking_predictive"]["word"] == v.INVALID
```

- [ ] **Step 3: Run, expect FAIL**

- [ ] **Step 4: Implement `verdicts.py`**

```python
"""Effectiveness verdicts (spec section 6; R5).

The numerical verdict (from the protocol's own numbers and pass rule) and the independence status (was the
sample untouched, with a committed audit?) are kept apart and combined by one fixed precedence. Integrity
of the registry against git (tags, file hashes, report numbers) is checked in CI by
tests/test_brain_observatory_verdicts_ci.py; a registry that fails those checks cannot be deployed.
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("validation_verdicts.json")
INVALID = "Verdict record invalid"
NO_PROTOCOL = "No frozen protocol yet"
INSUFFICIENT = "Insufficient evidence"
NOT_PROVEN = "Not proven"
PASSED_NOT_PROVEN = "Passed, not proven: independence not established"
PROVEN = "Proven"
INDEPENDENCE = ("untouched", "exposure_disclosed", "audit_uncommitted", "unaudited")
CLAIMS = (
    ("model_ranking_predictive", "Model top-5 ranking: picks better than a random pick"),
    ("model_ranking_economic", "Model top-5 ranking: profit after costs"),
    ("full_brain", "Full brain decisions"),
    ("learning_changes", "Changes proposed by learning (M09)"),
)


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def numeric_verdict(part: dict, minimums: dict) -> tuple[str, list[str]]:
    eligible, won = part["eligible_folds"], part["folds_won"]
    if not 0 <= won <= eligible:
        return "invalid", ["folds won is outside 0 to eligible folds"]
    if eligible and abs(part["share"] - won / eligible) > 1e-9:
        return "invalid", ["share does not equal folds won / eligible folds"]
    if eligible < minimums["eligible_folds"] or part["finished_ideas"] < minimums["finished_ideas"]:
        return "insufficient", ["below the protocol's minimum folds or finished ideas"]
    word = "pass" if part["share"] >= minimums["share"] and part["extra_check_value"] > 0 else "fail"
    if part["recorded_word"] != word:
        return "invalid", [f"report says '{part['recorded_word']}' but its numbers give '{word}'"]
    return word, []


def display_word(numeric: str, independence: str) -> str:
    if numeric == "invalid" or independence not in INDEPENDENCE:
        return INVALID
    if numeric == "insufficient":
        return INSUFFICIENT
    if numeric == "fail":
        return NOT_PROVEN
    return PROVEN if independence == "untouched" else PASSED_NOT_PROVEN


def _entry_problems(entry: dict) -> list[str]:
    sample = entry["sample"]
    problems = []
    if sample.get("kind") != "confirmation":
        problems.append("sample is not the protocol's confirmation sample")
    if sample.get("independence") in ("untouched", "exposure_disclosed") and not sample.get("audit_path"):
        problems.append("independence is claimed without a committed audit")
    return problems


def evaluate(registry: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for entry in registry.get("entries", []):
        independence = entry["sample"].get("independence")
        problems = _entry_problems(entry)
        for part in entry["parts"].values():
            numeric, why = ("invalid", problems) if problems else numeric_verdict(part, entry["minimums"])
            found[part["claim"]] = {
                "word": display_word(numeric, independence),
                "numeric": numeric,
                "independence": independence,
                "independence_note": entry["sample"].get("independence_note", ""),
                "protocol_id": entry["protocol_id"],
                "tested_subject": entry["tested_subject"],
                "numbers": {k: part[k] for k in ("eligible_folds", "folds_won", "share", "finished_ideas", "extra_check", "extra_check_value")},
                "problems": why,
            }
    out = []
    for claim, label in CLAIMS:
        item = found.get(claim) or {
            "word": NO_PROTOCOL, "numeric": None, "independence": None, "independence_note": "",
            "protocol_id": None, "tested_subject": None, "numbers": None, "problems": [],
        }
        out.append({"claim": claim, "label": label, **item})
    return out
```

- [ ] **Step 5: Run, expect PASS** (15 passed)

- [ ] **Step 6: Format, commit** ("Brain Observatory: verdict registry; numbers and independence kept
  separate")

---

### Task 6: Effectiveness integrity checks in CI (R6)

> **Plan rev 2:** apply C1 (E0 minimums, E4b audit blob) and C9b (tags not on origin); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Create: `backend/tests/test_brain_observatory_verdicts_ci.py`
- Modify: `.github/workflows/test.yml` (the `actions/checkout@v4` step). **Scope addition: confirm with the
  owner before committing.**

**How it runs in CI:**
- `test.yml` runs `pytest -q` in `backend/` on every push to `develop` and on every pull request. Deploy
  runs only after tests pass, which the deploy workflow already requires.
- These tests read git objects (`git rev-parse`, `git show <rev>:<path>`, `git ls-files`), so the checkout
  needs full history and tags (`fetch-depth: 0`).
- Under CI (`CI=true`, set by GitHub), a missing git or tag is a **failure**. Locally it is a skip with the
  reason printed.
- Hashes are computed from git blobs, so Windows line endings cannot change them.

- [ ] **Step 1: Write the tests**

```python
"""R6: the verdict registry must match the frozen artifacts in git, or CI fails (spec 6.1, E1-E4)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from swing_trade_ml.services.brain_observatory import verdicts as v

REPO = Path(__file__).resolve().parents[2]


def git(*args: str) -> bytes:
    if shutil.which("git") is None:
        _missing("git is not installed")
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True)
    if r.returncode != 0:
        _missing(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def _missing(why: str):
    if os.environ.get("CI"):
        pytest.fail(f"effectiveness integrity check cannot run in CI: {why} (needs checkout fetch-depth: 0)")
    pytest.skip(why)


def sha(rev: str, path: str) -> str:
    return hashlib.sha256(git("show", f"{rev}:{path}")).hexdigest()


ENTRIES = v.load_registry()["entries"]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e1_tag_and_protocol_file_are_frozen(entry):
    assert git("rev-parse", f"{entry['tag']}^{{commit}}").decode().strip() == entry["tag_commit"]
    assert sha(entry["tag"], entry["protocol_file"]) == entry["protocol_sha256"]
    assert sha("HEAD", entry["protocol_file"]) == entry["protocol_sha256"], "committed protocol differs from its tag"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e2_report_files_are_unchanged(entry):
    for f in entry["report_files"].values():
        assert sha(entry["evidence_commit"], f["path"]) == f["sha256"]
        assert sha("HEAD", f["path"]) == f["sha256"]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e3_registry_numbers_equal_the_report(entry):
    report = json.loads(git("show", f"HEAD:{entry['report_files']['json']['path']}"))
    pooled = report["pooled"]
    extra = {"predictive": pooled["model_edge_low"], "economic": pooled["model"]["avg_net"]}
    for name, part in entry["parts"].items():
        r = report["verdict"][name]
        assert part["recorded_word"] == r["word"]
        assert part["eligible_folds"] == r["eligible_folds"]
        assert part["folds_won"] == r["folds_won"]
        assert part["share"] == r["share"]
        assert part["finished_ideas"] == pooled["model"]["ideas"]
        assert part["extra_check_value"] == extra[name]
    assert report["protocol"] == entry["protocol_id"]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e4_sample_and_independence_record(entry):
    s = entry["sample"]
    protocol = git("show", f"{entry['tag']}:{entry['protocol_file']}").decode()
    assert f"{s['from']} to {s['to']}" in protocol and "Confirmation" in protocol
    if s["independence"] in ("untouched", "exposure_disclosed"):
        git("ls-files", "--error-unmatch", s["audit_path"])  # the audit must be committed
    else:
        assert s["audit_path"] is None
        assert s["independence_note"], "an uncommitted or missing audit must be explained"
```

- [ ] **Step 2: Run locally**

Run: `... -m pytest tests/test_brain_observatory_verdicts_ci.py -q`
Expected: 4 passed. Tags exist locally, and HEAD's committed protocol equals the tag. The uncommitted
working-tree edit is **not** read, because the hashes come from git objects.

- [ ] **Step 3: Prove each check fails when the registry is wrong** (one-off, not committed)

Temporarily change one digit of `protocol_sha256`, then of `report_files.md.sha256`, then
`folds_won: 7 → 8`, then `"from": "2023-07-02"`. Re-run after each change: the matching test fails. Undo
each change. Record the four failures in the PR description.

- [ ] **Step 4: CI checkout change** (only after the owner OKs this scope addition)

In `.github/workflows/test.yml`, replace:

```yaml
      - uses: actions/checkout@v4
```

with:

```yaml
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # tags and history: the Brain Observatory verdict checks read git objects
```

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_brain_observatory_verdicts_ci.py .github/workflows/test.yml
git commit -m "Brain Observatory: CI checks that the verdict registry matches the frozen artifacts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Outcomes: one function, category required, sources and honest gaps (R4, spec 13, evidence plan A2/A3)

> **Plan rev 2:** apply C2 (official forward gate), C6 (book and category), C7 (bounded loaders), C10 (evidence-defs-v1 baselines); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_observatory/outcomes.py`
- Test: `backend/tests/test_brain_observatory_outcomes.py`

**Why this shape:**
- **Spec addendum 13** (written with the evidence plan,
  `docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md`): finished-idea results come from **one
  read-only function** in this package, and `/outcomes` adds a momentum baseline and cash.
- **Evidence plan A3:** that function takes the **category** (`backtest` / `paper` / `practice`) as a
  required input and never mixes categories.
- **Evidence plan A4:** the evidence-defs-v1 matched baselines (for example NIFTY per idea with costs, and
  Random 5) are built **only after its section 3a is locked**. So 1A shows the trial journal's existing
  definitions and labels them that way. Changing other screens to call this function is A3 work, outside 1A.

**Interfaces:**
- Consumes (existing, read-only; check the exact names at the cited lines before coding):
  - `trial_journal.load_sessions(db, start, end, *, live) -> list[Session]`
  - `trial_journal.build_journal(sessions, bars, v1_by_day, *, index_bars) -> dict`
  - `trial_journal.gate(journal) -> dict`
  - `replay_score.load_bars(db, symbols, upto) -> dict[str, DataFrame]`
  - `walk_forward.momentum_scores(bars, days)`, `walk_forward.outcomes_for(bars, days, horizon, target, stop)`
  - `horizon_grid.summarise(by_day) -> {ideas, days, hit_rate, avg_net, avg_net_by_day}`
  - `replay_scoring.HORIZON_BARS, TARGET, STOP`
  - `queries.stored_grade_rows(db, start, end, live: bool)` (Task 8 Step 2)
- Produces:
  - `CATEGORIES = ("practice", "backtest", "paper")`
  - `SOURCES: dict[str, str]`
  - `stored_grades(rows) -> dict`
  - `journal_figures(journal: dict | None, error: str | None, momentum: dict | None) -> dict`
  - `momentum_summary(sessions, bars) -> dict`
  - `forward_trial(journal, error) -> dict`
  - `build(db, start: date, end: date, category: str) -> dict`. This is **the** one function. It raises
    `ValueError` for an unknown category.

Task 7's test imports `queries`, so write Task 8 Step 2 (`queries.py`) **before** running Task 7's tests.
The two tasks are committed in order: queries with Task 7, the API in Task 8.

Category meaning in 1A:

| Category | Source | Notes |
|---|---|---|
| `practice` | live nightly brain runs (the M18 practice stage) | |
| `backtest` | replay runs (`live = false`) | |
| `paper` | v1 paper trades | Not brain decisions, so in 1A it returns `available: false` with the reason. Never mixed in |

Verified sources (checked in code 2026-10-15):

| Figure | Verified source |
|---|---|
| Stored M09 grade | `m09_learn/outcomes.py` `score`: entry at the decision day's close, +8% / −4%, 15 bars, a same-bar touch of both counts as the stop, **gross** (no costs, no slippage, no half-out) |
| Net after costs | `walk_forward.outcomes_for` → `replay_scoring.strict_score`: next-day open, half out at +5% (`HALF_OUT` default), slippage and charges from `services/costs.py` |
| Every stock | `trial_journal.build_journal` `every_stock`: stocks the brain looked at that day, same rule |
| Momentum | `walk_forward.momentum_scores`: the 5 stocks with the highest 20-day return at the decision close, **chosen from the stocks the brain looked at that day**, same rule and costs |
| NIFTY | `trial_journal.index_baseline`: open after each session to the close of the 15th session, **no costs**. This is not the evidence-defs-v1 matched NIFTY (per idea, with costs), which is A4 |
| Cash | 0% |
| Costs | `services/costs.py`, `PAPER_SLIPPAGE_BPS` (5.0 default), `PAPER_BROKERAGE_PER_ORDER` (0.0), statutory rates in `core/config.py`. **Not yet checked against real Zerodha contract notes** (tracker bx5) |

- [ ] **Step 1: Write the failing tests**

```python
"""R4, spec 13, evidence plan A3: one function, category required and never mixed; every figure says where
it comes from; missing data says 'not available' and why."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from swing_trade_ml.services.brain_observatory import outcomes as o


def test_stored_grades_are_labelled_gross():
    g = o.stored_grades([("target", 0.08), ("stop", -0.04), ("timeout", 0.01)])
    assert g["count"] == 3 and g["by_outcome"] == {"target": 1, "stop": 1, "timeout": 1}
    assert abs(g["avg_gross_return"] - (0.05 / 3)) < 1e-12
    assert "no costs" in g["source"]


def test_no_stored_grades_is_not_zero():
    g = o.stored_grades([])
    assert g["available"] is False and g["avg_gross_return"] is None and g["why"]


def test_journal_failure_is_honest():
    f = o.journal_figures(None, "OperationalError: no candles", None)
    for key in ("brain_trade", "every_stock", "momentum", "nifty"):
        assert f[key]["available"] is False and "no candles" in f[key]["why"]
    assert f["cash"]["available"] is True and f["cash"]["avg_net"] == 0.0
    assert o.forward_trial(None, "x")["word"] == "Insufficient evidence"


def _journal(ideas=2, nifty=None):
    row = {"ideas": ideas, "avg_net": 0.01 if ideas else None, "hit_rate": 0.5 if ideas else None,
           "days": ideas, "avg_net_by_day": 0.01 if ideas else None}
    return {"summaries": {"brain_trade": {**row, "edge_vs_every_stock": 0.002}, "every_stock": dict(row), "nifty": nifty},
            "sessions": 2, "gate": {"word": "too early"}}


def test_missing_nifty_prices_are_reported():
    momentum = {"ideas": 3, "avg_net": 0.0, "hit_rate": 0.3, "days": 1, "avg_net_by_day": 0.0}
    f = o.journal_figures(_journal(), None, momentum)
    assert f["nifty"]["available"] is False and "NIFTY" in f["nifty"]["why"]
    assert f["brain_trade"]["available"] is True and f["brain_trade"]["source"] == o.SOURCES["net_after_costs"]
    assert f["momentum"]["available"] is True and "brain looked at" in f["momentum"]["source"]
    assert "not the evidence-defs-v1" in f["nifty"]["source"]


def test_zero_finished_ideas_is_unavailable_not_zero():
    empty = {"ideas": 0, "avg_net": None, "hit_rate": None, "days": 0, "avg_net_by_day": None}
    f = o.journal_figures(_journal(ideas=0, nifty={"finished": 0, "open": 3, "avg": None}), None, empty)
    assert all(f[k]["available"] is False for k in ("brain_trade", "every_stock", "momentum", "nifty"))


def test_forward_trial_never_says_proven():
    for gate_word in ("too early", "pass", "behind"):
        assert o.forward_trial({"gate": {"word": gate_word}, "sessions": 20}, None)["word"] != "Proven"
    assert o.forward_trial({"gate": {"word": "pass"}, "sessions": 20}, None)["word"] == "Forward gate (not frozen): pass"


def test_momentum_picks_the_five_strongest_of_the_days_pool():
    from swing_trade_ml.brain.trial_journal import Idea, Session

    days = list(pd.bdate_range("2026-08-03", periods=60).date)
    bars = {}
    for k in range(7):  # stock k rises k% a day: OBS6 strongest, OBS0 flat
        closes = [100 * (1 + k / 100) ** i for i in range(60)]
        bars[f"OBS{k}"] = pd.DataFrame({"day": days, "open": closes, "high": [c * 1.001 for c in closes],
                                        "low": [c * 0.999 for c in closes], "close": closes})
    day = days[30]
    session = Session(day=day, banner="NORMAL", ideas=tuple(Idea(symbol=f"OBS{k}", word="WAIT", score=None) for k in range(7)))
    m = o.momentum_summary([session], bars)
    assert m["picked"] == {day.isoformat(): ["OBS6", "OBS5", "OBS4", "OBS3", "OBS2"]}


def test_category_is_required_and_validated(db_session):
    with pytest.raises(ValueError):
        o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "everything")
    paper = o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "paper")
    assert paper["category"] == "paper" and paper["available"] is False


def test_categories_are_never_summed(monkeypatch, db_session):
    seen = []
    monkeypatch.setattr(o.queries, "stored_grade_rows", lambda db, s, e, live: seen.append(live) or [])
    monkeypatch.setattr(o, "_journal", lambda db, s, e, live: (None, None, "skipped in test"))
    a = o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "practice")
    b = o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "backtest")
    assert seen == [True, False]
    assert a["category"] == "practice" and b["category"] == "backtest"


def test_sources_name_their_code():
    assert "m09_learn/outcomes.py" in o.SOURCES["stored_grade"]
    assert "services/costs.py" in o.SOURCES["costs"] and "bx5" in o.SOURCES["costs"]
```

Before running, check that the `Idea` / `Session` dataclass fields in `brain/trial_journal.py` (lines
55–70) match the test (`symbol`, `word`, `score`; `day`, `banner`, `ideas`). Adjust the **test** to the
real field names if they differ. Do not change `trial_journal.py`.

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `outcomes.py`**

```python
"""Finished brain-idea results: THE one read-only function for them (spec addendum 13; evidence plan A3).

Two kinds of figure, never mixed:
- stored M09 grades (a record: gross, entry at the decision day's close), and
- figures computed now from stored prices (next-day open, half out, costs) with baselines.
The category (practice / backtest / paper) is required and never mixed. Missing data is 'not available'
with the reason, never zero.
"""

from __future__ import annotations

from datetime import date, timedelta

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.brain_observatory import queries

CATEGORIES = ("practice", "backtest", "paper")
TOP_MOMENTUM = 5
SOURCES = {
    "stored_grade": "M09 grade stored on each idea (brain/modules/m09_learn/outcomes.py): entry at the decision "
    "day's close, +8% target / -4% stop within 15 trading days, a day touching both counts as the stop. "
    "Gross: no costs, no slippage, no half-out.",
    "net_after_costs": "Computed now from stored daily prices (walk_forward.outcomes_for -> "
    "replay_scoring.strict_score): next-day open entry, +8% / -4%, half out at +5%, 15 trading days, "
    "slippage and charges from services/costs.py. Not a stored record.",
    "every_stock": "Every stock the brain looked at that day, same rule and costs (a random pick's expected "
    "result). Computed now.",
    "momentum": "The 5 stocks with the highest 20-day return at the decision close (walk_forward.momentum_scores), "
    "chosen from the stocks the brain looked at that day; same rule and costs. Computed now.",
    "nifty": "NIFTY 50 bought at the open after each session, sold at the close of the 15th session, from stored "
    "index prices, no costs (trial journal definition). This is not the evidence-defs-v1 matched NIFTY "
    "(per idea, with costs), which comes with evidence plan A4.",
    "cash": "Cash: 0%.",
    "costs": f"services/costs.py: slippage {settings.PAPER_SLIPPAGE_BPS} bps per side, brokerage "
    f"Rs {settings.PAPER_BROKERAGE_PER_ORDER} per order, statutory charges per side, a flat depository fee on "
    "sells. Not yet checked against real Zerodha contract notes (tracker task bx5).",
}
FORWARD_INSUFFICIENT = "Insufficient evidence"


def stored_grades(rows: list[tuple[str, float | None]]) -> dict:
    graded = [(o, r) for o, r in rows if o and o != "noscore"]
    if not graded:
        return {"available": False, "why": "No finished, graded ideas in these days.", "count": 0,
                "by_outcome": {}, "avg_gross_return": None, "source": SOURCES["stored_grade"]}
    by: dict[str, int] = {}
    for o, _ in graded:
        by[o] = by.get(o, 0) + 1
    returns = [r for _, r in graded if r is not None]
    return {"available": True, "count": len(graded), "by_outcome": by,
            "avg_gross_return": sum(returns) / len(returns) if returns else None, "source": SOURCES["stored_grade"]}


def _unavailable(why: str, source: str) -> dict:
    return {"available": False, "why": why, "source": source}


def _row(row: dict | None, source: str) -> dict:
    if row and row.get("ideas"):
        return {"available": True, "source": source, **row}
    return _unavailable("No finished ideas yet in these days.", source)


def journal_figures(journal: dict | None, error: str | None, momentum: dict | None) -> dict:
    out: dict = {"costs": SOURCES["costs"], "cash": {"available": True, "avg_net": 0.0, "source": SOURCES["cash"]}}
    if journal is None:
        why = f"The figures could not be computed: {error}"
        for key in ("brain_trade", "every_stock", "momentum", "nifty"):
            out[key] = _unavailable(why, SOURCES["net_after_costs" if key == "brain_trade" else key])
        return out
    out["brain_trade"] = _row(journal["summaries"].get("brain_trade"), SOURCES["net_after_costs"])
    out["every_stock"] = _row(journal["summaries"].get("every_stock"), SOURCES["every_stock"])
    out["momentum"] = _row(momentum, SOURCES["momentum"])
    nifty = journal["summaries"].get("nifty")
    if nifty is None:
        out["nifty"] = _unavailable("No NIFTY 50 prices are stored for these days.", SOURCES["nifty"])
    elif not nifty.get("finished"):
        out["nifty"] = _unavailable("No session has had 15 trading days yet.", SOURCES["nifty"])
    else:
        out["nifty"] = {"available": True, "source": SOURCES["nifty"], **nifty}
    return out


def momentum_summary(sessions, bars) -> dict:
    from swing_trade_ml.brain.horizon_grid import summarise
    from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, STOP, TARGET
    from swing_trade_ml.brain.walk_forward import momentum_scores, outcomes_for

    days = [s.day for s in sessions]
    scores = momentum_scores(bars, days)
    outs = outcomes_for(bars, days, HORIZON_BARS, TARGET, STOP)
    picked: dict[str, list[str]] = {}
    grouped = {}
    for s in sessions:
        pool = [i.symbol for i in s.ideas if s.day in scores.get(i.symbol, {})]
        top = sorted(pool, key=lambda sym: scores[sym][s.day], reverse=True)[:TOP_MOMENTUM]
        picked[s.day.isoformat()] = top
        grouped[s.day] = [outs[(sym, s.day)] for sym in top if (sym, s.day) in outs]
    return {**summarise(grouped), "picked": picked}


def forward_trial(journal: dict | None, error: str | None) -> dict:
    if journal is None:
        return {"word": FORWARD_INSUFFICIENT, "why": f"The figures could not be computed: {error}"}
    gate = journal["gate"]["word"]
    if gate == "too early":
        return {"word": FORWARD_INSUFFICIENT, "why": "Fewer than 15 sessions or 30 finished TRADE ideas."}
    return {"word": f"Forward gate (not frozen): {gate}",
            "why": "The forward gate (layer-2 draft 5a) is adopted for now but is not a frozen protocol, so it can never show Proven."}


def _journal(db, start: date, end: date, live: bool):
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.trial_journal import build_journal, gate, load_sessions

    try:
        sessions = load_sessions(db, start, end, live=live)
        symbols = sorted({i.symbol for s in sessions for i in s.ideas})
        upto = end + timedelta(days=60)  # ideas from the last session need about 15 more sessions
        bars = load_bars(db, symbols, upto)
        index = settings.BENCHMARK_INDEX_SYMBOL
        journal = build_journal(sessions, bars, {}, index_bars=load_bars(db, [index], upto).get(index))
        journal["gate"] = gate(journal)
        return journal, momentum_summary(sessions, bars), None
    except Exception as exc:  # noqa: BLE001 — shown to the owner as 'not available', never hidden
        return None, None, f"{type(exc).__name__}: {exc}"


def build(db, start: date, end: date, category: str) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    if category == "paper":
        return {"category": "paper", "available": False, "label": "Observed, not proof",
                "why": "v1 paper trades are not brain decisions; they are not shown in Phase 1A and are never added to brain results."}
    live = category == "practice"
    grades = stored_grades(queries.stored_grade_rows(db, start, end, live))
    journal, momentum, error = _journal(db, start, end, live)
    forward = forward_trial(journal, error) if live else {
        "word": FORWARD_INSUFFICIENT, "why": "The forward gate counts live practice ideas only."}
    return {"category": category, "available": True, "stored_grades": grades,
            "computed": journal_figures(journal, error, momentum), "forward_trial": forward,
            "label": "Observed, not proof"}
```

- [ ] **Step 4: Run, expect PASS** (11 passed). `test_category_is_required_and_validated` uses
  `db_session` only for the `paper` branch, which reads nothing.

- [ ] **Step 5: Format, commit** ("Brain Observatory: one outcomes function, category required, sources
  and honest gaps"). Include `queries.py` from Task 8 Step 2 in this commit, since Task 7 depends on it.

---

### Task 8: Queries, counts and the API (R3, spec 3.1, 3.3, 3.5)

> **Plan rev 2:** apply C3 (cursor, whole-day nightly), C6 (book/mode separation), C7 (no truncation), C5 (`/forward-gate`); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_observatory/queries.py`
- Create: `backend/src/swing_trade_ml/services/brain_observatory/counts.py`
- Create: `backend/src/swing_trade_ml/api/v1/endpoints/brain_observatory.py`
- Modify: `backend/src/swing_trade_ml/api/v1/router.py` (imports block and after line 64)
- Test: `backend/tests/test_brain_observatory_api.py`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces:
  - Routes, all `GET /api/v1/brain/observatory/...`:

    | Route | Parameters |
    |---|---|
    | `/days` | `from`, `to` |
    | `/runs` | `date`, `after_started_at?`, `after_id?`, `limit` |
    | `/runs/{run_id}` | |
    | `/runs/{run_id}/stocks` | `after_id?`, `limit`, `symbol?` |
    | `/runs/{run_id}/stocks/{decision_id}` | |
    | `/learning` | `from`, `to` |
    | `/outcomes` | `from`, `to` |
    | `/effectiveness` | |

  - `counts.idea_relation(universe: int | None, ideas: int, holdings: int) -> dict`
  - `counts.word_counts(rows: list[tuple[str, str, int]]) -> dict`
  - `queries.*` as below
  - Constants: `RECORDING_CARD = "Existing records only — partial visibility."`,
    `NOT_RECORDED_1A = "Not recorded in Phase 1A"`,
    `DEFERRED = "Not recorded — decision-path recording deferred during trial"`

- [ ] **Step 1: Write `counts.py`**

```python
"""Day counts and the only checkable relation between universe size and idea decisions (spec 3.1, C3).

M08 makes an idea for each universe stock not held, and a holding decision for each held stock (which may
be outside the universe). Runs store neither list, so only universe - holdings <= ideas <= universe can be
checked; inside it nothing is claimed.
"""

from __future__ import annotations


def idea_relation(universe: int | None, ideas: int, holdings: int) -> dict:
    if universe is None:
        return {"state": "not_observed", "why": "This run stored no universe size.", "ideas": ideas, "holdings": holdings}
    low = max(universe - holdings, 0)
    ok = low <= ideas <= universe
    return {"state": "within_range" if ok else "conflicting", "universe": universe, "ideas": ideas,
            "holdings": holdings, "allowed": [low, universe]}


def word_counts(rows: list[tuple[str, str, int]]) -> dict:
    out: dict[str, dict[str, int]] = {"idea": {}, "holding": {}}
    for kind, word, n in rows:
        out.setdefault(kind, {})[word] = n
    out["ideas_total"] = sum(out["idea"].values())
    out["holdings_total"] = sum(out["holding"].values())
    return out
```

- [ ] **Step 2: Write `queries.py`** (each function is one statement; batched over days)

```python
"""Every database read the Observatory makes. Each function issues one bounded statement; nothing writes."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import (
    BrainAlert, BrainDecision, BrainLearningRun, BrainProposal, BrainRun, BrainTrack, FeatureSnapshot,
)
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Signal, Strategy
from swing_trade_ml.services.brain_observatory.schedule import day_window

PAGE_MAX = 500


def runs_between(db: Session, start: date, end: date) -> list[BrainRun]:
    lo, _ = day_window(start)
    _, hi = day_window(end)
    return list(db.scalars(select(BrainRun).where(BrainRun.as_of >= lo, BrainRun.as_of < hi)
                           .order_by(BrainRun.started_at, BrainRun.id).limit(PAGE_MAX * 40)))


def runs_on(db: Session, day: date, after: tuple[datetime, str] | None, limit: int) -> list[BrainRun]:
    lo, hi = day_window(day)
    q = select(BrainRun).where(BrainRun.as_of >= lo, BrainRun.as_of < hi)
    if after is not None:
        q = q.where((BrainRun.started_at, BrainRun.id) > after)
    return list(db.scalars(q.order_by(BrainRun.started_at, BrainRun.id).limit(limit + 1)))


def run(db: Session, run_id: str) -> BrainRun | None:
    return db.get(BrainRun, run_id)


def word_rows(db: Session, run_ids: list[str]) -> list[tuple[str, str, str, int]]:
    if not run_ids:
        return []
    return list(db.execute(select(BrainDecision.run_id, BrainDecision.kind, BrainDecision.word, func.count())
                           .where(BrainDecision.run_id.in_(run_ids))
                           .group_by(BrainDecision.run_id, BrainDecision.kind, BrainDecision.word)).all())


def decisions(db: Session, run_id: str, after_id: int | None, limit: int, symbol: str | None) -> list[BrainDecision]:
    q = select(BrainDecision).where(BrainDecision.run_id == run_id)
    if after_id is not None:
        q = q.where(BrainDecision.id > after_id)
    if symbol:
        q = q.where(BrainDecision.symbol == symbol.upper())
    return list(db.scalars(q.order_by(BrainDecision.id).limit(limit + 1)))


def decision(db: Session, decision_id: int) -> BrainDecision | None:
    return db.get(BrainDecision, decision_id)


def snapshot_for_run(db: Session, run_id: str, symbol: str) -> FeatureSnapshot | None:
    return db.scalars(select(FeatureSnapshot).where(FeatureSnapshot.run_id == run_id,
                                                    FeatureSnapshot.symbol == symbol)).first()


def instruments(db: Session, symbol: str) -> list[Instrument]:
    return list(db.scalars(select(Instrument).where(Instrument.tradingsymbol == symbol).limit(10)))


def track_rows(db: Session, symbol: str, day: date) -> list[BrainTrack]:
    return list(db.scalars(select(BrainTrack).where(BrainTrack.symbol == symbol, BrainTrack.day == day).limit(10)))


def alerts_sent(db: Session, run_id: str) -> int:
    return db.scalar(select(func.count()).select_from(BrainAlert).where(BrainAlert.run_id == run_id)) or 0


def tracked_by_day(db: Session, start: date, end: date) -> dict[date, int]:
    rows = db.execute(select(BrainTrack.day, func.count()).where(BrainTrack.day >= start, BrainTrack.day <= end)
                      .group_by(BrainTrack.day)).all()
    return dict(rows)


def brain_signals_by_day(db: Session, start: date, end: date) -> dict[date, int]:
    lo, _ = day_window(start)
    _, hi = day_window(end)
    day = func.date(func.timezone("Asia/Kolkata", Signal.generated_at))
    rows = db.execute(select(day, func.count()).join(Strategy, Strategy.id == Signal.strategy_id)
                      .where(Strategy.strategy_type == "brain", Signal.generated_at >= lo, Signal.generated_at < hi)
                      .group_by(day)).all()
    return dict(rows)


def brain_orders_by_day(db: Session, start: date, end: date) -> dict[date, int]:
    lo, _ = day_window(start)
    _, hi = day_window(end)
    day = func.date(func.timezone("Asia/Kolkata", Order.placed_at))
    rows = db.execute(select(day, func.count()).join(Strategy, Strategy.id == Order.strategy_id)
                      .where(Strategy.strategy_type == "brain", Order.placed_at >= lo, Order.placed_at < hi)
                      .group_by(day)).all()
    return dict(rows)


def stage_on(db: Session, day: date) -> str | None:
    _, hi = day_window(day)
    return db.scalar(select(BrainStageChange.stage).where(BrainStageChange.changed_at < hi)
                     .order_by(BrainStageChange.changed_at.desc()).limit(1))


def stored_grade_rows(db: Session, start: date, end: date, live: bool) -> list[tuple[str, float | None]]:
    lo, _ = day_window(start)
    _, hi = day_window(end)
    return list(db.execute(select(BrainDecision.outcome, BrainDecision.outcome_return)
                           .join(BrainRun, BrainRun.id == BrainDecision.run_id)
                           .where(BrainDecision.kind == "idea", BrainDecision.outcome.is_not(None),
                                  BrainRun.kind == "nightly", BrainRun.live.is_(live), BrainRun.status == "done",
                                  BrainRun.as_of >= lo, BrainRun.as_of < hi)).all())


def learning_summary(db: Session, start: date, end: date) -> dict:
    graded = db.scalar(select(func.count()).select_from(BrainDecision).where(
        BrainDecision.resolved_on >= start, BrainDecision.resolved_on <= end,
        BrainDecision.outcome.is_not(None), BrainDecision.outcome != "noscore")) or 0
    lo, _ = day_window(start)
    _, hi = day_window(end)
    proposals = dict(db.execute(select(BrainProposal.status, func.count()).where(
        BrainProposal.created_at >= lo, BrainProposal.created_at < hi).group_by(BrainProposal.status)).all())
    learning_runs = db.scalar(select(func.count()).select_from(BrainLearningRun).where(
        BrainLearningRun.created_at >= lo, BrainLearningRun.created_at < hi)) or 0
    return {"results_collected": graded, "changes_proposed": proposals, "learning_checks": learning_runs}
```

Notes:
- `Order.strategy_id` is nullable; the join drops orders without a strategy, as intended.
- If `func.timezone` fails on a TimescaleDB column type, use `(Signal.generated_at.op("AT TIME ZONE")("Asia/Kolkata"))`
  instead.

- [ ] **Step 3: Write the failing API tests**

```python
"""Spec 3.3 / 3.5 / R3: the Observatory API, owner-only, GET-only, bounded, read-only, honest."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from observatory_fixtures import RUN_PREFIX, committed, make_decision, make_run, obs_clean  # noqa: F401
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainModuleSetting, FeatureSnapshot
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.session import engine

OWNER = {"X-API-Key": "test-api-key"}
BASE = "/api/v1/brain/observatory"
THU = date(2026, 10, 15)
AS_OF = datetime(2026, 10, 15, 10, 20, tzinfo=UTC)  # 15:50 IST
TRACE = [
    {"step": "perceive", "module_id": "M01", "status": "used", "reason": "", "ms": 5, "version": "1"},
    {"step": "reason", "module_id": "M06", "status": "shadow", "reason": "recorded, not used", "ms": 9, "version": "1"},
]


@pytest.fixture()
def now_after_deadline():
    from swing_trade_ml.api.v1.endpoints import brain_observatory as ep
    from swing_trade_ml.main import app

    app.dependency_overrides[ep.get_now] = lambda: datetime(2026, 10, 15, 18, 0, tzinfo=ep.IST)
    yield
    app.dependency_overrides.pop(ep.get_now, None)


def seed(**run_kw):
    run = make_run("n1", as_of=AS_OF, modules={"M01": "on", "M06": "shadow"}, trace=TRACE,
                   context={"data_manifest": {"universe_count": 3}, "sectors": []},
                   quality={"overall": {"score": 1.0, "fresh": True, "issues": []}, "stale": ["OBSXB"]}, **run_kw)
    return (
        run,
        make_decision("n1", "OBSXA", word="TRADE", reasons=["Model score 70% clears 60%."]),
        make_decision("n1", "OBSXB", word="WAIT", reasons=["error: token=abc123"], downgraded_from="TRADE",
                      downgrade_reason="Sector is weak."),
        make_decision("n1", "OBSXA", kind="holding", word="HOLD"),
        FeatureSnapshot(symbol="OBSXA", bar_date=THU, feature_set_version="v1", run_id=f"{RUN_PREFIX}n1",
                        close=100.0, atr_14=2.0, adv_inr_20=1e8, features={"rsi": 55}),
    )


def test_non_owner_is_refused_on_every_route(client, db_session, obs_clean):
    user = User(username="obs-guest", hashed_password="x", is_active=True, is_superuser=False, plan="free")
    db_session.add(user)
    db_session.flush()
    guest = {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}
    for path in ("/days?from=2026-10-15&to=2026-10-15", "/runs?date=2026-10-15", "/runs/x", "/runs/x/stocks",
                 "/runs/x/stocks/1", "/learning?from=2026-10-15&to=2026-10-15",
                 "/outcomes?from=2026-10-15&to=2026-10-15&category=practice", "/effectiveness"):
        assert client.get(BASE + path, headers=guest).status_code == 403, path


def test_only_get_routes_exist():
    from swing_trade_ml.api.v1.endpoints.brain_observatory import router

    assert {m for r in router.routes for m in r.methods} == {"GET"}


def test_range_over_92_days_is_refused(client, obs_clean):
    assert client.get(f"{BASE}/days?from=2026-01-01&to=2026-04-04", headers=OWNER).status_code == 422


def test_run_detail_recording_card_and_health(client, obs_clean, now_after_deadline):
    with committed(*seed()):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}n1", headers=OWNER).json()
    assert body["recording"]["card"] == "Existing records only — partial visibility."
    assert "decision path" in " ".join(body["recording"]["not_recorded"]).lower()
    m06 = next(r for r in body["modules"] if r["module_id"] == "M06")
    assert m06["flags"]["executed"] and not m06["flags"]["used"]
    assert body["counts"]["used"] == 1 and body["counts"]["shadow"] == 1
    assert body["universe_relation"] == {"state": "within_range", "universe": 3, "ideas": 2, "holdings": 1, "allowed": [2, 3]}


def test_stock_detail_is_honest_and_redacted(client, obs_clean):
    rows = seed()
    with committed(*rows):
        listing = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?symbol=OBSXB", headers=OWNER).json()
        did = listing["items"][0]["id"]
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks/{did}", headers=OWNER).json()
    assert "abc123" not in str(body["decision"]["reasons"])
    assert body["redacted_fields"] == ["decision.reasons[0]"]
    assert body["decision"]["downgraded_from"] == "TRADE"
    assert body["influence"]["text"] == "Influence on this stock: Not recorded in Phase 1A."
    assert body["not_recorded"]["decision_path"] == "Not recorded — decision-path recording deferred during trial"
    assert body["not_recorded"]["opinions"] == "Not recorded in Phase 1A"
    assert body["stale"]["listed_stale"] is True
    assert body["features"]["state"] == "not_observed"  # the snapshot belongs to OBSXA


def test_symbol_as_idea_and_holding_lists_both(client, obs_clean):
    with committed(*seed()):
        items = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?symbol=OBSXA", headers=OWNER).json()["items"]
    assert sorted(i["kind"] for i in items) == ["holding", "idea"]


def test_foreign_decision_id_is_404(client, obs_clean):
    other = make_run("n2", as_of=AS_OF)
    with committed(*seed(), other, make_decision("n2", "OBSXC")):
        did = client.get(f"{BASE}/runs/{RUN_PREFIX}n2/stocks", headers=OWNER).json()["items"][0]["id"]
        assert client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks/{did}", headers=OWNER).status_code == 404


def test_paging_cursor_is_typed_and_stable(client, obs_clean):
    with committed(*seed()):
        p1 = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?limit=2", headers=OWNER).json()
        assert isinstance(p1["next_cursor"]["after_id"], int)
        p2 = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?limit=2&after_id={p1['next_cursor']['after_id']}",
                        headers=OWNER).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["next_cursor"] is None


def test_days_counts_and_missing_runs(client, obs_clean, now_after_deadline):
    with committed(*seed()):
        days = client.get(f"{BASE}/days?from=2026-10-14&to=2026-10-17", headers=OWNER).json()["days"]
    by = {d["day"]: d for d in days}
    assert by["2026-10-15"]["nightly"]["state"] == "observed"
    assert by["2026-10-15"]["counts"]["ideas_total"] == 2
    assert by["2026-10-14"]["nightly"]["state"] == "not_observed"
    assert by["2026-10-17"]["nightly"]["state"] == "not_applicable"  # Saturday
    assert by["2026-10-15"]["signals"]["label"] == "not linked to a specific run"


def test_day_with_no_runs(client, obs_clean, now_after_deadline):
    r = client.get(f"{BASE}/runs?date=2026-10-17", headers=OWNER)
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["nightly"]["state"] == "not_applicable"


def test_old_run_without_context(client, obs_clean):
    with committed(make_run("old", as_of=AS_OF, context=None, modules={}, trace=[])):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}old", headers=OWNER).json()
    assert body["universe_relation"]["state"] == "not_observed"
    assert body["sectors"]["state"] == "not_observed"


def test_failed_run_error_is_redacted(client, obs_clean):
    with committed(make_run("bad", as_of=AS_OF, status="failed", error="OperationalError postgresql://u:pw123@db/x")):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}bad", headers=OWNER).json()
    assert body["headline"] == "failed" and "pw123" not in body["run"]["error"]


def test_symbol_on_two_exchanges(client, obs_clean):
    rows = (*seed(),
            Instrument(instrument_token=990001, tradingsymbol="OBSXA", exchange="NSE"),
            Instrument(instrument_token=990002, tradingsymbol="OBSXA", exchange="BSE"))
    with committed(*rows):
        did = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?symbol=OBSXA", headers=OWNER).json()["items"][0]["id"]
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks/{did}", headers=OWNER).json()
    assert sorted(i["exchange"] for i in body["instrument"]["current"]) == ["BSE", "NSE"]
    assert body["instrument"]["label"].startswith("current instrument master")


def test_effectiveness_route(client, obs_clean):
    claims = {c["claim"]: c for c in client.get(f"{BASE}/effectiveness", headers=OWNER).json()["claims"]}
    assert claims["model_ranking_predictive"]["word"] == "Not proven"
    assert claims["full_brain"]["word"] == "No frozen protocol yet"


def test_statement_count_is_bounded(client, obs_clean, now_after_deadline):
    counter = {"n": 0}

    def count(*_a, **_k):
        counter["n"] += 1

    with committed(*seed()):
        event.listen(engine, "before_cursor_execute", count)
        try:
            for path in (f"/runs/{RUN_PREFIX}n1", f"/runs/{RUN_PREFIX}n1/stocks", "/days?from=2026-08-01&to=2026-10-31",
                         "/runs?date=2026-10-15", "/effectiveness", "/learning?from=2026-08-01&to=2026-10-31"):
                counter["n"] = 0
                assert client.get(BASE + path, headers=OWNER).status_code == 200
                assert counter["n"] <= 12, (path, counter["n"])
        finally:
            event.remove(engine, "before_cursor_execute", count)


def test_a_write_attempt_through_a_route_is_refused(client, obs_clean, monkeypatch):
    from swing_trade_ml.services.brain_observatory import queries

    def sneaky(db, *a, **k):
        db.execute(text("INSERT INTO brain_modules (module_id, mode) VALUES ('OBSR', 'on')"))
        return []

    monkeypatch.setattr(queries, "runs_on", sneaky)
    with pytest.raises(DBAPIError, match="read-only"):
        client.get(f"{BASE}/runs?date=2026-10-15", headers=OWNER)
    with Session(engine) as check:
        assert check.get(BrainModuleSetting, "OBSR") is None
```

- [ ] **Step 4: Run, expect FAIL** (404s and the import error)

- [ ] **Step 5: Implement the endpoint module**

`backend/src/swing_trade_ml/api/v1/endpoints/brain_observatory.py`:

```python
"""Brain Observatory, Phase 1A (spec docs/superpowers/specs/2026-10-15-brain-observatory-design.md).

Owner only, GET only. Every request reads through its own READ ONLY, time-limited transaction
(services/brain_observatory/db.py) and every response passes through the free-text redaction.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from swing_trade_ml.api.deps import require_owner
from swing_trade_ml.core.config import settings
from swing_trade_ml.services.brain_observatory import counts, health, outcomes, queries, schedule, verdicts
from swing_trade_ml.services.brain_observatory.db import get_readonly_db
from swing_trade_ml.services.brain_observatory.redact import redact_response

IST = schedule.IST
MAX_DAYS = 92
RECORDING_CARD = "Existing records only — partial visibility."
NOT_RECORDED_1A = "Not recorded in Phase 1A"
DEFERRED = "Not recorded — decision-path recording deferred during trial"
NOT_RECORDED_LIST = [
    "Each module's opinion on each stock, including shadow modules",
    "The risk verdict per stock",
    "The sector and rank used for each stock",
    "The decision path: which rule or module changed a decision (deferred during the trial)",
    "Code, model and settings versions of each run",
]


def _brain_on() -> None:
    if not settings.BRAIN_ENABLED:
        raise HTTPException(404, "Not Found")


def get_now() -> datetime:
    return datetime.now(IST)


ReadOnlyDb = Annotated[Session, Depends(get_readonly_db)]
Now = Annotated[datetime, Depends(get_now)]
router = APIRouter(prefix="/brain/observatory", tags=["brain-observatory"],
                   dependencies=[Depends(_brain_on), Depends(require_owner)])


def _range(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(422, "'to' must be on or after 'from'.")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"Ask for at most {MAX_DAYS} days at a time.")


def _run_summary(r) -> dict:
    return {"id": r.id, "kind": r.kind, "live": r.live, "status": r.status, "book": r.book,
            "as_of": r.as_of.isoformat(), "day": schedule.run_day(r.as_of).isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "ms": r.ms, "error": r.error}


def _brief(r) -> dict:
    return {"id": r.id, "kind": r.kind, "live": r.live, "status": r.status}


@router.get("/days")
def days(db: ReadOnlyDb, now: Now, start: date = Query(..., alias="from"), end: date = Query(..., alias="to")) -> dict:
    _range(start, end)
    runs = queries.runs_between(db, start, end)
    by_day: dict[date, list] = {}
    for r in runs:
        by_day.setdefault(schedule.run_day(r.as_of), []).append(r)
    nightly_ids = {}
    for d, rs in by_day.items():
        state = schedule.nightly_state(d, now, [_brief(r) for r in rs])
        if state["state"] == "observed":
            nightly_ids[d] = state["run_id"]
    words: dict[str, list] = {}
    for run_id, kind, word, n in queries.word_rows(db, list(nightly_ids.values())):
        words.setdefault(run_id, []).append((kind, word, n))
    tracked = queries.tracked_by_day(db, start, end)
    signals = queries.brain_signals_by_day(db, start, end)
    orders = queries.brain_orders_by_day(db, start, end)
    out = []
    d = start
    while d <= end:
        rs = by_day.get(d, [])
        nightly = schedule.nightly_state(d, now, [_brief(r) for r in rs])
        run_id = nightly.get("run_id")
        out.append({
            "day": d.isoformat(),
            "nightly": nightly,
            "counts": counts.word_counts(words.get(run_id, [])) if run_id else None,
            "intraday": {**schedule.intraday_expectation(d, now),
                         "recorded": sum(1 for r in rs if r.kind == "intraday")},
            "tracked": {"count": tracked.get(d, 0), "label": "day-level context, not linked to a run"},
            "signals": {"count": signals.get(d, 0), "label": "not linked to a specific run"},
            "paper_orders": {"count": orders.get(d, 0), "label": "not linked to a specific run"},
            "other_runs": [_brief(r) for r in rs if r.id != run_id],
        })
        d = date.fromordinal(d.toordinal() + 1)
    return redact_response({"days": out})


@router.get("/runs")
def runs(db: ReadOnlyDb, now: Now, day: date = Query(..., alias="date"), after_started_at: datetime | None = None,
         after_id: str | None = None, limit: int = Query(200, ge=1, le=queries.PAGE_MAX)) -> dict:
    after = (after_started_at, after_id) if after_started_at and after_id else None
    rows = queries.runs_on(db, day, after, limit)
    page, more = rows[:limit], len(rows) > limit
    last = page[-1] if page else None
    return redact_response({
        "date": day.isoformat(),
        "nightly": schedule.nightly_state(day, now, [_brief(r) for r in page]),
        "intraday": schedule.intraday_expectation(day, now),
        "items": [_run_summary(r) for r in page],
        "next_cursor": {"after_started_at": last.started_at.isoformat(), "after_id": last.id} if more and last else None,
    })


@router.get("/runs/{run_id}")
def run_detail(run_id: str, db: ReadOnlyDb) -> dict:
    r = queries.run(db, run_id)
    if r is None:
        raise HTTPException(404, "No such run.")
    rows = health.module_rows(r.kind, r.modules, r.trace, health.current_step_map())
    fallbacks = health.step_fallbacks(r.trace)
    wc = counts.word_counts([(k, w, n) for _, k, w, n in queries.word_rows(db, [r.id])])
    ctx = r.context or {}
    manifest = ctx.get("data_manifest") or {}
    return redact_response({
        "run": _run_summary(r),
        "headline": health.headline(r.status, rows, fallbacks),
        "banner": {"mode": r.banner_mode, "headline": r.banner_headline},
        "modules": rows,
        "counts": health.flag_counts(rows),
        "step_fallbacks": fallbacks,
        "outside_steps": health.outside_rows(r.kind, r.live, r.status, r.alerts_checked_at, queries.alerts_sent(db, r.id)),
        "stage_that_day": {"stage": queries.stage_on(db, schedule.run_day(r.as_of)), "label": "day context, not part of this run"},
        "words": wc,
        "universe_relation": counts.idea_relation(manifest.get("universe_count"), wc["ideas_total"], wc["holdings_total"]),
        "quality": r.quality or {"state": "not_observed"},
        "sectors": {"state": "observed", "items": ctx["sectors"]} if "sectors" in ctx else {"state": "not_observed"},
        "situations": ctx.get("situations", {"state": "not_observed"}),
        "data_manifest": manifest or {"state": "not_observed"},
        "recording": {"card": RECORDING_CARD, "phase": "1A", "not_recorded": NOT_RECORDED_LIST,
                      "versions": NOT_RECORDED_1A},
    })


def _decision_brief(d) -> dict:
    return {"id": d.id, "symbol": d.symbol, "kind": d.kind, "word": d.word, "confidence": d.confidence,
            "score_source": d.score_source}


@router.get("/runs/{run_id}/stocks")
def stocks(run_id: str, db: ReadOnlyDb, after_id: int | None = None,
           limit: int = Query(200, ge=1, le=queries.PAGE_MAX), symbol: str | None = None) -> dict:
    if queries.run(db, run_id) is None:
        raise HTTPException(404, "No such run.")
    rows = queries.decisions(db, run_id, after_id, limit, symbol)
    page, more = rows[:limit], len(rows) > limit
    return redact_response({"items": [_decision_brief(d) for d in page],
                            "next_cursor": {"after_id": page[-1].id} if more and page else None})


@router.get("/runs/{run_id}/stocks/{decision_id}")
def stock_detail(run_id: str, decision_id: int, db: ReadOnlyDb) -> dict:
    d = queries.decision(db, decision_id)
    r = queries.run(db, run_id)
    if d is None or r is None or d.run_id != run_id:
        raise HTTPException(404, "No such decision in this run.")
    snap = queries.snapshot_for_run(db, run_id, d.symbol)
    quality = r.quality or {}
    insts = queries.instruments(db, d.symbol)
    return redact_response({
        "decision": {
            **_decision_brief(d), "entry_low": d.entry_low, "entry_high": d.entry_high, "target": d.target,
            "stop": d.stop, "qty": d.qty, "horizon_days": d.horizon_days, "reasons": list(d.reasons or []),
            "evidence_text": d.evidence_text, "downgraded_from": d.downgraded_from,
            "downgrade_reason": d.downgrade_reason,
            "downgrade_label": "as stored: the word before any downgrade, and the last downgrade reason; not a path",
            "overrule": None if d.overruled_word is None else {
                "word": d.overruled_word, "overrule_reason": d.overrule_reason,
                "at": d.overruled_at.isoformat() if d.overruled_at else None, "by": "owner"},
            "outcome": None if d.outcome is None else {
                "outcome": d.outcome, "gross_return": d.outcome_return, "days": d.outcome_days, "max_up": d.max_up,
                "max_down": d.max_down, "resolved_on": d.resolved_on.isoformat() if d.resolved_on else None,
                "source": outcomes.SOURCES["stored_grade"]},
        },
        "features": {"state": "observed", "bar_date": snap.bar_date.isoformat(), "close": snap.close, "atr_14": snap.atr_14,
                     "adv_inr_20": snap.adv_inr_20, "features": snap.features} if snap
                    else {"state": "not_observed", "why": "No feature snapshot stored by this run for this stock."},
        "stale": {"listed_stale": d.symbol in quality.get("stale", []),
                  "note": "Not listed means fresh or not assessed."} if "stale" in quality else {"state": "not_observed"},
        "tracker": {"label": "tracker records for this stock on this day: day-level context, not linked to this run",
                    "rows": [{"day": t.day.isoformat(), "day_n": t.day_n, "ret": t.ret, "status": t.status, "reason": t.reason}
                             for t in queries.track_rows(db, d.symbol, schedule.run_day(r.as_of))]},
        "instrument": {"label": "current instrument master, not recorded by the run",
                       "current": [{"exchange": i.exchange, "instrument_token": i.instrument_token} for i in insts]},
        "influence": {"state": "not_recorded_1a", "text": "Influence on this stock: Not recorded in Phase 1A."},
        "not_recorded": {"opinions": NOT_RECORDED_1A, "risk_verdict": NOT_RECORDED_1A, "stock_state": NOT_RECORDED_1A,
                         "sector_used": NOT_RECORDED_1A, "decision_path": DEFERRED, "why_no_trade": DEFERRED},
    })


@router.get("/learning")
def learning(db: ReadOnlyDb, start: date = Query(..., alias="from"), end: date = Query(..., alias="to")) -> dict:
    _range(start, end)
    claims = {c["claim"]: c for c in verdicts.evaluate(verdicts.load_registry())}
    return redact_response({**queries.learning_summary(db, start, end),
                            "proven_improvement": claims["learning_changes"],
                            "note": "Only M09 activity counts as learning: results collected, changes proposed, changes accepted."})


@router.get("/outcomes")
def outcomes_route(db: ReadOnlyDb, start: date = Query(..., alias="from"), end: date = Query(..., alias="to"),
                   category: str = Query(..., pattern="^(practice|backtest|paper)$")) -> dict:
    _range(start, end)
    return redact_response(outcomes.build(db, start, end, category))


@router.get("/effectiveness")
def effectiveness() -> dict:
    return redact_response({"claims": verdicts.evaluate(verdicts.load_registry())})
```

- [ ] **Step 6: Register the router**

In `backend/src/swing_trade_ml/api/v1/router.py`, add `brain_observatory,` to the endpoints import list
(alphabetically after `brain_golive,`). After line 64 add:

```python
api_router.include_router(brain_observatory.router, dependencies=protected)
```

- [ ] **Step 7: Run, expect PASS**

Run: `... -m pytest tests/test_brain_observatory_api.py -q`

If `test_statement_count_is_bounded` counts the read-only session's two `SET` statements, they are inside
the 12. If `/days` over 92 days exceeds 12, check that no per-day query slipped in; every per-day number
must come from the batched dicts.

- [ ] **Step 8: Run all Observatory tests and the existing brain API suites** (T1A-2 baseline)

Run: `... -m pytest tests/test_brain_observatory_*.py tests/test_brain_api.py tests/test_brain_console_api.py tests/test_brain_owner_only_writes.py -q`
Expected: all pass.

- [ ] **Step 9: Format, commit** ("Brain Observatory: read-only owner API (runs, stocks, days, learning,
  outcomes, effectiveness)")

---

### Task 9: No side effects beyond the database (spec 3.5; Postgres counters supplementary)

**Files:**
- Test: `backend/tests/test_brain_observatory_side_effects.py`

- [ ] **Step 1: Write the tests**

```python
"""Spec 3.5: calling every Observatory route runs no brain, queue, alert, broker or Telegram code, and writes
nothing. The database refusal (Task 1, Task 8) is the enforcement; these are extra checks."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from observatory_fixtures import committed, obs_clean  # noqa: F401
from swing_trade_ml.db.session import engine
from test_brain_observatory_api import AS_OF, BASE, OWNER, RUN_PREFIX, seed

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml" / "services" / "brain_observatory"
FORBIDDEN = ("swing_trade_ml.brain.service", "swing_trade_ml.brain.runner", "swing_trade_ml.brain.queue",
             "swing_trade_ml.brain.alerts", "swing_trade_ml.brokers", "swing_trade_ml.notifications", "redis")
PATHS = ("/days?from=2026-10-14&to=2026-10-15", "/runs?date=2026-10-15", f"/runs/{RUN_PREFIX}n1",
         f"/runs/{RUN_PREFIX}n1/stocks", "/learning?from=2026-10-01&to=2026-10-15",
         "/outcomes?from=2026-10-01&to=2026-10-15&category=practice", "/effectiveness")


def test_package_does_not_import_side_effect_modules_directly():
    for path in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not name.startswith(FORBIDDEN), f"{path.name} imports {name}"


def test_routes_never_call_side_effect_entry_points(client, obs_clean, monkeypatch):
    import swing_trade_ml.brain.alerts.service as alerts
    import swing_trade_ml.brain.queue as queue
    import swing_trade_ml.brain.runner as runner
    import swing_trade_ml.brain.service as service
    import swing_trade_ml.brokers as brokers
    from swing_trade_ml.notifications.telegram import TelegramNotifier

    def boom(*_a, **_k):
        raise AssertionError("side effect called")

    for mod, name in ((service, "run_brain"), (runner, "execute"), (queue, "request_run"), (queue, "process_next"),
                      (alerts, "send"), (brokers, "get_broker"), (TelegramNotifier, "send_sync")):
        monkeypatch.setattr(mod, name, boom)
    with committed(*seed()):
        for p in PATHS:
            assert client.get(BASE + p, headers=OWNER).status_code == 200, p


def _tuple_counters() -> dict:
    with Session(engine) as s:
        s.execute(text("SELECT pg_stat_clear_snapshot()"))
        rows = s.execute(text("SELECT relname, n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables")).all()
    return {r[0]: r[1:] for r in rows}


def test_supplementary_postgres_counters_do_not_move(client, obs_clean):
    """Supplementary only: statistics are reported asynchronously, so this cannot prove absence."""
    with committed(*seed()):
        before = _tuple_counters()
        for p in PATHS:
            client.get(BASE + p, headers=OWNER)
        after = _tuple_counters()
    moved = {t for t in before if after.get(t) != before[t] and not t.startswith(("brain_runs", "brain_decisions", "feature_snapshots"))}
    assert not moved, moved
```

The three fixture tables are excluded because the fixture's own cleanup may land in the counters. Any
other table that moves fails the test.

- [ ] **Step 2: Run, expect PASS** (the code under test already exists). If the tripwire test fails,
  the failure names the entry point; remove that call path from the package.

- [ ] **Step 3: Commit** ("Brain Observatory: side-effect tripwires and import guard")

---

### Task 10: Frontend page and owner-only menu entry (R3, spec 3.3)

> **Plan rev 2:** apply C5 (daily counts, learning, pagination, failure messages, error states); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:**
- Modify: `frontend/src/api/types.ts` (append), `frontend/src/api/client.ts` (inside `export const api = {`)
- Create: `frontend/src/trademind/pages/Observatory.tsx`
- Modify: `frontend/src/trademind/TradeMindApp.tsx` (`SECTIONS` Brain Logs pages, `visibleSections`, routes)

- [ ] **Step 1: Types** (append to `frontend/src/api/types.ts`)

```ts
// ---- Brain Observatory (Phase 1A, read-only) ----
export type ObsFlags = Record<
  'expected' | 'executed' | 'valid_output' | 'used' | 'shadow' | 'switched_off' | 'failed' | 'not_observed' |
    'not_applicable' | 'unknown_module' | 'duplicate' | 'conflicting',
  boolean
>
export interface ObsModuleRow {
  module_id: string
  step: string | null
  step_source: string | null
  mode_recorded: string | null
  statuses: string[]
  flags: ObsFlags
  inferred: Record<string, boolean>
  corroboration: 'corroborated' | 'single_source' | 'no_record' | 'conflicting'
  conflicts: string[]
  failure_messages: string[]
}
export interface ObsRunSummary {
  id: string; kind: string; live: boolean; status: string; book: string; as_of: string; day: string
  started_at: string | null; finished_at: string | null; ms: number; error: string | null
}
export interface ObsNightly { state: string; run_id?: string; run_ids?: string[]; expectation: string }
export interface ObsRuns {
  date: string; nightly: ObsNightly; intraday: Record<string, number | boolean>; items: ObsRunSummary[]
  next_cursor: { after_started_at: string; after_id: string } | null; redacted_fields: string[]
}
export interface ObsRunDetail {
  run: ObsRunSummary; headline: string; banner: { mode: string | null; headline: string | null }
  modules: ObsModuleRow[]; counts: Record<string, number | Record<string, number> | string[]>
  step_fallbacks: { step: string; reason: string }[]
  outside_steps: { module_id: string; state: string; detail: string }[]
  stage_that_day: { stage: string | null; label: string }
  words: { idea: Record<string, number>; holding: Record<string, number>; ideas_total: number; holdings_total: number }
  universe_relation: { state: string; universe?: number; ideas: number; holdings: number; allowed?: number[]; why?: string }
  recording: { card: string; phase: string; not_recorded: string[]; versions: string }
  redacted_fields: string[]
}
export interface ObsStockBrief { id: number; symbol: string; kind: string; word: string; confidence: number | null; score_source: string | null }
export interface ObsStocks { items: ObsStockBrief[]; next_cursor: { after_id: number } | null }
export interface ObsStockDetail {
  decision: ObsStockBrief & {
    entry_low: number | null; entry_high: number | null; target: number | null; stop: number | null; qty: number
    horizon_days: number; reasons: string[]; evidence_text: string | null; downgraded_from: string | null
    downgrade_reason: string | null; downgrade_label: string
    overrule: { word: string; overrule_reason: string | null; at: string | null; by: string } | null
    outcome: { outcome: string; gross_return: number | null; days: number | null; resolved_on: string | null; source: string } | null
  }
  features: { state: string; why?: string; close?: number; atr_14?: number | null; bar_date?: string }
  stale: { listed_stale?: boolean; note?: string; state?: string }
  tracker: { label: string; rows: { day: string; day_n: number; ret: number; status: string; reason: string }[] }
  instrument: { label: string; current: { exchange: string; instrument_token: number }[] }
  influence: { state: string; text: string }
  not_recorded: Record<string, string>
  redacted_fields: string[]
}
export interface ObsClaim {
  claim: string; label: string; word: string; numeric: string | null; independence: string | null
  independence_note: string; protocol_id: string | null; tested_subject: string | null
  numbers: Record<string, number | string> | null; problems: string[]
}
export interface ObsFigure { available: boolean; why?: string; source: string; ideas?: number; avg_net?: number | null; avg?: number | null }
export interface ObsOutcomes {
  category: 'practice' | 'backtest' | 'paper'
  stored_grades: { available: boolean; why?: string; count: number; avg_gross_return: number | null; source: string }
  computed: {
    brain_trade: ObsFigure; every_stock: ObsFigure; momentum: ObsFigure; nifty: ObsFigure; cash: ObsFigure; costs: string
  }
  forward_trial: { word: string; why: string }
  label: string
}
```

- [ ] **Step 2: Client calls** (add inside `export const api = {` and the type import list)

```ts
  // ---------------------------------------------- brain observatory (owner, read-only) --
  obsRuns: (date: string) => get<ObsRuns>(`/brain/observatory/runs?date=${date}`),
  obsRun: (runId: string) => get<ObsRunDetail>(`/brain/observatory/runs/${encodeURIComponent(runId)}`),
  obsStocks: (runId: string, symbol?: string, afterId?: number) =>
    get<ObsStocks>(
      `/brain/observatory/runs/${encodeURIComponent(runId)}/stocks?limit=500` +
        (symbol ? `&symbol=${encodeURIComponent(symbol.trim().toUpperCase())}` : '') +
        (afterId !== undefined ? `&after_id=${afterId}` : ''),
    ),
  obsStock: (runId: string, decisionId: number) =>
    get<ObsStockDetail>(`/brain/observatory/runs/${encodeURIComponent(runId)}/stocks/${decisionId}`),
  obsOutcomes: (from: string, to: string, category: 'practice' | 'backtest') =>
    get<ObsOutcomes>(`/brain/observatory/outcomes?from=${from}&to=${to}&category=${category}`),
  obsEffectiveness: () => get<{ claims: ObsClaim[] }>('/brain/observatory/effectiveness'),
```

- [ ] **Step 3: The page** (`frontend/src/trademind/pages/Observatory.tsx`)

```tsx
// Brain Observatory (Phase 1A): what the brain stored for a date, a run and a stock. Read-only, owner only.
// Three layers never mix: did it run / was it recorded / is it proven (spec section 0).
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { ObsModuleRow } from '../../api/types'
import { Card, Tabs } from '../ui'

const TABS = ['Decision flow', 'Module activity', 'Results & proof'] as const
type Tab = (typeof TABS)[number]
const FLAG_COLUMNS: (keyof ObsModuleRow['flags'])[] = [
  'expected', 'executed', 'valid_output', 'used', 'shadow', 'switched_off', 'failed', 'not_observed', 'not_applicable', 'conflicting',
]
const NIGHTLY_WORD: Record<string, string> = {
  observed: 'Ran', not_observed: 'Not observed', not_due: 'Not due yet', not_applicable: 'Not applicable (no trading)',
  conflicting: 'Conflicting records',
}

function todayIst(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())
}

function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? '—' : `${(x * 100).toFixed(2)}%`
}

function Redacted({ fields }: { fields: string[] }) {
  return fields.length ? <p className="tm-muted">Some text is hidden for safety ({fields.length}).</p> : null
}

export default function Observatory() {
  const [day, setDay] = useState(todayIst())
  const [runId, setRunId] = useState<string>('')
  const [symbol, setSymbol] = useState('')
  const [decisionId, setDecisionId] = useState<number | null>(null)
  const [tab, setTab] = useState<Tab>('Decision flow')

  const runs = useQuery({ queryKey: ['obs-runs', day], queryFn: () => api.obsRuns(day) })
  const chosenRun = runId || runs.data?.nightly.run_id || runs.data?.items[0]?.id || ''
  const run = useQuery({ queryKey: ['obs-run', chosenRun], queryFn: () => api.obsRun(chosenRun), enabled: !!chosenRun })
  const stocks = useQuery({
    queryKey: ['obs-stocks', chosenRun, symbol],
    queryFn: () => api.obsStocks(chosenRun, symbol || undefined),
    enabled: !!chosenRun,
  })
  const stock = useQuery({
    queryKey: ['obs-stock', chosenRun, decisionId],
    queryFn: () => api.obsStock(chosenRun, decisionId as number),
    enabled: !!chosenRun && decisionId !== null,
  })
  const proof = useQuery({ queryKey: ['obs-eff'], queryFn: api.obsEffectiveness })
  const results = useQuery({
    queryKey: ['obs-outcomes', day],
    queryFn: () => api.obsOutcomes(day.slice(0, 8) + '01', day, 'practice'),
    enabled: tab === 'Results & proof',
  })

  const r = run.data
  const ranking = proof.data?.claims.filter((c) => c.claim.startsWith('model_ranking')) ?? []
  const fullBrain = proof.data?.claims.find((c) => c.claim === 'full_brain')

  return (
    <div className="tm-page tm-grid">
      <Card title="Brain Observatory" sub="Owner only · Paper mode · Read-only">
        <div className="tm-row">
          <label>Date <input type="date" value={day} onChange={(e) => { setDay(e.target.value); setRunId(''); setDecisionId(null) }} /></label>
          <label>Run{' '}
            <select value={chosenRun} onChange={(e) => { setRunId(e.target.value); setDecisionId(null) }}>
              {(runs.data?.items ?? []).map((x) => (
                <option key={x.id} value={x.id}>{x.kind} · {x.status} · {x.started_at?.slice(11, 16)} UTC</option>
              ))}
            </select>
          </label>
          <label>Stock <input value={symbol} placeholder="e.g. INFY" onChange={(e) => { setSymbol(e.target.value); setDecisionId(null) }} /></label>
        </div>
        {runs.data && <p>Nightly run this day: <b>{NIGHTLY_WORD[runs.data.nightly.state] ?? runs.data.nightly.state}</b></p>}
      </Card>

      <div className="tm-grid tm-three">
        <Card title="1 / Did the brain run?" sub="Run health">
          {r ? (
            <>
              <h3>{r.headline === 'completed' ? 'Completed' : r.headline === 'degraded' ? 'Completed with problems' : r.headline}</h3>
              <p>{Math.round(r.run.ms / 1000)} s · {String(r.counts.used)} modules used · {String(r.counts.failed)} failed ·{' '}
                {String(r.counts.not_observed)} not observed (inferred)</p>
              {r.run.error && <p className="tm-bad">{r.run.error}</p>}
            </>
          ) : <p>{runs.isLoading || run.isLoading ? 'Loading…' : 'No run selected.'}</p>}
        </Card>
        <Card title="2 / Was it recorded?" sub="Recording health">
          <h3>{r?.recording.card ?? 'Existing records only — partial visibility.'}</h3>
          <ul>{(r?.recording.not_recorded ?? []).map((x) => <li key={x}>{x}</li>)}</ul>
          <p className="tm-muted">A complete record would still say nothing about whether decisions were good.</p>
        </Card>
        <Card title="3 / Is it proven to help?" sub="Effectiveness">
          {ranking.map((c) => <p key={c.claim}><b>{c.word}</b> — {c.label}</p>)}
          {fullBrain && <p><b>{fullBrain.word}</b> — {fullBrain.label}</p>}
          {ranking[0]?.independence_note && <p className="tm-muted">{ranking[0].independence_note}</p>}
        </Card>
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Decision flow' && (
        <div className="tm-grid tm-two">
          <Card title="Stocks in this run" sub="Stored final words">
            <ul>
              {(stocks.data?.items ?? []).map((s) => (
                <li key={s.id}>
                  <button type="button" onClick={() => setDecisionId(s.id)}>{s.symbol} · {s.kind} · <b>{s.word}</b></button>
                </li>
              ))}
            </ul>
          </Card>
          {stock.data ? (
            <Card title={`${stock.data.decision.symbol} · ${stock.data.decision.kind}`} sub="Stored final decision">
              <h3>{stock.data.decision.word}</h3>
              <h4>Reasons (stored text)</h4>
              <ul>{stock.data.decision.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
              {stock.data.decision.downgraded_from && (
                <p>Was {stock.data.decision.downgraded_from}; last downgrade reason: {stock.data.decision.downgrade_reason}
                  <br /><span className="tm-muted">{stock.data.decision.downgrade_label}</span></p>
              )}
              <h4>Recorded decision path</h4>
              <p className="tm-muted">{stock.data.not_recorded.decision_path}</p>
              <h4>Why no TRADE?</h4>
              <p className="tm-muted">{stock.data.not_recorded.why_no_trade}</p>
              <h4>Module opinions, risk verdict, sector used</h4>
              <p className="tm-muted">{stock.data.not_recorded.opinions}</p>
              <p className="tm-muted">{stock.data.influence.text}</p>
              <h4>Model inputs at decision time</h4>
              {stock.data.features.state === 'observed'
                ? <p>Close ₹{stock.data.features.close} on {stock.data.features.bar_date}</p>
                : <p className="tm-muted">Not observed — {stock.data.features.why}</p>}
              {stock.data.decision.outcome && (
                <p>Outcome: {stock.data.decision.outcome.outcome}, {pct(stock.data.decision.outcome.gross_return)} gross
                  <br /><span className="tm-muted">{stock.data.decision.outcome.source}</span></p>
              )}
              <p className="tm-muted">{stock.data.tracker.label}: {stock.data.tracker.rows.length} record(s)</p>
              <p className="tm-muted">{stock.data.instrument.label}: {stock.data.instrument.current.map((i) => i.exchange).join(', ') || 'none'}</p>
              <Redacted fields={stock.data.redacted_fields} />
            </Card>
          ) : <Card title="Pick a stock" sub="Choose one from the list" />}
        </div>
      )}

      {tab === 'Module activity' && r && (
        <Card title="Module activity" sub="Per run. Expected / not observed / not applicable are inferred from the current module list.">
          <table className="tm-table">
            <thead><tr><th>Module</th><th>Step</th>{FLAG_COLUMNS.map((f) => <th key={f}>{f.replace('_', ' ')}</th>)}<th>Records</th></tr></thead>
            <tbody>
              {r.modules.map((m) => (
                <tr key={m.module_id}>
                  <td>{m.module_id}</td>
                  <td>{m.step ?? '—'}{m.step_source === 'current code (inferred)' ? ' *' : ''}</td>
                  {FLAG_COLUMNS.map((f) => <td key={f}>{m.flags[f] ? '✓' : ''}</td>)}
                  <td>{m.corroboration.replace('_', ' ')}{m.conflicts.length ? `: ${m.conflicts.join('; ')}` : ''}</td>
                </tr>
              ))}
              {r.outside_steps.map((o) => (
                <tr key={o.module_id}><td>{o.module_id}</td><td colSpan={FLAG_COLUMNS.length + 2}>{o.state.replace('_', ' ')} — {o.detail}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="tm-muted">* step taken from the current code, not recorded by this run.</p>
          <p>Universe {r.universe_relation.universe ?? '—'} · idea decisions {r.universe_relation.ideas} · holding decisions{' '}
            {r.universe_relation.holdings} — {r.universe_relation.state === 'conflicting' ? 'Conflicting records' :
              r.universe_relation.state === 'not_observed' ? 'Not observed' : 'within the possible range; nothing more is claimed'}</p>
          <Redacted fields={r.redacted_fields} />
        </Card>
      )}

      {tab === 'Results & proof' && (
        <div className="tm-grid tm-two">
          <Card title="Results this month: what happened, compared with what" sub={results.data?.label ?? 'Observed, not proof'}>
            {results.data && (
              <>
                <p>Stored grades: {results.data.stored_grades.available
                  ? `${results.data.stored_grades.count} ideas, average ${pct(results.data.stored_grades.avg_gross_return)} gross`
                  : results.data.stored_grades.why}</p>
                <p className="tm-muted">Category: {results.data.category} (live practice ideas only; never mixed with backtests or v1 paper trades)</p>
                {(['brain_trade', 'every_stock', 'momentum', 'nifty', 'cash'] as const).map((k) => {
                  const f = results.data.computed[k]
                  return <p key={k}><b>{k.replace('_', ' ')}</b>: {f.available ? pct(f.avg_net ?? f.avg) : `Not available — ${f.why}`}
                    <br /><span className="tm-muted">{f.source}</span></p>
                })}
                <p className="tm-muted">Costs: {results.data.computed.costs}</p>
                <p>Forward trial: <b>{results.data.forward_trial.word}</b> — {results.data.forward_trial.why}</p>
              </>
            )}
          </Card>
          <Card title="Is it proven?" sub="Only frozen, independent tests count">
            {(proof.data?.claims ?? []).map((c) => (
              <div key={c.claim}>
                <p><b>{c.word}</b> — {c.label}</p>
                {c.numbers && <p className="tm-muted">Numbers: {c.numeric} ({String(c.numbers.folds_won)} of {String(c.numbers.eligible_folds)} windows) · independence: {c.independence}</p>}
                {c.tested_subject && <p className="tm-muted">{c.tested_subject}</p>}
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  )
}
```

If `tm-row`, `tm-three`, `tm-two`, `tm-table`, `tm-muted` or `tm-bad` are not defined in
`trademind/trademind.css`, use the nearest existing classes (`grep -n "^\.tm-" frontend/src/trademind/trademind.css`).
Do not add new global CSS.

- [ ] **Step 4: Owner-only menu entry and route** in `TradeMindApp.tsx`

1. Add the import:

   ```tsx
   import Observatory from './pages/Observatory'
   ```

2. Add the Brain Logs page:

   ```tsx
   { to: '/trademind/observatory', label: 'Observatory' },
   ```

3. In `visibleSections`, before `return s`, add:

   ```tsx
       if (!ownerConsole && s.label === 'Brain Logs') {
         return { ...s, pages: s.pages.filter((p) => p.to !== '/trademind/observatory') }
       }
   ```

4. Add the route next to `ai`:

   ```tsx
             <Route path="observatory" element={ownerConsole ? <Observatory /> : <Navigate to="/trademind" replace />} />
   ```

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no errors.

- [ ] **Step 6: Commit** ("Brain Observatory: owner-only page under Brain Logs")

---

### Task 11: Real local run, page check and scope guard (spec D6 / T1A-1, T1A-3, T1A-13)

> **Plan rev 2:** apply the updated acceptance checks A1–A5 and B1–B9 (replace Steps 4–5); see "Plan revision 2: corrections" above. Where they disagree, the correction wins.

**Files:** none committed, except screenshots if the owner wants them in `docs/brain/evidence/`.

- [ ] **Step 1: Full backend suite**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE ./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass. Report the totals exactly as printed.

- [ ] **Step 2: Scope guard (T1A-1)**

```bash
git diff --name-only develop...feature/brain-observatory-1a
```

Expected: only these files:
- `docs/superpowers/specs/2026-10-15-brain-observatory-design.md`
- the plan file
- `backend/src/swing_trade_ml/services/brain_observatory/*`
- `backend/src/swing_trade_ml/api/v1/endpoints/brain_observatory.py`
- `backend/src/swing_trade_ml/api/v1/router.py`
- `backend/tests/observatory_fixtures.py`
- `backend/tests/test_brain_observatory_*.py`
- `.github/workflows/test.yml` (only if the owner approved it)
- `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- `frontend/src/trademind/pages/Observatory.tsx`, `frontend/src/trademind/TradeMindApp.tsx`

Anything else fails the guard. Paste the output in the report.

- [ ] **Step 3: One real local brain run** (local database only; never prod, never Kite)

Start the local stack per `docs/DEPLOY.md` local section with `BRAIN_ENABLED=true` and the worker running.
Queue a run with "Run the brain now" in TradeMind Control, or
`curl -X POST localhost:8000/api/v1/brain/runs -H "X-API-Key: $API_KEY" -d '{"kind":"nightly"}' -H 'content-type: application/json'`.
Read `API_KEY` from `.env` into the shell **without printing it**.

Wait until `GET /api/v1/brain/runs/latest` shows `status: done`.

- [ ] **Step 4: API equals database for that run (T1A-3)**

In a scratch script (scratchpad, not the repo), for the run id:
- compare `/brain/observatory/runs/{id}` `words` with
  `SELECT kind, word, count(*) FROM brain_decisions WHERE run_id = :id GROUP BY 1, 2`
- compare the `modules` flags with the raw `trace` statuses
- compare `/runs/{id}/stocks` item count with the decision count
- compare one stock's detail fields with its `brain_decisions` row

Record the matches and any mismatch.

- [ ] **Step 5: Page check and screenshots (T1A-13)**

Use the browser-automation skill on `http://localhost:5173/trademind/observatory` as the owner:
1. select today's date and the new run
2. open the three tabs
3. pick one stock

Check that:
- card 2 reads "Existing records only — partial visibility."
- the decision-path panel shows the deferred wording
- module counts on the page equal Step 4's API values

Take screenshots of each tab.

- [ ] **Step 6: Report** (no push, no merge)

Report:
- test totals
- scope-guard output
- the run id
- Step 4 comparison results
- screenshots
- open items: owner OK for the `test.yml` scope addition; the audit-location and policy decisions
  (deferred; 1A shows "audit_uncommitted")

Update tracker tasks ob3–ob10 to `built` or `tested` as appropriate. Deployment is **not** part of this
plan; it is requested separately (spec P-1, P-2).
