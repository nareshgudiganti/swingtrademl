# Pause-number check (A8): would the pauses fire by bad luck?

Protocol `pause-check-v1`. **Diagnostic on development data, not proof** (EXPOSURE-LEDGER.md).
The pause numbers are the owner's provisional ones and are **not changed** by this report.

Data: 49 watchlist stocks, decision days 2022-01-03 to 2026-08-14 (1145 days). Every idea is scored with the settled rule (next-day open, +8% / -4%, half out at +5%, 15 trading days, real costs). Buying every stock every day averaged -0.10% a trade after costs and 53% of such trades lost money.

How to read the tables: we made pretend strategies on the real days, from plain random picks (no skill, bad luck only) to picks that are a little better or worse than buying every stock. 44 different 12-month stretches, many random draws each. 'Fires within 3 / 6 / 12 months' = the share of stretches where the pause would have switched on.

## Rule 1: 8 losing finished ideas in a row

**5 ideas a day** (real days, market ups and downs kept)

| Strategy | Fires within 3 months | 6 months | 12 months | Median months to first pause |
|---|---|---|---|---|
| Clearly bad (-1.0% a trade) | 100% | 100% | 100% | 0.5 |
| Bad (-0.5%) | 99% | 100% | 100% | 0.5 |
| **No skill (bad luck only)** | 98% | 100% | 100% | 0.5 |
| Slightly good (+0.3%) | 96% | 100% | 100% | 0.6 |
| Good (+1.0%) | 91% | 98% | 100% | 0.7 |

**0.64 ideas a day** (real days, market ups and downs kept)

| Strategy | Fires within 3 months | 6 months | 12 months | Median months to first pause |
|---|---|---|---|---|
| Clearly bad (-1.0% a trade) | 50% | 76% | 96% | 3.0 |
| Bad (-0.5%) | 39% | 66% | 89% | 4.0 |
| **No skill (bad luck only)** | 30% | 51% | 79% | 5.8 |
| Slightly good (+0.3%) | 24% | 43% | 71% | 7.2 |
| Good (+1.0%) | 13% | 24% | 45% | more than 12 |

Shuffled (ideas drawn independently, no market ups and downs), 5 a day: no skill fires within 12 months in 97%; +0.3% in 90%; -1.0% in 100%. At 0.64 a day: 37% / 25% / 80%.

Reading (fixed rule, 5 a day): false alarms **often by chance**; a slightly good strategy is stopped **often by chance**; a clearly bad one: **catches it quickly**.

## Rule 2: two months in a row below every stock

**5 ideas a day** (real days, market ups and downs kept)

| Strategy | Fires within 3 months | 6 months | 12 months | Median months to first pause |
|---|---|---|---|---|
| Clearly bad (-1.0% a trade) | 99% | 100% | 100% | 2.7 |
| Bad (-0.5%) | 84% | 99% | 100% | 2.7 |
| **No skill (bad luck only)** | 25% | 59% | 88% | 4.8 |
| Slightly good (+0.3%) | 4% | 12% | 27% | more than 12 |
| Good (+1.0%) | 0% | 0% | 0% | more than 12 |

**0.64 ideas a day** (real days, market ups and downs kept)

| Strategy | Fires within 3 months | 6 months | 12 months | Median months to first pause |
|---|---|---|---|---|
| Clearly bad (-1.0% a trade) | 67% | 96% | 100% | 2.6 |
| Bad (-0.5%) | 46% | 85% | 99% | 3.4 |
| **No skill (bad luck only)** | 26% | 61% | 89% | 4.6 |
| Slightly good (+0.3%) | 16% | 42% | 74% | 7.1 |
| Good (+1.0%) | 3% | 10% | 24% | more than 12 |

Shuffled (ideas drawn independently, no market ups and downs), 5 a day: no skill fires within 12 months in 91%; +0.3% in 43%; -1.0% in 100%. At 0.64 a day: 91% / 78% / 100%.

If 'two months' meant any two months, not two in a row: no skill fires within 12 months in 100% (5 a day).

Reading (fixed rule, 5 a day): false alarms **often by chance**; a slightly good strategy is stopped **sometimes**; a clearly bad one: **catches it quickly**.

