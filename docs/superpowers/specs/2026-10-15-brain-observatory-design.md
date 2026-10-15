# Brain Observatory — design (revision 4)

Status: **for owner review. Nothing implemented, nothing deployed.** The phase split (rev 3) is accepted in
principle. This revision makes the owner's focused corrections and defines the exact Phase 1A scope (section
10) for implementation approval. Deployment needs separate approval. **Phase 1B and Phase 2 remain
unapproved**, and no 1B instrumentation is added while implementing 1A.

History:
- Rev 1 (chat, 2026-10-15): approach 1 chosen (full per-stock evidence).
- Rev 2: five changes (health states, rejection summary, three layers, production safety, strict "proven").
- Rev 3: owner review items 1–9 and the split into phases. Items are tagged **[R3-n]**.
- Rev 4 (this): owner corrections C1–C7 for Phase 1A, plus the open 1B and Phase 2 issues. Items are tagged
  **[R4-Cn]** and **[R4-open]**. Section 11 records the source verification (C7).

Tracker: System Atlas → Pending work → section "Brain Observatory" (ob1–ob11).

## 0. Goal, limits, phases

The owner picks a date and a stock, and sees what the brain did, which modules took part, why the decision
came out as it did, and whether there is evidence the behaviour improves results.

Three layers are kept apart in data, API and page:

| Layer | Question | Never implies |
|---|---|---|
| 1. Brain execution health | Did the run finish; which modules executed and gave valid output? | that decisions were good |
| 2. Evidence-recording health | Is the record of that run complete? | that the brain worked or made money |
| 3. Decision effectiveness | Does predefined, independent evidence support it? | anything about a single run |

**Not changed in any phase:**
- stock selection, model weights, trading rules (+8% / −4% / half at +5% / 15 trading days), risk limits
- strategy parameters and module modes
- the frozen validation protocol `wf-protocol-v1` and its data and reports
- the forward-gate numbers (layer-2 draft section 5a)
- real-order permissions; `TRADING_MODE` stays `paper`

No paid service and no new infrastructure.

**No reconstruction:**
- Only inputs and outputs retained from the run itself are shown. Nothing is recomputed from current
  code or current data and presented as that run's.
- Contribution is never inferred from reason text. Stored text is shown as stored, labelled as text,
  never parsed, and passed only through the redaction in 3.4.

| Phase | Contents | Approval |
|---|---|---|
| **1A** | Read-only Observatory over records **already stored today**. No runner, decision, persistence or schema change | proposed for use during the trial, subject to the frozen change policy (section 1) |
| **1B** (optional) | Runner instrumentation and post-run persistence of in-memory inputs and outputs | **not permitted by the current policy** (section 1); only with an explicit owner waiver stating its effect on the trial |
| **2** | Decision-path recording in M08 and the constitution; changed-by attribution; primary rejection and overlap counts | separate approval after the trial, or an explicit trial-policy decision before deployment |

## 1. Forward-trial change policy and how each phase relates to it [R3-9]

### 1.1 The policy as it exists today

| # | Source | Text (quoted or summarised) |
|---|---|---|
| P1 | System Atlas tracker, Pending work tab, note dated 2026-10-14 | "The trial is frozen from 2026-10-14. Tasks marked *Safe now* don't change which stocks are picked or how orders are placed, so they can be built during the trial. Tasks marked *After trial* would change decisions or orders, so they wait. Deploy only after 16:30 or before 09:00." |
| P2 | Same tracker, task br2 (precedent) | "Store one model + rules version id on every brain decision" was classed **After trial**: "Writes into the brain's own records, so after the trial." |
| P3 | `docs/brain/ROADMAP.md` line 11 | "Freeze: no new trading features; prove the brain, then build only what evidence demands." |
| P4 | Layer-2 draft, section 5a (`docs/superpowers/specs/2026-10-13-layer2-validation-protocol-DRAFT.md`) | Forward-gate numbers (15 sessions, 30 finished TRADE ideas, profit and beats-random checks) are in use; "change them only before looking at a result, and record the change here with a date." |
| P5 | `CLAUDE.md` | Changes touching order placement, sizing, stops or limits need a test and the owner's approval before `main`. |

P1 and P2 live in the tracker artifact, not in the repo.

**Recommendation (owner decision):** copy P1 and P2 into `docs/brain/TRIAL-CHANGE-POLICY.md` so the
policy is versioned with the code. This spec does not create that file.

### 1.2 Classification of each phase

| Phase | Changes which stocks are picked or how orders are placed? (P1) | Writes into the brain's records? (P2) | Allowed under current policy? |
|---|---|---|---|
| 1A | No: new read-only routes and page; no change in `brain/`, `strategies/`, `services/execution.py`, `workers/` | No | **Proposed as permitted under P1**, as a UI/API task like the bx tasks already marked Safe now. Owner confirms. Deploy window P1 applies. |
| 1B | Not intended, but the runner and `_store` sit on the decision path | **Yes** (new columns and table written by every run) | **No.** By the P2 precedent, needs an explicit waiver (1.3) |
| 2 | Not intended, but M08 and the constitution are the decision code | Yes | **No.** After trial, or explicit trial-policy decision |

A passing on/off equivalence test is **evidence**, not authorization. It never by itself permits a
change during the frozen period.

### 1.3 Waiver requirements (only if the owner wants 1B or 2 during the trial)

