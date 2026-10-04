# TradeMind One App: Technical Design (backend)

Date: 2026-10-04 · Status: proposed, implementation not started · Branch: `brain/universe`
(production = `0c7bf1b`).

**Scope.** The 5-section UI (Decisions · Discover · Portfolio · Performance · Settings) is fixed
as proposed to the owner on 2026-10-04; see `docs/superpowers/plans/2026-10-04-one-app-trademind.md`
and memory `project-one-app-trademind`. **This document does not change the UI.** It reviews the
backend underneath it and lists the changes the UI needs to be correct, auditable and safe.

Every "current state" claim below was read from the code on 2026-10-04 (paths are under
`backend/src/swing_trade_ml/`).

---

## 0. Summary of findings

| # | Area | Current state | Risk | Change |
|---|---|---|---|---|
| 1 | Decision lifecycle | Implicit. A brain decision row is created by a run, then **mutated** by overrule (`overruled_*`) and by learning (`outcome*`). Approvals live in another table. Orders and positions link through a JSON field. | The UI can't show one honest timeline: "recommended, then overruled, then approved, then bought, then closed". | Explicit lifecycle with states and append-only events (§1). |
| 2 | Immutable recommendations | `brain_decisions` is updated in place (`service.overrule`, M09 scoring). A second overrule **overwrites** the first. | The record of what the brain said can't be trusted. Past overrules are lost. | Recommendations are write-once. Owner actions and outcomes go in their own tables (§2). |
| 3 | Asynchronous brain runs | `POST /brain/runs` runs the brain **inside the HTTP request** (`service.run_brain`). On prod a 304-stock run takes about 165 s, against nginx's 60 s, so it returns 504. There is no run lock, so a manual run and the 15:50 job can overlap. Status is only `done`/`failed`. | "Run the brain now" shows a false failure. Overlapping runs make "today's run" ambiguous. | Queued runs, single-flight lock, `queued/running/done/failed`, and a publish rule (§3). |
| 4 | Portfolio and risk aggregation | Portfolio rules (`risk.open_holdings`) count every open position **in the current mode**. The owner's hand-bought shares are stored as mode `live`. In paper mode they are **ignored**; in live mode they are **mixed in** with the bot's. There is no "money at risk if every stop is hit". | Sector limits and "how much to invest" are wrong for the owner's real total. | One exposure service, with explicit scopes `bot` / `own` / `all` (§4). |
| 5 | Decision and version tracking | A run stores module **modes** only. It does not store the code version, the model id or version per company size, the M06 artifact, the buy level, the locked trade rule, the universe size or the data date. | You can't explain why the brain said X on day Y, or compare versions. | A version stamp on every run, carried to signals and orders (§5). |
| 6 | Audit trail | Only stage changes are audited (`brain_stage_changes`). Halt and resume overwrite one `system_state` row. Module modes, strategy on/off, watch list edits, overrules, proposals and closes either keep only the last value or nothing. | You can't answer "who stopped trading on Tuesday, and why?" | One append-only `audit_events` table, written by every owner action (§6). |
| 7 | Market session state | Four separate helpers: `ingestion.is_market_open`, `approvals._market_open`, `m01 quality.is_trading_day`, `m09 scoring.last_closed_trading_day`, plus `core/holidays.py`, which covers **2025–2026 only**. | The helpers can disagree. In 2027 every holiday is treated as a trading day. | One `market_session` service and endpoint. It fails loudly when a year's holidays are missing (§7). |
| 8 | Signal vs final decision | The brain's word, the owner's overrule and the v1 `Signal` (with `was_executed` / `rejection_reason`) are mixed together. Approvals re-read "the latest run" rather than the recommendation the owner approved. | It is unclear what the owner approved compared with what was executed. | Three named layers: Signal, Recommendation, Final decision (§8). |

---

## 1. Decision lifecycle

### States

