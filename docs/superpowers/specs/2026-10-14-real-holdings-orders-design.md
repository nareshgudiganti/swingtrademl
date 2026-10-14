# Real buy/sell from My Holdings — design

Date: 2026-10-14 · Status: approved in chat, awaiting spec review · Owner decision required before `main`

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

## Non-goals

- No change to the bot, TradeMind approvals, or tester book: they stay on the paper broker.
- `TRADING_MODE` stays `paper`, `ALLOW_LIVE_TRADING` stays `false`.
- No GTT / stop orders at Zerodha, no automatic exits of real holdings.
- No limit-price orders (can be added later).

## Safety

1. **New latch `ALLOW_REAL_HOLDINGS_ORDERS: bool = False`** in `core/config.py`, set only in prod `.env`.
2. **Narrow gate in `KiteBroker.place_order`.** Today it refuses unless `settings.is_live_trading`.
   New rule: allow when `settings.is_live_trading` **or** (`ALLOW_REAL_HOLDINGS_ORDERS` **and**
   `request.tag` starts with the reserved prefix `stml-hold-`). Only `services/real_orders.py`
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
   calls `kite_broker.place_order` directly with tag `stml-hold-buy-<order_id>`.
3. Kite returns PENDING (accepted). Rejection → Order REJECTED, message shown + Telegram.
4. On fill (reconciliation, below) the `Position` is created in the `real_trading` book at the
   real average price with stop −4% / target +8%, so existing alerts apply.

**Sell** — `POST /portfolio/real/positions/{id}/sell {quantity?}`
1. Checks, then new `execution.place_real_holding_sell()`: `Order` (mode=`live`, SELL, MARKET,
   CNC, `exit_reason=MANUAL`, `position_id`) → `kite_broker.place_order`, tag
   `stml-hold-sell-<order_id>`.
2. On fill: full close or partial close via the existing finalize helpers; the Trade appears in
   the Buy and sell report. Real charges come in later through the nightly fill capture.

**Reconciliation** — `reconcile_pending_orders` today only checks `Order.mode == broker.mode`
(paper in prod), so live My Holdings orders would never finish. Add a second pass: PENDING/OPEN
orders with mode=`live` on the `real_trading` strategy are checked with `kite_broker`, finished
with the existing `_finish_reconciled_order` / `_fail_reconciled_order`. Live-charge estimation
inside `_finish_reconciled_order` must key off the order's mode, not `settings.is_live_trading`.

**Import from Kite** already skips stocks already tracked, so an app-bought stock is not duplicated.

## Files

| File | Change |
|---|---|
| `core/config.py` | `ALLOW_REAL_HOLDINGS_ORDERS`, `REAL_HOLDINGS_MAX_ORDER_INR`, `REAL_HOLDINGS_MAX_DAY_INR` |
| `.env.example` | the three names, latch `false` |
| `brokers/kite.py` | narrow gate (Safety 2) |
| `services/real_orders.py` (new) | checks + calls into execution |
| `services/execution.py` | `place_real_holding_buy/sell`, second reconcile pass, mode-based charge note |
| `api/v1/endpoints/portfolio.py` | two owner-only routes + a `GET /portfolio/real/orders-status` (latch on/off, limits, today's spend) for the screen |
| `frontend/src/api/client.ts`, `trademind/pages/MyHoldings.tsx` | "Buy real shares" form, "Sell real" per holding, red confirm, disabled while pending / switched off |

## Testing (no real Zerodha calls — Kite replaced by a recording fake)

- Latch on, bot latches off: bot / brain / tester orders still go to paper; `KiteBroker.place_order`
  refuses a request without the `stml-hold-` prefix.
- Latch off: both routes refused, Kite never called.
- ₹10,001 buy refused; third ₹10K buy in a day refused; sell allowed regardless of money limit.
- Sell more than held refused; non-`real_trading` position refused.
- Market closed refused; second order while one pending refused.
- Non-owner → 403.
- Reconcile: live real-holdings buy fill creates a Position; sell fill closes/shrinks it;
  rejection creates nothing; paper bot orders unaffected.

## Rollout

1. Tests green, code review.
2. **Owner approves** before merge to `main` (order-path rule).
3. Deploy with latch off; screen shows "Real orders are switched off".
4. Owner registers the prod server's static IP in the Kite developer console (needed for app orders).
5. Owner sets `ALLOW_REAL_HOLDINGS_ORDERS=true`; first trial: buy 1 share of a cheap stock, sell it
   the same week, check My Holdings and the report.
6. Rollback: set the latch to `false` — buttons stop at once; existing holdings unaffected.
