# Feature 2 requirements: Today, Discover and the Scanner (#281)

Status: **recorded for owner sign-off**, 26 Nov 2026 (IST). Source: the consolidated draft on #281 (26 Nov), the owner decisions
table on #281 (25 Nov), and the code on `origin/main` at `2f0696d7`. Parent feature: #227. Child issues: #238, #239, #260, #310, #416.
Shared dependencies owned by other features: #385, #341, #326, #353, #355, #356, #354.

This file proposes no new trading rule, threshold, target, stop or limit. Every number named here already exists in the app.
Nothing in it is approved by being written down: items the owner has not decided are kept in section 9.

Words used: **Today** = `/trademind`. **Discover** = `/trademind/opportunities`. **Scanner** = the nightly scan that produces what
Today and Discover show: the data update, the version 1 scan, the Brain's nightly run, the 5-day pick list, the top-picks and buy lists,
the stock search and the pattern tags.

## 1. What the user sees and does

**Today**
- A greeting, the market mode in one word (NORMAL, DEFENSIVE or NO NEW TRADES), its headline, the market situation and the time of the
  Brain's run.
- Counts of ideas by word (TRADE, WATCH, WAIT, AVOID) and the top 5 idea cards with a "View all" link. Five is where the list is cut;
  the Brain keeps every idea. Held: `frontend/src/trademind/today/TodayIdeas.tsx:23` (`TOP_IDEAS = 5`), cut applied at `:38`.
- When no idea is a TRADE, one plain reason why.
- Holdings that need attention (MONITOR, REDUCE, EXIT), what changed, today's insights, a horizon selector, and a practice-mode note
  (nothing here places an order).
- Scores read as a ranking, never as a chance of profit.

**Discover**
- Every idea of the Brain's latest run, filtered by word, by sector and by a search box. A TRADE row shows its plan (buy zone, target,
  stop, horizon). Other rows show "Where it stopped" (or "Not recorded").
- Stock search by symbol or name: any letter case, active stocks only, exact symbol first, an empty list (not an error) when nothing
  matches. Code: `backend/src/swing_trade_ml/api/v1/endpoints/instruments.py:18`.
- Pick lists: the 5-day picks, the top picks and the buy list (`backend/src/swing_trade_ml/api/v1/endpoints/signals.py`).
- Pattern tags from stored daily candles as of the run date: breakout, pullback in an up-trend, tight base, breakdown. A stock with
  fewer than 60 days of candles gets no tag (`brain/modules/m12_stock/setups.py:26`, `MIN_BARS = 60`). Only "breakdown" argues
  against buying.
- A stock page for any idea: price with its label, candle chart, plan, plain answers, score line, similar past cases (shown only from
  30 cases) and "what would have to change".

**The Scanner.** After the market closes the app updates its data, runs the version 1 scan, and the Brain makes its nightly run. Today
and Discover only display the stored decisions; they never run the Brain.

## 2. Missing, stale or failing data (decisions only move toward caution)

Held today, verified against the code (backend paths are under `backend/src/swing_trade_ml/`):

| Rule | Code |
|---|---|
| Under 200 days of NIFTY history: DEFENSIVE, "Not enough NIFTY history" | `brain/modules/m10_market/judge.py:69-74` (the 200-day test is in `classify_regime`, called at `:63`) |
| Missing foreign-investor data is said in words and does not change the mode | `judge.py:140` |
| NIFTY down 4% or more, or India VIX up 30% or more: NO NEW TRADES | `judge.py:29`, `:144-149` |
| A decision with a missing target, stop or buy zone, or levels out of order: no plan, no zero | `services/beginner_views.py:397` (`_plan_in_order`) |
| Fewer than 30 similar cases: no rate shown, the "lost money" rule is silent | `backend/tests/test_market_context_verify.py:402` |
| Pattern tags: none when data is missing or under 60 bars | `setups.py:26` |
| Top-bar price label counts trading days and says "No prices yet" with no stored price | `frontend/src/trademind/pricesAge.ts`, `verify240.test.tsx:63-100` |
| A never-priced position shows "No price yet" instead of 0.0% on the screens | `api/v1/endpoints/portfolio.py:312-315` (`has_price`); `frontend/src/components/PositionAttentionCard.tsx:142-145`, `frontend/src/pages/Positions.tsx:230` |
| A stored close with no live price says "Last close on <date>" | `frontend/src/trademind/stockParts.tsx:300-303` |
| Buy list and top picks accept a BUY at most 5 completed trading sessions old (provisional) | `api/v1/endpoints/signals.py:134-153` (`MAX_BUY_AGE_SESSIONS = 5`) |
| Screens read finished runs only and name an old run as old | `frontend/src/trademind/emptyReasons.ts:10-15`; `test_verify_238_5d_ideas_screens.py:205` |