```
RECOMMENDED ──► (owner) OVERRULED ─┐
     │                              │
     ├─► AWAITING_OK ─► APPROVED ─► ORDERED ─► OPEN ─► CLOSED ─► SCORED
     │        │            │           │
     │        ├─► REJECTED  ├─► EXPIRED └─► FAILED (not filled / refused)
     │        └─► EXPIRED
     └─► NOT_ACTED (practice stage, WATCH/WAIT/AVOID, or blocked by risk) ─► SCORED
```

- Ideas follow the chain above. Holdings use the same machine with HOLD / MONITOR / REDUCE / EXIT.
  For a holding, ORDERED means a sell order.
- **The state is derived, not stored**, from the recommendation plus its events (§2). This keeps
  the lifecycle impossible to corrupt. A view, `decision_timeline`, returns ordered events per
  recommendation for the UI's "Why" drawer.

### Backend changes
- `services/decisions/lifecycle.py`: `state_of(recommendation_id)` and `timeline(recommendation_id)`
  are pure functions over events.
- `GET /decisions/{id}/timeline` returns ordered events: who, what, when, why.

---

## 2. Immutable recommendations

### Rule
A row in `brain_decisions` is **write-once**. After the run commits, nothing updates it.

### Changes
| Today (mutable) | New home (append-only) |
|---|---|
| `overruled_word / overrule_reason / overruled_by / overruled_at` on the decision | `decision_events(kind='overrule', from_word, to_word, reason, actor, at)` |
| `outcome, outcome_return, outcome_days, max_up, max_down, resolved_on` written by M09 | `decision_outcomes(recommendation_id PK, …)`, one row, written once when resolved |
| Approval status changes on `brain_approvals` rows | `brain_approvals` stays the working table. Every transition also appends a `decision_events` row (`awaiting_ok`, `approved`, `rejected`, `expired`, `ordered`, `failed`). |

- **Effective word** = the latest `overrule` event's `to_word`, otherwise the brain's `word`. This
  replaces `overruled_word or word` everywhere: `strategies/brain.py`, `approvals.py`,
  `m09_learn`, the API serialisers.
- **Same-day carry** (shipped in `0c7bf1b`, `service._carry_overrule`) becomes an event too. When a
  new run supersedes an overruled recommendation on the same IST day and book, a
  `carried_overrule` event is written on the new recommendation, pointing to the original event.
  Nothing is copied into columns.
- DB guard: a trigger on `brain_decisions` rejects `UPDATE` (except a one-off backfill role).
  Tests assert that no code path issues an UPDATE.

### Migration (additive, no downtime)
1. Create `decision_events` and `decision_outcomes`.
2. Backfill: each decision with `overruled_word` gets an `overrule` event. Each with `outcome`
   gets an outcome row.
3. Switch readers to the new tables. Keep the old columns for one release, read-only, then drop
   them in a later migration.

---

## 3. Asynchronous brain runs

### Changes
- `brain_runs.status`: `queued | running | done | failed | superseded`, plus `requested_by`,
  `requested_at` and `finished_at`.
- `POST /brain/runs` **enqueues** and returns `202 {run_id, status:'queued'}` at once. The
  **worker** process, which already owns the scheduler, executes it. The web process never runs
  the brain.
- **Single flight:** a Postgres advisory lock per `(kind, book)`. A second request while one is
  queued or running returns the existing `run_id` ("already thinking"). The 15:50 job uses the
  same path.
- `GET /brain/runs/{id}` returns the status and progress (`steps_done`, plus `symbols_done` /
  `total`, updated every N stocks).
- **Publish rule:** "today's run" for the strategy, approvals and the Decisions page is the latest
  `done` live nightly run for the IST day and book. A run that is still running is never read.
  When a newer run finishes, older same-day runs are marked `superseded` (status only; their
  recommendations stay immutable).
- **Delivery mechanism:** a `brain_run_requests` table polled by a worker job every 10 s. This
  needs no new infrastructure. Redis/RQ would also work, but polling is enough here.
