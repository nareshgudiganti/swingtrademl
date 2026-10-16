# Multi-user private paper portfolios — technical design

**Date:** 2026-10-16 · **Revision:** 2 (owner review applied, 2026-10-16)
**Status:** architecture direction APPROVED by the owner; this revision awaits owner review.
Nothing built, nothing on `main`/prod. Only the **P0 (release A)** implementation plan is
prepared: `docs/superpowers/plans/2026-10-16-p0-security-hardening.md`.

**Scope decided by the owner:** invite-only; every new user is paper-only; each user has their
own virtual cash, holdings, orders, history, performance and risk limits; optional per-user
Telegram; reuse existing auth only after a security review; owner-only Zerodha features stay
isolated and the live trading gate stays disabled; plan architecture prepared, no payments;
frozen trading protocol, models and stock selection unchanged; no new paid infrastructure.

### Owner decisions (revision 2)

| # | Decision | Where it lands |
|---|---|---|
| D1 | Only the owner's **verified primary account** stays owner. The other superusers are audited and role changes are shown to the owner **before** they are applied | §6.5 (audit), P0 |
| D2 | New members start with **₹10,00,000** virtual capital, **owner-configurable** | §2.1 `portfolios.starting_capital`, setting `MEMBER_STARTING_CAPITAL` |
| D3 | Members start with **manual paper BUY/SELL only**. Automatic following is not enabled initially | §3, release D |
| D4 | Resets allowed; **previous trial history preserved**; **every reset audited** | §3.4 |
| D5 | Brain ideas blocked only by the house account's limits are **shown separately, never auto-executed** | §3.2 |
| D6 | Vijay moves toward a **normal private member account**; his tester history is preserved | §2.4, §6.5, release C |
| D7 | A dedicated **free email sender** is fine for a small pilot, after security and delivery testing | release E |

---

## 0. In plain English

- Today TradeMind has **one** paper account. Anyone who signs in sees that one account. Sign-up
  on swingtrademl.com is switched off (`GET /auth/options` → `signup_allowed: false`), which is
  why "sign up" does not work there.
