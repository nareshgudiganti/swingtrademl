# Data retention — PROPOSAL for owner review

Status: **proposal only. Nothing here is decided.** I am not a lawyer; the legal and tax periods marked
"check" must be confirmed by the owner or an adviser before launch (DPDP Act, tax/accounting rules for
invoices, SEBI record-keeping if it applies). The account-deletion code is built so that these choices
are small changes in `services/account_deletion.py::anonymise`.

## What "delete my account" does today (behind `ACCOUNT_DELETION_ENABLED`, off by default)

1. Person asks (signed in, password re-entered; Google accounts confirm by email only). The owner account is refused.
2. We email a one-hour confirm link. Nothing is deleted yet.
3. On confirm: a live Pro subscription is cancelled at the provider **first** (if that fails, nothing is
   scheduled and the link still works), every session is ended, sign-in is blocked, and a **14-day** grace
   period starts (`ACCOUNT_DELETION_GRACE_DAYS`). The email carries a "keep my account" link.
4. After the grace period the daily job (03:30 IST) anonymises the account. The row stays as a stub.
5. The person can download their own data any time before (`GET /account/export`).

## Table by table

| Table | Holds | Proposal | Why / open question |
|---|---|---|---|
| `users` | username, email, name, mobile, password hash, Google id, plan, role | **Anonymise**: keep the row; username becomes `deleted-<id>`; email, name, mobile, password hash, Google id, verification date cleared; inactive; plan free | Other tables point at the row id. Email becomes reusable. |
| `auth_tokens` | hashed email tokens, request IP | **Delete** all of the person's rows | No value after deletion. |
| `login_codes` | one-time Google sign-in codes | **Delete** | Same. |
| `user_watchlist_items` | the person's watchlist, notes, own buy price and quantity | **Delete** | Personal and not needed by anything else. |
| `invite_requests` | name, email, phone, note, invite code hash, linked user | **Anonymise** the linked row (name "Deleted", placeholder email, phone/note/code cleared) | Keeps the owner's count of invites without the person's details. Rows with no linked user (never signed up) are not touched here: **decide a separate age limit** (e.g. delete rejected/unused requests after 12 months). |
| `subscriptions` | provider subscription id, status, paid-through dates, user id | **Keep**, unchanged (no name/email in it) | Payment/tax records. **Check** the required period (commonly 6–8 years for invoices in India). Linked only to the anonymous stub afterwards. |
| `billing_events` | provider event ids, type, outcome, payload hash (no payload, no user id) | **Keep** | Idempotency and dispute evidence; holds no personal data. |
| `plan_grants` | free Pro the owner granted, reason text, who granted | **Keep** the row; **review** the free-text `reason` for names before launch | Reason text is written by the owner and may name the person. Option: blank `reason` on deletion. |
| `audit_log` | what happened, by whom, IP, user agent | **Keep**, but replace the person's username in `actor_label` with `deleted-<id>` (done). IP/user-agent kept | A security log should not be rewritten. **Decide**: keep IPs for 12 months then null them? The log is normally append-only; this is the one deliberate exception, limited to the label. Rows where the username was typed on a failed sign-in (no linked user) keep that text. |
| `account_deletions` | request status and dates, no personal data | **Keep** | Proof the request was honoured. |
| Alert / Telegram tables (`alert_outbox`, settings) | owner's own alerts | Not per customer; **no action** | Single-owner data. |
| Brain, signals, strategies, positions, orders, market data, models, features | owner's trading and shared market data | **Never touched** | Not customer data; the owner's private book is never deleted by a customer request. |
| Off-site backups | copies of everything above | **Proposal**: deleted data ages out of backups on the normal rotation (state the period, e.g. 35 days, in the privacy notice) | Backup/restore drill is a separate task; a restore must re-run deletions for completed requests (the `account_deletions` table lists them). |
| Email provider (Resend) and Razorpay | delivery logs, customer/subscription records at the provider | **Outside our database.** Razorpay keeps its own records; Resend log retention is set in its dashboard | Mention both in the privacy notice. |

## Decisions I need from the owner

1. Grace period: 14 days OK?
2. Keep subscription records for how many years (tax adviser)?
3. `plan_grants.reason`: keep, or blank on deletion?
4. IP / user agent in `audit_log`: keep forever, or clear after N months?
5. Unused invite requests (people who never signed up): age limit?
6. Backup rotation period to state publicly.
7. Should a person who deletes be allowed to sign up again with the same email straight away (currently yes, after completion)?

## Not covered yet

- Deleting an account that has real-money holdings: not applicable (only the owner has those).
- A deletion request submitted by an admin on someone's behalf (needs the admin role task).
- Frontend screens (request, confirm, keep-my-account pages): owned by the frontend work.
