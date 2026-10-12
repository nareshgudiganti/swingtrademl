# Wider stock universe: what data exists? (read-only check, 2026-10-12)

Question: can the model be trained and tested on more than the 49 watchlist stocks, and is the data good
enough for a fair comparison? Nothing was downloaded, no model changed, and Kite was not called.
Source: the local database (daily candles to 2026-09-07) and its delivery-feed table.

## What is already local

| Item | Result |
|---|---|
| NSE shares in the instrument list | 10,290 (all active) |
| Shares with daily candles | **306** (257 are not on the 49-stock watchlist) |
| History length | 293 have 1,200+ sessions; 300 have 1,000+. Calendar: 5 Aug 2021 to 7 Sep 2026 (1,262 sessions) |
| Short or stale | ICICIAMC 159 sessions, TMCV 204, IREDA 689, JSWINFRA 710, NUVAMA 732, KFINTECH 915. ICICIAMC and JSWINFRA stop on 11 Aug 2026 |
| Missing sessions | median 0 per stock since its first candle; only those two stale names miss more than 10 |
| Bad bars | none impossible (no high below low, no zero volume, no non-positive close) |
| Sector index mapped | all 306 return a sector; but training logged BHARTIARTL and ASIANPAINT as unmapped, to check |
| Sector spread | Infra 53, Fin services 33, Auto 32, Pharma 25, Commodities 23, Bank 20, IT 17, Energy 17, Metal 16, FMCG 16, others smaller |

Liquidity (median daily turnover, April to Oct 2026, from the delivery feed): 286 of the 306 trade at least
Rs 5 crore a day, 265 at least Rs 10 crore, 218 at least Rs 25 crore, 187 at least Rs 50 crore.

## Usable training rows

After the 200-session warm-up the features need, and the last 15 sessions that have no outcome yet:

| Universe | Stock-days |
|---|---|
| 49 watchlist | 51,303 |
| All 306 | 312,311 (6.1 times more) |

These are not independent. Stocks move together, so the real amount of new information is far smaller.

## Market regimes (share of stocks above their 50-day average)

Using breadth across all 306 (it correlates 0.895 with the 49-stock breadth):

| Year | 2021 (from Aug) | 2022 | 2023 | 2024 | 2025 | 2026 (to Sep) |
|---|---|---|---|---|---|---|
| Days under 30% | 9 | 61 | 20 | 30 | 59 | 30 |
| Sessions | 52 | 248 | 246 | 249 | 249 | 169 |

209 weak-market days in 32 separate episodes across the full history. The earlier test periods contained
only 62, because they began in Aug 2024 and the dataset starts Sep 2022. So the long history holds more weak
markets than the tests saw, but only by testing earlier years, which leaves little training data before them.

## Problems found

1. **Survivorship.** The 306 are shares listed today. Names that were delisted or merged are not here. The
   delivery feed shows 309 names with 250+ sessions that stopped trading before Aug 2026, but that list mixes
   delistings, renames and ETFs, and the feed has only close price and quantity, no high or low, so the
   +8% / -4% outcome cannot be built for them. Survivorship cannot be fixed with this data.
2. **Corporate actions.** No historical table exists (`upcoming_events` holds only future rows,
   `candle_corrections` is empty). Five one-day moves over 35% need a look: ALLCARGO -60% (12 Nov 2025),
   ABFRL -56% (22 May 2025), TRIVENI -42% (22 Jul 2026), BAJAJELEC +39% (14 Sep 2023), NMDC +86%
   (27 Oct 2022). Some may be unadjusted splits or demergers. The adjusted-price layer is deferred.
3. **Context inputs use the 49.** Market breadth and similar inputs are computed over the watchlist, not
   the wider list. Left alone for a clean comparison.
4. **Beyond 306.** About 2,800 symbols trade, and many liquid-looking names have no local candles, but that
   count is inflated by ETFs, new listings and odd turnover. Getting them needs the broker's history call.
   Cost, rate limits and licence terms were not checked here.

## Can it support a fair comparison?

Yes, without any download. `build_training_dataset` already takes a list of symbols, so a model can be
trained on the 49, on about 150 to 200, or on all 306, and then scored on the same 49 stocks and the same
dates. Rules, features and settings stay fixed.

## Untouched data

There is no untouched period left in the local data. Every window up to 14 Aug 2026 was used as a test
window in earlier experiments. A clean confirmation needs days nobody has looked at: sessions from 9 Sep
2026 on, which exist on the server but not in the local database, and those accrue over time because each
idea needs up to 15 sessions to finish. Use development windows only for choosing among universes.

## Effort

- 49 versus about 150 to 200 versus 306: low. Pass a symbol list, pick the liquid names, rerun the
  existing grid and the weakness experiment. No download, no cost.
- 400 to 500: needs about 100 to 200 more stocks of history from the broker, plus a survivorship decision.
  Not recommended until the 306 test shows a gain.