- The plan: the market analysis (prices, models, the brain's ideas) keeps running **once a day,
  for everybody**. Each member gets their **own pretend-money account** (₹10 lakh to start) and
  buys and sells in it **by hand**. Automatic buying for members comes later, only after its own testing.
- Your current account becomes the **"house" account**. Its numbers, its trial and its trading
  must come out of every change identical. That is the main thing the tests prove.
- Real Zerodha money stays yours alone, and the live-trading switch stays off.
- First step (release A): **lock the doors**. Fix the login weaknesses found in the review
  before anyone new is let in.

---

## 1. Current architecture vs proposed

### 1.1 Current (verified in code 2026-10-16)

```text
data ingest ─► models / brain (once) ─► strategies ─► engine.run_strategy
                                                         └─► execution.process_decision
                                                               └─► risk.check_entry  (GLOBAL book)
                                                               └─► paper_broker      (GLOBAL cash)
```

| Fact | Where |
|---|---|
| `users`: username, email, bcrypt hash, google_id, `is_superuser`, `plan`. Superuser = full owner powers | `db/models/session.py`, `api/deps.py:61` |
| Orders/Positions/Trades/Snapshots/RiskEvents have **no owner**; only `mode` and `strategy_id` | `db/models/trading.py`, `safety.py` |
| "Books" are told apart **by strategy name**: `real_trading` (My Holdings), `tester_paper` (Vijay), everything else = bot | `services/portfolio.py:30-49`, `services/tester_paper.py` |
| Paper cash is *derived*: `PAPER_STARTING_CAPITAL + Σ Trade.net_pnl − Σ open locked capital` | `brokers/paper.py:114` |
| The tester buy checks the **house** cash, not the tester cash (`paper_broker.get_available_cash`) | `services/tester_paper.py:257`, finding F-T1 |
| `check_entry` counts positions, drawdown, sector exposure for the **whole mode** | `services/risk.py:471` |
| Signal rows mix the **shared market call** with the **house outcome** (`was_executed`, `rejection_reason`) | `db/models/trading.py:93` |
| Brain TRADE already includes the house risk gate (M07); a TRADE lowered only by risk is WATCH + `blocked_by_risk` | `strategies/brain.py:92` |
| Kill switch `system_state`: one global row | `db/models/safety.py:20` |
| Writes owner-only; **reads open to any signed-in account while plans are off** | `api/deps.py:165` |
| Telegram: one bot, one `TELEGRAM_CHAT_ID` | `notifications/telegram.py:39` |
| API runs `uvicorn` **without `--proxy-headers`**, so `request.client.host` is the proxy, not the visitor | `backend/Dockerfile:62` |
| Redis is in the stack but **unused by the code** | `core/config.py:86` only |

### 1.2 Proposed

```text
          ┌────────────── SHARED, runs once (unchanged code) ──────────────┐
ingest ─► models / brain nightly ─► strategies evaluate ─► MARKET SIGNALS
          └────────────────────────────────────────────────────────────────┘
                                   │  (read-only to every portfolio)
         ┌─────────────────────────┼──────────────────────────────┐
         ▼                         ▼                              ▼
  HOUSE portfolio           member portfolio A             member portfolio B …
  house risk + execution    manual paper BUY/SELL          manual paper BUY/SELL
  (existing path,           via portfolio executor:        (release D: optional
   same numbers)            lock → check → reserve →        auto-follow runner)
                            fill → ledger → commit
```

Four ideas carry the design:

1. **Portfolio is a first-class thing** (`portfolios` table). Every money row points at one.
2. **Market signal ≠ portfolio decision.** A signal (stock, BUY/EXIT, confidence, levels) is
   shared. What a portfolio *did* with it lives in `portfolio_decisions`, house included. The
   house risk outcome stays on `signals` too, unchanged, so nothing that reads it breaks.
3. **Fail closed.** Every request resolves an explicit `PortfolioScope`. A member request with a
   missing, foreign or unknown portfolio is refused. There is **no silent fallback to the house**.
   Only the owner and the API key reach the house, and only by naming it.
4. **One executor per portfolio write.** Manual orders, exits and (later) automatic orders all
   pass through one atomic function that locks the portfolio, checks, reserves cash, fills,
   writes the ledger and commits, or does nothing at all.

### 1.3 Approaches considered

| | Approach | Verdict |
|---|---|---|
| **A** | `portfolios` table + `portfolio_id` FK + scoped service layer | **Chosen** |
| B | Postgres Row-Level Security alone | Not the main mechanism (scheduler crosses portfolios; failures silent). Optional later hardening on top of A |
| C | Schema or database per user | Rejected: N× migrations, no shared market data |

---

## 2. Database schema changes

Additive by intent: no existing column is renamed, dropped or re-meant. Additive does **not**
by itself prove rollback is safe. Every release has a rehearsed rollback (§8).

### 2.1 New tables

**`portfolios`**
| column | type | notes |
|---|---|---|
| id | int PK | |
| owner_user_id | FK users, nullable | null only for `house` |
| kind | varchar(16) | `house` · `tester` · `real` · `member` |
| generation | int default 1 | +1 on each reset (§3.4) |
| name | varchar(64) | |
| mode | varchar(8) | CHECK (kind = 'real' OR mode = 'paper') |
| starting_capital | numeric(14,2) | members: `MEMBER_STARTING_CAPITAL` (default 1,000,000) at creation; house: display only |
| status | varchar(12) | `active` · `paused` · `archived` |
| auto_follow | bool default **false** | release D only; CHECK false until then |
| started_at / archived_at | timestamptz | |
| UNIQUE (owner_user_id) WHERE kind='member' AND status <> 'archived' | | one live member portfolio per user |

**`cash_ledger_entries`**: append-only (no UPDATE/DELETE grant needed by the app)
| column | type | notes |
|---|---|---|
| id | bigint PK | |
| portfolio_id | FK | index (portfolio_id, ts) |
| ts | timestamptz | |
| kind | varchar(16) | `deposit` · `reserve` · `release` · `buy` · `sell` · `charges` · `adjustment` |
| amount | numeric(14,2) | signed |
| order_id / position_id / trade_id | FK null | cause |
| idempotency_key | varchar(64) null | UNIQUE (portfolio_id, idempotency_key, kind) |
| note / created_by | text / varchar(128) | |

Available cash = Σ amount. Reservations are `reserve` (−) and are matched by exactly one
`release` (+) when the order fills, fails or is cancelled. The **derived formula stays as an
independent cross-check** per portfolio (nightly + in tests). House: ledger is **shadow only**
until the owner approves switching. `brokers/paper.py` keeps the derived figure for the house,
so trial numbers cannot move.

**`portfolio_decisions`**: what a portfolio did with a shared signal
| column | type | notes |
|---|---|---|
| id | bigint PK | |
| portfolio_id / signal_id | FK | UNIQUE (portfolio_id, signal_id) |
| outcome | varchar(16) | `executed` · `rejected` · `ranked_out` · `skipped` · `error` |
| rule / reason | varchar(32) / text | same codes as `risk_events.rule` |
| quantity, order_id, position_id, decided_at | | |

**`invitations`** (release C): token_hash (SHA-256, unique), email (optional; if set, must match),
plan, starting_capital, created_by_user_id, expires_at (7 days), used_at, used_by_user_id, revoked_at.

**`audit_log`** (release A): append-only; ts, actor_user_id, actor_label, action, target_type,
target_id, before JSON, after JSON (changed fields only, never secrets), ip, user_agent.

**`login_codes`** (release A): one-time Google login hand-off: code_hash (unique), user_id,
expires_at (60 s), used_at.

**`user_notification_settings`** (release E), **`job_runs`** (release C minimum, D full): as revision 1.

### 2.2 Changed tables

| table | change | release |
|---|---|---|
| `users` | + `role` (`owner` · `tester` · `member`), + `token_version`, + `failed_login_count`, + `locked_until`; later + `status`, `email_verified_at`, `invited_by_user_id`. `is_superuser` kept, **always equal to `role = 'owner'`** (enforced on write) so old code stays correct | A (+C) |
| `orders` | + `portfolio_id`, + `client_order_id` varchar(64), UNIQUE (portfolio_id, client_order_id) | B |
| `positions`, `trades`, `portfolio_snapshots`, `risk_events`, `brain_approvals` | + `portfolio_id` (nullable → backfilled → NOT NULL in a later migration) + indexes | B |
| `signals`, `strategies`, market/feeds/ml/brain tables | unchanged; shared | – |
| `system_state` | unchanged (global owner kill switch, applies to every portfolio) | – |

### 2.3 Relationships

```text
users 1─* portfolios 1─* orders / positions / trades / snapshots / risk_events / cash_ledger_entries
portfolios 1─* portfolio_decisions *─1 signals *─1 strategies
users 1─* audit_log (actor)   users 1─* login_codes   users 1─* invitations (creator / user)
```

### 2.4 Backfill mapping (release B)

| existing rows | portfolio |
|---|---|
| strategy `real_trading` | `real` (owner) |
| strategy `tester_paper` | `tester`, `owner_user_id = vijay` (D6). Converted to `kind=member` in release C; history kept as-is |
| every other row (incl. `strategy_id IS NULL`, brain) | `house` |
| `portfolio_snapshots` | `house` (to be confirmed against `take_snapshot` during B) |

---

## 3. Shared signals vs portfolio decisions; execution safety

### 3.1 Shared (run once, unchanged)
Ingest, predictions, `brain_nightly`, strategy `evaluate()`, stock scores, and the **house**
book's `process_decision`, including its risk checks and orders.

### 3.2 What members see
- **Ideas**: today's shared signals (v1 strategies + brain TRADE) with confidence and levels.
- **"Held back by the house account"**: brain WATCH rows with `blocked_by_risk`, shown in a
  separate, labelled list (D5). They are **never** executed automatically, by anyone.
- Members buy or sell **by hand** (D3). The member's own risk rules (same ladder, +8/−4/15-day
  protocol, sector cap, drawdown halt, all computed on **their** account value) still gate a manual
  buy, and the reason is shown when one is refused.

