# Real buy/sell from My Holdings — design

Date: 2026-10-14 · Status: **spec approved by owner 2026-10-14** · Built on branch `feature/real-holdings-orders`, latch OFF. Not merged, not activated, until safety tests pass and the owner reviews.

## Goal

The bot keeps paper trading for at least six months. During that time the owner wants to buy and
sell **real** shares in their Zerodha account **from the My Holdings screen**, in small amounts,
by hand. Nothing automatic touches real money.

## Decisions (settled with the owner, 2026-10-14)

| Question | Decision |
|---|---|
| Approach | Real orders sent from the app (not Kite Publisher, not flipping the whole system live) |
| DDPI | Active (request completed 2026-09-20) — app sells are allowed by Zerodha |
| Limits | ₹10,000 per order, ₹25,000 per day — **buys only**; sells never blocked by the money limit |
| Stop/target | Alerts only (−4% / +8%, Telegram + screen). No GTT, no automatic real sells |
| Order type | MARKET with `KITE_MARKET_PROTECTION`, product CNC |
| Quantity on sell | Owner chooses; default = all held |

## Scope (owner, 2026-10-14)

In scope, and nothing else: **manual BUY, manual SELL, live holdings synchronisation, order safety,
reporting.**

Out of scope: any new automated trading or brain logic, any paid backup/infrastructure, any
redesign of the app. The paper trial stays untouched — its evidence decides whether TradeMind is
worth scaling.

## Non-goals

- No change to the bot, TradeMind approvals, or tester book: they stay on the paper broker.
- `TRADING_MODE` stays `paper`, `ALLOW_LIVE_TRADING` stays `false`.
- No GTT / stop orders at Zerodha, no automatic exits of real holdings.
- No limit-price orders (can be added later).

## Safety

