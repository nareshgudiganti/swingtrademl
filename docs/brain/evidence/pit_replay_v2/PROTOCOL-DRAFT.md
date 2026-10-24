# ps15 point-in-time replay, version 2: protocol `ps15-pit-replay-v2` (DRAFT)

**Status: DRAFT for the owner's OK. Docs only. No code is written and nothing is run until the owner approves
it (section 9).** It answers evidence Amendment 1, section A10: "rebuilding past portfolios … the biggest
open job". Defs version `evidence-defs-v2`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md:
all local data up to 2026-09-07 is development data).

## 1. Question

If the brain had run every evening on a past account **with every limit prod really applies**, how many of
its TRADE ideas would have become buys, which limit stopped the rest, and how would that account have done
against simpler ways of choosing on exactly the same rules?

## 2. Why ps12 is not enough

ps12 (`docs/brain/evidence/pit_replay/`) gave the brain a real past account, but left out eight limits
(its "Known limits"). The biggest gap is the **market-conditions money ceiling** (`DEPLOYABLE`): in a weak
or stressed market the bot may only have 30% or 10% of the account invested at all
(`services/deployable.py:60-66`). On prod this ceiling is the main reason brain ideas are blocked, but ps12
switched it off on purpose (`brain/pit_replay.py:82` and `:156`, `deploy_room = 1e15`). ps12's banner was
DEFENSIVE on all 25 days, which the market judge (M10) gives for the weak, stressed and unclear regimes
(and for a normal market with foreign selling), so the ceiling would probably have bound often. The run
will show how often. ps12 also bought on every gap past the brain's buy range, which prod refuses.

## 3. The missing limits, one by one

Prod checks a brain idea **twice**: (a) at the close, in the risk gate M07 (`m07_risk/module.py:82-124`),
which calls `risk.check_entry` **with no strategy** (`:119`), and (b) at the next open, when an approved idea
is placed (`services/brain_golive/approvals.py:315-337`), which calls `check_entry` **with the brain
strategy** and first refuses any price outside the brain's buy range or at or below the stop. ps15 copies
both checks.

| Limit | Live code | Can past days be rebuilt from local data? | Plan |
|---|---|---|---|
| Market-conditions ceiling | `risk.py:670-684`; table `deployable.py:90-121`; M07 room `module.py:92`, allocator `allocator.py:182` | **Yes.** `classify_deployable` is pure. Its inputs (NIFTY trend and volatility, INDIA VIX rank, breadth) come from the replay reader, bounded by each day (`reader.py:320-345`), the same as M10 already does in ps12 (`judge.py:67`). VIX is stored locally to 2026-09-09. There is no stored regime history table, but none is needed | Ceiling = fraction x account value; room = ceiling minus everything held (v1 + brain in variant B) |
| Owner's pause switch | `risk.py:504-507`; one `system_state` row (`db/models/safety.py`) | **NOT TESTABLE.** Only today's switch is stored, with no history | Assume "never paused", say so on the report. The replay's own 15% halt stays |
| Avoid list | `risk.py:522-528`; `avoid.py:31-95` | **Partly.** The live function has no upper date limit (`avoid.py:36, 50`), so it would see the future in a replay; ps15 uses a copy limited to each day. Surveillance lists (ASM/GSM) and delivery-only series: yes, if those days are stored (checked before the run). Results and split dates: `upcoming_events` keeps no record of *when* a date became known | Coverage check first. Any part with no rows for the window is NOT TESTABLE for that part. Results dates count only if the row's `created_at` is on or before the day (D6) |
| Cool-down after a stop | `risk.py:516-520`, `:138-156` (uses today's clock; 5 calendar days, `config.py:240`) | **Yes**, from the replay account's own stopped trades | Same 5 calendar days, counted from the replay day |
| Per-strategy slot share | `risk.py:538-560` (order time only; M07 passes no strategy) | **Yes**, as a fixed setting: brain share = slots ÷ (active v1 strategies + 1). At ₹9.8L (8 slots) and one v1 strategy that is 4 | Applied at the next-open check. v1 strategy count taken from prod today (D4) |
| Share-price cap | `risk.py:575-582`; `limits.py:127-133` | **Yes**, via `limits_for`. It exists only at the ₹10K rung, so it never binds on a ₹9.8L account | Applied as is. Reported as "not active at this size" |
| Cap tiers | `risk.py:588-613`; `limits.py:134-146` | **Yes** as a setting. The tier comes from the *strategy's* model name, not the stock. At M07 (no strategy) it is always large. At the open it uses the brain strategy row (prod id 7) | Applied at the next-open check with the brain strategy's tier (D4) |
| Liquidity ceiling | `risk.py:652-668`; 20-day traded value `risk.py:283-297` (latest 20 rows, no date limit) | **Yes**, from the stored bars, limited to each day | Copy limited to each day. Off below ₹10L (`limits.py` rung ₹1L has none), so it switches on only if the account grows past ₹10,00,000 |
| Buy range at the open (new) | `approvals.py:315-326` | **Yes**: the brain's plan (buy range, stop) is in each day's decisions; the next open is in the bars | A gap outside the range is "not bought", fixing a ps12 limit |

Note: ₹9,79,792 sits just under the ₹10L rung. If the account grows past ₹10,00,000, the ₹10L rules switch on
(liquidity ceiling, small companies allowed up to 20%). The report states on which days that happened.

## 4. Shared account: brain alone, or v1 + brain?

On prod the brain shares one paper account with version 1: v1 scans at 15:45 and fills first
(`services/engine.py:225-228`), the brain runs at 15:50 (`workers/scheduler.py:247`) and sees v1's positions,
cash and invested money. v1's holdings eat the same slots, sector room and market-conditions room.

- **v1 as it really ran in July–August 2026: NOT TESTABLE.** The brain was not live then (prod since
  2026-10-04); v1's 20 prod models (+2% in 5 days) were trained on data that includes the window, so they
  are not point-in-time; prod's positions from then are not in the local database, and that paper record is
  contaminated anyway.
- **A v1 stand-in is possible:** train one 5-day as-of model (+2% in 5 days, data to 2026-07-10) with the
  existing `ml/asof.py`, run v1's own buy rule (score at or above the buy level, strongest first, v1's
  `check_entry` with its strategy) at the decision day's close, and exit by v1's own rules
  (`services/exit_policy.py`, 30 calendar days). It is an approximation of v1, not v1.