### 3.3 Portfolio executor (`services/portfolio_executor.py`, release B/C)

One function for every member money movement: `execute(db, scope, intent, idempotency_key)`.
`intent` is a manual buy, manual sell, automatic exit (stop/target/time) or, in release D, an auto entry.

1. **Idempotency**: if an order with `(portfolio_id, client_order_id)` already exists, return it
   unchanged. A double-click or a retried request never buys twice.
2. **Lock**: `SELECT … FROM portfolios WHERE id = :pf FOR UPDATE` (one row lock per portfolio,
   no new infrastructure). For sells, also lock the position row and keep the existing
   `exit_in_progress_at` claim.
3. **Check**: portfolio `active`; global kill switch; member risk rules (`check_entry(scope)`).
4. **Reserve**: insert `reserve` = −(price × qty × (1 + slippage) + estimated charges).
5. **Fill** (paper broker, real prices) → order, position/trade rows stamped with `portfolio_id`.
6. **Settle**: `release` the reservation; insert `buy`/`sell` and `charges` entries for the actual
   amounts.
7. **Commit.** Any exception rolls back steps 4–6 together, so nothing half-written survives.

**Crash recovery:** paper fills are synchronous, so a crash is a rollback. A resting
(limit) paper order keeps its `reserve` until the order ends. `reconcile_orders` then writes the
`release`. A nightly `ledger_check` flags (a) any `reserve` without a `release` whose order is
finished, and (b) ledger ≠ derived cash. It alerts the owner, and **nothing self-corrects
silently**.