- The UI contract changes only in that "Run the brain now" shows "Thinking… (x of 304)" and
  then the result.

---

## 4. Portfolio and risk aggregation

### Changes
- `services/exposure.py` builds one `Exposure` snapshot:
  - **Scopes:** `bot` (the bot's book in the current mode), `own` (the owner's real holdings,
    `real_trading`), `all`.
  - **Per stock:** shares, value, stop, money at risk (`(price − stop) × qty`; stop missing →
    flagged).
  - **Per sector:** value and % of the scope.
  - **Totals:** invested, cash, "if every stop is hit you lose ₹X", deployable today (regime
    fraction).
- `risk.check_entry` sector and concentration rules read `Exposure(scope='all')`. **Policy
  ruling needed from the owner:** do the owner's own shares count toward the 25% sector cap and
  the one-per-sector rule? Recommended: **yes**. The account's risk is the account's.
  Position-slot limits stay bot-only.
- Fixes the accidental mode mixing. The `own` scope is always the real book, whatever
  `TRADING_MODE` is.
- `GET /portfolio/exposure?scope=bot|own|all` feeds Portfolio and the Decisions "How much to
  invest" card.
- The brain's M14 portfolio module reads the same service, so the brain and the safety check
  agree.

---

## 5. Decision and version tracking

### Run stamp (new JSONB `brain_runs.versions`, filled at run start)
- `code`: the release git SHA. Pass `RELEASE_SHA` into the api and worker containers as an env
  var in `docker-compose.prod.yml`; it already exists in `release.sh`.
- `models`: `{tier: {id, name, version}}` for each active `ml_models` row used, plus the M06
  artifact name and version if loaded.
- `modules`: `{id: {mode, version}}` (the manifest version as well as the mode).
- `policy`: buy level in force (default or accepted proposal id), the locked rule (+8% / −4% /
  15 trading days), market mode thresholds, and the slot share.
- `data`: latest candle date, `feature_set_version`, universe size and hash.

### Propagation
- `signals.brain_recommendation_id` (FK, nullable) and `signals.brain_run_id` replace the JSON
  `features.brain_decision_id`.
- `orders.recommendation_id` is copied from the signal when an order is placed for a brain idea.
  An order then traces back to a run, and through the run to its versions.
- `GET /brain/runs/{id}` includes `versions`. Performance groups results by `versions.code` and
  `versions.models` ("brain vs v1" and "this version vs the last").

---

## 6. Audit trail

### New table `audit_events` (append-only, DB trigger blocks UPDATE/DELETE)
`id, at, actor, actor_kind (owner|system|job), action, target_type, target_id, before (jsonb),
after (jsonb), reason, request_id`.

### Written by (one helper, `services/audit.record(...)`)
- Stop / allow new trades (`safety`): before and after state, plus the reason.
- Strategy on/off, brain module mode, brain stage change (also kept in its own table).
- Overrule, approve, reject, expire (system), close position, "I sold this", import holdings,
  sync and tradebook upload.
- Watch list edits, proposal accept/reject/revert, telegram test, refresh prices, run-now
  request.

`actor` comes from the authenticated user, **not** the client body. Today `by` on
approve/reject/stage is client-set; this fixes an M18 deferred minor. `GET /audit?since=&action=`
feeds a "History of changes" list under Settings.

---

## 7. Market session state

### `core/market_session.py`, the single source of truth
- `session(now) -> {state: PRE_OPEN|OPEN|CLOSED|HOLIDAY|WEEKEND, trading_day, next_open,
  next_close, last_closed_trading_day}`. The times come from `settings.MARKET_OPEN_TIME` and
  `MARKET_CLOSE_TIME`.
- Holiday calendar: the existing `core/holidays.py` data, with special sessions (e.g. Muhurat).
  **Coverage check:** asking about a year with no holidays raises `CalendarMissingError`. A daily
  health check warns 60 days before year end.
