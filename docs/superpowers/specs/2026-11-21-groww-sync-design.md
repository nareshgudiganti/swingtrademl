# Groww holdings sync into the existing Groww Tracker (design, rev 2)

Status: DRAFT for owner approval. Supersedes `2026-11-20-groww-tracker-design.md` (which planned a
separate tab and missed the tracker already on main). Issue #388. Related: #389/#390 (stock IDs).
Date: 2026-11-21. Nothing is built except the step-0 probe script.

## 1. Why

The owner adds and sells Groww stocks by hand in the Groww Tracker. Missed or late edits leave gaps,
so returns, recommendations and reports drift from the real portfolio. The tracker must show the
Groww portfolio as it is, kept up to date for months, with **no daily login of any kind**.

The Watchlist stays what it is for: a short focus list of Discover's top picks.

## 2. What exists today (on main)

- Groww Tracker = every active row of `user_watchlist_items` (one row per user + symbol, with
  `buy_price`, `quantity`, `added_at` as buy date, `note`) plus `user_watchlist_sales` (sold records).
  Endpoint `GET /me/watchlist/tracker` (`api/v1/endpoints/my_watchlist.py`), maths in
  `services/watchlist_tracker.py`, page `frontend/src/trademind/pages/GrowwTracker.tsx`.
- Advice on each row (stop / target / time / weak score) is recomputed on every load from
  `buy_price` and daily candles, so it follows any change to quantity or price automatically.
- Daily Kite prices are collected only for the bot's global list (`instruments.is_watchlisted`) and
  strategy lists (`workers/jobs.py::job_daily_ingest`). **A personal-watchlist stock outside those
  gets no price.** `instruments` has no ISIN column.

## 3. Goals

1. **Prove hands-off sync first** (§5). If Groww needs daily action or a paid plan: stop, report.
2. Groww supplies only: which stocks are owned, share quantity, average buy price. Kite stays the
   price source; TradeMind stays the advice source.
3. After a **complete** sync and a **confirmed** stock match, Groww wins for current quantity and
   average buy price. Original entries, buy dates, notes and history are preserved.
4. Sync automatically once after close, plus a Refresh button.
5. Owner-only.

## 4. Non-goals / anti-goals

Non-goals (phase 1): Brain review of holdings (phase 2, separate from shared Brain runs and trial
metrics), reading Groww order/trade history, sell prices from Groww, F&O/intraday positions,
charges/tax, any user other than the owner.

Anti-goals: any Groww order call; any daily manual step; a failed, partial or empty sync changing
holdings; a sale recorded without the owner confirming it; unknown values shown as 0; secrets in
the browser, logs, git or chat; Groww holdings entering the bot's scan or trading lists.

## 5. Step 0 — hands-off gate (before any build)

`backend/scripts/groww_probe.py`, run by the owner on their own machine with their own environment
variables. `day1` mints a token with TOTP and reads holdings; `day2` (after the next 06:00 IST)
confirms the old token is rejected, mints a new one with TOTP only, reads again. Prints only
pass/fail, counts and field presence. **PASS on day 2 = build may start.** FAIL, or any demand for a
paid plan, static IP or approval tap = stop and report findings.

The probe also answers: do all rows carry ISIN, symbol, quantity and average price; do symbols carry
a `-EQ`-style suffix; are pledged/T1 quantities present (they are stored, not netted, in phase 1).

## 6. Rules (owner-stated unless marked C = my call, approved 2026-11-21)

**Sync result**
- *Complete* = call succeeded and every row has ISIN, symbol, quantity and average price.
  *Partial* = any row malformed. *Failed* = error. Only complete syncs change anything.
- A complete sync returning **zero** holdings is treated as suspicious and not applied until the
  owner confirms "I hold nothing" (C; a failed call and an empty account can look identical — the
  Kite ghost-holdings lesson).
- Failed/partial: last successful holdings stay visible with "last synced <IST time>".

**Matching**
- Confirmed ISIN-to-stock matches are saved and reused on every future sync.
- First sight of an ISIN: if the cleaned Groww symbol (suffix like `-EQ` removed) equals exactly one
  NSE instrument, it is *suggested*; otherwise it goes to **Needs matching**. Suggestions are
  confirmed once by the owner (a "confirm all" on the first reconciliation screen) (C).