**Partial exits, fees, retries:** each sold slice writes its own `sell` and `charges` entries,
and its pro-rata entry charges move exactly as `execution._finalize_partial_close` does today.
Tests prove ledger = derived formula after every step, including retries of the same request.

### 3.4 Resets (D4)
Reset = archive and start a new generation, never delete:
1. lock portfolio; close open positions at current paper prices with exit reason `RESET`;
2. set `status=archived`, `archived_at`;
3. create a new `portfolios` row (same owner, `generation+1`, fresh `deposit` of the configured capital);
4. `audit_log` `portfolio.reset` with before/after summary (value, P&L, trade count).
Past generations stay readable under "Past practice runs". Reports default to the live generation.

### 3.5 Release D: optional automatic following
The revision-1 runner (after the 15:45 scan and the brain strategy run) is built only after
B and C are stable, behind `portfolios.auto_follow` (CHECK false until D ships). It goes through the same
executor. It never buys "held back by the house" ideas (D5), and it is validated separately before the owner
switches it on for anyone.

---

## 4. Backend changes (by release)

| area | change | release |
|---|---|---|
| `core/security.py`, `api/deps.py`, `endpoints/auth.py` | roles, token versioning, lockout, Google one-time code, startup secret guard, member reads fail closed, tester-only writes | **A** |
| `services/audit.py` (new) | `record(...)` used by auth, role changes, plan changes, resets, invitations | **A** |
| `cli.py` | `audit-roles` (dry run), `set-role`, `disable-user`; `create-user` requires `--role` | **A** |
| `services/scope.py` (new) | `PortfolioScope`; `scope_for(principal, portfolio_id)` raises on missing/foreign | B |
| `brokers/paper.py`, `services/risk.py`, `services/execution.py`, `services/portfolio.py` | thread `scope`; house path unchanged; member path through executor | B |
| `services/portfolio_executor.py` (new) | §3.3 | B/C |
| endpoints `portfolio.py`, `orders.py`, `signals.py`, `risk.py`, exports | scoped; member allowlist for manual paper orders | B/C |
| `endpoints/me.py`, `endpoints/admin.py` (new, minimum) | profile/password, reset; invitations, users, disable, audit log, job runs | C |
| `services/portfolio_runner.py` | auto-follow | D |
| Telegram per user, email verification/reset | | E |

