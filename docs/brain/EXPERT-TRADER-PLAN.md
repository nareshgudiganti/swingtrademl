# Making the brain trade like an expert — plan (2026-10-09)

Status: **design, not built.** Every step below runs in practice mode (shadow) first and needs
the owner's approval before it changes what is bought. Trading rules stay as settled:
≤ 15 trading days, −4% worst case per trade, half out at +5%, 15% drawdown halt, 25% sector cap.

## Why (what two weeks of production showed, 25 Sep – 9 Oct)

- Market fell ~4% (NIFTY 23,447 → 22,520), below its 50- and 200-day averages.
- The brain read the market right (DEFENSIVE every day) but wanted to buy **70–108 stocks a
  night**. All were stopped by the risk check. Of 519 brain ideas already scored, only **3–12%**
  reached +8% before −4%.
- Its confidence is ordered correctly (70%+ ideas did best) but far too high: "55%" came true ~5%.
- Version 1 uses +2% target / −4% stop: it must win 67% just to break even. Since 28 Sep: 121
  ideas, 65 target / 23 stop / 12 expired, about +0.2% per idea — break-even.

## What an expert does that the brain does not — and the change for each

| # | Expert habit | Brain today | Change | Where |
|---|---|---|---|---|
| 1 | Stop below the last swing low, target at the next resistance, sized to how much the stock usually moves | Same +8% / −4% for every stock (`fallbacks.py`, `m07_risk`, `m05_memory/cases.py`, M08 policy) | Per-stock levels: stop = recent swing low or 2× daily range (never wider than −4%); target = nearest resistance; **only TRADE if the target is at least 2× the stop** and reachable in 15 days at the stock's normal pace | M08 policy + M07 (levels), M05/M09 scoring must use the same levels |
| 2 | Picks 3–5 best ideas, ignores the rest | 70–108 candidates a night | Rank by expected result after costs; at most **5 TRADE a day** (fewer in DEFENSIVE, 0–2); the rest become WATCH with "not in today's top 5" | M08 |
| 3 | In a falling market, only buys stocks that are rising while the index falls | Relative strength is a feature, not a gate | In DEFENSIVE: require the stock to beat NIFTY over 1 and 3 months and sit above its own 50-day average | M08 rule using M03/M11 data |
| 4 | Waits for proof the down-trend has ended before buying again | Says DEFENSIVE; no "all clear" signal | "Turn" checklist: NIFTY back above its 50-day average, more than half of stocks above their 50-day averages, falling fewer than rising for 5 days. Banner explains which items are still missing | M10 |
| 5 | Knows their real hit rate | "55%" that comes true 5% | Weekly re-calibration from finished ideas (only once ≥ 100 have finished); until then show words, not percentages | M06/M09 |
| 6 | Buys on a pullback or a breakout day, not anywhere | Entry range is computed but nothing waits for it | Idea is "TRADE when price is between X and Y"; if it opens above Y it becomes WATCH for that day | M08 + M18 approvals |
| 7 | Reads results and news | Knows results *dates* only (M13) | **Owner decision** — needs a news source (breaks the settled "no outside data" rule). Not planned unless approved | — |
| 8 | Keeps a diary and changes behaviour from it | M09 report exists; proposals not acted on | Monthly "what worked" card by setup × market state; proposals with ≥ 50 cases go to the owner | M09 |

## Order of work

1. **Per-stock stops and targets (#1)** — biggest single effect. Test on past data first
   (`brain replay-week` over the last 6 months): compare hit rate and average result with the
   fixed +8/−4 rule. Ship only if the average result per idea is better after costs.
2. **Top-5 limit + strength gate in falling markets (#2, #3)** — same replay test.
3. **"All clear" checklist (#4)** — shown on the banner; changes no trades by itself.
4. **Entry range (#6)**, **calibration (#5)**, **diary (#8)** — after 30+ finished ideas.

## Measure of success (practice mode, before any approval)

- At least 30 finished brain ideas with **average result > 0 after costs** and a win/loss
  pattern where average win ≥ 1.5× average loss.
- Confidence bands within ±10 points of what actually happened.
- In a falling market, the brain buys little or nothing (it should not trade just to be busy).

## Open checks before building

- Confirm where M08's policy reads `target_pct`/`stop_pct` and how relative strength is stored
  (M03 state, M11 ranking) — not re-read during this write-up.
- Scoring (M09 `outcomes.score`) assumes fixed +8/−4; per-stock levels must be scored with the
  levels the idea actually had.
