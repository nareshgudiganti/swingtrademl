# oa5: Today = Home + Swing Picks merged — feature list

**Date:** 2026-10-23. **Task:** Atlas oa5. **Branch:** `feature/oa5-today-merged`.
**Rule:** display only. Nothing here changes picks, decisions, orders, sizing, stops, limits or the frozen trial.

This is the checklist the acceptance test runs against: every thing the old TradeMind **Home** (`/trademind`) and
**Swing Picks** (`/trademind/dashboard`) pages showed or let you do, plus the **classic Dashboard** (`/dashboard`),
and where each one lives after the merge. The same ids are in `frontend/src/trademind/today/featureList.ts`;
`frontend/src/trademind/today/featureList.test.tsx` checks the two lists match and that each item is reachable for
each role that should have it.

Roles:
- **owner**: the owner console.
- **tester**: sees the whole app while plans are off, but never the owner's private areas (safety switches, stage,
  approvals, alerts; see `TESTER_PRIVATE_PREFIXES` in `backend/src/swing_trade_ml/api/deps.py`).
- **member**: a plan user with TradeMind.
- **real**: only accounts in `REAL_ACCOUNT_USERS` (`can_see_real_account`).

Today shows no real-money figure and no real-money button for anyone. The holdings on Today come from the brain's
run, which is the bot's paper book, and are labelled Paper.

## The Today page, top to bottom

1. **Status strip**: market mode and banner (everyone); kill switch, drawdown against the halt level, and trading
   stage (owner only, each linking to Control, Risk or Go-live).
2. **Needs you**: holdings needing attention (everyone, Paper); ideas waiting for your OK and learning proposals
   waiting for a decision (owner only; you decide on Go-live and Learn, nothing is decided on Today). The holdings
   part is its own component (`today/HoldingsNeedsYou.tsx`) so the paused "What to do with your stocks today" card
   (`feature/holdings-daily-read`) can replace it with a small merge.
3. **Today's ideas**: the horizon selector (1 / 5 / 15 / 30 / 90 days, honest states), the idea counts, and the top 5
   ideas as the one recommendation card (`beginner/LiveIdeaCard`). A horizon with no strategy shows no ideas.
4. **What changed since yesterday** and **Today's insights**.
5. **All of today's picks** (`id="picks"`): everything Swing Picks had. `/trademind/dashboard` and the
   "Swing Picks" tab under Today (kept, so nothing moves in the menu) open Today here.

## Feature list

| id | From | Item | Where it lives now | Roles |
|---|---|---|---|---|
| market-mode | Home | Market mode word, its icon and plain-English tag | Today, status strip | owner, tester, member |
| run-time | Home | When the brain's run was made | Today, status strip | owner, tester, member |
| banner-headline | Home | The market banner's headline | Today, status strip | owner, tester, member |
| market-situation | Home | The market situation the brain recognised | Today, status strip | owner, tester, member |
| idea-counts | Home | Idea counts by TRADE / WATCH / WAIT / AVOID, with View All | Today, Today's ideas | owner, tester, member |
| no-trade-reason | Home | Why there is no TRADE idea today | Today, Today's ideas | owner, tester, member |
| holdings-attention | Home | Holdings needing attention (MONITOR / REDUCE / EXIT), each opens its stock | Today, Needs you (holdings slot) | owner, tester, member |
| changes-summary | Home | What changed since yesterday | Today | owner, tester, member |
| top-ideas | Home | Top 5 ideas as the one recommendation card, with View All | Today, Today's ideas | owner, tester, member |
| insights | Home | Today's insights | Today | owner, tester, member |
| horizon-cards | Swing Picks | Horizon selector with honest Validated / Experimental / Unavailable states | Today, Today's ideas | owner, tester, member |
| how-it-works | Swing Picks | "How it works?" | Today, All of today's picks | owner, tester, member |
| summary-strip | Swing Picks | Market view, NIFTY 50, top sectors, estimated chance, total picks | Today, All of today's picks | owner, tester, member |
| horizon-pills | Swing Picks | Horizon pills above the pick list, with the count | Today, All of today's picks | owner, tester, member |
| pick-filters | Swing Picks | Search, sector, minimum ranking, Reset | Today, All of today's picks | owner, tester, member |
| pick-table | Swing Picks | The pick list table and its View buttons | Today, All of today's picks | owner, tester, member |
| pick-detail | Swing Picks | Pick detail: chart, quote, trade setup, why, key risks | Today, All of today's picks | owner, tester, member |
| horizon-unavailable | Swing Picks | A horizon with no strategy says so and shows no picks | Today, both selectors | owner, tester, member |
| research-experiment | Swing Picks | The owner's research experiment on 5 and 30 days | Today, All of today's picks | owner |
| disclaimer | Swing Picks | Practice-mode note | Today, All of today's picks | owner, tester, member |
| dashboard-url | Swing Picks | `/trademind/dashboard` keeps working | Today, opened at the pick list | owner, tester, member |
| kill-switch | New | New buys on, or paused by the kill switch | Today, status strip | owner |
| drawdown | New | Drawdown from peak against the halt level | Today, status strip | owner |
| stage | New | Trading stage | Today, status strip | owner |
| approvals-waiting | New | Ideas waiting for your OK | Today, Needs you | owner |
| proposals-waiting | New | Learning proposals waiting for a decision | Today, Needs you | owner |
| classic-status | Classic Dashboard | Last scan, Paper badge, trend badge, warning banner | Admin > System (and the top bar chips) | owner |
| classic-refresh | Classic Dashboard | Refresh now | Admin > Control | owner |
| classic-attention-bot | Classic Dashboard | Bot's own trades to look at | Portfolio > Bot (Paper) | owner, tester, member |
| classic-attention-real | Classic Dashboard | Your own Zerodha shares that need a decision | Portfolio > My Zerodha (Real) | owner, real only |
| classic-worth-buying | Classic Dashboard | Worth buying today | Discover > Opportunities | owner, tester, member |
| classic-tier-performance | Classic Dashboard | How each company size did in 90 days | Insights > Records | owner, tester, member |
| classic-strategy-signals | Classic Dashboard | Per-strategy signals, read only | Discover > Opportunities ("Version 1 strategy signals", new) | owner, tester |
| classic-recent-exits | Classic Dashboard | Recent stop-loss and target exits | Insights > Records | owner, tester, member |
| classic-stock-detail | Classic Dashboard | A stock's detail | Discover > stock page | owner, tester, member |

**Not moved:** the classic Dashboard's "full model-ranked watchlist" (Advanced, `POST /ml/predict?persist=true`). It
generates and stores predictions, so it is the owner's decision (oa15); the classic page keeps it until then.

**Classic Dashboard route:** Today does not replace `/dashboard`. It stays for accounts without TradeMind until
Phase 6. `/home` is unchanged (oa10's rule is already how `App.tsx` routes it).

## Why the strategy signals are owner and tester only

`GET /strategies` and `/strategies/{id}/signals` are not opened to any plan (`core/plans.py` `ROUTE_RULES`), so a
member's request is refused. The list is drawn only for accounts that see the whole app.