1. **New latch `ALLOW_REAL_HOLDINGS_ORDERS: bool = False`** in `core/config.py`, set only in prod `.env`.
2. **Narrow gate in `KiteBroker.place_order`.** Today it refuses unless `settings.is_live_trading`.
   New rule: allow when `settings.is_live_trading` **or** (`ALLOW_REAL_HOLDINGS_ORDERS` **and**
   `request.tag` starts with the reserved prefix `stmlh` (`REAL_HOLDINGS_TAG_PREFIX` in `brokers/base.py`; Kite tags are alphanumeric, max 20 chars). Only `services/real_orders.py`
   builds requests with that prefix. `get_broker()` is unchanged, so every other path still gets
   `paper_broker`.
3. **Owner only.** Both routes use `Depends(require_owner)` (`api/deps.py`).
4. **Server-side checks** in `services/real_orders.py`, all before anything is sent:
   - latch on, else "Real orders are switched off."
   - market open (`core/market_session`), else "Market is closed, opens at …".
   - buy: `qty × live price ≤ REAL_HOLDINGS_MAX_ORDER_INR` (default 10000) and today's IST buy
     total (filled + pending real-holdings buy orders) + this order ≤ `REAL_HOLDINGS_MAX_DAY_INR`
     (default 25000).
   - sell: position is OPEN, belongs to the `real_trading` strategy, `1 ≤ qty ≤ position.quantity`.
   - no other PENDING/OPEN real-holdings order for the same instrument.
   - any refusal → HTTP 409/422 with one plain-English sentence; nothing reaches Zerodha.

## Flow

**Buy** — `POST /portfolio/real/buy {symbol, exchange, quantity}`
1. `real_orders.buy()` runs the checks, then calls a new `execution.place_real_holding_buy()`.
2. That writes an `Order` (mode=`live`, strategy=`real_trading`, BUY, MARKET, CNC, PENDING) and
   calls `kite_broker.place_order` directly with tag `stmlhb<order_id>`.
3. Kite returns PENDING (accepted). Rejection → Order REJECTED, message shown + Telegram.
4. On fill (reconciliation, below) the `Position` is created in the `real_trading` book at the
   real average price with stop −4% / target +8% of the fill price (fixed, the settled trade rules), so existing alerts apply.

**Sell** — `POST /portfolio/real/positions/{id}/sell {quantity?}`
1. Checks, then new `execution.place_real_holding_sell()`: `Order` (mode=`live`, SELL, MARKET,
   CNC, `exit_reason=MANUAL`, `position_id`) → `kite_broker.place_order`, tag
   `stmlhs<order_id>`.
2. On fill: full close or partial close via the existing finalize helpers; the Trade appears in
   the Buy and sell report. Real charges come in later through the nightly fill capture.

**Reconciliation** — `reconcile_pending_orders` today only checks `Order.mode == broker.mode`
(paper in prod), so live My Holdings orders would never finish. Add a second pass: PENDING/OPEN
orders with mode=`live` on the `real_trading` strategy are checked with `kite_broker`, finished
with the existing `_finish_reconciled_order` / `_fail_reconciled_order`. Live-charge estimation
inside `_finish_reconciled_order` must key off the order's mode, not `settings.is_live_trading`.

**Import from Kite** already skips stocks already tracked, so an app-bought stock is not duplicated.

## Live holdings synchronisation

Already on `main`: `services/holdings_sync.py::close_positions_no_longer_held`, run by the
"Import from Kite" button and the daily `sync_real_holdings` job (15:48 IST). It closes a tracked
holding that has left Zerodha at the last price the app saw.

Race this feature creates: an app sell fills at Zerodha, the holding disappears, and the sync can
close the position at a *guessed* price before reconciliation records the *real* fill. Fix: the sync skips any holding whose instrument has a PENDING/OPEN real-holdings order. That is
enough: reconciliation marks the order COMPLETE and closes the position in the same transaction,
so there is no moment where the order is finished but the position is still open for the sync to
guess at. (Reconciliation already returns early if a position is no longer open.)

A fresh app buy reads `quantity: 0` until settlement; the sync already counts `t1_quantity`, so it
is not closed by mistake (keep that guard; add a test with an app-bought T1 holding).

## Reporting

- My Holdings list and the **Buy and sell report** show app orders like any other real trade.
- A small **"Real orders today"** line on My Holdings: switch on/off, ₹ spent today / ₹25,000,
  and any order still waiting at Zerodha (from `GET /portfolio/real/orders-status`).
- Every placed, filled or rejected real order also goes to Telegram in plain words.

## Files

| File | Change |
|---|---|
| `core/config.py` | `ALLOW_REAL_HOLDINGS_ORDERS`, `REAL_HOLDINGS_MAX_ORDER_INR`, `REAL_HOLDINGS_MAX_DAY_INR` |
| `.env.example` | the three names, latch `false` |
| `brokers/kite.py` | narrow gate (Safety 2) |
| `services/real_orders.py` (new) | checks + calls into execution |
| `services/execution.py` | `place_real_holding_buy/sell`, second reconcile pass, mode-based charge note |
| `services/holdings_sync.py` | skip positions with a pending real-holdings order |
| `api/v1/endpoints/portfolio.py` | two owner-only routes + a `GET /portfolio/real/orders-status` (latch on/off, limits, today's spend) for the screen |
| `frontend/src/api/client.ts`, `trademind/pages/MyHoldings.tsx` | "Buy real shares" form, "Sell real" per holding, red confirm, disabled while pending / switched off |

## Testing (no real Zerodha calls — Kite replaced by a recording fake)

- Latch on, bot latches off: bot / brain / tester orders still go to paper; `KiteBroker.place_order`
  refuses a request without the `stmlh` prefix.
- Latch off: both routes refused, Kite never called.
- ₹10,001 buy refused; third ₹10K buy in a day refused; sell allowed regardless of money limit.
- Sell more than held refused; non-`real_trading` position refused.
- Market closed refused; second order while one pending refused.
- Non-owner → 403.
- Holdings sync skips a position with a pending app order; app-bought T1 holding is not closed.
- Reconcile: live real-holdings buy fill creates a Position; sell fill closes/shrinks it;
  rejection creates nothing; paper bot orders unaffected.

## Rollout

1. Build on branch `feature/real-holdings-orders` (from `origin/main`), latch default `false`.
   Not pushed to `main`, not deployed.
2. Tests green, code review.
3. **Owner reviews** the safety tests and code, and approves before merge to `main` (order-path rule).
4. Deploy with latch off; screen shows "Real orders are switched off".
5. Owner registers the prod server's static IP in the Kite developer console (needed for app orders).
6. Owner sets `ALLOW_REAL_HOLDINGS_ORDERS=true`; first trial: buy 1 share of a cheap stock, sell it
   the same week, check My Holdings and the report.
7. Rollback: set the latch to `false` — buttons stop at once; existing holdings unaffected.