A waiver must be written into the trial record (P4's change log, and the tracker) **before** deploy, and
must state:
1. the deploy date and commit
2. that from that date the trial runs on a different code version of the decision path
3. the continuity risk: if recording failed in a way that aborted `_store`, that night's decisions would
   be lost. That is one fewer session and possibly fewer finished ideas toward the 15 / 30 minimums (P4).
   The design (A6, section 4) is built to prevent this, but the risk is stated, not assumed away.
4. the validity effect **[R4-open]**: this spec does **not** decide whether ideas before and after a
   mid-trial deploy are pooled. That is a trial-continuity rule. It must be written into the trial change
   policy (1.1) by the owner **before** any 1B or Phase 2 waiver, and before seeing post-deploy results.
   The options are:
   - (a) pool, with the deploy recorded as a change event
   - (b) split at the deploy date
   - (c) restart the trial

   Equivalence tests are inputs to that decision, not a substitute for it.

## 2. Status words [R3-4, R3-7]

| Word | Meaning |
|---|---|
| **Not observed** | Expected for this run while recording was on, but no record exists |
| **Before recording began** | The run predates the recording epoch for that kind of evidence (2.1) |
| **Not recorded — decision-path recording deferred during trial** | Phase 2 data, deliberately not captured |
| **Not recorded in Phase 1A** | Data that exists only in memory during a run and is not stored today |
| **Switched off** | Disabled on purpose by a recorded setting; the setting is named (module mode `off`, rule id in the disabled list, `BRAIN_SECTOR_GATE_TOP_N=0`, recording switch) |
| **Not applicable** | This run kind never includes it (2.2) |
| **Recording failed** | Recording was attempted and failed; the error is shown |
| **Deleted (retention)** | Recorded, then removed by the retention rule |
| **Unknown** | The stored records cannot tell between two states; both are named, e.g. "Not observed or send failed" |
| **Conflicting records** [R4-C2] | Two stored records disagree, e.g. `modules` says `off` but the trace has a `used` line, or a module has more than one line in one run. Both values are shown; nothing is picked |
| **Inferred** (a label, not a state) [R4-C2] | Any count or state that depends on the current code's module manifests (module → step mapping), not on a record from that run |

### 2.1 Recording epochs

Each kind of evidence has a start date, stored in a small table `brain_recording_epochs` in 1B and 2, or
in a constant in 1A for the code's own fields:

| Field | Value |
|---|---|
| `kind` | e.g. `run_outcome`, `stock_evidence`, `decision_path` |
| `enabled_at` | when recording of that kind was switched on |
| `disabled_at` | when it was switched off, if it was |
| `code_version` | the code that started it |

A run **after** `enabled_at` with no record shows **Not observed** (or **Recording failed**), never
"Before recording began". That is how missing records after deployment are kept from being classed as
historical.

### 2.2 Run kinds (from `brain/module.py` `STEPS_FOR`)

| Kind | Steps |
|---|---|
| nightly | all 8 |
| why | all except Learn |
| intraday | Perceive, State, Risk, Decide |

## 3. Phase 1A — read-only Observatory over existing records

### 3.1 Field inventory [R3-1 of instruction]

"Stored" means persisted today. "Memory" means available only during the run. "Capture change" means what
would be needed to keep it. Phase 1A shows **only** rows marked Stored, and only when they were written by
that run.

**Run level**

| Shown | Existing source | Stored? | Capture change for 1A |
|---|---|---|---|
| Kind, as_of, book, live | `brain_runs.kind/as_of/book/live` | Stored | none |
| Requested / started / finished, duration | `requested_at`, `started_at`, `finished_at`, `ms` | Stored | none |
| Outcome, error | `status`, `error` | Stored | none |
| Banner | `banner_mode`, `banner_headline` | Stored | none |
| Mode used per module | `brain_runs.modules` (module id → mode used) | Stored | none |
| Step log | `brain_runs.trace` (step, module_id, status, reason text, ms, version) | Stored | none |
| Data quality | `brain_runs.quality` (overall score/fresh/issues, stale symbol list) | Stored | none |
| Sector table | `context.sectors` (each M11 sector state + plain name) | Stored (runs after the column existed; else "Not observed") | none |
| Market situations | `context.situations` (M04) | Stored | none |
| Portfolio view | `context.portfolio` (M14 summary) | Stored | none |
| Data manifest | `context.data_manifest` (feature set version, universe date and count, connectors) | Stored | none |
| Alerts check (M16) | `alerts_checked_at`; `brain_alerts` rows with this `run_id` | Stored | none |
| Daily check | `brain_daily_checks` (day, checks, run, intraday, trial) | Stored | none |
| Code commit, config fingerprint, model versions | none | **Not stored** | 1B |
| Failure subtype (error / bad output / too slow) | only inside the trace reason text | Text only | 1B adds a structured `outcome`. 1A shows the text verbatim and does **not** classify it |
| Planned (expected) module list | none | **Not stored** | 1B |

**Per stock**

| Shown | Existing source | Stored? | Capture change for 1A |
|---|---|---|---|
| Symbol, kind (idea / holding), final word | `brain_decisions` | Stored | none |
| Entry, target, stop, qty, horizon | `brain_decisions` | Stored | none |
| Confidence and its source | `confidence`, `score_source` | Stored | none |
| Reasons (as written by M08 at decision time) | `reasons` (list of text) | Stored | none; shown as stored text, **after the redaction pass** (3.4) |
| Evidence sentence | `evidence_text` | Stored | none; same redaction pass |
| "Was originally X" and "last downgrade reason" | `downgraded_from`, `downgrade_reason` (set by `contracts.downgrade`) | Stored | none. Labelled exactly as stored; **not** shown as a path or as changed-by |
| Owner overrule | `overruled_word`, `overrule_reason`, `overruled_at` (`overruled_by` shown as "owner") | Stored | none |
| Graded outcome | `outcome`, `outcome_return`, `outcome_days`, `max_up`, `max_down`, `resolved_on` | Stored | none |
| Model features and price facts at decision time | `feature_snapshots` (`close`, `atr_14`, `adv_inr_20`, `features`) **where `run_id` = this run** | Stored (nightly only; a same-night rerun re-points the row to the newer run) | none. Shown only when `run_id` matches; otherwise "Not observed for this run" |
| Listed as stale | stock in `quality.stale` | Stored | none. Note: not listed means fresh **or** not assessed; the page says so |
| Holding track points | `brain_track` for book + symbol + day | Stored, **no run id** | none. Shown as **day-level context** ("tracker record for this stock on this day"), never as this run's output [R4-C3] |
| Exchange, instrument token | `instruments` (current master) | Current, not per-run | Shown as "current instrument", never as decision-time input |
| Opinions (all, incl. M06 shadow) | `ctx.opinions`, `ctx.shadow` | **Memory** | 1B |
| Risk verdict (allowed, rule, max qty, note) | `ctx.verdicts` | **Memory** | 1B |
| Stock state, setups, past-case summary | `ctx.stocks`, `ctx.situations` (per stock), `ctx.recalls` | **Memory** | 1B |
| This stock's sector and rank as used | `IdeaFacts.sector_rank` | **Memory** | 1B |
| Draft, rule steps, constitution steps, changed-by, primary rejection, overlap | not produced anywhere | Not produced | Phase 2 |

**Day level**

| Shown | Existing source | Stored? |
|---|---|---|
| **Universe size** | `context.data_manifest.universe_count` (stocks the run was asked about) | Stored |
| **Idea decisions recorded** | count of `kind=idea` rows in the day's live nightly run (not superseded) | Stored |
| **Holding decisions recorded** | count of `kind=holding` rows in that run | Stored |
| TRADE / WATCH / WAIT / AVOID; holding words | `brain_decisions` of that run | Stored |
| Tracked holdings | `brain_track` rows for the day: day-level context, no run link | Stored |
| Brain strategy signals and paper orders that day | v1 `signals` / `orders` for the brain strategy | Stored, **not linked to a run id**. Shown at day level only: "not linked to a specific run" |

[R4-C3] Universe size and recorded idea decisions are two separate numbers. They are not the same thing.
M08 makes an idea for each universe stock **not held** (`m08_decide/module.py`: "if symbol not in held"),
and a holding decision for each held stock, which may be outside the universe. The run does not store its
universe list or held list. So the only checkable relation is:

  universe size − holding decisions ≤ idea decisions ≤ universe size

The page shows both numbers. A value outside that range is flagged **Conflicting records**. Inside it,
nothing is claimed.

### 3.2 Module health in 1A [R3-4]

Per module, from `brain_runs.modules` and `brain_runs.trace` only:

| State | Rule (stored fields only) |
|---|---|
| **Switched off** | trace status `skipped` **and** mode `off` in `modules` (if only one says off → Conflicting records) |
| **Executed** | the module's code ran: a trace line for this module (not `fallback` as module id) with status in {used, shadow, fallback, rejected}. **Executed says nothing about output use.** A module that executed and then failed, or ran in shadow, produced no output for the run [R4-C1] |
| **Valid output** | status in {used, shadow}: it passed contract, time budget and permissions |
| **Used** | status `used`: its output was **merged into the run's context**. This is the only state that means output went into the run [R4-C1] |
| **Shadow** | status `shadow` |
| **Failed** | status `fallback` or `rejected` on the module's own line; subtype = **"recorded message: …"** (verbatim, not classified) |
| **Step fallback answered** | trace line with module id `fallback` for that step |
| **Not observed** | mode on/shadow in `modules`, its step is in this run kind, no trace line |
| **Not applicable** | its step is not in this run kind |

**Inferred states [R4-C2].** Two things need the module → step mapping: whether a module was *expected* in
a run kind, and therefore *Not observed* vs *Not applicable*. No run stores that mapping, so it comes from
the current code's module manifests. Every such state and count is labelled **Inferred (current module
list)** on screen and in the API (`"inferred": true`). Modules in `brain_runs.modules` that the current
code no longer knows, or the reverse, show **Unknown: module list changed since this run**.