**Recommendation: run both, with variant A as the main result.**

- **A. Brain alone** (main): the brain owns the whole account. Every input is point-in-time. It answers
  "what do the brain's own limits let through?".
- **B. Shared account** (secondary, labelled APPROXIMATE): the v1 stand-in buys first each day, then the
  brain. It answers "how often does v1 crowd the brain out?". **Horizons are never mixed (A7):** only brain
  trades are scored. v1 stand-in trades only take up room and are reported as counts (slots and rupees
  used), never as results.

## 5. Fixed settings (as ps12 unless stated)

| Setting | Value |
|---|---|
| Decision days | 2026-07-13 to 2026-08-14 (25 days, same as ps1/ps12, so ps15 minus ps12 = the effect of the added limits). Optional longer window: D1 |
| Account days | decision days + 15 trading days with no new buys (to about 2026-09-04; local prices end 2026-09-07) |
| Model | `swing_classifier_asof_20260710` (15 days, +8%; data to 2026-07-10). Variant B adds a 5-day as-of model, same cutoff |
| Start money | ₹9,79,792 (paper trial's clean start, 2026-09-28) |
| Fills | brain decides after the close; approved ideas are bought at the **next open**, slipped, with charges (`services/costs.py`), only if the open is inside the buy range and above the stop. Every M07-approved idea counts as owner-approved (D5) |
| Exits | +8% / −4%, half out at +5%, 15 trading days; a bar touching the stop counts as the stop |
| Limits | everything in ps12 (ladder, sector rule, 15% halt, 5 new buys a day / 2 on DEFENSIVE / none on NO NEW TRADES, cash reserve) **plus section 3** |
| Buy level | `ML_MIN_CONFIDENCE` code default 0.60 (the local `.env` is not read) |
| Random draws | 200 accounts, seeds 12 to 211 |

## 6. Variants (identical days, money, fills, exits, costs and limits; each in A, and in B where marked)

1. **Brain** (A, B): the whole brain on the point-in-time account with all limits.
2. **Rules only** (A, B): the definition the owner settles in **tv7**. Until then, ps12's flat score at the
   buy level, labelled "ps12 definition, tv7 pending" (D3).
3. **Model only** (A): every stock the as-of model scores at or above the buy level, best first; account
   limits only (now including section 3).
4. **Random, same count a day** (A, B): as many random stocks as the brain bought, same list, same banner.
5. **NIFTY 50 bought and held** (A). 6. **Cash** (A).

## 7. What is reported

- ps12's columns per variant: money at the end, return, worst fall, trades finished, share reaching +8%
  first, average per trade after costs, NO NEW TRADES / DEFENSIVE days. Each with its count, period and
  range (A5).
- **Why TRADE ideas were not bought**, by rule (DEPLOYABLE, AVOID, COOLDOWN, POSITION_LIMIT incl. slot share,
  SECTOR_CAP, LIQUIDITY, CAP_TIER, SHARE_PRICE, BUY_RANGE, DRAWDOWN, MARKET), at the close and at the open.
- Daily market regime, deployable fraction, money invested vs the ceiling; days with a TRADE idea but no buy.
- ps15 vs ps12 (same days): how much the added limits changed buys and results.
- Variant B only: slots and rupees used by the v1 stand-in each day; brain ideas blocked because of it.
- Optional realism check (D7): the mix of block reasons against prod's trial **block counts by rule**
  (counts only, allowed by A4; no trial outcomes are read).

**Reading rule (fixed now).** The 25-day window has fewer than 30 trading days, so every "is it better"
reading is **INCONCLUSIVE** (A5). A result below the random 5th percentile, or a fall past the 15% halt, is
still recorded as a **warning** (A1). With the longer window (D1) the best possible label is
**NO WARNING (diagnostic)**, never PASS. The block-reason counts are facts about how the limits work, not
evidence about skill. Nothing in the brain, its settings or the trial changes because of this run.

## 8. Manifest (A6) and exposure-ledger row (added before the run)

Manifest at the top of the result file: protocol `ps15-pit-replay-v2`, defs `evidence-defs-v2`, code commit,
data window, stock list (each day's watchlist snapshot, survivor bias; breadth uses today's watchlist; sector
map is today's), model name and training window (and the 5-day stand-in model if B), horizon 15 days (v1
stand-in: 5 days, named separately), every NOT TESTABLE item, the ledger row.

Ledger row (`docs/brain/EXPOSURE-LEDGER.md`, local data):
`| 2026-07-13 to 2026-09-04 (decisions to 08-14, then 15 settle days) | ps15 point-in-time replay v2: ps12's accounts with the market-conditions ceiling, avoid list, cool-down, slot share, cap tier, share-price cap, liquidity ceiling and buy-range check added; variant B shares the account with a v1 stand-in (5-day as-of model trained on data to 2026-07-10) | Diagnostic only; nothing changed (protocol ps15-pit-replay-v2) | <run date> | pit_replay_v2/ |`
(plus a row per extra window if D1 is chosen).

## 9. Rough build (after the owner's OK)

- **New** `backend/src/swing_trade_ml/brain/pit_replay_v2.py` (about 400–500 lines): reuses ps12's
  `PointInTimeReader`, `PointInTimeRiskGate`, `run_account` and the `Book` by import, plus a stricter account
  (subclass) with day-limited copies of the parts of `check_entry` that read today's clock or unlimited data
  (deployable inputs, avoid list, 20-day traded value, cool-down), the next-open check, and the v1 stand-in.
- **New** `backend/tests/test_brain_pit_replay_v2.py`: each limit blocks when it should; each day-limited
  copy gives the same answer as the live function when the day is the last stored day; no look-ahead; no
  database writes; live runs unchanged.
- **New** outputs in `docs/brain/evidence/pit_replay_v2/`; one ledger row.
- **Not touched:** every file in `backend/tests/trial_freeze.json` (`services/risk.py`, `deployable.py`,
  `limits.py`, `avoid.py`, M07, `reader.py`, `market_context.py`, `engine.py`, strategies). They are used
  read-only, as ps12 did. `pit_replay.py` and `portfolio_sim.py` stay unchanged so ps12 can be rerun.
- Effort: about 2 days of build and tests; runs of about 2 hours for A (two brain variants x 25 days), about
  4 hours with B; each extra D1 window adds about 2 hours plus training one as-of model.

## 10. Owner decisions

- [ ] **D1 Window:** only ps12's 25 days (direct comparison, INCONCLUSIVE by A5), or also a longer window
  that needs 2–3 more as-of models (for example cutoffs 2026-01-09 and 2026-04-10) to reach 30+ days?
- [ ] **D2 Shared account:** A (brain alone) as the main result plus B (with v1 stand-in, APPROXIMATE) as a
  secondary one (recommended), or A only?
- [ ] **D3 Rules only:** use tv7's definition; until tv7 is settled, ps12's flat score, labelled?
- [ ] **D4 Settings from prod:** take today's count of active v1 paper strategies (slot share) and the brain
  strategy's tier from prod's configuration (read-only)?
- [ ] **D5 Approval:** treat every idea M07 approves as approved by the owner and placed at the next open?
- [ ] **D6 Avoid list:** count a results date only if it was stored on or before the day, and mark the parts
  with no stored history NOT TESTABLE?
- [ ] **D7 Realism check:** compare the block-reason mix with prod's trial block counts (counts only)?
- [ ] **D8 Go:** approve this draft as `ps15-pit-replay-v2`, then build (no frozen file touched), then run once.
