# Ops digest (DRAFT for owner review, not merged, not deployed)

Branch `draft/ops-digest`. Lets Claude (or you) check production each day through one read-only call.

## What it is

`GET /api/v1/ops/digest` returns one JSON summary for today (IST):

- **needs_attention**: a plain list of problems (empty and `all_clear: true` when none).
- **brain**: stage, today's runs and their status, the latest run's market banner (NORMAL / DEFENSIVE /
  NO_NEW_TRADES), stocks scanned, ideas per word (TRADE / WATCH / WAIT / AVOID), top 5 ideas.
- **v1_scan**: version 1 signals made today per strategy, how many were bought, top BUY signals and why one
  was blocked, the last scan result from the worker.
- **trading_paper**: orders today (by status and side, failures), positions opened and closed today
  (names and exit reason), open position counts for the bot and testing books.
- **scheduler**: worker alive, every job's last status, jobs needing a look.
- **data_freshness**: newest daily candle vs the one expected, trading days behind.
- **risk**: paper portfolio value, drawdown vs the 15% limit, whether new entries are halted.

No new table: what was scanned each day is already stored (`brain_runs`, `brain_decisions`, `signals`).
Nothing is written. No decision logic was added; every number comes from existing queries.

## What it leaves out on purpose

- Any profit, loss, return, win rate or outcome of any idea or position. This keeps the blind trial seal
  safe whether `trial_seal.SEALED` is on or off (a test checks the response text for those words).
- The real Zerodha book (`real_trading`) and owner-private strategies, even as counts.
- Secrets, settings values, account numbers.

## How the key works (changed from the original brief)

The repo already has scoped service keys (`services/service_keys.py`, owner-managed at
`/admin/service-keys`). Instead of a second mechanism with an env var, this draft adds one new scope,
**`read_ops`**: it may call only `GET /ops/*` and nothing else, and the existing rules apply (GET only, hashed
in the database, shown once, expiry, rotate, revoke, last-used time). With no key created, nothing can open
the route (fails closed). The shared `API_KEY` and the owner login can also read it; testers and members get 403.
The existing `read_all` scope can read it too (it already reads most screens).

I did not add `READ_ALL_API_KEY`: an env-var key would be a second long-lived secret outside the audit,
expiry and revoke trail. Say so if you still want one.

## Enable on prod (after you approve and merge)

1. Merge `draft/ops-digest` to `main` (deploys; no migration needed, `scope` is a plain text column).
2. Signed in as owner, open the admin service-keys screen (or `POST /api/v1/admin/service-keys`, which needs
   the admin step-up code) and create a key: `{"name": "claude-daily", "scope": "read_ops", "expires_in_days": 90}`.
3. Copy the `stk_...` key when shown (it is shown once). Keep it in your password manager, not in the repo.
4. Call it:
   `curl -s -H "X-API-Key: <the stk_ key>" https://swingtrademl.com/api/v1/ops/digest`
5. To stop access: revoke the key in the same screen. Rotate every 90 days.

No server env var and no restart are needed.

## Risks and notes

- The digest shows which stocks the brain likes today and your paper portfolio size and drawdown. Anyone with
  the key sees that. Treat the key like a password; it cannot place orders or change anything.
- It is the same data as the logged-in app, so it is not more sensitive than what Vijay or other owner-level
  logins see, but prod is public, so use the 90-day expiry.
- Cost: each call runs about a dozen small queries. Calling it once or twice a day is fine.
- Job statuses come from Redis; if Redis is down the section says "run records unavailable" rather than failing.
- A section that errors reports only the error type, never the message.
- The digest reports `trial_seal.active` so a reader knows whether the seal is on. It is currently `False`
  in the code (`SEALED = False`): confirm that is what you intend; the digest is safe either way.

## Open decisions for the owner

1. Accept the `read_ops` scope on the existing service keys instead of an env-var key?
2. Should `read_all` keys also see the digest (today yes), or only `read_ops`?
3. Any extra section wanted (e.g. weekly report status, model registry)? Kept small for now.
4. Deploy time: after 16:30 IST per the usual rule.