## Rule 3: the brain's own book falls 8% from its peak

Case A: the brain is the whole account (₹9,79,792). Case B: the account is split half and half with a second book of random picks (a stand-in for the v1 bot). The 15% halt reads the whole account.

| Account | Strategy | Ideas a day | Fires within 3 months | 6 months | 12 months | Median months | 15% halt within 12 months | Median worst fall of the book |
|---|---|---|---|---|---|---|---|---|
| A | Clearly bad (-1.0% a trade) | 5 | 39% | 70% | 95% | 4.0 | 69% | 16% |
| A | Bad (-0.5%) | 5 | 30% | 50% | 81% | 6.0 | 40% | 14% |
| A | **No skill (bad luck only)** | 5 | 16% | 35% | 66% | 8.7 | 14% | 10% |
| A | Slightly good (+0.3%) | 5 | 11% | 29% | 57% | 10.4 | 5% | 9% |
| A | Good (+1.0%) | 5 | 4% | 11% | 32% | more than 12 | 0% | 7% |
| A | Clearly bad (-1.0% a trade) | 0.64 | 13% | 50% | 88% | 5.9 | 43% | 14% |
| A | Bad (-0.5%) | 0.64 | 6% | 29% | 68% | 8.7 | 16% | 10% |
| A | **No skill (bad luck only)** | 0.64 | 2% | 20% | 48% | more than 12 | 2% | 8% |
| A | Slightly good (+0.3%) | 0.64 | 2% | 12% | 34% | more than 12 | 0% | 7% |
| A | Good (+1.0%) | 0.64 | 0% | 2% | 5% | more than 12 | 0% | 5% |
| B | Clearly bad (-1.0% a trade) | 5 | 51% | 81% | 97% | 3.0 | 50% | 19% |
| B | **No skill (bad luck only)** | 5 | 26% | 46% | 74% | 6.8 | 22% | 12% |
| B | Slightly good (+0.3%) | 5 | 21% | 40% | 68% | 8.4 | 15% | 10% |

Reading (fixed rule, Case A, 5 a day): false alarms **often by chance**; a slightly good strategy is stopped **often by chance**; a clearly bad one: **catches it slowly**.

## Order with the 15% halt

| Account | Strategy | Ideas a day | Accounts | Halt fired | Book 8% came first | Same day | After | Never | Rule 1 only after halt | Rule 2 only after halt |
|---|---|---|---|---|---|---|---|---|---|---|
| A | Clearly bad (-1.0% a trade) | 5 | 440 | 305 | 305 | 0 | 0 | 0 | 0 | 14 |
| A | Bad (-0.5%) | 5 | 440 | 174 | 174 | 0 | 0 | 0 | 0 | 3 |
| A | **No skill (bad luck only)** | 5 | 440 | 61 | 61 | 0 | 0 | 0 | 0 | 10 |
| A | Slightly good (+0.3%) | 5 | 440 | 23 | 23 | 0 | 0 | 0 | 0 | 7 |
| A | Good (+1.0%) | 5 | 440 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| A | Clearly bad (-1.0% a trade) | 0.64 | 440 | 190 | 190 | 0 | 0 | 0 | 1 | 0 |
| A | Bad (-0.5%) | 0.64 | 440 | 69 | 69 | 0 | 0 | 0 | 2 | 1 |
| A | **No skill (bad luck only)** | 0.64 | 440 | 10 | 10 | 0 | 0 | 0 | 0 | 0 |
| A | Slightly good (+0.3%) | 0.64 | 440 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| A | Good (+1.0%) | 0.64 | 440 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| B | Clearly bad (-1.0% a trade) | 5 | 440 | 221 | 221 | 0 | 0 | 0 | 0 | 9 |
| B | **No skill (bad luck only)** | 5 | 440 | 95 | 95 | 0 | 0 | 0 | 0 | 24 |
| B | Slightly good (+0.3%) | 5 | 440 | 67 | 67 | 0 | 0 | 0 | 0 | 18 |

A pause and the halt can never give opposite orders: both only stop new buys. The only possible 'conflict' is a pause that comes too late to matter (after the halt already stopped buying) or that the halt makes impossible (while halted the book buys nothing new, so it can only fall further on positions it already holds).

