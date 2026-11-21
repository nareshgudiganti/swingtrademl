# Groww Holdings Sync (phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing Groww Tracker equal to the owner's real Groww holdings (stocks, quantity, average price) with no daily login, preserving every manual entry.

**Architecture:** A read-only Groww client (token + holdings only) feeds an append-only sync log. Confirmed ISIN→stock matches drive updates to the existing `user_watchlist_items` rows, with every overwritten value kept in a change history. Kite remains the price source (held stocks are added to the daily candle top-up as unwatchlisted symbols). The tracker's existing advice keeps recomputing from the synced values.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Postgres, Redis, APScheduler, httpx, pyotp; React + TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-21-groww-sync-design.md` (read it first; this plan argues from it).

## Gates (do not skip)

- **G0a — One fetch + UI fit check (owner, 2026-11-21).** Owner runs `groww_probe.py fetch`, confirms values match the Groww app, and Claude reports the existing-match / new / unmatched check and UI gaps. No schema change or recurring sync before this report is reviewed, even though G1 is approved.
- **G0 (renewal) — after a few trading sessions.** Owner runs `backend/scripts/groww_probe.py day1` then `day2` after 06:00 IST next day and pastes the output. No task below starts until day 2 prints `PASS`. FAIL, paid plan, static IP or approval tap = stop and report.
- **G1 — Schema approval.** APPROVED by owner 2026-11-21 (spec §7 as written).
- **Execution method:** owner chose subagent-driven (2026-11-21), to start only after G0 passes.
- **G2 — Owner review + Codex review** before anything reaches `main` (= prod).

## Global Constraints

- Work in a new worktree on branch `feature/groww-sync` from `origin/main` (superpowers:using-git-worktrees). Never bare `git stash`.
- Groww calls allowed: get access token (TOTP flow), get holdings. Nothing else, ever.
- Settings names: `GROWW_TOTP_TOKEN`, `GROWW_TOTP_SECRET` (blank → feature off). Add names only to `.env.example`. Never read `.env`.
- Owner-only: every Groww route depends on `require_real_account` (`api/deps.py:320`); 403 otherwise.
- Only a `complete` sync changes data. `partial`, `failed`, and `empty_unconfirmed` change nothing.
- Unknown values are `null` in the API and "—"/"no price yet" in the UI, never 0.
- IST everywhere: `core.market_session.IST`; candle dates via `.astimezone(IST).date()`.
- Held stocks must never enter `is_watchlisted`, any strategy list, or the brain universe.
- Format only touched backend files with ruff; frontend check `npx tsc --noEmit -p .`; no prettier on existing files.
- Tests: `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE backend/.venv/Scripts/python.exe -m pytest <path> -q` with Docker Postgres up.

## Review Focus

1. A complete sync returning zero holdings must not mark everything not-held → pinned in Task 3 (`test_empty_sync_changes_nothing_until_confirmed`).
2. A stock renamed on NSE keeps its ISIN → alias by ISIN must still apply; pinned in Task 3 (`test_saved_alias_reused_by_isin_when_symbol_changes`).
3. Sold fully, then bought again later → row goes not_held → held; buy date becomes the re-buy sync day with a history entry (my call); pinned in Task 4 (`test_rebuy_after_not_held_sets_new_buy_date_with_history`).
4. Owner tries to hand-edit quantity on a linked row → 409 with plain message; pinned in Task 5 (`test_patch_quantity_on_linked_row_refused`).
5. Refresh clicked twice / during the scheduled job → one sync runs, second gets "already refreshing"; pinned in Task 5 (`test_concurrent_refresh_returns_already_running`).

---

### Task 1: Schema (after G1)

**Files:**
- Create: `backend/alembic/versions/20261121_1200_groww_sync.py` (down_revision = output of `alembic heads`; must be a single head)
- Create: `backend/src/swing_trade_ml/db/models/groww.py` (`GrowwSync`, `GrowwHolding`, `StockAlias`)
- Modify: `backend/src/swing_trade_ml/db/models/user_watchlist.py` (4 columns on `UserWatchlistItem`; new `UserWatchlistItemChange`)
- Modify: `backend/src/swing_trade_ml/db/models/__init__.py` (register)
- Test: `backend/tests/test_groww_models.py`