Owner-only and unchanged in every release: Zerodha/Kite, My Holdings, real orders, safety,
brain stage/approvals, strategies, ML, finance, mutual funds, backtest, system administration.
`ALLOW_LIVE_TRADING`/`TRADING_MODE` are not touched by any release.

---

## 5. Frontend screens and journeys

| Journey | Screens | release |
|---|---|---|
| Sign in (password or Google, now via one-time code) | Auth screen | A |
| Change password / sign out everywhere | Settings | A |
| Owner invites | Admin → Invitations | C |
| New member joins | `/join?token=…` → username, password → account with ₹10,00,000 practice money → Home | C |
| Member daily use | Home, Ideas (shared + "held back by the house" list), My portfolio, Positions, Records, My limits, Settings | C |
| Manual buy/sell | Ideas / Watchlist / Positions buttons (as the tester screens work today) | C |
| Reset | Settings → "Start a new practice run" (confirm; old run kept) | C |
| Owner admin (minimum) | Users (role, status, last login, value), disable/enable, Audit log, Jobs | C |
| Telegram link, email reset | Settings | E |

Every member screen shows "Practice money: no real orders". Plain English throughout.

---

## 6. Security and authentication assessment

### 6.1 Threat model (release A focus)

| Asset | Threat actor | Threat | Today | Release A control |
|---|---|---|---|---|
| Owner powers (stage, approvals, safety, real account) | Any account wrongly marked superuser | Abuse of owner powers | **3 superusers** incl. a tester | Roles; only the verified primary stays owner (D1); `is_superuser` mirrors `role` |
| Owner powers | Internet attacker | Password guessing on `/auth/login` | No limit | Per-account lockout, constant-time failure path, audited |
| Sessions | Thief of a token (laptop, logs, XSS) | Reuse for 12 h, even after a password change | No revocation | `token_version` in JWT; bump on password change / sign out everywhere / disable / role change |
| Sessions | Log/history/Referer reader | JWT in Google redirect URL | `/?token=<JWT>` | 60-second one-time code, exchanged by POST |
| Token signing | Anyone, if a deploy forgets secrets | Forge owner JWTs | Defaults `change-me` | API refuses to start outside `local` with default/empty secrets |
| House portfolio data | Any non-owner signed-in account | Read the owner's book | Readable while plans off | Members fail closed (plan rules apply even when plans are off); tester sees only tester book + shared screens |
| Tester book | Tester | Close any position via generic close route | Allowed (tester is owner today) | Tester writes limited to tester-book buy/close |
| Accounts | Internet | Self-register | Code default `ALLOW_SIGNUP=True` (prod: false) | Default false; invitations in C |
| Audit trail | Insider | Change roles/plans without trace | No audit | `audit_log` for auth + admin actions |
| Real Zerodha | Everyone but the owner | Real orders | `require_real_account` | Unchanged; tests re-asserted |

Out of scope for A, and accepted for now with a note: token in `localStorage` (XSS → token theft;
mitigate later with CSP / httpOnly cookie); no email verification/reset (E); IP-based limits
(the API cannot see real visitor IPs until `--proxy-headers` is configured, so limits are per account).

### 6.2 Findings and fixes

| # | Finding | Fix | Release |
|---|---|---|---|
| S1 | Non-owner accounts read the house book while plans are off | Member reads fail closed | A |
| S2 | Three superusers; tester has owner powers | Roles + audited change (§6.5) | A |
| S3 | No login rate limit/lockout | 5 failures → 15-minute lock per account; dummy bcrypt for unknown users | A |
| S4 | No token revocation; `sub` = username | `uid` + `tv` claims; lookup by id | A |
| S5 | JWT in Google redirect URL | One-time code | A |
| S6 | Default secrets accepted | Startup guard | A |
| S7 | Token in `localStorage` | Later (CSP / cookie) | later |
| S8 | No email verification/reset | Free sender, tested (D7) | E |
| S9 | `ALLOW_SIGNUP` defaults true in code | Default false; invitations | A / C |
| S10 | Shared API key = owner | Unchanged; documented; maps to house only | – |
| F-T1 | Tester buy checks house cash | Fixed by per-portfolio cash in B | B |