**Multiple attempts [R4-C2]:**
- *Within one run*: each module runs at most once per step. Two or more trace lines for one module →
  **Conflicting records**, all lines shown.
- *Within one day*: several runs can exist (nightly, superseded nightly reruns, intraday every 15 min, why
  runs). Module health is **always per run, never merged across runs**.
- Day-level numbers use the one live nightly run that is not `superseded`. The other runs are listed as
  separate attempts, with their own health.
- More than one non-superseded live nightly run on a day → **Conflicting records**.
- No nightly run on a trading day (`core/holidays.is_trading_holiday` false, weekday) → **Not observed**.
  Weekends and listed holidays → **Not applicable**.

Modules outside the 8 steps:

| Module | 1A rule |
|---|---|
| M00 runner | the run row: Executed, plus outcome `done` / `failed` / `superseded` |
| M16 alerts | Alerting kinds are **nightly and intraday** (`ALERTING_KINDS` in `brain/alerts/service.py`; corrected in rev 4). On a live run of those kinds: `alerts_checked_at` set → **Executed** (the stamp is written even when there is nothing to tell, `_mark_checked`), plus "N alerts sent" from `brain_alerts.run_id`. Stamp null → **Unknown: not observed or send failed** (a failed send is deliberately not stamped). `why` runs and non-live runs → **Not applicable** |
| M17 console | **Not applicable** (it is the UI) |
| M18 go-live | **Not applicable to a single run.** No per-run M18 execution is recorded, and none is inferred from approvals, stage or same-day signals. The page shows the day's stage (from `brain_stage_changes`) as day context only |

Per-module health is **run-level**. "Executed" means the code ran. Only "Used" means its output was merged
into the run. Neither says anything about any one stock. Per-stock influence in 1A reads: **"Influence on
this stock: Not recorded in Phase 1A."** [R4-C1]

**Run-level aggregation:**
- **Run completed** = M00 status `done`.
- Module counts:
  - expected (Inferred) = applicable and not switched off
  - executed, valid output, used, shadow, failed, not observed (Inferred), conflicting, unknown: each
    counted separately. A module is counted once, in its single state.
- The run headline is **Degraded** if any expected module is Failed or Not observed, or any step was
  answered by a fallback.
- **Unknown** cases are counted separately and never merged into OK.

### 3.3 Phase 1A pieces

**API:** `/api/v1/brain/observatory/`, GET only, `require_owner`, redacted.

| Route | Returns |
|---|---|
| `GET /days?from&to` | day counts (3.1 day level) and the day's nightly run health |
| `GET /runs?date=` | runs that IST day, with health |
| `GET /runs/{id}` | run fields (3.1) and the module health table (3.2) |
| `GET /runs/{id}/stocks` | stored decisions: symbol, kind, word, confidence |
| `GET /runs/{id}/stocks/{key}` | the per-stock stored fields; every 1B and Phase 2 field returned as a status word |
| `GET /learning?from&to` | results collected (graded decisions), changes proposed (`brain_proposals` by status), learning drift runs, proven improvement (section 6) |
| `GET /outcomes?from&to` | finished ideas from `brain_decisions`: gross, costs, net, NIFTY over the same holding days, every-stock baseline, count; labelled **"Observed, not proof"**. Uses `services/costs.py`; `brain/trial_journal.py` only under the section 10 condition |
| `GET /effectiveness` | section 6 verdicts |

**Stock key [R3-5]:**
- `{key}` is the `brain_decisions.id`.
- A symbol search returns every match in that run as `(symbol, kind)` pairs. When a symbol appears both
  as an idea and as a holding, both are listed and the owner picks one; there is no silent choice.
- Exchange is shown from the current instrument master and labelled as such.

**Page:** `/trademind/observatory` under Brain Logs, owner-only. Layout as in the owner's mockup:
- date / run / stock pickers
- the three layer cards
- tabs: *Decision flow*, *Module activity*, *Results & proof*

In 1A, *Decision flow* shows:
- the stored final word, reasons (verbatim), evidence sentence, "originally X / last downgrade reason"
  (as stored), feature snapshot, stale flag, and outcome
- the path panel and the "Why no TRADE?" panel read **"Not recorded — decision-path recording deferred
  during trial."**
- opinion, verdict and sector panels read **"Not recorded in Phase 1A."**

### 3.4 Free text and redaction [R4-C6]

Stored free text can hold more than the brain intended. Exception reprs in `brain_runs.error` and in trace
reasons ("error: …") can carry connection strings, URLs or tokens.

"Verbatim" therefore means: **the stored text, unchanged except for the redaction pass, and never parsed
for meaning.**

One redaction function is applied on the server to **every** string value in every Observatory response:
run error, trace reasons, decision reasons, evidence text, downgrade and overrule reasons, banner, daily
check text, proposal text, and anything else.

It replaces each match with `[redacted]`:

| # | What is replaced |
|---|---|
| 1 | the current process's values of the secret settings named in CLAUDE.md (`KITE_API_KEY`, `KITE_API_SECRET`, `KITE_PASSWORD`, `KITE_TOTP_SECRET`, `KITE_USER_ID`, `API_KEY`, `JWT_SECRET_KEY`, `GOOGLE_CLIENT_SECRET`, `POSTGRES_PASSWORD`, `DATABASE_URL` and its password part, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), exact match, when non-empty |
| 2 | URL credentials: `scheme://user:pass@` becomes `scheme://[redacted]@` |
| 3 | email addresses |
| 4 | JWT-shaped strings (three base64url parts) |
| 5 | `access_token`, `api_key`, `secret`, `password`, `token` followed by `=` or `:` and a value |
| 6 | long opaque tokens (32+ characters of hex or base64) |

Each response field that was changed carries `"redacted": true`. The page shows "some text hidden for
safety".

The **check that redaction worked** is a test (T1A-10), not trust. Fields that are never text, such as
numbers and words from the fixed vocabulary, are not altered.

### 3.5 No side effects and bounded queries [R4-C5]

GET-only routes are not enough on their own. The existing `GET /brain/why/{symbol}` runs the brain and
stores a run, which shows that a GET route can have side effects. Every Observatory route is therefore:

1. **Read-only at the database:** each request runs in a transaction opened with
   `SET TRANSACTION READ ONLY`, so Postgres rejects any insert, update or delete. The session is rolled
   back at the end, never committed.
2. **No other effects:** no call into `brain/service`, the runner, the brain queue, alerts, Telegram,
   brokers or Kite. The new package imports models and pure helpers only. An import test enforces this.
3. **Bounded:**
   - `SET LOCAL statement_timeout = '5s'` per request
   - date ranges at most 92 days (else 422)
   - list routes capped at 500 rows, with explicit paging
   - per-request query count bounded (at most 12 statements, measured in a test), so there are no
     per-row queries
   - `/outcomes` reads stored outcomes only and never fetches prices or recomputes grading
4. **No cache writes:** no Redis writes.

### 3.6 1A risk

1A adds read paths only. Its risks:

| Risk | Handled by |
|---|---|
| Misleading display | tests T1A-3 to T1A-8 |
| Data exposure | T1A-9, T1A-10 |
| Side effects or heavy queries on the prod database | T1A-15, T1A-16 |
| Deploy timing (a restart near 15:50 could drop a run) | P1 deploy window |

## 4. Phase 1B — optional, requires a waiver (1.3)

Status: **unapproved.** Nothing here is built with Phase 1A.

**Exact decision-time input source [R4-open].** Rev 3 proposed reading the context after the run. That is
not decision-time: the Learn step runs after Decide, and the context at the end includes everything merged
later.

