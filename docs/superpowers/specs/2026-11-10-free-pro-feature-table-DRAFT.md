# Free / Pro feature table — DRAFT for the owner (decision D7)

Status: DRAFT, nothing here changes the app. Edit the last column; I will then change the plan
defaults to match. Today's defaults were read from the code, not from the live database: if you
ever edited a plan in the Plans Manager on prod, that saved row wins over the code default, so
please glance at the Plans Manager once before relying on the "today" columns (ASSUMPTION A1).

How plans work today (one paragraph): new people are Free. You switch a person to Pro by hand
(no payment). The master "plans on/off" switch is OFF by default, which only shows the whole app
to testers; members are always limited to their plan. You (owner) are never limited.

## 1. The table

Source for every "today" cell: `backend/src/swing_trade_ml/core/plans.py`. Free = line 103 (features)
and 104 (limits); Pro = line 108 (every feature on) and 109 (no limits). Feature wording = lines 33-79.

| # | Feature (what you call it) | What the customer sees | Free today | Pro today | Suggested for customers | Why (one line) |
|---|---|---|---|---|---|---|
| 1 | Today's picks (`picks`, l.34) | BUY ideas with entry price, target, stop-loss and confidence | ON | ON | Free + Pro | The core product; Free needs it to see any value. |
| 2 | Picks from every model (`all_models`, l.39) | Free: only the base Large Cap model's picks. Pro: picks from all models | OFF | ON | Pro only | Main reason to upgrade; more ideas, more risk of confusion for beginners. |
| 3 | Suggested quantity and rupee amount (`sizing`, l.44) | A box where they type a budget and see how many shares of each pick to buy | OFF | ON | Pro only | Turns a pick into an action; good paid feature. |
| 4 | Market mood (`regime`, l.49) | "Is the market rising, falling or choppy today" | ON | ON | Free + Pro | Cheap, builds trust, and explains why fewer picks appear on bad days. |
| 5 | Past picks and results (`track_record`, l.54) | Every past pick and whether it hit target or stop-loss (Scan Results) | ON (last 30 days, base model, large caps only) | ON (everything) | Free (30 days) + Pro (all) | Honest results help trust; full history is the upgrade. |
| 6 | Bot's closed trades (`bot_performance`, l.59) | The bot's own closed trades and profit or loss (Reports) | OFF | ON | Pro only, but see note N1 | Shows the paper bot's real record; sensitive while the trial is sealed. |
| 7 | Bot's open positions (`bot_portfolio`, l.64) | What the bot holds now and a summary (Open positions page) | OFF | ON | Pro only, but see note N1 | Same as row 6. |
| 8 | Model Lab (`model_lab`, l.69) | How accurate each model's confidence really is | OFF | ON | Pro only (or hide from customers) | Technical; the owner said no jargon for beginners. |
| 9 | TradeMind (`trademind`, l.74) | The TradeMind app's brain decisions and "why" explanations (read-only) | OFF | ON | Pro only, and only after the sealed trial ends | Must never expose sealed trial results (see section 3). |

Limits (plans.py l.82-98 and defaults l.104 / l.109)

| Limit | Free today | Pro today | Suggested for customers | Why |
|---|---|---|---|---|
| Picks shown per day | 5 | no limit | Free 5, Pro no limit | Clear, easy to explain. |
| Company sizes shown | Large only | Large, mid and small | Free large only, Pro all | Small caps are riskier; a natural Pro tier. |
| Days of history | 30 | no limit | Free 30, Pro no limit | Matches row 5. |

Always on for every signed-in person, no plan needed (not in the catalogue; `api/deps.py` l.200):
their own watchlist and its tracker (`/me/watchlist...`), their own account (sign in, password, logout everywhere)
and "what does my plan show" (`/me/plan`). Suggested: keep as is. (ASSUMPTION A2: the watchlist stays free for all.)

Notes
- N1. Rows 6 and 7 show the bot's paper trades. They are not the sealed brain trial, but they are the house
  book. Decide whether customers should see the house record at all; the safest default is "Pro only, after trial".
- N2. The plans on/off master switch is OFF in code. Before any customer signs up it must be ON, otherwise
  testers see everything. (Members are already limited either way.)
- N3. Free users already see the Pro rows greyed or hidden by the app menu, and the API refuses them (proved by
  `backend/tests/test_plans_route_coverage.py`).

## 2. Owner-only: never opens to any plan

These are not products, they are your account. No plan setting can open them, and the new tests refuse a Pro caller on all of them.

- Real Zerodha holdings, My Holdings, real orders and the real-account reports.
- Capital, money added, finance and mutual funds (`/finance`, `/mutual-funds`).
- Safety switches, risk limits and the Zerodha login (`/safety`, `/risk`, `/auth/kite`).
- Placing, approving or cancelling any order, and every trading-stage control (go-live, approvals, stage, compare, trial journal).
- Alerts and notifications (`/notifications`, `/brain/alerts`).
- Settings, jobs, server watch, model registry and backups, backtests, experiments, lanes and the weekly report.
- The brain console: module list, run traces, per-run alerts, what-if, proposals.
- Plans Manager, user list, invites and the plan switch (`/admin/...`).
- Every write (anything that changes data), except a person editing their own watchlist and a tester's paper buy.

## 3. Sealed trial

Brain trial results that are sealed (`services/trial_seal.py`) must stay hidden from customers. Today Pro's
TradeMind reads (`/brain/runs/latest`, `/brain/runs/{id}`, `/brain/health`, `/brain/learning`, `/brain/changes`,
`/brain/why/{symbol}`, `/brain/track/{symbol}`) apply the seal in the learning and proposals handlers, but I did
not audit every handler for it (ASSUMPTION A3). Recommendation: keep row 9 OFF for everyone until the trial ends.

## 4. Things the audit found that you should decide on (no behaviour was changed)

1. `/signals/buy-list` (Pro, row 7) ignores the plan filters: it lists every strategy's BUY signals, including
   rule strategies and the hand-bought `real_trading` strategy, and every company size, and leaves out stocks the
   bot holds. Free cannot reach it. Suggested fix: apply the same visibility filter as `/signals/picks`. **FIXED on main (holdings PR): owner-private strategies are hidden from members; see `tests/test_pro_real_holdings_gaps.py`.**
2. `/brain/track/{symbol}?book=real` (Pro, row 9) accepts a `book` from the caller with no check, so a Pro user could
   ask for the real-holdings track. **FIXED on main (holdings PR, 2026-11-10/11): the handler now refuses any non-paper book for a non-owner (403). The former xfail test is now a normal passing test.**
3. `/ml/models` and `/ml/calibration` (Pro, row 8) accept `strategy_id`, `mode`, `model_id` filters and return every model,
   not only the ones the plan covers. Low risk, but not plan-filtered.
4. `/auth/kite/login` has no sign-in requirement (by design for the browser redirect). It starts a Zerodha login.
   Check that it only redirects and cannot be abused (not changed here).
