# Five-day picks window: one listing-freshness definition (proposal)

Status: **proposal only, 26 Nov 2026 (IST). No code is changed by this document.** Parent: #227 and #281
(`docs/requirements/feature-2-today-discover-scanner.md`, AC-17 and AC-18). Code checked on `origin/main` at `897da862`.
Paths below are under `backend/src/swing_trade_ml/` unless they start with `frontend/` or `backend/tests/`.

## 1. What is inconsistent

Three lists show a BUY signal "while it is fresh", and they do not agree on what fresh means.

| List | Endpoint | Rule | Code |
|---|---|---|---|
| 5-day picks ("Today's picks") | `GET /signals/picks` | signal time at most **5 calendar days** before now | `api/v1/endpoints/signals.py:133` (`PICK_MAX_AGE = timedelta(days=5)`), used at `:179` |
| Top picks | `GET /signals/top-picks` | at most **4 completed trading sessions** old (ages 0-4) | `signals.py:139` (`MAX_BUY_AGE_SESSIONS = 4`), `:142-152` (`buy_fresh_since`), used at `:270` |
| Buy list | `GET /signals/buy-list` | same as top picks | `signals.py:394` (docstring `:357`) |

The session rule skips weekends and NSE holidays (`core/market_session.py:76` `previous_trading_day`, `:109` `last_closed_trading_day`,
holiday list `core/holidays.py:50` includes 24 Nov 2026). The calendar rule does not. The code comment at `signals.py:131-132` says five
calendar days "covers a long weekend and a holiday", but that was written before the session rule existed and is no longer the rule the
other two lists follow. PR #540 (26 Nov 2026) moved the buy list and top picks to ages 0-4 and left `/picks` alone
(`test_five_session_contract_227.py:58`, `test_a_calendar_window_would_disagree_the_holiday_changes_the_answer`, already demonstrates
the disagreement for a holiday).

## 2. Worked example: a weekend plus the 24 Nov 2026 holiday