The exact source is **the view object the runner passes to M08**, `ctx.view_for(M08 manifest)`, recorded
by the runner at the moment it calls M08's `run()`. That is what M08 actually saw:

| Field | Source inside that view |
|---|---|
| Opinions | `opinions`, plus `ctx.shadow` contributions as they stood at that moment, marked shadow |
| Risk verdict | `verdicts` |
| Stock state | `stocks` |
| Setups | `situations` |
| Past cases | `recalls` |
| Sector table | `sectors` |
| Market mode | `market` |
| Data quality and snapshots | `quality`, `snapshots` |
| Holdings | `holdings` |

Recording the view is a runner change. It holds a reference, never a copy that M08 could see. Values are
serialized after the run.

**What 1B still cannot give:**
- which opinion M08 *chose*
- the sector rank M08 *derived* for a stock

Both are computed inside M08 (`IdeaFacts`), so they are Phase 2. 1B labels them **Not recorded in 1B**.

**Recording switch lifecycle [R4-open].** `BRAIN_EVIDENCE_ENABLED` is an environment setting, read at
process start, so a change needs a worker restart.

At start-up, the worker compares the setting with the newest `brain_recording_epochs` row for each kind:
- opening a new epoch (`enabled_at`, code version) when the setting turns on
- closing it (`disabled_at`) when it turns off

Every run also stores the setting it actually ran with, so a run is never classed by date alone.

| Run's stored setting | No evidence row means |
|---|---|
| on | **Not observed** or **Recording failed** |
| off | **Switched off** |
| absent | **Before recording began** |

Restarts with an unchanged setting add no rows.

**Runner additions:**

| Addition | What |
|---|---|
| `TraceEvent.outcome` | structured value (off, error, bad_output, too_slow, not_permitted, shadow, used, step_fallback), set in the same branches that set `status` |
| `expected_modules` | written before step 1 |
| `code_version` | from a `GIT_SHA` build argument |
| `config_fingerprint` | a hash, no values |
| `model_versions` | `{v1_model, m06}` |

**Tables and columns:**
- new table `brain_stock_evidence` (one row per decision, FK `decision_id` unique)
- new nullable run columns `evidence_status/error/count/ms/bytes`
- `brain_recording_epochs`

**Completeness [R3-5]:**
- The set of `decision_id` in evidence equals the set of the run's decisions exactly. No extra, missing
  or foreign-run links.
- Mandatory sections per kind:

  | Kind | Mandatory |
  |---|---|
  | idea | inputs, opinions, verdict |
  | holding | inputs, verdict, track |

- Missing-value semantics:
  - a section present with `null` means no source provided it that run, with the reason code (e.g.
    `no_opinion_for_symbol`)
  - an absent section is a schema error, which makes the run `failed`
- A zero-decision run is `complete` with count 0 only when the run status is `done`. It is flagged
  "no decisions" in layer 1.

**Failure guarantee [R3-6], stated precisely:**
1. Capture code runs **after** the runner returns. It cannot change any decision object, because they are
   frozen dataclasses and are only read.
2. Building the rows is wrapped. Any exception means no rows, `evidence_status=failed` with the error, and
   decisions written as before.
3. Rows are inserted in a savepoint. An insert failure rolls back only the evidence, then the same
   `failed` status is written.
4. **Not guaranteed by the savepoint:** if the outer transaction fails at commit, the run, decisions and
   evidence are all lost together. That is today's behaviour for decisions, unchanged by 1B. 1B never
   commits evidence without its decisions.
5. The runner `outcome` field is set by plain assignments in existing branches. A test proves every branch
   still yields the same `status` and the same merged context.

Size and storage are covered in section 7. 1B adds the D-tests marked 1B in section 8.

## 5. Phase 2 — decision-path recording (after trial, or explicit trial-policy decision)

Carried from rev 2, with review items applied.

### 5.1 Path steps [R3-1, R3-2]

`Decision.path` holds a tuple of `PathStep` records. **No condition reads it.**

`PathStep` fields:

| Field | Values |
|---|---|
| `seq` | position in the path |
| `stage` | draft / rule / constitution / fallback / final |
| `code` | structured code (see below) |
| `executor` | the code that ran the check (e.g. `M08.rule.sector_gate`, `constitution.data_unreliable`) |
| `input_provenance` | list of `{input, provider, provenance}` (see below) |
| `result` | see table below |
| `from_word`, `to_word` | the word before and after this step |
| `reason` | text |

**`result` values:**

| Result | When |
|---|---|
| `drafted` | the draft step |
| `changed` | the word was lowered |
| `already_cautious` | the rule asked for a word that was not lower |
| `passed` | the rule was evaluated and returned nothing |
| `disabled_rule` | rule id in `policy.disabled`; never evaluated |
| `inactive_setting` | rule evaluated as a no-op because of a recorded setting, e.g. sector gate with `BRAIN_SECTOR_GATE_TOP_N=0`. The rule must report this explicitly; it is never shown as `passed` |
| `input_missing` | the input it needs came from no source |

**Input provenance.** `provider` is a module id or `fallback:<step>`. `provenance` is one of:
- `module_used`
- `step_fallback`
- `default_value`
- `absent`

**Actual provenance, per record [R4-open].** The runner always runs a step's fallback **after** its modules
(`runner.execute`), and `merge` never overwrites. So a fallback can fill *some* records, for example a
snapshot for one stock, even in a step where a module was used. Provenance must therefore be kept **per
record**, not per step:
- `BrainContext.merge` takes the contributor's id (module id, or `fallback:<step>`).
- For each record it actually adds (key = record type + symbol, or `*`), it writes `provider` and
  `module_used` / `step_fallback`.
- Records it skips because they were already present get nothing.

**`default_value`** is never inferred. It is set only where code substitutes a constant for a missing
input, for example a default market mode when no market state exists. Each such site in M08, the
constitution and the fallbacks reports it explicitly through the recorder. A test lists every default site
(T2-15).

**`absent`** = no record and no default.

Credit rules:
- A module that is **switched off, failed, or shadow** can never be a provider.
- Shadow outputs are never merged, so they cannot appear as `module_used`.
- A module gets **changed-by** credit for a stock only when a step with `result=changed` lists it as
  provider with `module_used`.
- The executor (M08 or the constitution) is credited separately as executor.

**Drafts** have one code per branch:
- ideas: `no_price`, `no_opinion`, `below_calibrated_threshold`, `below_buy_level`,
  `signals_unfavourable`, `draft_trade`
- holdings: `holding_no_price`, `holding_on_track`, plus the track step

**Fallback coverage [R4-open].** `brain/fallbacks.py` `FALLBACKS`:

| Step | Fallback |
|---|---|
| perceive | `perceive` |
| state | `state` (incl. `_market_from_trend`) |
| recognise, remember, risk, learn | `nothing` |
| reason | `reason` (`_model_opinion`) |
| decide | `decide` |

Phase 2 covers every one of them:
- **Decide fallback:** when M08 is off, failed or too slow, `fallbacks.decide` makes the decisions. It
  gets its own recorder, so its path has a `fallback` stage step per branch it takes. It is not a single
  opaque step.
- **Input fallbacks** (perceive, state, reason): seen through per-record provenance (`step_fallback`).
- **Risk with no module:** gives no verdict. The constitution turns that into NO NEW TRADES; its check
  step records `input_missing` for the verdict.
- **Recognise, remember, learn:** provide nothing, so dependent inputs are `absent`.

**Rejection summary** (ideas whose final word is not TRADE):
- **primary** = the first step whose `to_word` is below TRADE (draft or changed step)
- **overlap** = every `changed` or `already_cautious` step
- primary counts add up to the number of non-TRADE ideas; overlap counts are listed separately

### 5.2 Path integrity [R3-3]