### 6.3 Authorization model
`Principal(user, via_api_key)` gains `role`. `is_owner` = API key or `role == 'owner'`.
`is_tester` = `role == 'tester'`. `require_auth`:
- owner → as today;
- tester → reads as today (shared screens + `book=tester`), writes only `POST /portfolio/tester/buy`
  and `POST /portfolio/positions/{id}/close` **for tester-book positions** (checked in the handler);
- member → reads by plan rules **even when plans are off** (fail closed), no writes except
  self-service auth routes (password, sign out everywhere).
Real-account routes: `require_real_account` unchanged (owner role + `REAL_ACCOUNT_USERS`).

### 6.4 Telegram (release E)
One bot; per-user chat id linked by a one-time `/start CODE`. No cross-portfolio content.

### 6.5 Production account audit (read-only, 2026-10-16, via `GET /admin/users`)

| id | username | sign-in | today | last login | **proposed role** | why |
|---|---|---|---|---|---|---|
| 48 | sudeeksha | password | OWNER | 2026-10-16 | **owner (the only one)** | owner's verified primary account (decided 2026-10-16); stays the only name in `REAL_ACCOUNT_USERS` |
| 1 | naresh | password | OWNER | 2026-08-28 | **member** | secondary account: no owner powers, no My Holdings |
| 51 | vijay | password | OWNER | 2026-10-16 | **tester** (→ member in C, D6) | secondary: no owner powers, no My Holdings; keeps only his testing-book buy/close so his 4-week test keeps working |
| 50 | naresh.gudiganti23 | Google | user | 2026-09-10 | **member** | secondary account |
| 44 | admin | password | user | 2026-09-09 | **disable** | generic name, unknown holder |
| 2 | claude_verify_tmp | password | user | 2026-08-10 | **disable** | leftover test account |
| 4 | claudecheck1787413845531 | password | user | 2026-08-22 | **disable** | leftover test account |

**Owner decision (2026-10-16): `sudeeksha` is the only owner; every other account is secondary,
with no owner privileges and no My Holdings / real-account access.** `REAL_ACCOUNT_USERS` stays
`sudeeksha` (unchanged). Since P0 real-account access needs `role = owner` **and** a name in
`REAL_ACCOUNT_USERS`, no secondary account can reach My Holdings even if listed by mistake.
**Nothing has been changed on prod yet.** The changes are applied after the P0 deploy by the
owner-run CLI (`swingtrade set-role` / `disable-user`), each one audited (runbook step 12).

---

## 7. Scheduler and jobs

| job | change | release |
|---|---|---|
| all existing jobs | unchanged | A |
| `check_exits` 60 s | positions carry `portfolio_id`; member exits go through the executor; alerts to the portfolio owner | B/C |
| snapshots | one per active portfolio | B |
| `ledger_check` 16:30 (new) | ledger vs derived; orphan reservations; alert, never auto-fix | B |
| `portfolio_runner` | auto-follow | D |
| `daily_summary` | per member if enabled | E |

Concurrency: APScheduler `max_instances=1`; portfolio row lock in every executor call; position
exit claim; ledger idempotency keys; `portfolio_decisions` unique key.

---

## 8. Migration and rollback

### 8.1 Principles
- Every migration has an `upgrade` and a tested `downgrade`.
- **Rollback is rehearsed, not assumed.** For every release: on a local DB shaped like prod,
  (1) upgrade, (2) start the **previous** commit's API and worker against the upgraded schema and run
  its smoke tests, (3) downgrade and run the old code again. Known trap: the old code's startup
  calls `alembic upgrade head` and will not know the newer revision. It then falls back to
  `create_all` (`db/session.py:130`). The rehearsal must show that this boots cleanly and changes nothing.
- **Production-shaped data**: release A needs only the 7-user shape (built in tests from §6.5).
  Release B needs a real prod snapshot: the owner runs `pg_dump` on the droplet and restores it
  locally (open question Q3). Migration post-checks (row counts, zero NULLs, house cash/value/drawdown
  identical) run against it before prod.
- A pre-deploy database backup is taken for every release.

