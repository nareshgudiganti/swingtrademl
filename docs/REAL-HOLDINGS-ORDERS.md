# Real orders from My Holdings — owner guide

## What it does
On the **My Holdings** screen you can press **Buy real** or **Sell real** to send a small,
real order to your Zerodha account. You choose the stock and the number of shares; the app
shows a red confirm box first. The trading bot itself stays on paper — this only sends the
orders you place by hand. A bought stock gets a safety stop 4% below and a target 8% above
the price it actually filled at, and is then tracked like your other holdings.

## Switching it on and off
- It is **off** until `ALLOW_REAL_HOLDINGS_ORDERS=true` is set in the prod `.env` on the
  server, and the app is restarted. While it is off the buttons do not appear.
- To switch it off again: set `ALLOW_REAL_HOLDINGS_ORDERS=false` (or delete the line) and
  restart the app. Orders already sent to Zerodha are not cancelled by this.
- Never change `TRADING_MODE` or `ALLOW_LIVE_TRADING` for this feature — it does not need them.

## Limits (buys only — selling is never blocked by money limits)
- At most ₹10,000 per order: `REAL_HOLDINGS_MAX_ORDER_INR` in the prod `.env`.
- At most ₹25,000 of buys per day: `REAL_HOLDINGS_MAX_DAY_INR` in the prod `.env`.
- Orders only go in while the market is open, only one order per stock at a time, and you can
  never sell more shares than the app shows you hold.

## One-time Zerodha step
Zerodha only accepts orders sent by an app from a registered address. In the Kite developer
console, open the app's settings and register the prod server's static IP address. Without
this, every order is refused by Zerodha.

## First trial checklist
1. Pick a cheap stock and **Buy real** 1 share during market hours.
2. Check the Kite app: the order should be there and complete.
3. Within a few minutes it shows in **My Holdings**, and in the **Real-money report** tab.
4. Sell that share with **Sell real** the same week, and check both places again.

## "Waiting at Zerodha"
An order shows as waiting from the moment it is sent until the app hears it is finished
(filled, refused or cancelled). The app checks about once a minute during market hours; an
order that fills just before the close may only be finished the next morning. While a stock
has a waiting order, its sell buttons are greyed out, a new buy for it is refused, and
**Import from Zerodha** skips it.

If one stays stuck for a day:
1. Look in the Kite app first — did it fill, or was it cancelled?
2. If Zerodha says it is finished but the app still shows it waiting, the order row has to be
   marked CANCELLED in the database. Nothing in the screen does this — ask Claude or a
   developer to do it, and tell them what the Kite app shows.

## "I sold this" vs "Sell real"
- **Sell real** sends a real sell order to Zerodha and records the real price it fills at.
- **I sold this** only updates the app's records, for a sale you already made yourself in
  the Kite app. It sends nothing to Zerodha. Do not use it while a real order is waiting.