A path is valid only if all of these hold:
1. It starts with exactly one draft or fallback step.
2. Each step's `from_word` equals the previous step's `to_word`.
3. `changed` lowers the word; every other result keeps it.
4. Every rule applicable to the decision kind appears exactly once, in the engine's order, with one of the
   results above.
5. Every constitution check appears exactly once.
6. The final word equals the stored `brain_decisions.word`.

An invalid path fails the run's evidence (`failed`); it is never stored partially.

### 5.3 Failure isolation inside the decision code [R3-6]

- Steps are built by a recorder helper. **Every exception inside the helper is caught in the helper.** The
  decision continues exactly as with recording off, and the recorder marks the path `broken`.
- A broken path makes the run's evidence `failed`. The decision itself is unaffected.
- The runner's M08 time budget includes the recorder's time. Timing tests are T2-9 and T2-10.

Phase 2 keeps the 1B completeness, failure-guarantee, epoch and retention rules.

## 6. Effectiveness verdicts [R3-8]

### 6.1 The registry and the rule

Verdicts come from `backend/src/swing_trade_ml/services/brain_observatory/validation_verdicts.json` (inside the new read-only package, section 10), a reviewed file changed
only by commit.

Each entry binds the verdict to:

| Field | Content |
|---|---|
| `protocol_id` | `wf-protocol-v1` |
| `protocol_file`, `protocol_sha256` | the protocol spec and its hash at the tag |
| `tag`, `tag_commit` | `wf-protocol-v1` and its commit |
| `tested_subject` | what was tested, e.g. "model top-5 ranking, model retrained per fold by `brain/walk_forward.py` at `<commit>`, feature set `<version>`"; with the protocol's own limit: not the exact prod model |
| `sample` | confirmation dates and fold count, and `independence`: one of `untouched` / `exposure_disclosed` / `unaudited`, with the audit's location. See 6.2 on the audit's current, uncommitted state |
| `report_files`, `report_sha256` | `docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.{md,json}` |
| `parts` | each part's verdict and numbers as in the report |
| `minimums` | the protocol's own minimums, and the observed counts |

A claim shows **Proven** only if **every** condition holds. Each is checked by code and tested on its own:

| # | Condition | Enforced by |
|---|---|---|
| E1 | the protocol file's hash equals `protocol_sha256`, and the tag points at `tag_commit` | CI test reading git (CI checkout needs tags: `fetch-depth: 0`) |
| E2 | the report files' hashes equal `report_sha256` | CI test |
| E3 | the registry's part verdicts and numbers equal those in the report JSON | CI test |
| E4 | the sample is the protocol's confirmation sample (not "seen"), **and** `independence = untouched` with a committed audit. `exposure_disclosed` or `unaudited` can never yield Proven; the best possible word is "Pass with disclosed exposure (not proof)" [R4-open] | code plus a CI test that checks the dates against the protocol text and the audit file at its committed path |
| E5 | observed counts meet the protocol's minimums (wf-protocol-v1: at least 12 eligible folds and 100 finished ideas per part) | code; below → **Insufficient evidence** |
| E6 | the protocol's pass rule is met for that part. For wf-protocol-v1: folds-won share ≥ 60% of eligible folds **and** that part's extra check (predictive: lower bound of daily edge over every-stock > 0; economic: average per trade after costs > 0) | code, from E3 numbers; failing either half → **Not proven** [R4-open] |
| E7 | `tested_subject` matches the claim shown (a model-ranking verdict is never shown for "full brain") | code |

A tag or an entry alone never yields Proven. Any failed check yields one of: Not proven / Insufficient
evidence / No frozen protocol yet / **Verdict record invalid** (E1–E3 or E7 fail).

### 6.2 Checked against the frozen artifacts (2026-10-15)

From `docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.md`:

| Part | Result | Folds won |
|---|---|---|
| Predictive skill | **fail** | 7 of 21 |
| Economic value | **fail** | 9 of 21 |

The report's verdict line reads "No evidence of skill and no profit". The protocol rule: at least 60% of
eligible folds, 12 eligible folds and 100 finished ideas minimum.

Re-checked in rev 4 [R4-C7] against `walk_forward_2023-07-01_2025-01-31.json` → `verdict`:

| Part | word | eligible_folds | folds_won | share |
|---|---|---|---|---|
| predictive | `fail` | 21 | 7 | 0.333 |
| economic | `fail` | 21 | 9 | 0.429 |

`reading` = "No evidence of skill and no profit."

Other report figures: model 1980 ideas; model minus every-stock −0.19% per day, lower bound −0.51%. Tag
`wf-protocol-v1` = commit `7b97291` (2026-10-12 22:45 +05:30). Evidence commit `e160276`.

**Independence audit is not committed [R4-C7].** The committed protocol file at `HEAD` is identical to the
tag. The working tree has an **uncommitted** addition, section 4a "Independence audit". It finds that
2024-08-01 to 2025-01-31 was exposed to a feature-selection decision (the extra-inputs spike), so the run
used the signed-off sample with disclosed exposure ("Option B").

Consequences:
- (a) The registry records `independence = exposure_disclosed` for wf-protocol-v1. Under E4, Proven is
  impossible for this run regardless of results. Today's verdict is fail/fail anyway.
- (b) The audit must not be added *inside* the frozen protocol file without a decision, because E1 hashes
  that file at its tag. **Owner decision:** commit the audit as a separate file (recommended, e.g.
  `docs/brain/evidence/wf_v1/independence-audit-2026-10-12.md`), or accept a protocol file that differs
  from its tag. This spec does not touch that file.

### 6.3 What the page shows today

| Claim | Shown |
|---|---|
| Model top-5 ranking, predictive skill | Not proven |
| Model top-5 ranking, economic value | Not proven |
| Full brain decisions (layer 2) | No frozen protocol yet (`wf-protocol-l2-v0` is a draft) |
| Any M09 learning change | Insufficient evidence (no predefined out-of-sample test exists; task br3) |
| Forward paper trial | Insufficient evidence until the P4 minimums are met. Even then it shows the P4 gate answer labelled "forward gate (not frozen)", never "Proven", because P4 is not a frozen protocol |

"Learning" is used only for M09 activity: collected, proposed, accepted.

## 7. Storage [R3-7] (1B and 2 only; 1A stores nothing)

**Cold-start estimate (before any evidence exists) [R4-open: complete].** All inputs are measured, none
assumed. The upper bound uses **uncompressed** JSON size, because Postgres compression is not counted on.

| Term | Formula |
|---|---|
| Nightly | B_stock × (ideas + holdings per nightly, from the latest prod run) × trading days per year (~248) |
| Superseded nightly reruns | B_stock × the same count × reruns per year (prod history, last 60 days scaled) |
| Intraday | B_holding × holdings × 24 runs per day × 30 days (steady state after retention) |
| Why runs | B_stock × why runs per year (prod history scaled) |
| Run-level columns | B_run × all runs per year |
| Index overhead | ×1.3 on the sum |
| Phase 2 extra | path bytes per stock, measured the same way |
| **Backups** | 12-month growth of `pg_dumpall` size: the per-deploy dumps in `/root/backups` on the same disk and the nightly offsite backup. Per-deploy dumps share the droplet disk, so they count against free space |

The projection is done twice: once with Postgres-measured relation size after a local demo week, once
uncompressed. The **larger** is used.

**Database size:** `pg_database_size` and `pg_total_relation_size` on the evidence tables, via a read-only
owner route.

**Database disk free:**
- Postgres cannot report free disk. The DB data lives in a Docker volume on the droplet's disk. The
  verification is an **owner-run** step (Claude cannot SSH): `df -h /var/lib/docker` on the droplet, or
  the DigitalOcean disk graph, recorded in the tracker before deploy.
