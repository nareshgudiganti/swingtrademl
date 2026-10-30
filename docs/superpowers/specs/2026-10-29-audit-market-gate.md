# Audit: the market gate (NORMAL / DEFENSIVE / NO_NEW_TRADES), 2026-10-29

Read-only audit. No code, config, test, protocol or evidence file was changed. The database, the test suite
and prod were not touched. Branch at audit time: `change/stock-page-clarity` (HEAD `4de482a`).

**What "the market gate" means here:** everything that decides "should we open new trades today?" from the
state of the market, not from the stock. In this codebase that is more than the brain's banner. There are
seven live mechanisms and seven replay or evidence versions. Section 2 lists them side by side.

**Owner's framing, used throughout:** the gate is a **risk-control hypothesis, not proven protection**.
It is meant to decide *whether* to trade. The model is meant to decide *which* stock.

---

## Summary

| # | Finding | Class | Severity | Changes prod behaviour today? | Touches a locked protocol / sealed evidence? | Proposed fix (proposal only) |
|---|---|---|---|---|---|---|
| F1 | Breadth (share of stocks above their 50-day average) is always worked out over **today's** watchlist, for every past day too | CONFIRMED DEFECT (already known: look-ahead audit item 12) | Medium | Live banner: no look-ahead. Replays, evidence and model training: survivor bias, and past values change when the watchlist is edited | Yes: Phase B B3 and the weakness experiment use breadth from "the 49"; `ml/market_context.py` is trial-frozen | New, separate point-in-time breadth built from `watchlist_as_of` (snapshots exist). Report-only first. Never edit the frozen loader silently |
| F2 | Prod breadth is reported to use a **10-stock** watchlist. All gate evidence used **49** stocks | LIKELY (count not re-verified; source is BUILD_NOTES 2026-10-04) | Medium | Yes: with 10 stocks each one is 10 points, so the 30/40/55/70% lines are coarse | No, but the evidence does not describe the prod gate | Record how many stocks the breadth counted in every banner's reasons. Confirm the prod count with a read-only API check |
| F3 | A **half-formed daily candle** can be stored during market hours ("Refresh data" or the backfill endpoint). The gate and v1's market ceiling then read it as "today's close" | CONFIRMED gap in the code path; whether it has happened is UNTESTED | Medium | Yes, but only if someone refreshes data during the session | No | Never store today's daily bar while the session is open, or make the gate ignore a bar dated today before 15:30 IST. Needs a test. The v1 ingestion change needs owner approval |
| F4 | M10's "wait a second day before relaxing" check **cannot see FII selling** on the previous day: it gets 19 days of FII data but needs 20 | CONFIRMED DEFECT | Low (a rare path, one day too early, in the bolder direction) | Yes (FII data exists in prod from 28 Sep 2026) | `brain/modules/**` is trial-frozen, so this needs a change note | Read 21 FII days, or judge the previous day on its own 20-day window. Add a unit test |
| F5 | M10's inputs (NIFTY, VIX, breadth) lose their dates and are assumed to end on the same day. A lagging VIX or breadth row makes "today's" VIX-spike rule and the 2-day check compare the wrong days. M01 checks NIFTY's freshness, not VIX's | LIKELY (no evidence it has happened) | Low | Possible | Frozen module | Line inputs up by IST date. Report a lagging VIX or breadth as stale. Test |
| F6 | Replays do **not** compute the gate the way live does (5 different versions, see section 3) | CONFIRMED inconsistency (mostly disclosed in each report's limits) | Medium for reading results | No | Phase B settings fix "every day NORMAL" (locked). fd-protocol-v1 copies v1's bear rule (locked) | Add one "gate fidelity" report: for every day with a recorded banner, re-derive it and print how often they agree. Report only |
| F7 | A day with **no known mode** is NORMAL in `portfolio_sim`, DEFENSIVE in `replay_report` and live, and NORMAL in `bad_market` timing | CONFIRMED inconsistency (disclosed) | Low–Medium | No (live is cautious) | `portfolio_sim.py` is frozen by fd-protocol-v1 | Make the default an explicit, printed parameter in new code. Show both readings |
| F8 | Version 1's money ceiling for market conditions (20–85% of the account may be invested) is a **second market gate**. `pit_replay` and `portfolio_sim` leave it out | CONFIRMED (disclosed in both) | Low–Medium | No | No | Keep disclosed. Optionally add a point-in-time version for replays (a new file) |
| F9 | **Two different gates run in prod.** The v1 path uses its money ceiling, the 15% halt and a +0.10 higher buy line in a NIFTY down-trend. The brain path uses M10 + M04 + the same ceiling + the halt. On a −4% crash day the brain says NO NEW TRADES, but v1 can still buy inside its ceiling | CONFIRMED inconsistency (by design: v1 is frozen) | Medium | Yes | No | Write it down for the owner. Whether v1 should obey the brain's banner is an owner decision, not a silent change |
| F10 | **The gate is inside the model score.** 6 of the model's inputs are market-wide (NIFTY trend and volatility, VIX change and percentile, two breadth numbers). They are the same for every stock on a day, so they can lift or sink every score together against a fixed buy line. That is a hidden, untested market gate | CONFIRMED separation breach (design) | Medium | Yes | `ml/features.py` is trial-frozen. M06 and M09 use the same inputs | Lab experiment only (selection-model design §10): a model without market-wide inputs, judged on ranking within the day. No prod change |
| F11 | The "+10-point NIFTY downtrend boost" in the fd_v1 report is **not a score boost**. It raises v1's buy line from 60% to 70% when NIFTY's 50-day average is below its 200-day one | NOT A DEFECT (but it is a gate, see F9) | — | — | fd-protocol-v1 replays it exactly | Wording only: call it a "stricter buy line in a down-trend" in future reports |
| F12 | Inside the brain's decision layer the banner changes **words, counts and size only, never scores** | NOT A DEFECT | — | — | — | None |
| F13 | `walk_forward.classify_regime` uses the **end** of a window (hindsight), and has the same name as the live `market_context.classify_regime` | NOT A DEFECT today (used only to label reports). Naming risk | Low | No | evidence-defs-v1 (locked) | A test that no decision code imports the hindsight one. A docstring warning in new code |
| F14 | Percentile and window maths (VIX percentile, volatility rank, novelty check) only look back. IST-midnight candle stamps are handled correctly | NOT A DEFECT | — | — | — | None |
| F15 | Market-mode history takes the newest "nightly" run of each day, and a manual "Run the brain now" is also a nightly run. If the 15:50 run fails, a daytime run's banner (built on yesterday's close) is filed under today. `brain_banner` (used to size the brain's reserved slot) takes the latest banner, however old | LIKELY | Low | Slightly (sizing of the reserved slot on a stale banner) | No | Store the market data's own date with each banner. Ignore banners whose data is older than the last trading day |
| F16 | Uncommitted local edits to M07 and `risk.py` (testing mode) | Noted, not judged | — | Not on main | — | — (section 6) |

**Evidence that the gate protects (section 5), in short:** the only support is **exploratory**. In the
bad-market test the banner roughly halved the worst fall in 5 windows that were picked *because* the market
fell. That test cannot see the cost of false alarms. Two other exploratory results point the **other way**
for the breadth part of the gate: buying every stock did best when breadth was under 30% and worst when it
was over 70%. M04's "bear phase", "crash" and "unknown" days also had better 15-day outcomes. The 15% halt
has never fired in any replay. NO_NEW_TRADES never fired in the tested windows. There is no live evidence
yet. **Status: hypothesis. It has some support for limiting drawdown, and no support (some contrary signs)
for its effect on returns.**

---

## 1. Where the gate lives (live code)

| Piece | What it does | Evidence |
|---|---|---|
| M10 market judge | Decides NORMAL / DEFENSIVE / NO_NEW_TRADES. It runs v1's regime table (trend, volatility, breadth, VIX). FII selling turns a "normal" market DEFENSIVE. A crash day (NIFTY −4% or VIX +30%) means NO_NEW_TRADES. Relaxing back to NORMAL needs two good days | `brain/modules/m10_market/judge.py:28-31, 61-103, 137-162`; module `m10_market/module.py:32-34` |
| M04 situations | A crash (on any of the last 3 days), a bear phase, or an "unlike any past day" market suggests DEFENSIVE | `m04_situations/rules.py:27-34, 45-68`; `module.py:63-81`; `novelty.py:60-84` |
| `effective_mode` | Combines the two: it can only make the mode more careful. No mode at all means DEFENSIVE | `brain/market_mode.py:18-29` |
| Fallback if M10 is missing | Trend only, at best DEFENSIVE. NO_NEW_TRADES if breadth is missing too | `brain/fallbacks.py:78-110` |
| M07 allocator | NO_NEW_TRADES: every buy refused. DEFENSIVE: at most 2 new buys, each half size | `m07_risk/allocator.py:115-119, 130-139, 183-185`; committed `m07_risk/module.py:29-31, 167-180` |
| M08 rules | In a careful market, a falling stock becomes WATCH (an idea) or MONITOR (a holding). This changes the word, not the score | `m08_decide/rules.py:23, 111-117, 196-199` |
| Constitution | Enforces NO_NEW_TRADES and the M04 suggestion even if M08 ignores them. If M07 fails, the run is NO_NEW_TRADES | `brain/constitution.py:64-67, 110-122` |
| v1 money ceiling for market conditions | Caps the share of the account that may be invested: stressed 20%, weak 30%, normal 55%, strong 75%, very strong 85%, unknown 30% | `services/deployable.py:60-66, 90-121, 134-166`; used in `services/risk.py:789-808`, `services/engine.py:93`, committed `m07_risk/module.py:92` |
| 15% drawdown halt | No new buys while the account is 15% or more below its peak (measured on the live value) | `services/risk.py:174-196, 683-692`; `core/config.py:239` |
| v1 ml_swing buy line in a down-trend | The buy line is raised by 0.10 when NIFTY's 50-day average is below its 200-day one | `strategies/ml_swing.py:78-80, 136-144` |
| Brain order cap on non-NORMAL days | An order is never bigger than M07's half-size quantity | `strategies/brain.py:105-113`; `services/brain_golive/approvals.py:340-348` |

Timing in prod (`workers/scheduler.py`):
- 15:40 IST: candle ingest (122-127).
- 15:45: v1 scan.
- 15:50: brain nightly run (261-266). A live run uses `as_of = now` (`brain/service.py:104-109`).
- Every 15 minutes in market hours: brain intraday run (holdings only, but M10 runs) (267-272).
- 09:15–09:19: approved ideas are bought, using the **previous evening's** banner (275-280).
- 19:20: FII and other evening feeds (167-172).

---

## 2. Every definition of "market regime / breadth / stressed", side by side

| # | Definition | Inputs | Thresholds | Stock list (universe) | Timing | Used for |
|---|---|---|---|---|---|---|
| D1 | **M10 banner** (live) | NIFTY closes, VIX closes, breadth series, FII net for the last 20 days | Trend: 50-day avg vs 200-day avg. Volatility "elevated" = 20-day volatility in the top 25% of the past 252 days. VIX "elevated" ≥ 80th percentile of 252 days, "calm" ≤ 30th. Breadth: stressed < 30% (falling trend), narrow < 40%, strong ≥ 55%, very strong ≥ 70%. NORMAL = normal / strong / very strong. FII: 4 of last 5 days sold AND 20-day sum < 0 (only on "normal"). Crash: NIFTY ≤ −4% or VIX ≥ +30% on the latest day. 2-day confirmation | Breadth: `Instrument.is_watchlisted` **now** (`market_context.py:157-159`). Prod reportedly 10 stocks, local 49 | 15:50 IST nightly; also intraday and on demand | Brain banner |
| D2 | **M04 market label** (live) | NIFTY and VIX closes, by date | Crash: −4% / +30% on any of the last 3 days. Bear: ≥ 10% below the 1-year high AND below the 200-day avg. "Unknown": distance to nearest past day > 99th percentile | NIFTY only | Same run | Turns NORMAL into DEFENSIVE |
| D3 | **Brain fallback** (M10 missing) | NIFTY trend, breadth | At best DEFENSIVE. NO_NEW_TRADES when breadth is missing | Watchlist now | Same run | Safety net |
| D4 | **v1 money ceiling** `classify_deployable` | Same as D1 except FII. No crash rule, no confirmation | Same table as D1 → 20/30/55/75/85% invested | Watchlist now | At every entry check (15:45 scan, 09:15 approvals, any check_entry) | v1 and brain sizing |
| D5 | **v1 down-trend buy line** | NIFTY `nifty_trend_regime` = sign(50-day avg / 200-day avg − 1); missing → 0 | < 0 → buy line +0.10 | NIFTY | 15:45 scan | v1 ml_swing BUY |
| D6 | **Model inputs** | `nifty_trend_regime`, `nifty_volatility_20`, `vix_change_5d`, `vix_percentile_rank` (rank over 252 days), `breadth_pct_above_sma50`, `breadth_advance_pct` | Learned by the model, no fixed line | Breadth: watchlist now, for all training years | Training and every score | Model score (v1, brain fallback, M06 shadow, M09 drift) — `ml/features.py:42-64, 200-202, 214, 346-365` |
| D7 | **15% drawdown halt** | Account value vs its running peak | ≥ 15% | Account | Every entry check | v1 and brain |
| D8 | **Phase B B3** (locked) | Breadth of "the 49", counting only stocks with a bar that day | Trade **only** when breadth < 30% | Fixed list of 49 (chosen today) | Decision close | Evidence candidate. Note it points the **opposite** way to D1: it buys *after* weakness | 
| D9 | **Weakness experiment** (2026-10-12) | Same breadth over 49 | < 20 / 30 / 40% | 49 | Decision close | Evidence only |
| D10 | **Hindsight market type** `walk_forward.classify_regime` (evidence-defs-v1, locked) | Average stock move from first to **last** bar of a 28-day window | > +3% rising, < −3% falling | The run's stocks | **After the fact** | Report splits only (`splits.py:5-7`, `phase_b.py:835`, `five_day.py:600`, observatory `defs.py:30-31`) |
| D11 | **fd_v1 down-trend** (locked) | Same feature as D5 | Same +0.10. A day with no NIFTY row counts as a down-trend (prod would use the previous day's value) | NIFTY | Decision close | 5-day protocol. The report counted 0 such days, so the sealed result is unaffected |
| D12 | **Bad-market replay** | D1 inputs **without FII** | D1 thresholds | Watchlist now (49) | Each day's close | Evidence |
| D13 | **Market-mode history, derived days** | D1, data up to 23:59 IST | D1 thresholds, **no M04** | Watchlist now | End of the IST day | Replays |
| D14 | **Display** `/market-data/regime` | NIFTY trend and volatility only | — | — | On request | UI only |

Where they disagree in a way that matters:
- **Direction.** D1–D4 treat weak breadth as a reason for **less** buying. D8 and D9 test **only** buying
  when breadth is weak.
- **Universe.** Live D1 uses about 10 stocks (if F2 holds). Every evidence version (D8, D9, D12) uses 49.
- **Crash day.** D1 says NO_NEW_TRADES. D4 has no crash rule, so v1 may still buy (F9).
- **The day after a crash.** D2 holds caution for 3 days. D1's confirmation does not include the crash rule,
  so M10 alone can be NORMAL the next day. Live uses D1 and D2 together. D12 and D13 use D1 alone.
- **Down-trend.** v1 (D5) raises the buy line. The brain does not use D5. It uses DEFENSIVE instead.
  Two different mechanisms answer the same question.

---

## 3. Look-ahead check (question 1)

| Input | Uses data after the decision close? | Evidence |
|---|---|---|
| NIFTY / VIX closes in the brain | No. `Candle.ts <= as_of`, candles stamped at IST midnight, and the replay's as_of is 23:59 IST | `brain/reader.py:278-289, 320-336`; `market_mode_history.py:71-73` |
| Breadth values | No later **days**: the 50-day average only looks back, and the series is cut at as_of | `market_context.py:116-134, 182-185`; test `test_lookahead_audit.py:87` |
| Breadth **stock list** | **Yes, in the survivorship sense.** Today's watchlist is used for every past day (F1) | `market_context.py:157-159`; `reader.py:338-345` (the reader ignores its own point-in-time `universe()` at `reader.py:59-66`) |
| VIX percentile | No. Trailing 252 days, including today | `deployable.py:124-131`; `features.py:214` |
| NIFTY volatility percentile | No. Rolling 252-day rank | `market_context.py:210-220` |
| M04 novelty | No. Standardised on past days only, today left out | `novelty.py:63-76` |
| FII flows | Live: no. Derived replays read FII for day D (published about 19:20), which the 15:50 live run did not have. That is not look-ahead for a buy at the next open, but it is not what live saw (F6) | `reader.py:347-360`; scheduler 167-172 |
| Same-day intraday data | **Possible** (F3). Ingestion re-fetches the newest bar because it is "possibly incomplete" (`ingestion.py:363-374`). `/system/refresh-data` (`api/v1/endpoints/system.py:270-289`) and the backfill endpoint (`market_data.py:170-190`) can run during the session. Nothing stops a half-formed daily bar from being stored | as cited |
| Next-day bars | No | Every read is `<= as_of` |
| IST midnight stamps | Handled: `.astimezone(IST).date()` throughout. `bad_market.py:203-204` has a naive-timestamp branch that would mis-date a bar, but stored timestamps are timezone-aware, so it is never used | as cited |
| Whole-history statistics | None found in the gate. (The hindsight label D10 uses whole windows but never feeds a decision) | `walk_forward.py:85-96` |
| v1 `current_deployable` | Not bounded by an as_of, but it is only called live (`risk.py:791`, `engine.py:93`, `m07_risk/module.py:92`, `api/v1/endpoints/risk.py:36`). The v1 backtest does not call it | grep of callers |

**F4 detail (FII confirmation).** `inputs_from` reads `fii_net(20)` (`judge.py:133`). `_trim_last_day` drops
one value (`judge.py:111`), leaving 19. `_fii_selling` returns False below 20 (`judge.py:55-56`). So the
"was yesterday careful?" check (`judge.py:153-155`) can never see FII-driven caution. Example: yesterday the
market was DEFENSIVE only because of FII selling; today the selling stops. The judge relaxes to NORMAL today
instead of waiting for a second day. No test covers this (`tests/test_brain_m10_judge.py` passes no FII data
to the confirmation tests). The error is in the bolder direction, so it goes against principle 5 ("decisions
only move toward caution"). It is a small effect.

**F5 detail (dates dropped).** `_closes` returns a plain list of values with no dates (`reader.py:278-289`).
`breadth_series` drops its dates too (`reader.py:345`). The judge assumes all three series end on the same
day (`judge.py:42-51, 106-112`). M01 checks that NIFTY and the stocks are fresh, but not VIX
(`m01_quality/module.py:53-57`).

**F3 detail (half-formed bar).** If "Refresh data" is pressed at, say, 11:00:
- Today's partial daily bar is stored.
- Every intraday brain run, a "Run the brain now", and every v1 entry check then treat that bar as today's
  close. The crash rule, the trend and the money ceiling all use it.
- At 15:40 the bar is overwritten with the final one, so later replays of that day give a different answer
  from the one live gave.

---

## 4. Replay fidelity (question 3)

| Tool | M10 | M04 | FII | Money ceiling (D4) | Mode on a day with no data | as_of |
|---|---|---|---|---|---|---|
| **Live** | yes | yes | to D−1 (normally) | yes | DEFENSIVE / NO_NEW_TRADES | 15:50 IST |
| `market_mode_history` derived | yes | **no** (disclosed, `market_mode_history.py:37-42`) | to D | — | left missing | 23:59 IST |
| `bad_market` | yes | **no** | **none** (`bad_market.py:133`, disclosed) | — | NORMAL (`bad_market.py:157`) | per day |
| `pit_replay` / `replay_week` / `module_ablation` | yes | yes | to D | **no** (`pit_replay.py:82, 156`, disclosed) | banner from the run | 23:59 IST (`pit_replay.py:340`) |
| `portfolio_sim.simulate` | recorded, else derived (M10 only), else **NORMAL** | via recorded only | — | **no** (`portfolio_sim.py:942`) | **NORMAL** (`portfolio_sim.py:457, 488, 801`) | — |
| `replay_report` | given banners | — | — | — | **DEFENSIVE** (`replay_report.py:84-91`) | — |
| Phase B accounts (locked) | — | — | — | — | **every day NORMAL** (`2026-10-22-phase-b-settings.md:32`) | — |

Breadth in every replay uses today's watchlist (F1), even though the replay reader has a point-in-time stock
list. No test checks "recorded live banner == re-derived banner for the same day". The selection-model design
(§10) asks for exactly that test.

---

## 5. Separation: is the gate mixed into stock scores? (question 4)

- **Brain decision layer: separated.** The banner changes M07's counts and size and M08's words. It never
  changes a score (`allocator.py:115-185`, `m08_decide/rules.py:111-117`). M08's buy line is the plain
  `ML_MIN_CONFIDENCE` or the accepted level, with no down-trend boost (`reader.py:457-458, 490-496`).
- **The model score itself: not separated (F10).** The market-wide inputs (`features.py:47-64`) are the same
  for every stock on a given day. A tree model can use them to push every score above or below the fixed buy
  line on that day. That acts as a market gate nobody wrote down or tested. The same inputs are in M06
  (`m06_reason/dataset.py:38-43`, shadow) and the M09 drift check (`m09_learn/drift.py:53-62`). They do not
  change the **order** of stocks on a day much, but they do change **how many** pass a fixed line.
- **v1 down-trend buy line (F11):** a raised threshold (`ml_swing.py:139-144`), not a score boost. The
  fd_v1 report's "+10-point NIFTY downtrend boost" refers to this. It is replayed exactly in
  `five_day.py:112-185` (locked).

---

## 6. Local uncommitted M07 edit (reported, not judged)

The committed M07 (`git show HEAD:.../m07_risk/module.py`) builds the account with
`deployable.current_deployable(db).fraction` (line 92) and calls `risk.check_entry` with no waiver (111-120).
A replay never approves a trade (152-163).

The working tree has an uncommitted diff (with `services/testing_mode.py` untracked, `core/config.py`, `.env.example`
and `services/risk.py` also modified). It adds a `TESTING_NO_LIMITS` waiver that applies only in the shadow
stage and never in live trading. When on, it sets the money ceiling to 100% and relaxes the v1 limits
(including the drawdown halt) for the brain's risk check. The **banner rules in the allocator are not
touched**: NO_NEW_TRADES and DEFENSIVE's 2 buys at half size still apply. This audit does not assess the
change.

---

## 7. Evidence status: does the gate protect? (question 5)

| Claim | Evidence | Class | Label |
|---|---|---|---|
| "The banner turns careful in falls" | `docs/brain/evidence/bad_market/bad_market.md` rows 10-14: careful by day 0–14. In 4 of 5 windows less than ⅓ of the fall had happened by then; in the 2024-09/10 window 72% had. NO_NEW_TRADES never fired | SUPPORTED | Exploratory, development data, 49 survivor stocks, M10 only, no FII |
| "The banner reduces drawdown" | Same file, rows 20-24: worst fall with the banner vs always NORMAL: −5.6 vs −9.6, −5.3 vs −7.1, −5.9 vs −10.2, −4.4 vs −8.9, −8.9 vs −16.4 | SUPPORTED | Exploratory. Windows chosen **because** NIFTY fell, so the cost of false alarms in rising markets is not measured |
| "The banner improves returns" | Same rows: better in 4 windows, worse in 1 (−2.0% vs −1.2%) | UNTESTED EXPLANATION (falls only) | Exploratory |
| "Ideas on careful days are bad" | Same file rows 30-34: average −0.32% to −1.60% | SUPPORTED within falls | Exploratory, falls only |
| "Weak breadth is a reason to stay out" | `input_and_regime_spike_2026-10-12.md` §2: buying every stock earned +0.04% under 30% breadth and −0.54% over 70%. `weakness_experiment_2026-10-12.md`: B5 +0.28% vs A −0.25%, inside the error, and the 30% line is not out-of-sample | OBSERVED FAILURE of the hypothesis's direction (not significant) | Exploratory |
| "Crash / bear / unknown days are dangerous" (M04) | `docs/brain/BUILD_NOTES.md:155-161`: these days had **better** +8%-before-−4% rates (crash 55%, bear 29% vs up-trend 17%). Kept "for safety", owner decision pending | OBSERVED FAILURE of the hypothesis's direction (9 crash days, survivor list) | Exploratory |
| "The 15% halt protects" | `portfolio_replay_2025-10-01_2026-09-17.md:7, 14-22`: the halt never fired (worst falls 11–14%). Every day NORMAL. `pit_replay.md:43`: worst fall 1.3% | UNTESTED EXPLANATION | Exploratory |
| "NO_NEW_TRADES on a crash day helps" | Never fired in any replay window. BUILD_NOTES lists 3 real crash days (04 Jun 2024, 05 Aug 2024, 07 Apr 2025) that were never scored for this rule | UNTESTED EXPLANATION | — |
| "The gate's mechanics behave as written" | Tests: `test_brain_m10_judge.py` (10), `test_brain_market_mode.py` (never bolder), `test_brain_market_mode_history.py:96, 113` (derived reads only up to the day), `test_brain_bad_market.py:114`, `test_lookahead_audit.py:48, 87`, `test_market_breadth_missing.py`, `test_deployable_bands.py` | SUPPORTED (mechanics only, not protection) | Unit tests |
| Live protection | No brain trades counted yet (two-week review). Sealed trial from 2026-10-14 | UNTESTED | — |
| Missing tests | Half-formed bar (F3), FII confirmation (F4), date alignment (F5), live == derived for the same day (F6), point-in-time breadth (F1) | — | — |

Overall: the gate is a **reasonable caution rule with exploratory support for smaller drawdowns in
hand-picked falls**. There is **no evidence it improves returns**. Two exploratory results suggest its
breadth and "bear/crash" parts may cut the best entry days. It should keep being described as a
risk-control hypothesis.

---

## 8. Proposed fixes, in order (none applied; each needs owner approval if it touches prod or a frozen file)

1. **Report-only, safe now:**
   - (a) A "gate fidelity" report: recorded banner vs re-derived banner for each day, with the agreement rate
     and the reasons for each disagreement.
   - (b) Record the breadth denominator and the input dates with every banner, in new code outside the
     frozen modules.
   - (c) Split every lab result by banner state, as selection-model design §10 says (reporting only).
2. **Point-in-time breadth** (F1): a new function that reads `watchlist_as_of` (`brain/universe.py:43-59`,
   `services/watchlist_snapshots.py`). Use it in replays and evidence first. Days before snapshots exist stay
   marked "survivor-biased". Changing the live banner or the model inputs would be a separate, approved
   change, because `ml/market_context.py` and `ml/features.py` are trial-frozen and Phase B B3 is locked.
3. **F4 and F5** (brain module bugs): a change note under the trial change policy. Fix and add tests. Both
   only make the gate more careful or more correct, but `brain/modules/**` is frozen during the trial.
4. **F3** (half-formed bar): block storing today's daily bar while the session is open (v1 ingestion, owner
   approval), or have the gate ignore a bar dated today before 15:30. Add a test.
5. **F9** (two gates): owner decision whether v1 should respect the brain's NO_NEW_TRADES. No silent change.
6. **F10** (gate inside the score): lab test of a model without market-wide inputs, judged within the day.
   No prod change. Any result is development data.
7. **F15:** store the market-data date with each banner, and treat a banner older than the last trading day
   as unknown (DEFENSIVE).
8. **Evidence:** a pre-registered test of the gate on **all** days (not just falls), so the cost of false
   alarms is measured. The current bad-market test cannot answer that.

No result already produced (fd_v1, Phase B settings, bad_market, the sealed trial) should be re-run or
re-labelled because of this audit. Each fix applies only to work done after it is approved.
