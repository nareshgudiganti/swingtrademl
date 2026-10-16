# Multi-user private paper portfolios — technical design

**Date:** 2026-10-16 · **Status:** DRAFT for owner review — nothing built, nothing on `main`/prod
**Scope decided by the owner (2026-10-16):** invite-only; every new user is paper-only; each user
has their own virtual cash, holdings, orders, history, performance and risk limits; optional
per-user Telegram; reuse existing auth only after a security review; owner-only Zerodha features
stay isolated; plan architecture prepared, no payments; frozen trading protocol, models and stock
selection unchanged; no new paid infrastructure.

---

## 0. In plain English

- Today TradeMind has **one** paper account. Anyone who signs in sees that one account. Sign-up
  on swingtrademl.com is switched off (`GET /auth/options` → `signup_allowed: false`), which is
  why "sign up" does not work there.
- The plan: the market analysis (prices, models, the brain's ideas) keeps running **once a day,
  for everybody**. Each user then gets their **own pretend-money account**. The same ideas are
  checked against *their* cash and *their* limits, and bought or skipped in *their* account only.
- Your current account becomes the **"house" account**. Its numbers, its trial and its trading
  must come out of the change identical. That is the main thing the tests prove.
- Real Zerodha money stays yours alone, exactly as today.

---

## 1. Current architecture vs proposed

### 1.1 Current (verified in code 2026-10-16)

```
data ingest ─► models / brain (once) ─► strategies ─► engine.run_strategy
                                                         └─► execution.process_decision
                                                               └─► risk.check_entry  (GLOBAL book)
                                                               └─► paper_broker      (GLOBAL cash)
```

| Fact | Where |
|---|---|
| `users` table: username, email, bcrypt hash, google_id, `is_superuser`, `plan` | `db/models/session.py` |
| Orders/Positions/Trades/Snapshots/RiskEvents have **no owner**; they carry only `mode` and `strategy_id` | `db/models/trading.py`, `safety.py` |
| "Books" are distinguished **by strategy name**: `real_trading` (My Holdings), `tester_paper` (Vijay's book), everything else = bot | `services/portfolio.py:30-49`, `services/tester_paper.py` |
| Paper cash is *derived*, not stored: `PAPER_STARTING_CAPITAL + Σ Trade.net_pnl − Σ open locked capital` | `brokers/paper.py:114` |
| `check_entry` counts positions, drawdown, sector exposure for the **whole mode** (not per user) | `services/risk.py:471-640` |
| Signal rows mix the **market call** (BUY, confidence, levels) with the **book outcome** (`was_executed`, `rejection_reason`) | `db/models/trading.py:93` |
| Brain TRADE already includes the house book's risk gate (M07); a TRADE lowered only by risk becomes WATCH with `blocked_by_risk` | `strategies/brain.py:92` |
| Kill switch `system_state` is one global row | `db/models/safety.py:20` |
| Every write route is owner-only (`require_auth`), reads open to any signed-in account while plans are off | `api/deps.py:165` |
| Telegram: one bot, one `TELEGRAM_CHAT_ID` | `notifications/telegram.py:39` |

### 1.2 Proposed

```
                 ┌──────────── SHARED, runs once (unchanged code) ────────────┐
data ingest ─► models / brain nightly ─► strategies evaluate ─► market signals
                 └────────────────────────────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼───────────────────────────┐
              ▼                          ▼                           ▼
     HOUSE portfolio (owner)     user portfolio A            user portfolio B …
     existing path, same         portfolio runner:           portfolio runner
     behaviour, same numbers     risk.check_entry(pf=A)
                                 paper_broker(pf=A)
                                 ledger, snapshots, alerts(A)
```

Three ideas carry the whole design:

1. **Portfolio is a first-class thing** (`portfolios` table) and every money row points at one.
   Users own portfolios; the owner owns the house, tester and real portfolios.
2. **A market signal is shared; a portfolio decision is private.** New table
   `portfolio_decisions` records "what *this* portfolio did with *that* signal". The house book
   keeps writing `signals.was_executed` exactly as today, so nothing reading it breaks.
3. **Scoping lives in one place.** A `PortfolioScope` object (portfolio id + mode) is passed
   into risk, execution, portfolio and report functions. Every query on a money table filters by
   it. The house default keeps old callers working during the transition.

### 1.3 Approaches considered

| | Approach | Verdict |
|---|---|---|
| **A** | `portfolios` table + `portfolio_id` FK on money tables + scoped service layer | **Recommended.** Fits one backend/Postgres, follows the existing "book" idea, testable |
| B | Postgres Row-Level Security alone (per-request `SET app.portfolio_id`) | Rejected as the main mechanism: scheduler jobs work across all portfolios, and RLS failures are silent. Kept as an **optional later hardening** on top of A |
| C | Schema or database per user | Rejected: migrations ×N, no shared market data, far beyond single-developer scale |

---

## 2. Database schema changes

All changes are **additive** (new tables, new nullable columns, later tightened). No existing
column is renamed, dropped or re-meant.

### 2.1 New tables

**`portfolios`**
| column | type | notes |
|---|---|---|
| id | int PK | |
| owner_user_id | FK users.id, nullable | null only for the house portfolio before an owner user is linked |
| kind | varchar(16) | `house` · `tester` · `real` · `member` |
| name | varchar(64) | shown in UI |
| mode | varchar(8) | `paper` for every `member`; CHECK (kind <> 'member' OR mode = 'paper') |
| starting_capital | numeric(14,2) | members: chosen at creation; house: see §7.3 |
| base_currency | char(3) default INR | |
| status | varchar(12) | `active` · `paused` (no new entries) · `closed` |
| auto_follow | bool | portfolio runner buys signals automatically (default true for members) |
| trial_started_at | timestamptz | per-portfolio trial start (house = existing `trial_start`) |
| created_at / updated_at | | |
| UNIQUE (owner_user_id, kind) WHERE kind='member' | | one member portfolio per user (v1 of this feature) |

**`cash_ledger_entries`**: append-only, never updated
| column | type | notes |
|---|---|---|
| id | bigint PK | |
| portfolio_id | FK portfolios | indexed with ts |
| ts | timestamptz | |
| kind | varchar(16) | `deposit` · `buy` · `sell` · `charges` · `adjustment` · `reset` |
| amount | numeric(14,2) | signed: + adds cash, − removes |
| order_id / position_id / trade_id | FK, nullable | link to cause |
| note | text | |
| created_by | varchar(128) | actor (user, `system`, `admin:<name>`) |

Cash = Σ amount. The existing derived formula stays as a **cross-check**: a nightly job compares
both per portfolio and alerts on a mismatch. For the house portfolio the ledger is
*shadow only* in phases 1–4. `brokers/paper.py` keeps using the derived figure for the house, so the
trial's numbers cannot move.

**`portfolio_decisions`**: what a portfolio did with a shared signal
| column | type | notes |
|---|---|---|
| id | bigint PK | |
| portfolio_id | FK | |
| signal_id | FK signals | UNIQUE (portfolio_id, signal_id): idempotent re-runs |
| outcome | varchar(16) | `executed` · `rejected` · `ranked_out` · `skipped_paused` · `error` |
| rule / reason | varchar(32) / text | same codes as `risk_events.rule` |
| quantity | int null | |
| order_id / position_id | FK null | |
| decided_at | timestamptz | |

**`invitations`**
| column | type | notes |
|---|---|---|
| id | int PK | |
| token_hash | char(64) UNIQUE | SHA-256 of the token; raw token only ever in the invite link |
| email | varchar(255) null | if set, signup must use this email |
| plan | varchar(16) | plan the new user starts on |
| starting_capital | numeric null | default from settings |
| created_by_user_id | FK users | |
| expires_at | timestamptz | default 7 days |
| used_at / used_by_user_id | | single-use |
| revoked_at | timestamptz null | |

**`audit_log`**: append-only
| column | type | notes |
|---|---|---|
| id | bigint PK | |
| ts | timestamptz | indexed |
| actor_user_id | FK null | null = API key or system |
| actor_label | varchar(128) | from `actor_name()` |
| action | varchar(48) | e.g. `invite.create`, `user.disable`, `portfolio.reset`, `plan.change`, `auth.login_failed` |
| target_type / target_id | varchar / varchar | |
| before / after | JSON | changed fields only, secrets never |
| ip / user_agent | varchar | |

**`user_notification_settings`**
| column | type | notes |
|---|---|---|
| user_id | PK FK users | |
| telegram_chat_id | varchar(64) null | set only via the link flow (§6.4) |
| telegram_link_code_hash / _expires_at | | one-time code |
| alerts_enabled | bool | |
| alert_kinds | JSON | e.g. `{"entries":true,"exits":true,"daily_summary":true}` |

**`job_runs`**: operational visibility for the admin dashboard
| column | type | notes |
|---|---|---|
| id | bigint PK | |
| job_id | varchar(48) | e.g. `portfolio_runner` |
| portfolio_id | FK null | null = shared job |
| started_at / finished_at | | |
| status | `ok` · `error` · `skipped` | |
| detail | JSON | counts, error text (redacted) |

### 2.2 Changed tables

| table | change |
|---|---|
| `users` | + `role` varchar(12) (`owner`·`admin`·`member`), + `status` (`invited`·`active`·`disabled`), + `token_version` int default 0, + `email_verified_at`, + `failed_login_count`, `locked_until`, + `invited_by_user_id` FK. `is_superuser` kept and kept in sync for old code until removed in a later cleanup |
| `orders`, `positions`, `trades`, `portfolio_snapshots`, `risk_events`, `brain_approvals` | + `portfolio_id` FK portfolios, nullable first → backfilled → NOT NULL (separate migration). Indexes: `(portfolio_id, mode, status)` on positions, `(portfolio_id, ts)` on snapshots, `(portfolio_id, exit_at)` on trades, `(portfolio_id, placed_at)` on orders |
| `system_state` | unchanged (global owner kill switch). Per-portfolio pause = `portfolios.status` |
| `position_score_history` | unchanged; owned through its position |
| `signals` | **unchanged.** Shared market rows; house outcome columns keep their meaning |
| `strategies` | unchanged. Strategies stay shared definitions |
| market, feeds, ml, brain tables | unchanged. Shared, read-only for members |

Untouched owner-only tables: `broker_sessions`, `fills`, finance, mutual funds. Members have no
route to them (§6).

### 2.3 Relationships

```
users 1─* portfolios 1─* orders / positions / trades / snapshots / risk_events / cash_ledger_entries
portfolios 1─* portfolio_decisions *─1 signals *─1 strategies
users 1─1 user_notification_settings
users 1─* invitations (created_by)   invitations 0..1─1 users (used_by)
audit_log *─0..1 users (actor)
```

### 2.4 Backfill mapping (existing rows → portfolios)

| existing rows | portfolio |
|---|---|
| strategy name `real_trading` | `real` (owner) |
| strategy name `tester_paper` | `tester` (owner; Vijay's book keeps its own capital `PAPER_TESTER_STARTING_CAPITAL`) |
| every other row, incl. `strategy_id IS NULL` and the brain strategy | `house` |
| `portfolio_snapshots` | `house` (snapshots never included tester/real; verified against `take_snapshot` during build) |

---

## 3. Shared signals vs per-user decisions (requirement 1 and 4)

**Run once (no change to code or behaviour):** ingest, predictions, `brain_nightly`, strategy
`evaluate()` producing `SignalDecision`s, stock score history, the house book's
`process_decision`.

**New: `services/portfolio_runner.py`** runs after the 15:45 v1 scan and after the brain
strategy's run, for every `member` portfolio with `status=active` and `auto_follow=true`:

1. Load today's shared signals (`signals` rows for the day, both v1 active strategies and the
   brain strategy). Candidate BUYs = `signal_type=BUY` **plus** brain WATCH rows where
   `blocked_by_risk` is true (the idea was good and was only lowered because the house book was full).
   A brain idea that was downgraded for any other reason is never bought. This only ever
   *adds* ideas the brain itself rated TRADE, so it does not loosen the brain's judgement.
2. EXIT/SELL signals for instruments this portfolio holds → close through the existing
   `close_position` path with `PortfolioScope`.
3. BUY candidates strongest-first through `risk.check_entry(scope=pf, …)` sized by
   `limits_for(pf value)`. The same ladder, +8/−4/15-day protocol and sector rules apply, since they
   are code, not settings. Slots spent by fills only (same rule as `engine.run_strategy`).
4. Write `portfolio_decisions`, ledger entries and orders/positions under the portfolio.

The brain's M18 stage applies to members exactly as to the house: in **practice (shadow)**, brain
ideas are recorded for members but never bought; v1 strategies trade as today.

**Efficiency:** shared work is O(stocks); per-portfolio work is O(candidates ≈ 5–30). 100 users
≈ 3,000 risk checks of indexed queries, a few seconds. One DB transaction per portfolio, so one bad
portfolio cannot stall or roll back others.

---

## 4. Backend changes

### 4.1 Core services (thread `PortfolioScope`)

| file | change |
|---|---|
| `services/scope.py` (new) | `PortfolioScope(portfolio_id, mode)`, `house_scope(db)`, `scope_for(principal)` |
| `brokers/paper.py` | `get_available_cash(db, scope=None)`; None → today's derived house formula unchanged; member → ledger sum |
| `services/risk.py` | every query helper (`open_position_count`, `has_open_position`, `stopped_out_recently`, `open_exposure_value`, `current_drawdown`, `open_holdings`, `in_flight_buy_holdings`) takes `scope`; filters `portfolio_id` |
| `services/execution.py` | `open_position`, `close_position`, `manual_*`, `check_exits`, `reconcile_pending_orders` stamp/filter `portfolio_id`; write ledger entries for member portfolios; alerts routed via the portfolio owner |
| `services/portfolio.py` | `portfolio_value_and_cash`, `mark_to_market`, `take_snapshot`, `performance_stats`, `equity_curve`, `drawdown_peak`, `trial_start` per portfolio |
| `services/engine.py` | unchanged behaviour; after `run_all_active` the scheduler calls the runner |
| `services/tester_paper.py` | reads its portfolio row instead of strategy-name subqueries (phase 6 cleanup, optional) |
| `notifications/telegram.py` | `send_to_user(user_id, text)`, owner path unchanged |

### 4.2 API (`api/v1/endpoints/`)

**Principle:** existing routes keep their URLs; their data is scoped by `scope_for(principal)`.
Owner → house (or `?portfolio_id=` for any portfolio, audited). Member → own portfolio only;
any other `portfolio_id` → 404, not 403, so ids can't be probed.

| endpoint file | change |
|---|---|
| `portfolio.py` (summary, positions, trades, equity, performance) | scope by portfolio |
| `orders.py` | scope; members may place **manual paper** buy/sell on own portfolio only |
| `signals.py` (picks, buy-list, track-record) | market part shared; "acted on?" fields from `portfolio_decisions` for members |
| `risk.py` (`/risk/limits`) | per-portfolio limits and drawdown |
| `real_report.py`, My Holdings, `/auth/kite/*`, `safety.py`, `brain_golive.py` writes, `brain.py` writes, `ml.py` writes, `strategies.py` writes, `finance.py`, `mutual_funds.py`, `backtest.py`, `system.py` admin bits | **owner-only, unchanged** |
| `auth.py` | invite-based signup, refresh/logout, password change/reset, rate limits (§6) |
| `me.py` (new) | `GET/PATCH /me` profile, `/me/portfolio` create/reset (reset = new trial, audited), `/me/notifications`, `/me/telegram/link` |
| `admin.py` (new, `require_owner`) | invitations CRUD, users list/detail, disable/enable, change plan/role, reset a member portfolio, audit log, job runs, ledger-mismatch report |
| `deps.py` | `require_auth` gains an explicit **member write allowlist** (manual paper orders, `/me/*`); every other write stays owner-only. `book_for` stays |
| exports (CSV/report downloads, wherever present) | same scope as the screen they export |

---

## 5. Frontend screens and journeys

| Journey | Screens |
|---|---|
| Owner invites | Admin → Invitations → "Invite" (email optional, plan, starting cash) → copy link |
| New user joins | `/join?token=…` → set username, password, email → (verify email, phase 7) → choose starting cash within owner's range → Home |
| Daily use (member) | TradeMind Home, Opportunities (shared ideas + "what my account did"), Portfolio, Positions, Records, Risk (my limits), Settings (profile, password, Telegram) |
| Telegram link | Settings → "Connect Telegram" → shows one-time code + bot link → user sends `/start CODE` → linked |
| Owner admin | Admin → Users (status, plan, last login, portfolio value, drawdown), User detail (disable, reset portfolio, change plan), Audit log, Jobs (last runner per portfolio, failures), Ledger check |
| Hidden for members | Control, GoLive, System, Models/ModelLab, Safety, My Holdings, Real report, Finance, Plans Manager, Observatory |

Wording stays jargon-free; each member screen carries the line "Practice money — no real orders".

---

## 6. Security and authentication assessment (existing auth reviewed)

### 6.1 What is sound
- bcrypt hashing with direct `bcrypt` (no unmaintained passlib); generic login error (no user enumeration).
- Disabled users are rejected on **every request** (`_user_from_bearer` checks `is_active`).
- Google OAuth uses a CSRF `state`, verified-email check and an allow-list.
- API key compared with `hmac.compare_digest`.
- Writes already default to owner-only; real-account routes behind `require_real_account`.

### 6.2 Findings to fix before any member joins

| # | Finding | Risk | Fix |
|---|---|---|---|
| S1 | **Any signed-in account reads the house book** while plans are off (reads are unrestricted) | A new member would see the owner's portfolio | Scope reads (§4.2); until then keep signup closed |
| S2 | **Testers hold `is_superuser`** (`deps.py:66` note): superuser = full owner powers | A tester can change stages, approvals, safety | Introduce `role`; audit current superusers; only the owner(s) keep `owner` |
| S3 | No login/signup **rate limit or lockout** | Password guessing | Redis-backed counters (already in stack): 5 failures / 15 min per username+IP → temporary lock; audit `auth.login_failed` |
| S4 | JWT `sub` = username, 12 h, **no revocation** | Password change/disable can't kill a stolen token (disable does, via is_active) | Put `uid` + `token_version` in JWT; bump version on password change/reset/"log out everywhere" |
| S5 | Google callback puts the **JWT in the URL** (`/?token=`) | Leaks into history, logs, Referer | One-time code (60 s, Redis) exchanged by the SPA via POST |
| S6 | Defaults `JWT_SECRET_KEY`/`API_KEY` = `"change-me"` | Forged tokens if a deploy forgets them | Refuse to start with defaults when not local |
| S7 | Token in `localStorage` | Any XSS steals it | Accept for now + strict CSP; httpOnly cookie is a later option |
| S8 | No email verification / password reset | Account recovery by owner only | Phase 7; free SMTP (e.g. Gmail app password), or owner-issued reset links until then |
| S9 | Open signup default `ALLOW_SIGNUP=True` in code | Accidental open registration | Replace with `SIGNUP_MODE = closed | invite | open`, default `invite` |
| S10 | Shared `X-API-Key` = owner | Unchanged; maps to house scope only | Document; never accepted for member actions |

### 6.3 Authorization model
`Principal` gains `role` and `portfolio_ids`. Rules: owner → everything (as today); admin
(optional, later) → admin screens, no trading stage/safety/real account; member → own
portfolio reads/writes from the allowlist, shared market reads by plan. Zerodha/real
routes: `require_real_account` unchanged, members can never pass it.

### 6.4 Telegram
One shared bot token. A user links by sending `/start <one-time code>`; the chat id is then
stored per user. Messages to members never include other portfolios' data. Owner alerts are
unchanged.

---

## 7. Background scheduler and queue changes

| job | today | change |
|---|---|---|
| `signal_scan` 15:45 | v1 scan + house execution | unchanged, then enqueue `portfolio_runner(source=v1)` |
| brain strategy run after `brain_nightly` | house | unchanged, then `portfolio_runner(source=brain)` |
| `check_exits` 60 s | all open positions | unchanged loop (positions now carry `portfolio_id`); alert goes to the portfolio owner; member ledger entry on fill |
| `reconcile_orders` 60 s | | paper fills are instant; member orders are paper only → no change |
| `refresh_quotes` / mark-to-market | per position | unchanged (price is shared) |
| `daily_summary` 16:00 | owner Telegram | + per-member summary if enabled |
| snapshots | house | one per portfolio |
| new `ledger_check` 16:30 | | derived vs ledger per portfolio → admin + owner alert on mismatch |
| `brain_approvals_open` | house | unchanged; members get no approvals while paper-auto |

**Concurrency rules**
- APScheduler jobs keep `max_instances=1, coalesce=True`.
- Every write to one portfolio's money takes `pg_advisory_xact_lock(hashtext('pf'), portfolio_id)`:
  the runner, `check_exits` for that portfolio's position, manual orders from the API. Two
  writers can't both see the same cash.
- The existing per-position exit claim (`exit_in_progress_at`) stays the guard against double sells.
- `portfolio_decisions` UNIQUE(portfolio_id, signal_id) makes a re-run or a crash-and-retry harmless.
- Runner iterates portfolios in id order, one transaction each, records a `job_runs` row each.

### 7.3 House account capital
The house portfolio keeps reading `PAPER_STARTING_CAPITAL` and its trial start exactly as
today (known `.env` opening-equity issue stays an owner decision, not part of this work). Its
`starting_capital` column is filled for display only.

---

## 8. Migration and rollback

### 8.1 Migration steps (alembic, each its own revision)
1. **M1 (additive):** create new tables; add nullable `portfolio_id` columns + indexes; add
   `users.role/status/token_version/...` with defaults that reproduce today (`role=owner` where
   `is_superuser` **only after the owner confirms the list**, else `member`).
2. **M2 (data):** insert `house`, `tester`, `real` portfolios; backfill `portfolio_id` per §2.4.
   Shadow ledger entries for house (opening `deposit` + historical rows) for the cross-check.
   Post-checks inside the migration (fail = abort):
   - row counts per table unchanged; zero NULL `portfolio_id`
   - house derived cash, holdings value, drawdown peak, trial P&L **identical** before/after
   - tester book cash identical
3. **M3 (tighten):** `portfolio_id` NOT NULL + FK, after M2 has run in prod for one clean day.

### 8.2 Preserving the trial
No existing row is updated except setting `portfolio_id`. `signals`, trial dates, snapshots,
brain tables are untouched. A pre-migration `pg_dump` is taken (existing backup path) and kept.

### 8.3 Rollback
- **Code rollback** = redeploy the previous commit. Because every change is additive, old code
  runs against the new schema (it ignores new columns/tables). Members' data stays in the DB,
  unseen.
- **Schema rollback** (only if needed): alembic downgrade M3 → M2 → M1 drops the new columns and
  tables; house data unaffected. Member data would be lost, so export first.
- **Kill switch for the feature:** `MULTI_USER_ENABLED=false` → runner skips, member routes 404,
  signup closed. House unaffected.

---

## 9. Testing strategy and acceptance criteria

| Suite | What it proves | Acceptance |
|---|---|---|
| **House golden test** | Same seeded DB, same day → house signals, orders, positions, cash, drawdown before vs after | Byte-identical results for v1 scan, brain strategy, `check_exits`, snapshots |
| **Isolation** | Two members + house; every scoped endpoint and service | Member A never sees/changes B's or the house's rows; foreign `portfolio_id` → 404; a test enumerates **every** route and fails if a new money route lacks scoping |
| **Authorization** | role × route matrix | Members: no owner route, no real-account route, no write outside allowlist; disabled user rejected; token invalid after password change |
| **Auth security** | rate limit, lockout, invite single-use/expiry/revocation, email-bound invite, Google one-time code | All negative cases rejected and audited |
| **Ledger** | ledger vs derived formula after buys, partial exit, full exit, charges, reset | Equal to the paisa |
| **Risk per portfolio** | drawdown, sector cap, slots, ladder computed on own value | A's losses never halt B or the house |
| **Scheduler concurrency** | runner + `check_exits` + manual order on one portfolio in parallel threads | No negative cash, no double sell, no duplicate `portfolio_decisions` |
| **Runner idempotency** | run twice / crash mid-way | Same final state |
| **Migration** | M1–M3 up on a copy of prod-shaped data, then down | Post-checks pass; downgrade leaves house identical |
| **Alerts** | per-user Telegram routing | No message contains another portfolio's data |
| **Frontend** | `tsc --noEmit`; member nav hides owner screens | Owner screens unreachable by URL for members (backend enforces) |

Trading-sensitive tests (risk, sizing, execution) need owner approval before merge, per CLAUDE.md.

---

## 10. Phased implementation plan

| Phase | Content | Size | Depends on | Ships to prod? |
|---|---|---|---|---|
| **P0 Security hardening** | S2–S6, S9, `role`/`status`/`token_version`, audit_log table, rate limits | M | – | Yes (no member visible change) |
| **P1 Portfolio model + migration** | `portfolios`, `portfolio_id` columns, backfill, shadow ledger, golden tests | L | P0 | Yes, after golden test + owner OK |
| **P2 Scoping** | `PortfolioScope` through paper/risk/execution/portfolio/reports + API scoping + isolation & route-enumeration tests | XL | P1 | Yes, still no members |
| **P3 Invitations + member onboarding + member UI** | invitations, `/join`, `/me`, member nav | M | P2 | Behind `MULTI_USER_ENABLED` |
| **P4 Portfolio runner + scheduler** | runner, locks, per-portfolio snapshots, `job_runs`, ledger_check | L | P2 | Behind flag |
| **P5 Admin dashboard** | users, invites, audit, jobs, ledger check UI | M | P0, P3, P4 | Behind flag |
| **P6 Per-user Telegram** | link flow, routing, member summary | S–M | P4 | Behind flag |
| **P7 Email verify / reset** | SMTP, tokens | M | P0 | Optional |
| Plans prep | plan limits (max members, starting-cash range, features) reuse existing `plans` system; no payments | S | P3 | With P3 |

First invited member is possible after P0–P5. Each phase gets its own plan, tests, and owner
approval before `main`.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Missing one query in ~500 money-table references across 44 files leaks or mixes data | Route-enumeration test, service-level isolation tests, grep audit list in the plan, optional RLS later |
| Refactor changes house numbers mid-trial | House default path + golden test; house ledger shadow-only |
| Member auto-buys look like "advice" to real people | Regulatory question below. Members stay invite-only and practice-only |
| Scheduler window grows with users | Measured in P4; runner is O(candidates); alert if > 5 min |
| Superuser role cleanup locks someone out | Owner confirms the list first; API key still works |

## 12. Unresolved questions for the owner

1. **Regulation:** showing buy/sell ideas to other people, even practice-only, may fall under SEBI
   research-analyst rules if it grows or is ever paid. Get advice before opening beyond friends/testers.
2. **Who is "owner" today?** Which of the 3 prod superuser accounts stay owner, and which become member?
3. **Member starting cash:** fixed (e.g. ₹1,00,000) or chosen within a range (₹10K–₹10L)?
4. **Auto-follow default:** should a member's account buy the ideas automatically (recommended,
   same as the house), or only let them buy by hand?
5. **Reset:** may a member restart their practice account themselves (audited), or only the owner?
6. **Brain ideas blocked only by the house book's limits** (WATCH + `blocked_by_risk`): allow
   members to buy them (recommended), or show-only?
7. **Vijay's tester book:** keep as the owner's `tester` portfolio, or move him to a normal member account?
8. **Email:** OK to use a free SMTP account for verification/reset (P7), or skip and keep owner-issued reset links?
