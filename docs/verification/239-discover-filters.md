# #239 Verification: Discover scanner filters and pattern tags

Baseline: main at 5de3b9c (24 Nov 2026 IST). Tests and this note only; no behaviour was changed.

## In plain English

- **The filters that exist return exactly the stocks that match.** Each was compared with an independent filter over a fixed set of stocks. Discover itself filters by word (TRADE, WATCH, WAIT, AVOID), sector and a search box. There is no cap-tier, price, liquidity or score-band filter on Discover. Cap tier and a confidence floor exist on the top-picks list, and a company-size filter exists on the 5-day picks list.
- **Stock search** matches the symbol or name in any letter case, hides inactive stocks and other exchanges, ranks the exact symbol first, and returns an empty list (not an error) when nothing matches.
- **Signals and picks** filter correctly by type, executed flag, age, confidence floor (exactly at the floor is kept), small-cap switch, budget, already-held stocks and count. The 5-day picks list uses a 5-day window, shows one row per stock with the most confident model, and each pick carries its own horizon (5 or 15 days).
- **Pattern tags** (breakout, pullback in an up-trend, tight base, breakdown) are computed from stored daily candles as of the evening of the run date. Later candles are not seen, the India trading day is used, and a stock with fewer than 60 days gets no tag. Breakout and breakdown also need traded volume; pullback and base do not, so a zero-volume stock can still be tagged a base. Only "breakdown" argues against buying.
- **Gaps found:** the top-picks and buy lists have no age limit, so a BUY signal weeks old is still listed (the 5-day picks list stops at 5 days); and the buy list keeps a stock whose old BUY came from one strategy even after another strategy's newer HOLD, although its own text says it uses each stock's single newest signal.
- Plan access, the 15-day label on 5-day scores and stock identity are cited, not re-tested.

## Results

| # | Check | File:line (baseline) | Expected | Observed | Result |
|---|---|---|---|---|---|
| 1 | Stock search, watchlist, exchange, active, limit, ranking, empty | `api/v1/endpoints/instruments.py:18-55` | equals an independent filter | equal; exact symbol first, watchlisted prefix next | pass |
| 2 | Signals by type, executed, age window, limit, newest first | `signals.py:31-73` | equals an independent filter | equal | pass |
| 3 | Top-picks: confidence floor, small-cap switch, budget, held, count, practice evidence, empty | `signals.py:189-325` | only stocks that qualify | as expected; exactly 0.70 kept, 0.6999 dropped | pass |
| 4 | Picks: 5-day window, one row per stock, own horizon, order | `signals.py:132-186` | as stated | as expected | pass |
| 5 | Pattern tags from stored candles, as of that evening | `brain/modules/m12_stock/setups.py`, `brain/reader.py:89-111` | tagged with what was seen; none for later days | as expected | pass |
| 6 | Tags absent with missing data | `setups.py` (60-bar minimum, zero volume) | none, not a guess | none | pass |
| 7 | Tags named honestly | `setups.py:55-89` | each label and line says what the rule saw | as expected; only breakdown is non-confirming | pass |
| 8 | Old BUY signals on top-picks and buy-list | `signals.py:189-325`, `:328-384` | no signal weeks old | listed at 40 days old | gap f1 (2 strict xfails) |
| 8b | Buy-list: newest signal per stock, any strategy | `signals.py:355-366` (dedupes per strategy and stock; the text says per stock) | an old BUY dropped by another strategy's newer HOLD | still listed | gap f2 (strict xfail) |
| 8c | Buy-list controls | `signals.py:328-384` | fresh BUY listed; a later HOLD from the same strategy and a held stock dropped | as expected | pass |
| 9 | Discover word, sector and search filters, empty message | `frontend/src/trademind/discoverRules.ts`, `newLookW2.test.tsx` (24 pass) | as stated | as expected | cited |
| 10 | 5-day score labelled 15 days | see #385 | | | cited |
| 11 | Plan access for filters or tags | see #335, #458, `test_plans.py` | refused server-side without the feature | `test_plans.py` re-run passes | cited |
| 12 | A stock added from Discover resolves to one stock ID | see #456, #476 | one ID | not re-tested | cited |

## Gaps (strict xfail, not fixed)

- `test_top_picks_do_not_list_a_buy_signal_that_is_weeks_old` and `test_buy_list_does_not_list_a_buy_signal_that_is_weeks_old`: no age limit on either list.

- `test_buy_list_drops_a_stock_whose_newest_signal_from_any_strategy_is_not_a_buy` (gap f2): the buy list's text and code disagree. Also, the buy list uses the broker's mode while top-picks hard-codes paper. The fix for f1 touches the same query.

## Limits

- No cap-tier, price, liquidity or score-band filter exists on Discover, so none could be tested there.
- Tests use the app's API and a test database; production data was not read.

## Tests

New: `backend/tests/test_discover_filters_239.py` (24 pass, 3 strict xfail). Re-run: `test_lane_picks_filters`, `test_lane_picks`, `test_plans`, `test_brain_m12_stock` (95 pass), frontend `newLookW2.test.tsx` (24 pass).
