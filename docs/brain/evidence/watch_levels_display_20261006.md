# WATCH rows: entry zone / target / stop on Opportunities (2026-10-06)

**Classification:** Product/UI gap — not a backend bug at baseline `0bdaa76`.

## What the owner saw

TradeMind **Discover → Opportunities**, filter **WATCH** (~69 rows): high model scores, WHY explains M07 risk (e.g. market under stress, 10% deploy cap, headroom below minimum position). Columns **Entry zone**, **Target**, **Stop** show **—**.

## What the brain actually does (M08 + M07)

1. Liked stock → draft **TRADE** with entry zone, +8% target, −4% stop, sized `qty` when risk allows.
2. Risk refusal → **downgrade** to **WATCH** via `contracts.downgrade`: `qty` → 0, **levels kept** on `brain_decisions` / API.
3. `reasons[0]` is the risk line; a **“Plan: buy around …”** line may appear later in `reasons`.

## Why the list is empty

`frontend/src/trademind/pages/Opportunities.tsx` renders zone/target/stop **only when `word === 'TRADE'`**.

`frontend/src/trademind/pages/StockDetail.tsx` shows buy/target/stop when numeric fields exist **regardless of word** — detail view may show the hypothetical plan.

## Validation implication

- Observe stored `entry_low` / `target` / `stop` on risk-blocked WATCH in API or DB; do not treat list dashes as missing brain output.
- Optional regression: assert risk WATCH retains `entry_low` after downgrade (follows from `downgrade()` today).

## Recommended fix (owner approval; not validation-phase trading change)

1. **UI:** Show plan levels on WATCH when `entry_low != null`, dimmed + label e.g. “Not approved to buy (risk)”.
2. **UI (small):** Surface “Plan:” line in list WHY when present.
3. **Docs:** WATCH includes “liked but blocked by risk,” not only “entry not right yet” (legacy architecture text).

No change to M08/M07 decision logic required for this display issue.