- All four current helpers are replaced by calls to it:
  - `ingestion.is_market_open`
  - `approvals._market_open`
  - `quality.is_trading_day`
  - `scoring.last_closed_trading_day`
- `GET /market/session` feeds the top bar ("Market open · closes 3:30 pm") and the after-hours
  wording in dialogs.
- Order paths (approvals, close position) consult it: in live mode a market order outside
  `OPEN` is refused with a plain reason. This prepares for the after-close-orders blocker; it
  does not solve it.
- Add the 2027 NSE holidays once published.

---

## 8. Signal vs final decision

### Three named layers
| Layer | What it is | Table | Mutable? |
|---|---|---|---|
| **Signal** | A raw model opinion per stock per day (v1 classifier score, or a brain module opinion) | `signals` (v1), `brain_runs.trace` (brain) | v1: execution columns move out (below) |
| **Recommendation** | The brain's word, levels and size for a stock in one run | `brain_decisions` | **No** (§2) |
| **Final decision** | What the account will actually do: the recommendation, plus owner events, plus stage, plus risk at order time | derived (`lifecycle.state_of`), materialised as `decision_events` and `orders` | Append-only |

- v1 `signals.was_executed / rejection_reason` describe execution, not the signal. They are kept
  for compatibility, but new code writes the outcome to `decision_events` (for brain ideas) or
  `risk_events` (v1). Moving them out of `signals` fully is a later cleanup.
- **Approval binding:** `brain_approvals.recommendation_id` is the recommendation the owner saw.
  At order time it is re-validated against the **latest published** recommendation for that stock
  (as today). If the effective word is no longer TRADE, the levels moved outside tolerance, or the
  stage changed, it expires with a plain reason. Both ids are stored on the `ordered` / `expired`
  event, so the owner sees what was approved and why it was or wasn't bought.
- The Decisions page reads **final decisions**: Needs attention, Waiting for your OK and Worth
  buying are all lifecycle states, not raw words.

---

## 9. Endpoints the 5-section UI reads (no UI change; data only)

| Section | New or changed endpoints |
|---|---|
| Decisions | `GET /attention` (one list: holdings MONITOR/REDUCE/EXIT across `all`, approvals waiting or expiring, data/broker issues; drives the 🔔 count), `GET /portfolio/exposure?scope=all`, `GET /market/session`, existing latest run (now published-only) |
| Discover | unchanged (latest published run, watch list, v1 picks) |
| Portfolio | `GET /portfolio/exposure?scope=…`, `GET /decisions/{id}/timeline` |
| Performance | results grouped by `versions`; outcomes from `decision_outcomes` |
| Settings | `POST /brain/runs` → 202 + `GET /brain/runs/{id}`; `GET /audit` |

The per-idea "₹ amount and shares" already exists: `brain_decisions.qty` is M07's allocator
quantity. The UI only needs to show `qty × entry`. No backend change is needed.

---

## 10. Order of work (each step ships alone, tests first)

1. **Async runs + single flight** (§3). Fixes the prod 504 and overlapping runs. Smallest, most
   visible.
2. **Market session service** (§7). Unifies the four helpers and adds the calendar coverage
   check.
3. **Audit events** (§6) and actor from auth. Needed before more owner actions are added.
4. **Immutable recommendations + decision events + outcomes table** (§2, §1, §8), with backfill
   migration.
5. **Version stamp + FK links** (§5).
6. **Exposure service + risk using scope `all`** (§4), after the owner's ruling on counting own
   shares.
7. `GET /attention`, then the UI reshuffle into 5 sections reads these.

## 11. Open owner decisions
1. Do your own Zerodha shares count toward the sector limits (recommended: yes)?
2. Keep superseded same-day runs visible in Performance or hide them (recommended: hide; keep
   them in the audit)?

## 12. Not in scope
UI layout (fixed). Fundamentals, news and macro data. After-close order method (separate live
blocker). Paper +435% bug (separate, awaiting OK).
