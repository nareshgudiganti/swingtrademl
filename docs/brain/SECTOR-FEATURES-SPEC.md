# Sector inputs (B1-5..B1-8): final feature definitions

Status: PREPARATION (2026-11-04). Nothing trained, nothing signed, nothing activated. Owner decision of
2026-11-04: prepare the 5D sector-only research challenger and the 10D sector-only B1 candidate.
Code: `backend/src/swing_trade_ml/ml/sector_features.py` (one builder), `sector_features_loader.py` (read-only
loader), `exclusion_report.py`. Tests: `backend/tests/test_sector_features.py`, `test_exclusion_report.py`.

## 1. In plain English

For each stock and each trading day we add four numbers, all known at that day's close:

1. How much the stock's sector index beat (or lagged) NIFTY 50 over the last 10 trading days.
2. The same over the last 20 trading days.
3. Where that sector ranks today among all sectors on 10-day return, from 0 (weakest) to 1 (strongest).
4. How much the stock beat (or lagged) its own sector index over the last 10 trading days.

"Sector" always means the stock's **official NSE sector index** (a price series we already store). The four
market-breadth inputs (B1-1..4) are rejected (no point-in-time stock universe; the local stock set is survivors
only) and are not part of this spec.

Two ways to measure a sector exist; they are not mixed:

| | Official sector index (USED) | Leave-one-stock-out average over our stocks (NOT USED) |
|---|---|---|
| What it is | NSE's own index series for the sector, built from all its member stocks, with NSE's weights | Average return of the other stocks of that sector among the 49 (or our local set) |
| Needs | Index closes only | A dated list of which stocks existed, and the survivors-only local set is biased |
| Sector with 1 or 2 stocks in our 49 | Fine: the index still holds many stocks | Breaks: one stock leaves nothing to average; stock-vs-sector would be 0 or undefined |
| Stock-vs-sector | stock minus index, normally not 0 | forced to 0 for a one-stock sector |

Under the official rule a one-stock sector (ADANIENT, APOLLOHOSP, TITAN) still gets a real, non-zero
stock-vs-sector value, because the index holds many other stocks. (A stock that is itself a large index member
is partly compared with itself; that is accepted and stated.)

## 2. Exact formulas

Let `C_x(d)` be the close of series `x` on IST date `d`. `n` sessions back means `n` rows back on the shared
calendar (section 3). `R_x(t, n) = C_x(t) / C_x(t-n) - 1`. If either close is missing, `R` is missing.

| Input | Name in code | Formula |
|---|---|---|
| B1-5 | `sector_ret_10d_vs_nifty` | `R_sector(t,10) - R_NIFTY50(t,10)` |
| B1-6 | `sector_ret_20d_vs_nifty` | `R_sector(t,20) - R_NIFTY50(t,20)`. **Not used by the research challenger C_56 (2026-11-06)**: it equals `relative_strength_20d - sector_relative_strength_20d` of the existing inputs except on 13 of 45,930 rows where the sector index lacks sessions (a window-definition difference, no new information; `docs/brain/evidence/sector_prep/c56_decision_v3.json`). The builder still computes it. |
| B1-7 | `sector_rank_10d` | among the 15 sector indices with a valid `R(t,10)` on day t: `(average_rank - 1) / (N - 1)`, 0 weakest, 1 strongest. Ties take the average rank. Missing if `N < 5` |
| B1-8 | `stock_vs_sector_10d` | `R_stock(t,10) - R_sector(t,10)` (same two dates for the stock and the index) |

Rank universe (`DEFAULT_RANK_UNIVERSE`, the distinct indices behind `ml/sector_map.py`): AUTO, BANK, CAPITAL MKT,
COMMODITIES, CONSR DURBL, CONSUMPTION, ENERGY, FIN SERVICE, FMCG, HEALTHCARE, INFRA, IT, METAL, PHARMA, REALTY.
NIFTY CHEMICALS is excluded on purpose (exists only from 2025-11-24; it would change the rank scale part-way).
The rank is a per-day comparison: it uses only that day's 10-day returns. There is no full-sample or expanding
normalisation. Ranking raw sector returns or returns minus NIFTY 50 gives the same order.