**Interfaces — Produces:** tables/columns exactly as spec §7. Enum-like strings as module constants in `groww.py`: `SYNC_COMPLETE="complete"`, `SYNC_PARTIAL="partial"`, `SYNC_FAILED="failed"`, `SYNC_EMPTY="empty_unconfirmed"`; `MATCH_CONFIRMED`, `MATCH_SUGGESTED`, `MATCH_NEEDS="needs_matching"`; `HELD="held"`, `NOT_HELD="not_held"`, `HELD_UNKNOWN="unknown"`; `SOURCE_MANUAL="manual"`, `SOURCE_GROWW="groww"`. `StockAlias` unique `(provider, external_id)`.

- [ ] **Step 1: Failing tests** — `test_existing_rows_default_manual_unknown` (insert a `UserWatchlistItem` without new fields → `source=="manual"`, `held_state=="unknown"`); `test_alias_unique_per_provider_isin` (second `StockAlias("groww","INE002A01018")` raises `IntegrityError`).
- [ ] **Step 2: Run, expect FAIL** (import errors).
- [ ] **Step 3: Models + migration.** Migration additive only; server defaults `'manual'`/`'unknown'` so existing rows backfill; downgrade drops exactly what upgrade adds.
- [ ] **Step 4: Run tests + migration check** — tests PASS; `cd backend && ../backend/.venv/Scripts/python.exe -m alembic heads` shows one head; CI migration check script (added in 1ca0aa3) passes locally.
- [ ] **Step 5: Commit** `feat(groww): schema for sync log, holdings, aliases, watchlist link and history`

### Task 2: Read-only Groww client

**Files:**
- Create: `backend/src/swing_trade_ml/services/groww/__init__.py`, `backend/src/swing_trade_ml/services/groww/client.py`
- Modify: `backend/src/swing_trade_ml/core/config.py` (settings beside the Kite block), `.env.example`
- Test: `backend/tests/test_groww_client.py`

**Interfaces — Produces:**
- `BASE_URL = "https://api.groww.in"`, `ALLOWED_PATHS = frozenset({"/v1/token/api/access", "/v1/holdings/user"})`
- `class GrowwAuthError(Exception)`, `class GrowwUnavailable(Exception)`
- `def is_configured() -> bool`
- `def get_access_token(*, force: bool = False) -> str` — Redis cache key `groww:access_token`, TTL until next 06:00 IST; `force=True` skips cache.
- `def fetch_holdings() -> list[dict]` — returns the `holdings` list; on 401 calls `get_access_token(force=True)` once and retries once.

Token request body/headers for the TOTP flow: copy from the `growwapi` package source (download it into a throwaway venv; do not add it as a dependency) and confirm against G0's working probe. Use `httpx` (already a dependency), timeout 10 s. Redact: never log token, TOTP code, or response body.

