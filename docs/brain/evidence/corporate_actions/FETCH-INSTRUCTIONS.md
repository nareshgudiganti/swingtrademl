# How to run the read-only price check (for the owner)

**What it does.** It asks Zerodha Kite for the current daily prices of two stocks and puts them next to the prices we have stored, so we can tell whether Kite has already adjusted old prices for a company split or demerger.

- HINDUNILVR, 25 Nov 2025 to 12 Dec 2025 (the Kwality Wall's demerger)
- BAJAJELEC, 8 Sep 2023 to 20 Sep 2023

**It cannot change anything.** The database is opened in read-only mode (the database itself refuses writes), it never logs in to Kite, never renews or switches off a session, and never places an order. It uses the newest Kite session that is already stored, makes two history requests, and closes. It does not print any password, key or token.

## How to run (on the production server)
1. Do not run it during market hours if you can avoid it (after 16:30 IST is best).
2. Log in to the server and, in the project folder, run:

       bash docs/brain/evidence/corporate_actions/hul_fresh_fetch_readonly.sh

   (If the container is not called `stml-worker`, check with `docker ps` first.)

## What you will see
For each stock, three parts:
1. A list `date,open,high,low,close,volume` of the fresh prices from Kite.
2. A comparison list `date,stored_close,fetched_close,ratio_fetched_over_stored`.
3. One line `VERDICT HINT`:
   - ratio about 1.000 on every date: Kite's old prices are the same as ours (not adjusted).
   - the same number (for HINDUNILVR roughly 0.98) on every earlier date: Kite has adjusted its history, ours is the old scale.
   - anything else: do not guess, send it to us.

## What to send back
Copy everything the script printed (it contains only prices) and paste it in the chat. Nothing in it is secret.

## If it stops with a message
- `STOP: no active Kite session` or `session has expired` or any line beginning `ERROR:`: **stop.** Do not log in to Kite from anywhere else, do not retry repeatedly, and do not try to fix the session. Send us the message exactly as printed.
- Reason: a new login from another place can end the live session the trading system is using.