## Our real model's picks (walk-forward, best 5 a day)

| Window | Ideas | Avg after costs | Edge vs every stock | Longest losing run | Rule 1 fires | Rule 2 fires | Book 8% fall | 15% halt | Book worst fall |
|---|---|---|---|---|---|---|---|---|---|
| 2023-07-01 to 2025-01-31 | 1980 | -0.20% | -0.19% | 27 | 2023-07-11 | 2023-12-21 | 2024-11-13 | never | 13% |
| 2025-10-01 to 2026-08-15 | 1075 | -0.10% | +0.22% | 31 | 2025-11-04 | never | 2026-03-13 | never | 11% |

Reproduction check: both windows reused the stored `wf_h15_*` models (21 and 12 folds, none trained) and matched the stored walk-forward results exactly: 1,980 ideas at -0.204% a trade (wf_v1) and 1,075 ideas at -0.104% a trade (2025-10 to 2026-08).

## What this means (plain English)

- **Rule 1 (8 losses in a row) cannot tell good from bad.** About half of all trades under the +8% / -4% rule lose money (53% for every stock after costs), and ideas from the same day move together. At 5 ideas a day it fires within a month for every strategy we tried, even a good one (+1% a trade: 91% within 3 months). At the brain's slower pace (0.64 a day) it still fires within a year for 79% of no-skill strategies and 45% of good ones. Our real model hit 27 and 31 losses in a row. As written it would pause the brain almost at once, whatever its quality.
- **Rule 2 (two months in a row below every stock) is the only rule that separates skill from no skill**, but only at 5 ideas a day: a slightly good strategy (+0.3%) is stopped in 27% of years, a good one never, a bad one within about 3 months. A no-skill strategy is stopped in 88% of years - which is arguably what it should do (it is no better than buying everything). At 0.64 ideas a day (about 13 ideas a month) a month's average is too noisy: a slightly good strategy is still stopped in 74% of years.
- **Rule 3 (brain book 8% below its peak) fires on bad luck in 2 of 3 years** when the brain is the whole account at 5 a day (no skill: 66% within 12 months; slightly good: 57%). At 0.64 a day it fires in 48% of no-skill years. It catches a clearly bad strategy within a year in 95% of cases, but only 70% within 6 months.
- **Order with the 15% halt: no problem found.** In every account where the 15% halt fired (1,218 of 5,720 accounts), the brain book's 8% fall had already fired on an earlier day - never the same day, never after, never missing - in both Case A and Case B. No pause can give an order opposite to the halt (all of them only stop new buys). The only overlap: rule 2 (and very rarely rule 1) sometimes fires only after the halt had already stopped buying (up to 24 of 440 accounts); those fires add nothing but do no harm.
- **On our real model's picks** (development data): rule 1 would have paused it within days of each window, rule 2 after about 6 months in the first window and never in the second, rule 3 after 16 and 5 months. The 15% halt never fired.

**Reading by the fixed rule (PROTOCOL.md): all three rules read 'consider loosening'** - each fires 'often by chance' for a no-skill strategy (over 33% within 12 months). Rule 1 also stops good strategies often. Suggestions for the owner, not changes (nothing was changed): rule 1 is the weakest - as a count of losses in a row it would need to be far longer (our real model reached 31), or be replaced by a rate over the last N ideas; rule 2 works only with enough ideas a month, so a minimum count per month (or a longer window) would make it usable at the brain's real pace; rule 3 always comes before the 15% halt, so it is safe in order, but 8% is inside normal bad-luck swings - a deeper level (for example 10% to 12%, still before 15%) would false-alarm less. Any new number would need its own check run before it is used. The owner decides.

Diagnostic on development data, not proof.

## Limits

- Survivor bias: today's 49 watchlist stocks; today's sector map.
- Accounts run every day as NORMAL (no replayed banner); DEFENSIVE days would buy less, so real books fall more slowly.
- The 'slightly good' and 'bad' strategies are manufactured from real prices with a known edge; they are not real strategies.
- Case B's second book is random picks, not the real v1 bot.
- Account runs used 10 draws per start month; run time 1701 s.