- Only confirmed rows are applied to the tracker.

**Applying to the tracker (confirmed rows, complete sync)**
- Existing row for that stock: quantity and buy price set from Groww; the previous values are
  written to the change history first. Buy date and note never change. A top-up that changes the
  average keeps the original buy date (Day count does not restart) (C).
- Held in Groww, no row: a row is added, marked "from Groww", buy date = sync day (C).
- On the list, not held in Groww: unchanged, it is just a watched stock.
- Quantity falls: quantity updated; row shows "Groww shows N fewer shares — confirm sale". A sale
  record is created only when the owner confirms (with their sell price) (owner rule).
- Confirmed zero (ISIN absent from a complete, non-empty sync, or quantity 0): row stays on the
  watchlist, marked **not held**, and stops counting as held in reports. Its unconfirmed sale shows
  realized profit as missing, never zero.
- On linked rows, quantity and buy price are shown "from Groww" and are not hand-editable (C).

**Prices (gap 1, approved)**
- Stocks currently held via Groww are added to the daily price collection as *unwatchlisted*
  symbols, the same way strategy lists already are, so they get Kite prices without entering any
  scan or trade list. A held stock without a price shows "no price yet", never a value of 0.

**Advice**
- Phase 1: the tracker's existing advice, which already recalculates from the new quantity/price.
- Phase 2 (separate plan, likely after the 4 Dec freeze): Brain holdings review, stored outside
  `brain_runs`, never in trial metrics.

**Connection**
- Settings `GROWW_TOTP_TOKEN`, `GROWW_TOTP_SECRET` on the server (owner enters them; Claude never
  reads them). Token minted on demand, cached in Redis until the next 06:00 IST. Backend client
  knows exactly two calls: get token, get holdings.
- Owner-only on every route (`require_real_account`), 403 for anyone else.
- One sync at a time (Redis lock); Refresh at most once a minute.

## 7. Schema changes (APPROVED by owner 2026-11-21)

| Change | Purpose |
|---|---|
| New `groww_syncs` — id, started_at, finished_at, trigger (scheduled/manual), status (complete/partial/failed/empty_unconfirmed), holdings_count, error_code | One row per sync; "last synced" and audit |
| New `groww_holdings` — id, sync_id→groww_syncs, isin, trading_symbol, quantity, average_price, extra JSONB (pledge/T1/locked), instrument_id (null), match_state (confirmed/suggested/needs_matching) | What each sync returned |
| New `stock_aliases` — id, provider ('groww'), external_id (ISIN), external_symbol, instrument_id→instruments, confirmed_by_user_id, confirmed_at; unique(provider, external_id) | Saved confirmed matches; shaped so #389's stock IDs can reuse it instead of a second table |
| `user_watchlist_items` + `source` ('manual'/'groww', default manual), `groww_isin` (null), `held_state` ('unknown'/'held'/'not_held', default unknown), `groww_synced_at` (null) | Link + held status on the existing row |
| New `user_watchlist_item_changes` — id, item_id→user_watchlist_items, field, old_value, new_value, changed_by ('groww_sync'/'user'), sync_id (null), changed_at | Append-only history; preserves original entries |

All additive; existing rows default to `manual` / `unknown`, so the tracker behaves exactly as today
until the first confirmed sync. Rollback = drop the new columns/tables; no existing data is altered
by the migration.

## 8. Acceptance

- Probe PASS recorded before build.
- Tests prove the client exposes only token + holdings and no order URL is reachable.
- Partial, failed and empty syncs change nothing; repeated syncs are idempotent.
- Confirmed matches are reused; ambiguous rows land in Needs matching; nothing is silently dropped.
- Change history holds every overwritten value; buy date and note never change on sync.
- Partial sale updates quantity and prompts; zero marks not held; no sale without confirmation.
- Reports' "currently held" counts only `held_state='held'` (or manual rows never linked).
- Held stocks get daily prices without appearing in any scan/strategy/brain universe.
- Non-owner gets 403 on every Groww route.
