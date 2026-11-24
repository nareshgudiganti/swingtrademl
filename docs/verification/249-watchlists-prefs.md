# #249 Verification: watchlists and risk preferences

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev3b_test`. Written 2026-11-24 (IST).
Tests and this note only. No behaviour was changed. Nothing sensitive is in this note.

## In plain English

- **Each person's watchlist is their own.** Adding, removing and re-adding work; the same stock cannot be on one person's list
  twice (the database refuses a second row); a list holds at most 50 stocks. The buy price, quantity, tracker and "sold records"
  are per person too: person B sees none of person A's, and cannot change, remove or sell A's stock. No way for one person to
  reach another's list or records was found (existing tests cover the basics, the new ones add the tracker and sold records).
- **Only the owner can change the bot's own watchlist or a strategy's limits.** A member or a tester gets "403" on every one of
  those routes, and the strategy stays unchanged. The only routes open to everyone are the eight "my watchlist" ones.
- **There is no 10-stock limit in the code.** The personal list stops at 50. The bot's own watchlist has no maximum at all (60
  stocks were accepted in a test), and no plan limit mentions a watchlist (plans limit picks per day, history and company size).
  The 10-stock figure for the brain is therefore a production setting or a habit, not a rule the app enforces.
- **A person has no risk setting of their own.** Nothing on a user, and nothing on the personal list, stores or changes a
  limit. Limits come from the account size ladder plus two settings the owner holds (1% risked per trade, 15% drawdown stop).
  The only per-strategy knobs are "most positions" and "share of the account in one stock", and an unset or zero value gives
  exactly the ladder. A tighter value is honoured. A looser value replaces the ladder: that is the known gap #463, not
  repeated here.
- **Two gaps (none fixed):**
  1. **A renamed stock splits a list entry.** Entries are saved by the symbol's text, not by the stock's id. The identity layer
     follows a rename to one stock (tested), but after a rename the old entry shows no company name or prices, and adding the new
     symbol puts the same company on the list twice.
  2. **The stop setting on a strategy does nothing for the main strategy.** The screen labels a strategy "Conservative" or
     "Aggressive" using its stored stop percentage, but the production strategy takes its stop from the settled rule (-4%). Only
     the simple benchmark strategy reads the stored value. Display only; no limit is loosened.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test in `test_watchlists_prefs_verify.py` unless named) | Result |
|---|---|---|---|---|---|
| w1 | Add, remove, re-add; duplicates; one list per person | `api/v1/endpoints/my_watchlist.py:162-215`; `db/models/user_watchlist.py` (unique per person and symbol) | works, no duplicate | `test_my_watchlist.py` (cited); `test_the_database_itself_refuses_a_second_row_*` | Pass |
| w2 | Size limits | `my_watchlist.py:41` (`MAX_ITEMS = 50`), `services/ingestion.py:208` (no cap), `core/plans.py` limits | a stated cap | personal list 50 (`test_my_watchlist.py::test_list_is_capped`); no cap on the bot's list; no plan limit about a watchlist (`test_the_personal_list_is_capped_at_fifty_*`, `test_the_bots_own_watchlist_has_no_size_cap_*`) | Observed: no 10-stock rule in code |
| w3 | Per-person isolation | `my_watchlist.py:_me` (user from the credential only), `api/deps.py:SELF_SERVICE_ROUTES` | A never sees or changes B | `test_my_watchlist.py::test_nobody_sees_or_changes_someone_elses_list` (cited); `test_a_persons_buy_price_quantity_tracker_and_sold_records_are_their_own` | Pass |
| w4 | Tracker and sold rows behave the same | `my_watchlist.py:/tracker, /sold, /{symbol}/sold` | own rows only; a sale keeps its entry price | the isolation test above; `test_a_sale_keeps_the_entry_price_it_was_made_with_*` | Pass |
| w5 | Who may change the bot's watchlist or a strategy | `api/deps.py:require_auth` (every non-read route is owner-only except the eight self-service ones) | member and tester refused | `test_a_member_or_tester_cannot_change_the_bots_watchlist_or_a_strategys_limits` (four routes, both roles, strategy unchanged); `test_the_only_routes_open_to_every_person_are_the_eight_*` | Pass |
| w6 | An entry through a rename | `user_watchlist_items.symbol` (text) | one stock id, one entry | identity follows the rename (`test_the_identity_layer_follows_a_symbol_change_to_one_stock`, cites #456); the entry loses its name; the new symbol makes a second entry | **GAP** |
| r1 | How a user's risk preference is stored | `db/models/session.py:User` | n/a | no such column or route (`test_a_person_has_no_stored_risk_setting_*`) | Observed: none exists |
| r2 | Defaults when unset | `services/limits.py:219-226` (`if strategy.max_positions:` / `if strategy.capital_allocation:`) | the ladder | unchanged at all six rungs plus two in-between sizes; a zero cannot loosen it (`test_an_unset_strategy_setting_gives_the_ladder_unchanged_*`) | Pass |
| r3 | Only tighter, never looser | same | tighter honoured, looser refused | tighter honoured (`test_a_strategy_may_tighten_*`); looser replaces the ladder: #463 (cited) | Pass / known gap |
| r4 | Settled rules independent of overrides | `core/config.py` (15% halt, 1% risk), `limits.py` (25% sector cap) | unchanged by a strategy value | `test_the_settled_risk_rules_do_not_come_from_any_person_or_strategy_field` | Pass |
| r5 | A stored stop or target percent | `strategies/ml_swing.py:211` (settings only), `strategies/sma_crossover.py:123-124` (reads the stored value), `services/rules_watch.py:121-136` | applied, or not offered | benchmark reads it (`test_only_the_sma_crossover_benchmark_reads_*`); production strategy does not | **GAP** |
| r6 | What the screens show | `frontend/src/pages/Strategies.tsx:57`, `lib/strategyRisk.ts` (label from `stop_loss_pct`); `pages/Capital.tsx`, `trademind/pages/Risk.tsx` (server limits: open positions against the account's limit) | numbers that are applied | the limits screens show the server's ladder numbers; the strategy label uses the stored stop (r5). Read from the source, not run | Observed |

## Gaps (strict expected-failure tests with `raises=AssertionError`, none fixed)

1. **w6:** key a personal list row by the stock's id (and show the current symbol) so a rename keeps one entry. Tests:
   `test_a_list_entry_still_shows_its_company_after_the_symbol_changes`,
   `test_adding_the_new_symbol_of_a_stock_already_on_the_list_is_refused_as_a_duplicate`.
2. **r5:** hide or label the stop and target fields for strategies that do not use them, or have `ml_swing` read them (and only
   when tighter). Test: `test_the_ml_swing_entry_stop_uses_the_strategys_stored_stop_percent`.

## Not covered here

The new look's wave-2 screens were read, not run. The Groww sync (#388) is not on main, so only the existing Groww tracker
(personal list with buy price, quantity and sold records) was checked. A per-user risk preference does not exist yet (the v2
profiles are parked), so there is nothing to test for "can only tighten" beyond the strategy fields above.