Built since the 24 Nov draft (merged, no longer gaps): G3 and G4 (PR #497), G10 (PR #498), G11 (PR #499), the display part of G5, G6
and G8 (#486), G7 (#470), missing-session chart markers and the empty-chart guard (PR #520, which replaced closed PR #509), and the
admin model overview (PR #510, #385).

Still open (each pinned by a strict expected failure unless noted):
- **G1** missing breadth or VIX is not said, and a rising market with no breadth is judged NORMAL
  (`test_market_context_verify.py:224`). Owner decision recorded: keep DEFENSIVE with a missing-data reason. Not applied: needs
  trial-freeze approval for `m10_market/judge.py`.
- **G2** breadth counts today's watch list, not the list on the judged date (`test_market_context_verify.py:163`). No decision recorded.
- **G9** a score from a 5-session model carries a 15-day label: `brain/modules/m08_decide/engine.py:177` stamps `policy.horizon_days`
  (`test_verify_238_5d_ideas_screens.py:224`, `test_horizon_385_mixup.py:44`). Owner decision recorded: show 5D, plan horizon shown
  separately. Not applied: needs trial-freeze approval for five files and a migration.
- **G11 remainder** the idea list can read a different run from the plain answers when a live-book run is newest
  (`test_verify_238_5d_ideas_screens.py:274`; #486).
- **G12** an idea whose sector has no rank passes the sector gate silently (`brain/modules/m08_decide/rules.py:93-94`), the gate's
  reason prints "of 15" whatever the real total (`rules.py:98`), and the gate is off by default (`core/config.py:255`,
  `BRAIN_SECTOR_GATE_TOP_N: int = 0`). The production value of that setting has not been read.
- **A2** a stored decision carries no record or prediction id (the link is stock + date + score) (#238).
- **#260** scan coverage, stale, skipped, score and rank record: not started.

## 3. What the admin sees

Built: System and Jobs pages (last scan, each job's last run and status, Brain last run and health, data quality, quote age); the
daily Brain check; the Observatory; the operations digest (it never contains profit or loss); the idea's reasons and "Where it
stopped"; the read-only 5-day and 15-day model overview (#385, PR #510, `test_admin_model_overview.py`).
Not built: the #260 scan record (coverage, stale, skipped, score, rank).

## 4. Dependencies

Data: daily candles (stock, NIFTY 50, India VIX, sector indices), foreign-investor flows, NSE holidays, the watch list, #316 candle
readiness. Jobs: nightly Brain run, version 1 scan, data update, weekly learning and health jobs. Shared features: #385 (model view,
G9 label), #341, #326, #353, #355, #356, #354 (several gated). Trading numbers come from `GET /config/trading-rules`
(`api/v1/endpoints/system.py:236`; #416, still open).

## 5. Out of scope

- New buy rules, thresholds, targets, stops or limits.
- Orders, sizing, and the paper/live switch.
- Frozen-file changes without the approval script.
- Live quotes on idea rows; a chance-of-profit figure on Today or Discover.
- 10-day or 15-day research horizons as product picks.
- New data sources or model changes.
- Fixes for #341, #353, #354, #355, #360; #310 beyond planning.
- Filters by cap tier, price, liquidity or score band on Discover (none exist today).

## 6. Acceptance criteria

Each is pass or fail. "Today" says what the check does on `origin/main` now. Test paths are under `backend/tests/` or
`frontend/src/trademind/`.

| # | Criterion | Issue | Proving test | Today |
|---|---|---|---|---|
| AC-1 | One stored idea has the same id, run, score, horizon, plan levels, word and first reason on Today, AI Analysis and Stock Detail | #238 | `test_verify_238_5d_ideas_screens.py:106,115,135` | passes |
| AC-2 | The score is rounded one way on every screen, and the stock-page score line ends on that decision's score and names its model | #238 | `fiveDayIdeaScreens.test.ts:54,102`; `test_verify_238_5d_ideas_screens.py:127` | passes |
| AC-3 | A room-only idea shows WATCH plus a separate room line on every screen | #238 (G11) | `fiveDayIdeaScreens.test.ts:72,79,84,95` | passes |
| AC-4 | The idea list and the plain answers read the same run when a live-book run is newest | #238 (G11 remainder) | `test_verify_238_5d_ideas_screens.py:274` | fails (strict xfail) |
| AC-5 | An idea scored by a 5-session model is labelled 5D; the plan horizon is shown separately | #238, #385 | `test_verify_238_5d_ideas_screens.py:230`; `test_horizon_385_mixup.py:44` | fails (strict xfail), blocked on frozen files and a migration |
| AC-6 | An idea traces to its 5-session record (same stock, model, score) | #238 | `test_verify_238_5d_ideas_screens.py:155` | passes (record only; no id on the decision, see A2) |
| AC-7 | Plan percentages on the stock page come from the Brain's policy, not v1 settings | #238, #416 | `test_verify_238_5d_ideas_screens.py:261` | passes |
| AC-8 | A run dated D uses nothing after D (NIFTY, VIX, flows, sectors, similar cases) | #281 | `test_market_context_verify.py:98,144,257,374,387` | passes |
| AC-9 | Breadth for a past run date does not change when the watch list changes later | #281 (G2) | `test_market_context_verify.py:163` | fails (strict xfail), no owner decision |
| AC-10 | Missing breadth or VIX gives DEFENSIVE with a plain reason | #281 (G1) | `test_market_context_verify.py:224` (asserts "not NORMAL, or said in words"; tighten to DEFENSIVE when approved) | fails (strict xfail), blocked on frozen file |
| AC-11 | Fewer than 30 similar cases shows no rate and fires no "lost money" rule | #281 | `test_market_context_verify.py:402` | passes |
| AC-12 | An idea whose sector has no rank is held by the sector gate, and the gate reason names the sector and the real total | #281 (G12) | `test_market_context_verify.py:322,310` | fails (strict xfail) |
| AC-13 | An unscanned stock, a decision with a missing level, and an old run each say so | #238 | `test_verify_238_5d_ideas_screens.py:186,195,205` | passes |
| AC-14 | The price label counts trading days and shows "No prices yet" when empty | #281 | `pricesAge.test.ts`; `verify240.test.tsx:63-100`; `test_verify_240_quote_states.py:67,79` | passes |
| AC-15 | A stored fallback close shows its date; a never-priced position says "No price yet", not flat | #281 | `verify240.test.tsx:137`; no test of the Positions screen text; `verify240.test.tsx:131` is a stale-looking `it.fails` (section 8) | partly tested |
| AC-16 | Chart labels are India dates, no chart prints NaN, and only missing expected trading sessions are marked | #281 | `verify240.test.tsx:162,170,197,210`; `chartSessions.test.ts` | passes |
| AC-17 | No buy-list or top-pick row is older than 5 completed trading sessions; one buy-list row per stock | #239 | `test_discover_filters_239.py:234,252,264` | passes (age number provisional) |
| AC-18 | The 5-day pick list gives one row per stock, the best confidence, inside its window | #239 | `test_discover_filters_239.py:273,286` | passes (window is 5 calendar days in code, see section 8) |
| AC-19 | Each Discover filter and the stock search return exactly the matching stocks | #239 | `test_discover_filters_239.py:107,114,121,128,153,198,209,215` | passes |
| AC-20 | Pattern tags use only candles up to the run date; a stock under 60 days gets none | #239 | `test_discover_filters_239.py:329,340,352,360`; `test_brain_m12_stock.py` | passes |
| AC-21 | The frontend holds no copy of +8/-4/+5/15 or the holiday list; they come from the backend | #416 | `noHardcodedRules.test.ts`; `tradingRules.test.tsx` | passes (issue #416 still open) |
| AC-22 | Discover filters by word and sector and searches as specified | #239 | `newLookW2.test.tsx` | passes |
| AC-23 | The admin sees last scan time, each job's status, Brain last run and quote age | #281 | `jobs.test.ts`; `live-system.test.ts`; `test_admin_jobs.py` | passes |
| AC-24 | The admin sees which 5-day and 15-day models are approved, scheduled, last run, and whether the Brain used them | #385 | `test_admin_model_overview.py:36,59,68` | passes (PR #510) |
| AC-25 | The ops digest carries runs, failures, ideas, jobs and freshness, and never profit or loss | #281 | `test_ops_digest.py` | not confirmed: no test found for "no profit or loss" by name; verify before sign-off |
| AC-26 | A scanner record for a candle bar cannot be overwritten | #260 (needs #355) | none | no test yet; testable after #355 ships |
| AC-27 | A stale or missing candle gives no score and a recorded reason | #260 (needs #353) | none | no test yet; testable after #353 ships |
| AC-28 | The scan records coverage, stale, skipped, score and rank each night | #260 | none | no test yet; not built |
| AC-29 | The top 5 is a display cut: the Brain keeps every idea, and Today and the digest agree | #281 | `test_market_context_verify.py:333` | passes |
| AC-30 | Saved screens and the watch-list change digest | #310 | none | no test yet; planning only |

Totals: 30 criteria.
- Test passes today: 19 (AC-1, 2, 3, 6, 7, 8, 11, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23, 24, 29).
- Test written and failing on purpose (strict expected failure): 5 (AC-4, 5, 9, 10, 12).
- Partly tested or unconfirmed: 2 (AC-15, AC-25).
- No test yet: 4 (AC-26, 27, 28, 30).

## 7. How this is checked

Each strict expected failure (`xfail` or `it.fails`) stays until its gap is fixed, then the marker is removed on purpose in the fixing
change. Gap fixes are separate work items (#486, #488, #385, #470, #416). Frozen-file changes (G1, G9) go through the approval script
and the owner's decision, not through this document.

## 8. Draft claims the code contradicts or has overtaken

1. The draft says pick lists are capped at 5 completed sessions. Only the buy list and top picks are (`signals.py:134-153`). The 5-day
   picks use `PICK_MAX_AGE = timedelta(days=5)`, which is 5 calendar days (`signals.py:131-133`).
2. The draft lists G5 to G8 as open and cites PR #509. #509 is closed; #520 replaced it and merged on 26 Nov. The display parts of G5,
   G6 and G8 (#486) and G7 (#470) are in the code. One marker looks stale: `verify240.test.tsx:131` is still `it.fails` although
   `stockParts.tsx:300-303` now prints "Last close on <date>". The API still returns the entry price as `current_price` and 0% for a
   never-priced position (`portfolio.py:270`), but the screens say "No price yet" (`has_price`). Position rows still carry no price time:
   `test_verify_240_quote_states.py:185` asserts fields that do not exist and has no expected-failure marker, so it fails if run.
3. G3, G4 and G10 are described as open in the 24 Nov draft; they are fixed on main (PRs #497, #498).
4. "Under 200 days of NIFTY gives DEFENSIVE" is correct, but the 200-day test is in `classify_regime`, not `judge.py`; `judge.py:69-74`
   only reacts to it.
5. The draft says the fail-safe "last stored run" behaviour is unverified. Partly verified: screens read finished runs only
   (`emptyReasons.ts:10`), an old run is named old, and a failed-run note exists (`runFailedNote`). A full failure drill is not tested.
6. The sector gate's reason does not name the sector and prints "ranks N of 15" for every N (`rules.py:98`).
7. G2 (breadth counts today's watch list) is missing from the 26 Nov consolidated draft. It is kept here because its test still fails.

## 9. Still needs an owner decision

Kept open. Nothing below has been decided by the owner on #281.

1. **Strongest-sectors gate**: on by default or not, and for how many sectors. The 9 Oct decision says "strongest sectors by default";
   the code default is off (0). The production value is unknown.
2. **BUY age limit after the signal-contract check.** A provisional 5 completed sessions is built (PR #497). The owner has not
   confirmed it as final, and the signal-contract check has not been done.
3. **Wording for a never-priced position**, and whether position rows should show a price time. "No price yet" is built; the owner has
   not signed the wording, and no price-time field exists.
4. **Which word the owner sees** for a room-only idea. WATCH with a room line is built (PR #499) as an owner-visible change. Confirm it
   as final, or keep both labels.
5. **G1 trial-freeze approval** for `m10_market/judge.py` (decision recorded, not applied).
6. **G9 trial-freeze approval** for `reader.py`, `fallbacks.py`, `contracts.py`, `m08_decide/engine.py`, `service.py`, plus the migration
   `brain_decisions.prediction_horizon_days`, plus the owner's edit of `test_horizon_385_mixup.py`.
7. **G2**: should breadth use the watch list as of the judged date (the snapshot table `watchlist_snapshots` exists)?
8. **#260 migrations** (scan history, rank).
9. **#316 timing change.**
10. **Merges and deploys** of the above (each a separate approval), and **sign-off of this document and closure of #227**.