- The API container's `shutil.disk_usage` is shown only as "API container disk", not as database disk.

**Pass condition:** projected 12-month growth below 5% of the verified free database disk. Otherwise the
owner chooses a shorter retention. No paid storage.

**Retention:**
- nightly and why evidence: kept
- intraday evidence: deleted after 30 days, status `pruned`
- run rows and step logs: always kept

## 8. Acceptance-test matrix

**Item key:**
- **I1–I9**: owner review items 1–9 of rev 2 → rev 3
- **R1–R5**: rev 2 changes
- **G1–G6**: rev 3 instruction points:
  - G1 field inventory
  - G2 Phase-2 data kept out of 1A
  - G3 execution vs per-stock influence
  - G4 policy citation
  - G5 proportionate tests
  - G6 phase approval

### Phase 1A

| ID | Test | Closes |
|---|---|---|
| T1A-1 | **Scope guard**: before merge, `git diff --name-only main...` must list only the section 10 files. Any path under `brain/`, `strategies/`, `services/` (except the new `services/brain_observatory/`), `workers/`, `db/`, `alembic/` or `infra/` fails the check; the output is pasted in the PR | G4, I9 |
| T1A-2 | **Baseline equivalence for the deploy**: the existing brain, strategy and paper-execution test suites pass unchanged on the 1A commit; a fixture nightly run gives byte-identical stored decisions before and after the 1A commit | G5, I6 |
| T1A-3 | **API equals DB**: for a real local nightly run, every number from `/runs/{id}`, `/runs/{id}/stocks`, `/days` equals a direct SQL query | G1, acceptance |
| T1A-4 | **Module health derivation**: fixture traces for each status (used, shadow, skipped/off, fallback, rejected, step fallback, missing line, step not in kind) map to the 3.2 states; failure subtype is shown verbatim, never classified | I4, R1 |
| T1A-5 | **M16 / M18 rules**: stamped run with zero alerts → Executed; null stamp on an alerting live run → "Unknown: not observed or send failed"; `why` run or non-live run → Not applicable; **intraday live run is alerting** (stamped → Executed, null → Unknown); M18 per run → Not applicable even when approvals, stage changes and same-day signals exist | I4 |
| T1A-6 | **Honest missing states**: 1B and Phase 2 fields return their status words; a superseded run's feature snapshot re-pointed to the newer run shows "Not observed for this run"; runs before the context column show "Not observed" for sectors | G1, G2, R-add |
| T1A-7 | **No text inference**: injecting misleading reason text changes no state, count or label | I2, G2 |
| T1A-8 | **Per-stock influence never claimed**: every per-stock response says influence is not recorded, whatever the run-level module states | G3 |
| T1A-9 | **Owner-only, read-only**: non-owner gets 403 on every route; the route table under the prefix holds only GET | owner access |
| T1A-10 | **Redaction, including free text** [R4-C6]: seed a local run's `error`, trace reasons, decision reasons, evidence text, downgrade and overrule reasons with each secret kind in 3.4: a real-looking value of each CLAUDE.md secret setting (set in the test env), `postgresql://u:p@h/db`, an email, a JWT, `api_key=…`, a 40-character hex token. Every route's response contains none of them, each affected field has `redacted: true`, and the surrounding text is unchanged. A response with no secrets is byte-identical to the stored text | redaction, C6 |
| T1A-11 | **Stock lookup**: a symbol present as both idea and holding returns both; lookup by decision id is exact; a foreign run's decision id gives 404 | I5 |
| T1A-12 | **Effectiveness rule**: section 8 "Effectiveness" tests | I8, R5 |
| T1A-13 | **Page equals API**: headless browser on the demo run; every displayed number equals the API value; Phase-2 panels show the deferred wording | acceptance, G2 |
| T1A-14 | **Day counts** [R4-C3]: universe size, idea decisions, holding decisions, words and tracked count equal SQL for 3 real local days. A fixture outside `universe − holdings ≤ ideas ≤ universe` shows Conflicting records; one inside shows both numbers with no claim. Tracker rows are labelled day-level | original requirement 7, C3 |
| T1A-15 | **No side effects** [R4-C5]: snapshot row counts and `max(updated_at/created_at)` of every table, call every route with valid and invalid parameters, and compare: unchanged. A route forced to attempt a write gets a Postgres read-only error. Import test: the package does not import `brain.service`, `brain.runner`, `brain.queue`, `brain.alerts`, `brokers`, `notifications` or Redis clients | C5 |
| T1A-16 | **Bounded queries** [R4-C5]: an SQLAlchemy statement counter keeps every route at ≤ 12 statements on a 300-stock fixture run (no per-row queries); a 93-day range gets 422; list routes cap at 500 rows with a page cursor; `statement_timeout` is set (checked with `SHOW statement_timeout` inside the request) | C5 |
| T1A-17 | **Executed vs Used, inferred, conflicting, multiple attempts** [R4-C1, C2]: fallback, rejected and shadow lines are Executed but never Used; expected and not-observed values carry `inferred: true`; `modules`=off with a `used` line shows Conflicting records; two lines for one module shows Conflicting records; a module missing from the current manifests shows Unknown; a day with a superseded rerun counts only the live non-superseded nightly and lists the other run separately; two live non-superseded nightlies show Conflicting records | C1, C2 |

### Effectiveness (runs in 1A)

| ID | Test | Closes |
|---|---|---|
| TE-1 to TE-7 | One test per condition E1–E7: the registry with that condition broken (wrong protocol hash, moved tag, wrong report hash, numbers differing from the report, "seen" sample, minimum not met, mismatched subject) never yields Proven, and yields the specified word | I8 |
| TE-8 | With every condition met on a synthetic passing fixture, the page shows Proven only for the claim whose subject matches | I8 |
| TE-9 | Real registry vs real `wf_v1` files: both parts Not proven, numbers 7/21 and 9/21 | I8 |
| TE-10 | Forward trial never shows Proven, at any count | I8, R5 |
| TE-11 | **Failed pass rule, each half** [R4-open]: folds-won share ≥ 60% with a negative extra check → Not proven; extra check positive with share < 60% → Not proven; both met → passes E6 only | I8 |
| TE-12 | **Independence** [R4-open]: `exposure_disclosed` with every other condition met → "Pass with disclosed exposure (not proof)", never Proven; `unaudited` → same; `untouched` without an audit file at its committed path → Verdict record invalid; real registry for wf-protocol-v1 records `exposure_disclosed` | I8 |

### Phase 1B (only if waived)