Why windows are in sessions of the shared calendar and not in calendar days: it matches `ml/features.py`
(`return_5d`, `return_20d` are row-based).

## 3. Alignment and missing days

- Dates are IST dates. Daily bars are stamped IST midnight (18:30 UTC the previous day), so
  `ts.astimezone(IST).date()` is always used (`close_series_from_candles`).
- Shared calendar = every date on which NIFTY 50 or any supplied sector index has a close. It does not depend on
  the stock, so two stocks see identical index values on the same day.
- The stock and each index are placed on that calendar by exact date. A close missing on a session may be carried
  forward from the previous session **once** (`MAX_FFILL = 1`, at most one session stale). A second
  consecutive missing session stays missing. Never filled with 0, never carried further.
- Non-positive or NaN closes are treated as missing.
- A return is missing if either of its two closes is missing. A missing return gives a missing feature that day.
- A stock row on a date not in the shared calendar gets missing features.
- Local data facts (read-only check 2026-11-04): all 15 rank indices and NIFTY 50 have daily bars from 2021-09-13
  (NIFTY 50 from 2021-08-09); sector indices end 2026-09-09, NIFTY 50 ends 2026-09-07 (the calendar union keeps
  the last two days). NIFTY HEALTHCARE has 1228 bars vs 1240 for the others (12 missing days; these are what the
  one-session carry and the missing rule handle).

## 4. Warm-up

Longest window is 20 sessions: the first 10 rows of the shared calendar have no 10-day features and the first 20
have no 20-day feature. The 5D/10D datasets additionally skip the first 252 sessions per stock (exclusion report).

## 5. Stocks with no sector index

`resolve_sector_index(symbol)` returns the official index from `ml/sector_map.py`, or `None`. For `None` (and for
the two unverified stocks below unless the caller opts in with `include_unverified=True`) all four inputs are
**missing (NaN)**: no guess, no imputation, no fallback to NIFTY 50 (the old `get_sector_index` fallback to the
benchmark would silently give ~0 and is NOT used here). The row is then handled by the trainer's existing
missing-value policy: `ml/dataset.py` drops any row with a missing feature column (`dropna` over
`FEATURE_COLUMNS` and the target). Whether a future protocol keeps such rows with a native missing value must be
stated in that protocol; this spec only guarantees the value is missing, never invented.

## 6. Point in time and no leakage

- Decision at the close of day t; entry at the next open. The value at t uses only closes dated `<= t`.
- Every number is a backward ratio (`t` against `t-n`) or a same-day rank. There is no forward-looking operation:
  no centred windows, no full-sample statistics, no future-dated index close.
- The single builder `build_sector_features(..., as_of=t)` cuts every input to dates `<= t` before doing
  anything. Tests: changing any stock/index value after t never changes any feature at or before t; a rank on
  day t is unchanged when later days explode.
- Caveat (stated, not fixable here): the **sector label of a stock is static** (today's mapping applied to the
  whole history), and index membership changes over time. This is a mild non-point-in-time input; it affects
  which index is chosen, not any price used.

## 7. One definition for training and serving

Training calls `build_sector_features(...)` on the full history. Serving calls `sector_features_asof(..., t)`,
which calls the same function with `as_of=t`. The parity tests assert exact equality (`check_exact`):
every date of a toy history (with holes in the stock and in an index), and on real local data for HDFCBANK, TCS
and SUNPHARMA (every 7th valid date plus the last 30). Rationale: the obv_slope incident
(`docs/superpowers/specs/2026-10-30-obv-slope-incident.md`) came from training and serving computing the same
input differently and on different history lengths. Here no input depends on history length beyond 20 sessions.

Not yet wired into `ml/features.py` or `ml/predict.py` (both fingerprinted in `backend/tests/trial_freeze.json`);
wiring would need an owner-approved freeze change or a separate research path.

