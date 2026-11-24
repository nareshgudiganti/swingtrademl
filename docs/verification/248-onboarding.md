# #248 Verification: onboarding and paper account setup

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev3b_test`. Written 2026-11-24 (IST).
Tests and this note only. No behaviour was changed. No email was sent (the tests use the existing log-only sender).
Nothing sensitive is in this note.

## In plain English

- **Sign-up follows the settled rules.** Public registration is closed by default; the invite route needs an owner-approved
  code for the same email, used once; a new account is always an ordinary free member (never owner or tester), and no login
  token is returned at registration. Google sign-in admits only addresses the owner has listed (empty by default), only when
  Google says the email is verified, and creates no account otherwise. All of this was already tested; the new tests add the
  Google refusals and the member-only result for a new Google account.
- **Outgoing mail is off by default** (it is only logged until a provider is set), and the app defaults to paper trading only:
  setting "live" on its own still gives the paper broker.
- **Email verification is a switch that ships off.** When it is on, an unverified member cannot sign in (tested). Whether it is
  on in production was not read.
- **A new member gets no paper account of their own.** There is one shared paper book (starting capital 10,00,000, which sits
  exactly on the 10 lakh rung of the limits ladder: up to 8 positions, 25% per sector). The tables for positions, orders, trades
  and strategies have no user column, so registering creates no book rows, no strategy and no broker connection. Per-person
  paper accounts are planned, not built.
- **What a brand-new member sees first is honest.** With plans switched on a free member gets empty lists (watchlist, tracker,
  sold records, picks, past results) and a market mood of "unknown" with no numbers, never invented ones. With plans off they are
  refused the house screens outright. They cannot reach the broker session, the real account, orders or the safety switches.
- **One person's sign-up does not touch another's data.** Registering, verifying and signing in a second person left the first
  person's account row and watchlist exactly as they were, and the second person sees none of the first's data.
- **Deleting an account leaves no row pointing at a missing person** (the account is kept as an anonymised stub, so nothing is
  orphaned). **Two gaps:** a deleted person's sold records stay on the stub, and the data export leaves out their sold records.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test in `test_onboarding_verify.py` unless named) | Result |
|---|---|---|---|---|---|
| s1 | Defaults: closed sign-up, mail off, paper only, Google list empty | `core/config.py:66,77,95,123-124,135` | closed and safe | `test_the_defaults_are_paper_only_closed_sign_up_and_outgoing_mail_off`; `test_a_live_setting_alone_still_gives_the_paper_broker` (`brokers/__init__.py:25`) | Pass |
| s2 | Verified email | `api/v1/endpoints/auth.py:196-201` (`REQUIRE_EMAIL_VERIFICATION`), `account_auth.py:114-178` | unverified cannot sign in | enforced when the switch is on (`test_account_auth_email.py::test_login_enforcement_matrix`, cited); the switch defaults OFF (`test_email_verification_is_not_enforced_by_default`) | Observed: production value not read |
| s3 | Invite-only route; register route | `auth.py:218-310`, `invites.py` | invite needed, one use, member only | `test_invites.py` (cited, 40 tests) | Pass (cited) |
| s4 | Google gates | `auth.py:543-665` | allow-list and Google-verified email, member only | `test_google_refuses_an_address_that_is_not_on_the_allow_list_*`, `test_google_refuses_an_address_google_has_not_verified_*`, `test_a_new_google_account_is_an_ordinary_free_member_*` | Pass |
| p1 | Starting capital and ladder tier | `services/portfolio.py:portfolio_value_and_cash`, `services/limits.py` | 10,00,000 on the 10 lakh rung | `test_a_brand_new_book_starts_at_the_paper_starting_capital_on_the_matching_ladder_rung` | Pass |
| p2 | A paper account per person | `db/models/trading.py` (no user column) | n/a | none exists (`test_there_is_no_per_person_paper_account_*`) | Observed: not built |
| p3 | Registering creates nothing in the book, no broker link | `account_auth.py:register` | no new book rows | `test_registering_creates_no_book_rows_no_strategy_and_no_broker_connection` | Pass |
| p4 | A member cannot reach a broker, real account, orders, safety | `api/deps.py:require_auth`, `TESTER_PRIVATE_PREFIXES` | refused | `test_a_new_member_cannot_reach_a_broker_*` (five calls); `test_p0_member_reads.py` (cited) | Pass |
| p5 | Tester and member limits | `api/deps.py`, `core/plans.py` | plan limits, private accounts hidden | cited: #335 (plans and entitlements) and #426 (private accounts); not re-tested | Pass (cited) |
| v1 | What a new member sees first | `/me/watchlist*`, `/signals/picks`, `/signals/track-record`, `/market-data/regime`, `/me/plan` | empty, unknown, no invented figures | `test_a_brand_new_member_sees_empty_lists_and_unknown_not_invented_numbers` | Pass |
| v2 | Plans off, brand-new member | `api/deps.py:require_auth` | house screens refused | `test_with_plans_off_a_brand_new_member_is_refused_the_house_screens_*` | Pass |
| i1 | One person's sign-up never touches another's rows | register, verify, login | A unchanged | `test_one_new_persons_sign_up_verification_and_sign_in_change_nobody_elses_rows` (A's whole account row and list compared before and after) | Pass |
| d1 | Deletion leaves no orphan | `services/account_deletion.py:anonymise`, FKs to `users` | no row points at a missing person | `test_after_deletion_no_row_points_at_a_missing_person` (every foreign key to users checked) | Pass |
| d2 | Deletion removes the person's own records | `account_deletion.py:165-190` (clears the list, invites, tokens, login codes) | all personal records | the sold records (`user_watchlist_sales`) stay on the stub | **GAP** |
| d3 | Data export | `account_deletion.py:238-280` | the person's own data, complete | lists watchlist items and buy price only; no quantity, no sold records | **GAP** |

## Gaps (strict expected-failure tests with `raises=AssertionError`, none fixed)

1. **d2:** `anonymise` should also delete the person's `user_watchlist_sales` rows. Test: `test_a_deleted_persons_sold_records_are_removed`.
2. **d3:** the export should include quantity and sold records. Test: `test_the_data_export_includes_the_persons_sold_records`.

Plus the observations: email verification ships off (s2, check the production value) and no per-person paper account exists (p2).

## Not covered here

The new-user screens were not run in a browser. Billing and Pro setup, account deletion's billing side and the sign-in screens'
wording were left to their own tests (cited). Production settings were not read.
