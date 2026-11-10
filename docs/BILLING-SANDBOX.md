# Pro billing in the Razorpay SANDBOX

This is for the owner. Billing is built, private, and switched off. Nothing here moves real money.
Live billing stays off through 2026.

## What exists

- Free and Pro only. Pro comes from any one of: the plan an admin set by hand (as before), an owner-made
  complimentary grant (own record: who, when, why, optional end date), or a paid subscription.
- A paid subscription gives Pro while its status is `active`, or `pending` (the bank is retrying a renewal),
  and only up to the paid-through date plus `BILLING_GRACE_DAYS` (default 4). Cancelling at the end of the
  period keeps Pro until the paid-through date, then it returns to Free by itself (worked out when read; no job).
  `halted`, `paused`, `completed`, never-paid (`created`/`authenticated`) and cancelled-past-the-date are Free.
- Who scheduled a cancel matters. When WE ask for a cycle-end cancel we store `cycle_end_requested_at`. A provider
  status `cancelled` keeps Pro until the paid-through date ONLY if that request is recorded AND the fetched
  `ended_at` is at (within an hour of) the paid-through date. An immediate cancel in the Razorpay dashboard, a
  `cancelled` with no `ended_at`, or one we never requested all count as ended now (less access, never more).
  An `active` subscription with our request keeps Pro until the paid-through date; our cancel with
  `at_cycle_end=false` ends access at once.
- A FAILED lookup is not a cancellation. If the fetch from Razorpay fails (network error, timeout, 4xx/5xx, auth
  error, a reply that is not readable) nothing is stored: status, paid-through date and flags stay exactly as
  they were, the webhook answers 502 so Razorpay retries, and the event id is forgotten so the retry is
  processed. Plan resolution and `/billing/me` keep serving the last stored state, so an entitled subscriber
  stays Pro until a confirmed state arrives or the paid-through date plus grace passes. Only a SUCCESSFUL fetch
  can end access. The conservative "treat as ended" rule above applies only to successful fetches whose fields
  are ambiguous, never to failed lookups.
- Two switches, both default false, and plan resolution obeys neither:

  | Switch | Controls | Does NOT control |
  |---|---|---|
  | `BILLING_ENABLED` | the billing routes (false = every one answers 404) | who is Pro |
  | `BILLING_ACCEPT_NEW_CHECKOUTS` | only `POST /billing/checkout` (false = 404); `GET /billing/plans` still works and says `checkout_open: false` so the screen can show "upgrades are closed" | `/billing/me`, `/billing/cancel`, the webhook (all keep working when `BILLING_ENABLED` is true) |

  Existing entitlements (unrevoked grants, entitled subscriptions in the database) are ALWAYS honoured by plan
  resolution, whatever the switches say, so turning billing off never silently drops a paying member. A person
  with no subscription and no grant resolves exactly as before.
- `BILLING_PROVIDER=fake` (default) needs no keys and no network: the private journey can be walked with
  `POST /api/v1/billing/fake/simulate` (activated, charged, pending, halted, cancelled, completed).

## Test the real Razorpay sandbox

1. Create a Razorpay account and stay in TEST mode (toggle at the top of the dashboard).
2. Dashboard, Account and Settings, API Keys, generate TEST keys. Key id starts with `rzp_test_`.
3. Create the monthly plan in test mode. Either in the dashboard (Subscriptions, Plans) or with the script,
   which is a dry run unless you add `--execute` and refuses any key that is not `rzp_test_`:
   `RAZORPAY_KEY_ID=... RAZORPAY_KEY_SECRET=... python backend/scripts/razorpay_create_test_plan.py`
   Copy the plan id (`plan_...`).
4. Dashboard, Webhooks, add `https://<your-site>/api/v1/billing/webhook`, choose a webhook secret of your own,
   and tick the subscription events (authenticated, activated, charged, pending, halted, cancelled, completed, paused, resumed, updated).
5. In the deployment `.env` ONLY (never in the repo, a chat or a ticket) set:
   `BILLING_ENABLED=true`, `BILLING_PROVIDER=razorpay`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
   `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_PLAN_ID_PRO_MONTHLY`, and `PRO_PRICE_MONTHLY_PAISE` (the default is a placeholder).
   Leave `ALLOW_LIVE_BILLING` unset: with it false a key that is not `rzp_test_` is refused.
6. The checkout screen is a later (frontend) task. Until then call `POST /api/v1/billing/checkout` as a signed-in
   member; it returns `key_id` and `subscription_id` for Razorpay Standard Checkout. Pay with the test card
   `4718 6091 0820 4366`, any CVV, any future expiry.
7. To see a renewal: Dashboard, Subscriptions, open the subscription, "Charge this now" (test mode only).
   "Charge as Success" sends `subscription.charged`. "Charge as Failure" moves it to pending (`subscription.pending`;
   the member keeps Pro for the grace window); four failures in a row halt it (`subscription.halted`, member goes to Free).
   `GET /api/v1/billing/me` shows status, paid-through date and whether a cancel is scheduled.

## How webhooks are handled (so you can reason about it)

Signature first (HMAC-SHA256 of the raw body with the webhook secret, `X-Razorpay-Signature`); a bad one gets 400.
Each event id is stored once (`billing_events`), so a repeat does nothing. Delivery order is not guaranteed, so on
every subscription event the app fetches the subscription's current state from Razorpay and stores that, never the
event's own content. No payload is stored, only a hash. If the fetch fails the app answers 5xx and forgets the
event so Razorpay's retry is processed.

## Still UNVERIFIED (confirm in the sandbox before trusting)

- Provider fields the cancel rule relies on: that a fetched `cancelled` subscription carries `ended_at`, that for a
  cycle-end cancel `ended_at` is at the paid-through date and for an immediate cancel it is the time of the cancel,
  and that an `active` subscription stays `active` (not `cancelled`) between our cycle-end request and the cycle end.
  `cancel_at_cycle_end` and `has_scheduled_changes` are NOT read; the code is conservative if these assumptions
  fail (it ends access rather than extending it).
- Whether a cancel-at-cycle-end shows up in the fetched subscription (we keep our own record and do not rely on it).
- That `current_end` stays set on a cancelled subscription, and what `current_end` is for a `pending` one.
- Webhook retry count, schedule and timeout; the exact event header name casing (we read `X-Razorpay-Event-Id`;
  without it the body hash is used as the id).
- Whether `total_count` of 120 is accepted for "until cancelled".
- Whether a `pending` subscription's `current_end` is the due date, which decides the grace window.
- UPI Autopay and e-mandate in test mode, plan change, and pause/resume (pause is not offered).
- Recurring and UPI Autopay may need separate enablement on a live account.

## Going live (not before a written go-ahead; not in 2026)

`ALLOW_LIVE_BILLING=true` is the only switch that lets a live key work, and nothing sets it. Before anyone does:

1. A compliance opinion on whether paid stock ideas count as investment advice (SEBI), and any registration it requires.
2. Written confirmation from Razorpay about our business category (they ask for SEBI proof for advisory merchants).
3. GST and invoicing decisions with a CA (Razorpay's invoices API makes non-GST invoices only).
4. Terms, refund and cancellation policy, pricing and contact published on the site.
5. KYC and bank account complete, and live-key activation approved.
6. Repeat the whole sandbox run with live keys at a tiny price before inviting anyone.