| ID | Test | Closes |
|---|---|---|
| T1B-1 | **Three-way equivalence**: unchanged baseline commit vs 1B with recording OFF vs 1B with recording ON, for nightly, intraday and why runs. Identical: decisions (all fields), brain strategy signals, paper orders and positions. Run on a fixture day and on one real stored day | I6 |
| T1B-2 | **Runner branches**: each branch (off, error, bad output, too slow, not permitted, shadow, used, step fallback) gives the same `status` and merged context as baseline, plus the right `outcome` | I4, I6 |
| T1B-3 | **Fallback and timeout boundaries**: a module finishing just under, and just over, its budget gets the same decision under baseline / OFF / ON | I6 |
| T1B-4 | **Build exception**: injected exception in row building → zero rows, `failed` plus error, decisions identical to OFF | I6 |
| T1B-5 | **Insert failure**: injected database error on insert → savepoint rollback, zero rows, `failed`, decisions committed | I6 |
| T1B-6 | **Outer failure**: injected commit failure → no run, no decisions, no evidence (all-or-nothing as today); documented, not hidden | I6 |
| T1B-7 | **Completeness**: missing row, extra row, row linked to another run's decision, missing mandatory section, `null` with and without a reason code, zero-decision run. Each gives the specified status | I5 |
| T1B-8 | **Epochs**: a run after `enabled_at` without evidence → Not observed; before → Before recording began; `disabled_at` → Switched off | I7 |
| T1B-9 | **Versions**: code version, fingerprint (no values inside), model versions and expected modules present on every run | rev 2 #6 |
| T1B-10 | **Deploy compatibility**: migration upgrade and downgrade on a restore-drill copy of the prod schema; the previous commit's code runs a nightly against the migrated schema (rollback safety) | I7 |
| T1B-11 | **Capture timing**: `evidence_ms` recorded; under 1 s for 300 stocks locally | I7 |
| T1B-12 | **Storage**: every section 7 term filled from measured values, backups included; the larger of compressed and uncompressed used; the owner's disk check recorded; pass condition met | I7 |
| T1B-13 | **Switch lifecycle** [R4-open]: worker start with the setting on (no epoch) opens one; restart unchanged adds nothing; off closes it; runs store their setting, and the three "no row" meanings in section 4 hold | I7 |
| T1B-14 | **Decision-time view** [R4-open]: evidence equals the view object M08 received (identity check in a test), not the end-of-run context; a contribution merged by Learn after Decide is absent from the evidence | I5 |

### Phase 2

| ID | Test | Closes |
|---|---|---|
| T2-1 | **Every draft branch** (6 idea and 2 holding codes) produces its code and correct words | I3 |
| T2-2 | **Multiple ordered downgrades**: TRADE → WATCH → WAIT across two rules, in engine order; then a third rule `already_cautious` | I3 |
| T2-3 | **Continuity and coverage**: every path satisfies 5.2 rules 1–6; a test fixture with a missing middle step, a broken from/to, a duplicated rule or a missing applicable rule is rejected → run `failed` | I3, I5 |
| T2-4 | **Disabled vs inactive vs module off**: rule id in `policy.disabled` → `disabled_rule`; sector gate with TOP_N=0 → `inactive_setting`; M11 off → provider `fallback:state` with `step_fallback`; none of the three shows `passed` | I1, I2 |
| T2-5 | **No unsupported credit**: M11 off, M11 failed, M06 shadow → never a provider and never in changed-by; credit only via `module_used` provenance on a `changed` step | I2 |
| T2-6 | **Constitution transitions**: each check changing TRADE → WATCH, and passing, recorded once each | I3 |
| T2-7 | **Fallback decisions and holdings**: M08 off → a single fallback-stage path; holdings paths include the track step | I3 |
| T2-8 | **Recorder exception**: forced exception inside the recorder → decision identical to OFF, path `broken`, run evidence `failed` | I6 |
| T2-9 | **M08 latency, local**: 20 timed runs each OFF and ON on the same fixture and machine; pass when the median increase is under 10% and p95 is under 50% of M08's nightly budget | I7 |
| T2-10 | **Budget boundary**: M08 near its budget with ON does not cross it where OFF did not (tested with an injected clock) | I6 |
| T2-11 | **Rejection counts**: primary counts add up to non-TRADE ideas; overlaps equal the fired steps | R2 |
| T2-12 | **Three-way equivalence**: as T1B-1, for the Phase 2 commit | I6 |
| T2-13 | **Path is write-only**: source check that no condition in M08, the constitution or the strategy reads `path` | I6 |
| T2-14 | **Fallback coverage** [R4-open]: each `FALLBACKS` entry exercised. Decide fallback paths per branch; perceive, state and reason fallback records carry `step_fallback` provenance even in a step where a module was used for other records; risk with no module → `input_missing` at the constitution | I3, I2 |
| T2-15 | **Default provenance** [R4-open]: a list of every default-substitution site in M08, the constitution and the fallbacks is checked against the code (a new site without recorder support fails the test); each reports `default_value`; none is inferred | I2 |

### Production acceptance (any phase that is deployed) [R3-7]

| ID | When | Check |
|---|---|---|
| P-1 | Before deploy | Owner approval of the phase. For 1B or 2: written waiver (1.3). CI green on that phase's tests. Deploy within the P1 window |
| P-2 | **First prod nightly after deploy** | Run `done`; no module newly Failed or Not observed vs the previous night. Counts [R4-C4]: `universe − holding decisions ≤ idea decisions ≤ universe`, Holding decisions are shown next to the open positions the prod API reports just before the run. A difference is **flagged for review**, not failed, because runs do not store their holdings list. All decisions are never compared with universe size. For 1B / 2: `evidence_status=complete`, membership exact, final words match. One stock's page read end to end. Result logged in the tracker Daily log and ob11 |
| P-3 | **Follow-up, 5 nightly runs after** (1B / 2) | Comparable latency: M08 `ms` and total run `ms` from the step log, nightly runs only, same universe count. The 5 nights before vs the 5 after; pass rule as T2-9 (median under 10%). Plus each night `complete` and storage growth within the estimate |
| P-4 | **Rollback, rehearsed before deploy** | Locally: (a) switch recording off and restart → runs show Switched off, decisions unchanged; (b) revert commit on the migrated schema → nightly runs (T1B-10). On prod the owner performs (a) or (b) per `docs/DEPLOY.md` (revert and push, never force-push) |

## 9. What is pending

| Item | Status |
|---|---|
| Phase 1A | scope in section 10, awaiting owner approval to **implement**; deploy needs a separate approval within the P1 window |
| Phase 1B | **unapproved**; not permitted under current policy without a written waiver; open items resolved on paper in section 4 |
| Phase 2 | **unapproved**; after the trial, or an explicit trial-policy decision |
| Owner decisions | (1) copy P1 / P2 into a repo policy file (1.1); (2) the trial-continuity (pooling) rule before any waiver (1.3); (3) where to commit the independence audit (6.2) |

## 10. Phase 1A — exact implementation scope (for approval) [R4]

**Files created**

| Path | Purpose |
|---|---|
| `backend/src/swing_trade_ml/services/brain_observatory/__init__.py` | package |
| `.../brain_observatory/queries.py` | read-only, bounded SQL over existing tables (3.1) |
| `.../brain_observatory/health.py` | module-health derivation (3.2): pure functions over stored `modules` / `trace` / run row, plus the inferred step map read from current manifests |
| `.../brain_observatory/counts.py` | day counts and the universe / idea / holding relation (3.1) |
| `.../brain_observatory/redact.py` | the 3.4 redaction pass |
| `.../brain_observatory/verdicts.py` + `validation_verdicts.json` | section 6 rules E1–E7 and the registry (wf-protocol-v1 = fail / fail, `exposure_disclosed`) |
| `backend/src/swing_trade_ml/api/v1/endpoints/brain_observatory.py` | the 3.3 GET routes, `require_owner`, read-only transaction and `statement_timeout` (3.5) |
| `backend/tests/test_brain_observatory_*.py` | T1A-2 to T1A-17, TE-1 to TE-12 |
| `frontend/src/trademind/pages/Observatory.tsx` | the page (3.3), mockup layout, deferred-panel wording |

**Files edited (additive only)**

| Path | Change |
|---|---|
| `backend/src/swing_trade_ml/api/v1/router.py` | one `include_router` line for the new endpoint module |
| `frontend/src/api/client.ts`, `frontend/src/api/types.ts` | Observatory calls and types |
| `frontend/src/trademind/TradeMindApp.tsx` (and its route table) | "Observatory" under Brain Logs, **shown only when `ownerConsole`**; route added |

