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
- Everything is behind `BILLING_ENABLED` (default false). While false, every billing route answers 404 and the
  plan system ignores subscriptions and grants, so today's members resolve exactly as before.
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

- Whether a cancel-at-cycle-end shows up in the fetched subscription (we keep our own flag and do not rely on it).
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