## 8. Sector mapping verification (ASIANPAINT, BHARTIARTL)

Both are the only two of the 49 with no label in `ml/sector_map.py`. Method: individual look-ups only, no bulk
scraping, per `docs/superpowers/specs/2026-10-29-nse-feed-licensing-inventory.md` (NSE website terms forbid
scripted collection; this was a handful of manual look-ups, nothing stored).

| Stock | Proposed official index | Local candles | Evidence | Status |
|---|---|---|---|---|
| ASIANPAINT | NIFTY CONSR DURBL (Nifty Consumer Durables) | yes, 1240 daily bars 2021-09-13..2026-09-09 | Third-party page onetradejournal.com/learn/nifty-consumer-durables-index (dated 19 Jun 2026, looked up 2026-11-04) lists "Asian Paints, paints and coatings, 6 to 8%". Official factsheet https://www.niftyindices.com/Factsheet/Factsheet_nifty_consumer_durables.pdf and the niftyindices index page timed out (60 s) and could not be read | **UNVERIFIED against NSE** (third-party only) |
| BHARTIARTL | NIFTY INFRA (Nifty Infrastructure; telecom is inside its scope) | yes, 1240 daily bars 2021-09-13..2026-09-09 | Third-party page onetradejournal.com/learn/nifty-infrastructure-index (19 Jun 2026) lists "Bharti Airtel, Telecom, 17.5%"; web search result states the index covers Telecom, Power, Port, Air, Roads, Railways, shipping and other utilities. The NSE PDF archives.nseindia.com/content/indices/ind_nifty_infra.pdf returned an unrelated (Midcap 100) image and could not confirm | **UNVERIFIED against NSE** |

There is no dedicated NSE telecom sector index among the indices we hold (`ml/sector_map.py` says the same), so
BHARTIARTL on NIFTY INFRA is a thematic fit, not a pure sector. Both stocks are therefore kept as "no sector"
(features missing) unless the owner accepts the proposed mapping or an official factsheet is read by hand.
Indices present locally (segment INDICES, daily): NIFTY 50, INDIA VIX, AUTO, BANK, CAPITAL MKT, CHEMICALS (only
from 2025-11-24, 198 bars), COMMODITIES, CONSR DURBL, CONSUMPTION, ENERGY, FIN SERVICE, FMCG, HEALTHCARE, INFRA,
IT, METAL, PHARMA, REALTY. No MEDIA, PSU BANK, PRIVATE BANK, TELECOM, OIL & GAS, etc.

Also not verified in this task: the other 47 stocks' index membership (the existing map was checked against the
instrument list, not against index constituent lists), and UPL and GRASIM sit in bucket CHEMICALS but map to
NIFTY COMMODITIES, which is shared with ADANIENT (bucket COMMODITIES).

Sectors with fewer than 3 stocks among the 49 (by existing map): COMMODITIES 1 (ADANIENT), HEALTHCARE 1
(APOLLOHOSP), CONSUMPTION 1 (TITAN), CHEMICALS 2 (GRASIM, UPL; share one index with ADANIENT), and the 2 unlabeled
stocks. Under the official-index rule this does not matter for the sector figures (the index needs no equal-weight
mean from our stocks); the stock-vs-sector value is not forced to 0. These are, though, thin groups for any
sector-level learning: a model sees few distinct stocks per sector.

## 9. NOT done

- No model trained; no protocol written, signed or amended; nothing activated or deployed; nothing committed.
- No wiring into `ml/features.py` / `ml/predict.py` / the trainer (frozen files).
- Open items: (1) the lock (trial freeze: any wiring touching fingerprinted files needs owner approval);
  (2) the fetch (fresh-fetch comparison for HINDUNILVR 2025-12-05 and BAJAJELEC 2023-09-14; reading the two
  official factsheets by hand); (3) owner approval of the mapping for ASIANPAINT and BHARTIARTL and of the
  missing-value policy; (4) the 15D pools report (not produced: no pool list was supplied; the CLI takes any
  symbol list via `--universe-json/--universe-key`).