Trading sessions around the dates: Fri 20 Nov, Mon 23 Nov, **Tue 24 Nov = NSE holiday**, Wed 25, Thu 26, Fri 27, Mon 30 Nov.
Take a BUY signal from the scan after Friday 20 Nov's close (session 20 Nov). Age = number of completed sessions between that session and
the last closed session (the session's own signals are age 0).

| Viewed (10:00 IST, market open) | Last closed session | Age of the 20 Nov signal | Buy list and top picks (ages 0-4) | `/picks` (5 calendar days) |
|---|---|---|---|---|
| Mon 23 Nov | Fri 20 Nov | 0 | listed | listed |
| Wed 25 Nov | Mon 23 Nov (24 Nov is not counted) | 1 | listed | listed (5 days not yet passed) |
| Thu 26 Nov | Wed 25 Nov | 2 | listed | **dropped** (6 days) |
| Fri 27 Nov | Thu 26 Nov | 3 | listed | **dropped** |
| Mon 30 Nov | Fri 27 Nov | 4 | listed (last day) | **dropped** |
| Tue 1 Dec | Mon 30 Nov | 5 | dropped | dropped |

So on Thu 26 to Mon 30 Nov the same stock is on the buy list and top picks but missing from "Today's picks". Two things are
assumptions of this table and should be confirmed by the tests in section 7: the scan stamps the signal at or after Friday's close, and
the 5-day boundary is compared against the signal's stored `generated_at` time, not its session date (`signals.py:179`), so the exact
drop-off hour moves with the scan time.

In the other direction the calendar rule is not looser in this example or in any week with a weekend or holiday: five calendar days
never reach further back in sessions than ages 0-4 do once a non-session day sits inside the window. So `/picks` is the shorter list
in those weeks, and the two lists give the same answer only when no weekend or holiday falls inside the window.

## 3. Every consumer of `/picks`

Frontend
- `frontend/src/api/client.ts:555` defines `api.picks` (`get<PlanPick[]>('/signals/picks')`).
- `frontend/src/pages/PlanHome.tsx:163` is the only caller (`useQuery(['picks'], api.picks)`), shown on the "Today's picks" screen
  (`frontend/src/App.tsx:82`, route `/home`). The same page feeds the "split a budget across today's picks" block (`PlanHome.tsx:111`).

Backend
- `api/v1/endpoints/signals.py:155-206` is the endpoint itself (plan-limited by `core/plans.py:119`, feature `picks`, and
  `limit = plan.limits.picks_per_day`, `PlanHome.tsx:165`).
- `core/plans.py:119` maps the route to the `picks` plan feature (access control only, no window logic).
- No other backend module imports or calls `picks()` or `PICK_MAX_AGE` (searched `backend/src`, `backend/scripts`, `scripts`).
  Other grep hits for the word "picks" (`brain/portfolio_sim.py`, `shadow_lanes/*`, `brain/trial_journal.py`, lane picks) are separate
  features and do not read `/signals/picks`.

Tests that pin the current behaviour
- `backend/tests/test_discover_filters_239.py:273` (`test_picks_use_a_five_day_window_one_row_per_stock_the_best_confidence_and_the_signals_own_horizon`)
  and `:286` (highest confidence first). Also route-access tests such as `test_onboarding_verify.py` and `test_p0_tester_private.py`
  mention the route; they test access, not freshness.

## 4. Proposal: one definition of listing freshness

**Listing freshness** = the number of completed trading sessions between the signal's session and the last closed session, computed by
the one existing function `buy_fresh_since` (or a small shared helper that wraps it). A BUY is listed on `/picks`, `/top-picks` and
`/buy-list` while that age is 0 to `MAX_BUY_AGE_SESSIONS` (4). Same constant, same function, same holiday calendar, same IST-midnight
cutoff (`signals.py:149-152`).

Why: one answer to "is this still a pick today" on every screen; weekends and holidays stop changing the answer; the rule is already
tested for the other two lists (`test_five_session_contract_227.py`, `test_buy_window_sessions.py`); and it matches the 5-day protocol
reasoning in the code comment at `signals.py:135-138` (a signal from session D is entered at the next open and the trade ends by the
close of D+5, so an age-5 signal could only be entered outside its window).

## 5. Recommendation

Adopt the single session-based definition for `/picks` (replace `PICK_MAX_AGE` at `signals.py:133` and the filter at `:179` with
`buy_fresh_since(datetime.now(UTC))`), and delete the calendar constant. Effect: "Today's picks" keeps a Friday signal through the following Monday and across a holiday week (age 4 at most), and shows the
same freshness as the buy list. No other file needs to change; no frontend change (the window is not copied on the frontend,
`test_five_session_contract_227.py:88`). No migration, no setting.

Do this as its own small PR with a test, after the owner agrees. It is not part of the sealed-trial freeze: `api/v1/endpoints/signals.py`
is not in `backend/tests/trial_freeze.json` (the file lists engine, risk, limits and brain files; confirm with the test before merging).

## 6. What this is NOT

- **Not position expiry.** The v1 time stop is 30 calendar days and the Brain horizon is 15 trading days (CLAUDE.md, "Risk rules").
  Neither is touched, and the 30-day value is not to be "fixed" to 15.
- **Not execution or fill timing.** When an order is placed or filled is decided by the order path (`services/engine.py`, M18 approvals:
  valid till the next close, placed at the next open). This proposal only changes which signals a list still shows.
- **Not a change to how signals are scored, targets, stops or limits.** Listing a signal does not place an order.

## 7. Owner decision needed and test plan

Owner decision needed (one question): should "Today's picks" (`/picks`) use the same completed-session freshness as the buy list and top
picks (ages 0-4)? Options: (a) yes, recommended; (b) keep 5 calendar days and say so on the screen; (c) change the shared limit
(`MAX_BUY_AGE_SESSIONS`) for all three lists, which is a separate decision.

If (a), tests (all backend, none touch order placement):
1. `/picks` includes an age-0 signal and an age-4 signal, and excludes an age-5 signal (mirror `test_five_session_contract_227.py:44`).
2. With the 24 Nov 2026 holiday and a weekend between, a Fri 20 Nov signal is still listed on Mon 30 Nov and gone on Tue 1 Dec
   (the example in section 2), with `now` pinned.
3. A parity test: for the same fixture, `/picks` and the buy list apply the same cutoff (the value returned by `buy_fresh_since`).
4. `test_discover_filters_239.py:273,286` keep passing (one row per stock, best confidence first, plan limit honoured).
5. A guard that no second freshness constant exists (extend `test_five_session_contract_227.py:88`).
6. Run `test_trial_freeze.py` to confirm no frozen file changed.