- [ ] **Step 1: Failing tests** —
  - `test_only_allowed_paths_requested` (patch `httpx`'s transport with `httpx.MockTransport`; run token + holdings; assert every requested path ∈ `ALLOWED_PATHS`)
  - `test_module_has_no_order_surface` (`[n for n in dir(client) if any(w in n.lower() for w in ("order","place","cancel","modify"))] == []`)
  - `test_401_mints_once_then_raises_auth_error` (holdings returns 401 twice → exactly 2 token calls, `GrowwAuthError`)
  - `test_token_cached_until_6am_ist` (fake Redis; TTL equals seconds until next 06:00 IST)
  - `test_logs_never_contain_token` (caplog after a run does not contain the fake token string)
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** settings + client.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(groww): read-only client (token + holdings only)`

### Task 3: Sync and matching

**Files:**
- Create: `backend/src/swing_trade_ml/services/groww/sync.py`
- Test: `backend/tests/test_groww_sync.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `fetch_holdings`, `GrowwAuthError`, `GrowwUnavailable`.
- Produces:
  - `def clean_symbol(raw: str) -> str` — upper-case, strip a trailing `-EQ`/`-BE`/`-BZ` style suffix.
  - `def classify(rows: list[dict]) -> str` — `complete` if every row has non-empty `isin`, `trading_symbol`, numeric `quantity`, numeric `average_price`; else `partial`. Empty list → `empty_unconfirmed`.
  - `def match_rows(db, rows) -> list[tuple[dict, int | None, str]]` — (row, instrument_id, match_state): saved `StockAlias` by ISIN → `confirmed`; else exactly one NSE `Instrument` with `tradingsymbol == clean_symbol(...)` → `suggested`; else `needs_matching`.
  - `def run_sync(db, *, user_id: int, trigger: str) -> GrowwSync` — takes Redis lock `groww:sync_lock` (60 s); stores a `GrowwSync` + its `GrowwHolding` rows for every outcome; raises `SyncAlreadyRunning` if locked. Calls Task 4's `apply_sync` only when status is `complete`.

- [ ] **Step 1: Failing tests** — `test_clean_symbol` (`"RELIANCE-EQ"→"RELIANCE"`, `"m&m"→"M&M"`); `test_partial_when_any_row_missing_isin`; `test_failed_sync_recorded_and_holdings_untouched`; `test_empty_sync_changes_nothing_until_confirmed` (status `empty_unconfirmed`, every item's `held_state` unchanged); `test_saved_alias_reused_by_isin_when_symbol_changes` (alias ISIN→instrument A; payload symbol "NEWNAME" → `confirmed`, instrument A); `test_two_instruments_same_symbol_goes_to_needs_matching`; `test_repeat_sync_idempotent` (two identical complete syncs → item values identical, history rows only from the first).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(groww): sync log, completeness check and ISIN matching`

### Task 4: Apply a complete sync to the tracker

**Files:**
- Create: `backend/src/swing_trade_ml/services/groww/apply.py`
- Test: `backend/tests/test_groww_apply.py`

**Interfaces:**
- Consumes: Task 3 matched rows.
- Produces:
  - `def apply_sync(db, sync: GrowwSync, *, user_id: int) -> dict` — returns counts `{"updated","added","not_held","pending_sale","needs_matching"}`.
  - `def confirm_match(db, *, user_id: int, isin: str, instrument_id: int) -> None` — writes `StockAlias`, marks that ISIN's rows in the latest sync `confirmed`, then re-applies the latest complete sync.
  - `def confirm_all_suggested(db, *, user_id: int) -> int`
  - `def confirm_empty(db, *, user_id: int, sync_id: int) -> None` — flips an `empty_unconfirmed` sync to `complete` and applies it.
  - `def pending_sale_qty(db, item: UserWatchlistItem) -> float | None` — quantity drop since the last confirmed sale, from `user_watchlist_item_changes`.
  - `def groww_held_symbols(db) -> list[str]` — symbols with `held_state == "held"`.
  - `def is_currently_held_clause()` — SQLAlchemy condition: `held_state == "held"` OR (`source == "manual"` AND `held_state == "unknown"` AND `buy_price IS NOT NULL`). The single definition reports and the tracker share.

Rules exactly per spec §6 "Applying to the tracker". Every overwritten field writes one `UserWatchlistItemChange` (`changed_by="groww_sync"`, `sync_id`) before the update. `added_at` and `note` are never touched except the re-buy case below.

- [ ] **Step 1: Failing tests** — `test_confirmed_row_overwrites_qty_and_price_and_keeps_history`; `test_buy_date_and_note_never_change`; `test_topup_keeps_original_buy_date`; `test_unknown_holding_added_as_groww_source_with_sync_day_buy_date`; `test_watch_only_stock_untouched`; `test_partial_sale_updates_qty_and_sets_pending_sale` (`pending_sale_qty == 3`, no `UserWatchlistSale` row); `test_absent_isin_marks_not_held_and_stays_on_list` (`removed_at is None`); `test_suggested_rows_not_applied`; `test_rebuy_after_not_held_sets_new_buy_date_with_history`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(groww): apply complete syncs to the Groww Tracker with full history`

### Task 5: API, sale confirmation, scheduled sync, reports

**Files:**
- Create: `backend/src/swing_trade_ml/api/v1/endpoints/groww.py`
- Modify: `backend/src/swing_trade_ml/api/v1/router.py` (include router with `protected` deps)
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/my_watchlist.py` — tracker items gain `source`, `held_state`, `groww_synced_at`, `pending_sale_qty`; response gains `groww: {"configured", "last_success_at", "last_status", "last_attempt_at"}` (owner only, else omitted); `PATCH` refuses `quantity`/`buy_price` on `source=="groww"` or `groww_isin` rows (409 "This comes from Groww and updates on every sync."); `POST /{symbol}/sold` accepts optional `quantity` — when the row is Groww-linked it records the sale for that quantity and does **not** set `removed_at`.
- Modify: `backend/src/swing_trade_ml/services/idea_report.py:300-325` — `held_or_sold_symbols` uses `is_currently_held_clause()`.
- Modify: `backend/src/swing_trade_ml/workers/jobs.py` (`job_groww_sync`), `backend/src/swing_trade_ml/workers/scheduler.py` (weekdays 15:35 IST, before `daily_ingest` 15:40)
- Modify: `backend/src/swing_trade_ml/workers/jobs.py::job_daily_ingest` — after strategy lists, `ingestion.backfill_symbols(db, groww_held_symbols(db), interval="day")` in its own try/except so a failure never blocks the rest.
- Test: `backend/tests/test_groww_api.py`, extend `backend/tests/test_my_watchlist.py`, `backend/tests/test_idea_report.py`

**Routes (all `require_real_account`):** `POST /groww/sync` (Refresh; 429 if last attempt < 60 s; 409 `already refreshing`), `GET /groww/status`, `GET /groww/matching`, `POST /groww/matching/{isin}` body `{instrument_id}`, `POST /groww/matching/confirm-all`, `POST /groww/syncs/{sync_id}/confirm-empty`.

`job_groww_sync`: skip if not `is_configured()`; owner user = first username in `REAL_ACCOUNT_USERS`; call `run_sync(..., trigger="scheduled")`; errors go to `_report_error("groww_sync", exc)`.

- [ ] **Step 1: Failing tests** — `test_every_groww_route_403_for_non_owner` (parametrized over all routes); `test_patch_quantity_on_linked_row_refused`; `test_sold_with_quantity_keeps_row_on_list`; `test_concurrent_refresh_returns_already_running`; `test_refresh_rate_limited`; `test_tracker_includes_groww_status_for_owner_only`; `test_not_held_excluded_from_held_or_sold` (still counted as sold if a sale exists); `test_groww_held_symbols_backfilled_but_not_watchlisted` (after ingest, `is_watchlisted` unchanged).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS**, then the full suite: `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE backend/.venv/Scripts/python.exe -m pytest backend/tests -q -x` — no new failures vs `origin/main`.
- [ ] **Step 5: Commit** `feat(groww): owner-only sync routes, sale confirmation, 15:35 sync job, held stocks priced`

### Task 6: Tracker screen

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts` (Groww calls above)
- Modify: `frontend/src/trademind/pages/GrowwTracker.tsx`, `frontend/src/trademind/trackerRules.ts` (if held filtering lives there)
- Test: `frontend/src/trademind/growwTracker.test.tsx`

**What the owner sees (owner only):** a status strip — "Groww synced 21 Nov, 15:35 IST · prices from 21 Nov close" — with a **Refresh** button (loading / done / failed states; failure text keeps old data and says "showing holdings from <time>"); a **Needs matching** panel listing ISIN + Groww symbol with a stock picker and "Confirm all suggestions"; row badges "from Groww" (quantity/price not editable), "Not held", "Groww shows N fewer shares — Confirm sale" (opens the existing sell form with quantity prefilled); an empty-sync banner "Groww returned no holdings — do you hold nothing?" with Confirm.

- [ ] **Step 1: Failing tests** — `shows last successful sync time when the latest sync failed`; `needs-matching panel lists unmatched rows and confirm posts instrument_id`; `quantity and price inputs are read-only on Groww rows`; `confirm sale prefills the pending quantity`; `not held rows are labelled and excluded from the held total`; `non-owner sees no Groww strip`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/trademind/growwTracker.test.tsx` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest PASS and `npx tsc --noEmit -p .` clean.
- [ ] **Step 5: Commit** `feat(groww): sync status, refresh, needs matching and confirm sale in the tracker`

### Task 7: Hand-off

**Files:** `docs/ai/HANDOFF.md`, `.env.example` (verify), `docs/superpowers/specs/2026-11-21-groww-sync-design.md` (record G0 result)

- [ ] **Step 1:** Run superpowers:verification-before-completion: backend Groww tests, full backend suite, vitest, tsc. Paste real outputs into HANDOFF.
- [ ] **Step 2:** Update HANDOFF (branch, files, results, open items: phase 2 Brain review; owner to put the two settings on the server).
- [ ] **Step 3:** Update issue #388 via the update-tickets skill. Stop for Codex review (AGENTS.md loop) and owner approval. No push to `main`.