**Explicitly not touched:**
- `brain/` (runner, service, contracts, modules, constitution, fallbacks, alerts)
- `strategies/`, `services/execution.py`, `services/risk.py`, other `services/`
- `workers/`, `db/models/`, `alembic/`, `infra/`
- `.env*`, the frozen protocol file

No migration, no scheduled job, no new setting, no runner or decision-time change, **no Phase 1B
instrumentation**.

Reused **read-only**: existing models and `services/costs.py`. `brain/trial_journal.py` helpers are used
only if the import test (T1A-15) shows they have no side effects; otherwise the calculation is copied
read-only into `queries.py`.

**Done means:**
- all T1A and TE tests green locally (with Docker Postgres up)
- `npx tsc --noEmit -p .` clean
- the scope guard (T1A-1) output pasted
- a real local nightly run shown on the page with screenshots, and T1A-3 / T1A-13 compared against SQL
- deploy is **not** part of done; it is requested separately (P-1, P-2)

## 11. Source verification for rev 4 [R4-C7]

Checked on 2026-10-15 against the working tree and git.

| Claim in this spec | Checked against | Result |
|---|---|---|
| P1 tracker note text | System Atlas artifact HTML, Pending work intro | matches |
| P2 br2 title and note | tracker `tasks/br2` | matches |
| P3 freeze line | `docs/brain/ROADMAP.md:11` | matches |
| P4 forward gate (15 sessions, 30 ideas, "change them only before looking at a result") | layer-2 draft section 5a | matches |
| P5 approval rule | `CLAUDE.md` Risk rules | matches |
| wf-protocol-v1 minimums and 60% rule | protocol section 5 at `HEAD` (= tag) | matches |
| Verdict fail / fail, 7 / 21, 9 / 21 | report `.md` and `.json` `verdict` | matches (6.2) |
| Tag commit | `git rev-parse wf-protocol-v1` → `7b97291` | recorded |
| Protocol "section 4a" independence audit | working tree vs `HEAD` | **uncommitted; rev 3 citation corrected** (6.2) |
| M16 alerting kinds | `brain/alerts/service.py:26` `{"nightly", "intraday"}` | **rev 3 was wrong about intraday; corrected** (3.2, T1A-5) |
| M16 stamp on "nothing to tell" | `_mark_checked` | matches |
| Feature snapshot rerun re-points `run_id` | `service._store_snapshots` `on_conflict_do_update` sets `run_id` | matches |
| Ideas only for stocks not held | `m08_decide/module.py` (`if symbol not in held`) | matches; basis of C3 / C4 |
| `brain_track` has no run link | `db/models/brain.py` `BrainTrack` | matches |
| v1 signals not linked to a run | `signals` model, no run column | matches |
| Fallbacks always run after modules, merge never overwrites | `runner.execute` comment and code | matches; basis of per-record provenance |
| `GET /brain/why/{symbol}` writes a run | `api/v1/endpoints/brain.py` `why` calls `service.run_brain` | matches; motivates 3.5 |
| `require_owner` exists | `api/deps.py:217` | matches |
| Brain Logs menu visible to all; owner pages gated by `ownerConsole` | `TradeMindApp.tsx` | matches; the entry must be gated |

## 12. Addendum: last Phase 1A corrections (rev 4a)

A self-review of rev 4 found these Phase 1A points. Fixes 1–3 are applied in the text above; 4–7 are
binding here. Nothing else changes.

| # | Correction |
|---|---|
| 1 | Section 0 said "verbatim"; it now says "as stored, only redacted (3.4)", matching 3.4 |
| 2 | A day-level table row ("Brain strategy signals …") had been cut off from its table; restored. No change in meaning |
| 3 | "No nightly run" uses the existing trading calendar (`core/holidays.is_trading_holiday`): a trading day with no run → Not observed; weekends and holidays → Not applicable. Test: T1A-17 adds a holiday fixture |
| 4 | **Day assignment**: a run belongs to the IST date of its `as_of` (`as_of.astimezone(IST).date()`, per CLAUDE.md), not `started_at` and not UTC. Test: T1A-14 adds a run whose UTC and IST dates differ |
| 5 | **Redaction scope**: rules 2–6 apply only to free-text fields. Structured fields (run id, decision id, symbol, words, numbers, timestamps) are never altered. Run ids (`<kind>-YYYYMMDDTHHMMSS-<6 hex>`) cannot match rule 6 (32+ characters). Test: T1A-10 adds a free-text field holding a run id and a symbol, which stay unchanged |
| 6 | `/outcomes` wording aligned with section 10: `services/costs.py` is used; `brain/trial_journal.py` is used only if the T1A-15 import test shows it has no side effects |
| 7 | **No-side-effect check made exact** (T1A-15): not every table has timestamps, so the test compares `pg_stat_user_tables` insert/update/delete counters for **all** tables before and after calling every route (after `pg_stat_clear_snapshot()`), plus row counts. **Read-only enforcement**: the Observatory routes use their own session, and its **first** statement is `SET TRANSACTION READ ONLY`. Auth runs before it and does not share that transaction. The test checks that `SHOW transaction_read_only` returns `on` inside a route |

**Phase 1A scope (section 10) is unchanged by this addendum.**


## 13. Addendum: the four questions and one source of truth (2026-10-15)

Adopted with the evidence plan (`docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md`, task A2/A3).
Phase 1A answers only these four questions; anything that answers none of them is out of 1A:

| Question | Where it is answered in 1A |
|---|---|
| 1. What did the brain decide? | run, day counts, per-stock final word (3.1) |
| 2. Why did it decide that? | stored reasons, evidence sentence, "originally X / last downgrade reason", module health (3.1, 3.2); the full path stays Phase 2 |
| 3. What happened afterwards? | graded outcome, `/outcomes` (3.3) |
| 4. Compared with what? | `/outcomes` baselines: every stock (matched random), 5 strongest 20-day risers, NIFTY over the same holding days, cash; `/effectiveness` verdicts (section 6) |

**One source of truth:** finished-idea results (gross, costs, net, baselines) are computed by one read-only
function in `services/brain_observatory/` over `brain_decisions` and `services/costs.py`. Other screens
that later show brain idea results call it rather than computing their own. Changing existing screens to
use it is not part of 1A (it would touch files outside section 10); it is task A3 of the evidence plan.

The momentum baseline is added to `/outcomes`; it is computed from stored daily candles as of each idea's
decision day, read-only, and labelled "Observed, not proof" like the rest of `/outcomes`.

**Phase 1A scope (section 10) is otherwise unchanged.**

## 14. Rev 4b and plan revision 2 (owner review of the plan, 2026-10-15)

Requirements R1–R9 and corrections C1–C10 in `docs/superpowers/plans/2026-10-15-brain-observatory-phase-1a.md`
are part of this spec: independent health flags and counts; single-source vs conflicting records; the
recording card "Existing records only — partial visibility."; sourced outcome, cost and benchmark figures
with honest unavailable states; numerical verdict separate from independence with fixed precedence; claims
and minimums bound by code; CI integrity checks against git objects; missing-run checks using holidays and
deadlines; database-enforced read-only transactions with isolated write tests; redaction that never alters
ids or cursors; book and category separation; no silent truncation; committed test rows only in the
dedicated test database.

Owner approved on 2026-10-15: scope additions S1 (view-time outcome calculations, using the locked
evidence-defs-v1 trade-level baselines) and S2 (CI checkout `fetch-depth: 0`); publishing tags
`wf-protocol-v1` and `evidence-defs-v1`.

Two corrections to earlier sections:
- 3.3 `/outcomes`: the figures are computed at view time from stored prices (section 13's one function,
  category required) and labelled so; only the M09 grades are stored records.
- 6.3 learning changes: "No frozen protocol yet", by the precedence rule, since no protocol exists for them.
