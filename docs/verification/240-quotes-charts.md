# #240 Verification: quote freshness and chart states

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev1b_test`. Written 2026-11-24 (IST).
Tests and this note only. No screen, price, calendar, chart or order behaviour was changed. The note holds nothing sensitive.
New tests: `frontend/src/trademind/verify240.test.tsx` (18: 12 pass, 6 are `it.fails` gap markers) and
`backend/tests/test_verify_240_quote_states.py` (9: 8 pass, 1 strict xfail). `tsc --noEmit` is clean. The quote and snapshot rules
(stale, missing, future and raw quotes) were verified in #246 (`docs/verification/246-data-freshness.md`, tests b1 to b7) and are cited here, not repeated.

## In plain English

The question: does every place that shows a price say how old it is, never present a stale or missing price as live, show the last
close with its date when there is no fresh quote, and draw charts honestly (loading, empty, missing days, holidays)?

- **Every TradeMind page carries an age label.** The top bar chip ("Prices from the Fri 27 Nov close", amber when out of date) is mounted in both
  shells. It counts in trading days: a weekend or a market holiday is not a missed day, and the evening after the close one day of age is normal.
  With no stored price it says "No prices yet", never "fresh", and while the market session is unknown it shows nothing at all.
- **The stock page price is labelled** live, delayed, stale, holiday or closed, with its time or date (existing tests plus #246); a stale price is
  never shown as live; while the price is loading no price number is drawn.
- **Charts draw only what exists.** Candle charts draw one body per stored candle and never invent a missing day. The line and area charts are
  drawn only when there is data, and say "Not enough days yet" when there is too little. Missing numbers print a dash, never zero.
- **Four gaps found, pinned by seven markers (six in the browser, one on the server; none fixed):**
  1. **b1, b2: the stock page's fallback close has no date.** Without a snapshot it shows the stored close with the words "at last close" but not
     which day, and when there is no change to show (only one candle) it shows the number with no label at all.
  2. **b6 (server test c3): a position row carries no price time or status.** A position that was never priced is shown at its entry price as exactly 0%
     flat; the only warning on the row is "Exit check unavailable". Screens that list positions therefore cannot say how old each price is.
  3. **c2, c3: two charts print the wrong date.** The Swing Picks and Opportunities charts cut the label from the first ten characters of the candle's
     timestamp, which is a UTC time, so the bar for 30 Nov is labelled 11-29. The candle chart on the stock page reads the date with the browser's own
     time zone and says so in a comment; in any browser outside India it shows the neighbouring day.
  4. **c1, c1b: the candle chart can print invalid numbers** when it is given no candles (no screen does this today, both callers hide the chart) or when
     every volume is zero (a quiet or suspended day), which draws volume bars with `NaN` size.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| a1 | Every page carries an age label | `trademind/TradeMindApp.tsx:202`, `NewLookShell.tsx:125` mount `PricesBadge` | label on both shells | present (`verify240.test.tsx`, "every TradeMind shell mounts the badge") | Pass |
| a2 | The label counts trading days, not calendar days | `trademind/pricesAge.ts:76-127`; calendar from `GET /market/session` (`api/v1/endpoints/system.py:267-289`, `core/market_session.py:120`) | weekend and holiday are not a missed day | Monday morning on Friday's close: fresh, 0 days; after the 24 Nov holiday: fresh; evening after close: "1 day old", not amber; 12 days old: "Out of date" amber (server tests a1-a3; browser tests; `pricesAge.test.ts` full matrix) | Pass |
| a3 | No stored price | `pricesAge.ts:63-69`, `system.py:289` | "No prices yet", not fresh; null date | as expected (`test_a4_*`, browser test) | Pass |
| a4 | Candle dates in IST | `system.py:289` (`astimezone(IST)`) | IST date of a 18:30 UTC stamp | 27 Nov for the bar stamped 26 Nov 18:30 UTC (`test_a1_*`) | Pass |
| a5 | Badge while the session is unknown | `PricesBadge.tsx:13-14` | nothing | renders empty (`verify240.test.tsx`) | Pass |
| a6 | Calendar source | `core/holidays.py`, `core/market_session.py`; #416's `/config/trading-rules` carries the holiday list and trial count, not the badge's day counting | one calendar | both read the same lists (`test_a5_*`); cite #416 | Pass (cited) |
| b1 | Stock page fallback close shows its date | `trademind/stockParts.tsx:112-118,278` ("at last close") | the close with its date | no date anywhere in the header | **GAP** |
| b2 | A bare stored close is labelled | `stockParts.tsx:278` (the words ride on the change) | labelled as a close | `₹123.57` with no label when there is no change to show | **GAP** |
| b3 | Price while loading | `stockParts.tsx` (`last != null &&`) | no number drawn | no `₹`, no `NaN` (browser test) | Pass |
| b4 | Stale, delayed, mismatch, holiday labels | `stockParts.tsx:270-285`, `services/quote_snapshot.py` | labelled, never live | `priceSnapshot.test.tsx` (6 tests); #246 b1-b4 | Pass (cited) |
| b5 | A position that was never priced | `api/v1/endpoints/portfolio.py` (`current = current_price or entry_price`), `services/sell_labels.py:51` | not shown as a real price, or clearly flagged | shown at entry price, 0% flat; `sell_status` says "Exit check unavailable" (`test_c1_*`, `test_c2_*`) | Pass (warned) |
| b6 | A position row says how old its price is | position row in `portfolio.py:312-345` | a price time or status | none of `price_as_of`, `price_status`, `price_is_stale` exists (`test_c3_*`) | **GAP** |
| c0 | Candle chart: one body per candle, no invented day | `trademind/ui.tsx:540-640` (`Candles`) | only given candles; own labels | 3 candles with 2 missing days draw 3 bodies and the right labels (browser test) | Pass |
| c2 / c3 | Chart date labels are India dates | `trademind/live-stock.ts:10-16` (local `getDate`), `today/SwingPicks.tsx:369,471`, `pages/Opportunities.tsx:128` (`c.ts.slice(5, 10)`) | the IST trading day | `29 Nov` for the 30 Nov bar in a UTC browser; the two `slice` labels show the UTC date (the API serves 29 Nov 18:30 UTC, `test_b1_*`) | **GAP** |
| c1 / c1b | Empty and invalid input to the candle chart | `ui.tsx:540-570` | no invalid numbers | zero candles and all-zero volume print `NaN`; callers hide the empty chart (`StockDetail.tsx:212-232`, `StockAnalysis.tsx:182`) | **GAP** (latent) |
| c4 | Loading and empty states of the line and area charts | `SwingPicks.tsx:409,513`, `Opportunities.tsx:141`, `PortfolioNew.tsx:447-456`, `Risk.tsx:351`, `Portfolio.tsx:159-167`, `GrowwTracker.tsx:648-651` | drawn only with data; plain words otherwise | all guarded; "Not enough days yet" wording present (read from source; recharts cannot render without a browser) | Pass |
| c5 | Missing numbers | `trademind/trackerRules.ts:73-86` | a dash, never zero | `fmtPrice(null)`, `fmtPct(null)` give a dash; a real zero stays `0.0%` | Pass |

## Gaps for the owner (one line each, none fixed)

- **b1 / b2:** show the date of the stored close on the stock page whenever the fallback is used, and label a bare close even when there is no change.
- **b6:** add a price time or status to each position row so a list can say how old its price is; show a never-priced position as "no price yet", not as flat.
- **c2 / c3:** take chart labels from the India date (the server's `latest_candle_date` pattern, or a fixed `Asia/Kolkata` formatter) in `live-stock.ts`, `SwingPicks.tsx` and `Opportunities.tsx`.
- **c1 / c1b:** make the candle chart return nothing for no candles, and treat a zero largest volume as no volume bars.

## Limits worth knowing (not gaps)

- The line and area charts use a smooth ("monotone") curve between real points and place days by position, so a missing session is not shown as a gap
  (it is not invented either: no extra point is drawn). Whether a visible gap marker is wanted is a design choice.
- Discover, the Watchlist and the Today ideas show the brain's words and run-time numbers, not live quotes; their prices are the run's own and are
  labelled by the run (the brain's stored decision keeps its price; the current price is a separate read, per `api/v1/endpoints/market_data.py`).
  Those screens were checked by reading the source, not by component tests.
- The Groww Tracker shows each row's last price with a dash when missing, and relies on the top-bar label for age; its return chart spaces closes by
  position and has no dates of its own.

## Not covered here

Live Kite quotes, production, real accounts and the sealed trial were not touched. No browser run was made (vitest runs in Node), so the recharts charts
are checked through their guards, not rendered.

Re-run for this note: `verify240.test.tsx`, `priceSnapshot.test.tsx` and `pricesAge.test.ts` (**27 passed, 6 expected failures**); and
`test_verify_240_quote_states.py`, `test_quote_snapshot.py`, `test_market_session.py` and `test_status_candle_date.py` (**53 passed, 1 xfailed**).