### 8.2 Release-specific
- **A**: §8 of the P0 plan (users columns, `audit_log`, `login_codes`; role backfill = today's powers).
- **B**: M1 additive → M2 backfill with in-migration post-checks → M3 NOT NULL after one clean prod day.
- Feature switch `MULTI_USER_ENABLED=false` (B onward): member routes 404, executor refuses
  member intents, house unaffected.

---

## 9. Testing strategy and acceptance criteria

| Suite | Acceptance |
|---|---|
| House golden test (B+) | Same seeded DB → identical house signals, orders, positions, cash, drawdown before/after each release |
| Isolation (B+) | Every route (walked from OpenAPI, like `test_permissions_review.py`), every report/export, every job: member A never reads/changes B or house; foreign/missing scope → refused; a new money route without a scope rule fails the walk |
| Authorization (A+) | role × route matrix: owner / tester / member / disabled / no credentials / API key |
| Auth security (A) | lockout, unlock after 15 min, revocation on password change & sign-out-everywhere & disable & role change, one-time Google code (single use, 60 s, wrong user), startup guard |
| Executor concurrency (B/C) | Parallel threads: two manual buys on one portfolio with cash for one → exactly one fills; manual sell + `check_exits` on the same position → one sell; retried request with same `client_order_id` → one order |
| Ledger (B/C) | ledger = derived after buy, partial exit, full exit, fees, retry, cancelled limit order, reset; to the paisa |
| Crash recovery (B/C) | exception injected after reserve / after fill → no rows, no ledger entries |
| Resets (C) | old generation readable, new one funded, audit row written, open positions closed with `RESET` |
| Migration (every release) | upgrade/downgrade on prod-shaped data; post-checks; old-code-on-new-schema rehearsal |
| Real account (every release) | members/testers refused on every real-account route; live trading gate unchanged |

Trading-sensitive changes (risk, sizing, execution, exits) need tests and owner approval before `main`.

---

## 10. Release sequence

| Release | Content | Size | Depends on |
|---|---|---|---|
| **A: Security hardening (P0)** | roles + account audit, lockout, token revocation, Google one-time code, startup guard, member reads fail closed, tester write limits, audit log, CLI | M | – |
| **B: Migration + isolation (P1/P2)** | portfolios, ledger (house shadow), `portfolio_id` backfill, `PortfolioScope` fail-closed, executor, isolation/golden/migration tests | XL | A, prod snapshot (Q3) |
| **C: Manual-paper member pilot (P3 + minimum P5)** | invitations, join flow, member screens, manual BUY/SELL, resets, Vijay → member, minimum admin (users, disable, audit, jobs) | M–L | B |
| **D: Optional auto-follow (P4)** | runner, separate validation, owner switch per portfolio | L | C stable |
| **E: Telegram + account management (P6/P7)** | per-user Telegram, free email sender after security/delivery tests, verification, password reset | M | C |

Each release: own plan → tests → owner approval → merge to `main` (= prod). No push, merge,
deploy or permission change without the owner's separate approval.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| A missed query in ~500 money-table references mixes data (B) | OpenAPI route walk, service isolation tests, grep audit list, optional RLS |
| A refactor moves house numbers mid-trial (B) | House path unchanged + golden test; house ledger shadow-only |
| Role change locks the owner out (A) | Backfill reproduces today; changes applied one by one by CLI after owner approval; API key always works |
| Vijay's test breaks mid-way (A) | `tester` role keeps exactly his tester routes; rehearsed with his real routes |
| Everyone is signed out once at deploy (A) | Expected: old tokens lack `tv`. Tell testers in advance |
| Old code on new schema at rollback | Rehearsed per release (§8.1) |
| Member ideas look like advice | Invite-only, practice-only; Q1 |

## 12. Open questions

1. **Regulation**: SEBI research-analyst rules if this grows beyond friends/testers or is ever paid.
2. ~~Primary owner account~~: **decided 2026-10-16: `sudeeksha` only; all others secondary.**
3. **Prod snapshot for release B**: can the owner run `pg_dump` on the droplet for a local rehearsal copy?
