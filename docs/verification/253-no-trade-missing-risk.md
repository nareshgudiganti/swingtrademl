# #253 Verification: no new trades when risk evidence is missing

Baseline commit: `7ba3547` (main). Test database: `swing_trade_ml_dev4b_test`. Written 2026-11-24 (IST).
Tests and this note only. No risk, sizing, limit, order or frozen code was changed.

## In plain English

The rule is: if the app cannot check the risk, or the data is bad, it must buy less, never more.

- **The Brain follows the rule.** If its risk check is missing, crashes, runs too slowly or returns rubbish, the Brain
  says "no new trades" and suggests nothing to buy. Missing or old prices, a missing market index and a crashed module
  all make it more careful. This was already tested and passes.
- **The simulation follows the rule.** A "no new trades" day, an unknown market mode, or a day with no recorded mode buys nothing,
  and every held-back pick is listed with its reason.
- **The 15% drawdown stop works,** including when the last daily snapshot is weeks old (it measures from the last known peak).
- **One confirmed gap:** the original daily scan (version 1) does not check how old a stock's latest price bar is. If price
  data stops arriving, it still scores the last bar it has, even if that is 12 days old, and passes a BUY on. This is
  already tracked as #344/#353 and waits for the owner's approval because it touches frozen code. It is pinned below as a
  strict expected-failure test; I did not fix it.
- **One limit to know about:** if there has never been a single equity snapshot, the drawdown stop has no peak to measure
  from and reads zero. That is right for a brand-new account but cannot tell a new account from a wiped history.
- **One design choice to know about:** when the market context is missing, version 1 does not stop; it drops to the
  "weak market" allowance (30% of the account may be invested) instead of the normal 55%. More careful, not zero.

## Findings table

| # | Question | Code (at `7ba3547`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| a1 | Brain: risk gate (M07) missing, crashing, too slow, or returning nothing/garbage | `brain/constitution.py:25,62-63` (`NO_RISK_GATE`); `:107` `enforce` sets the banner; `brain/runner.py:73` marks the gate as run | banner NO_NEW_TRADES, every TRADE downgraded, no sizes | `test_bad_data_drills.py:312` `test_drill_risk_gate_fault_means_no_new_trades` (5 faults) | Pass |
| a2 | Brain: the risk gate cannot be switched off | `brain/module.py:60,89,102` (only the risk gate is mandatory) | refused | `test_bad_data_drills.py:325` | Pass |
| a3 | Brain: with the banner at NO_NEW_TRADES the brain strategy buys nothing | `strategies/brain.py:120-164` (BUY only for a TRADE word) | no BUY signals | `test_bad_data_drills.py:346`; no run today: `:378` (HOLD for every stock) | Pass |
| b1 | Brain: stale, missing, NaN or zero prices; missing NIFTY; a week without ingestion | M01 quality gate feeding `constitution.py:54-60` | never bolder; stale stocks stop new trades | `test_bad_data_drills.py:571-668` (`test_db_drill_*`, 10 drills) | Pass |
| b2 | Brain: no breadth or crash day makes the market mode NO_NEW_TRADES | `brain/fallbacks.py:100`; `modules/m10_market/judge.py:147,150` | NO_NEW_TRADES | `test_brain_m10_judge.py:52` (crash day), `:58` (VIX spike); no index history: `test_bad_data_drills.py:249`; the no-breadth branch (`fallbacks.py:100`) has no dedicated test, only the drills | Pass (no-breadth by drills only) |
| b3 | v1: market context missing or unreadable | `services/deployable.py:67,99,134-165` (`UNKNOWN_FRACTION = weak = 0.30`) | never bolder than a normal market | `test_no_trade_missing_risk.py::test_missing_market_context_*` (2 tests) | Pass (reduced, not zero) |
| b4 | v1: the newest stored candle is old | `services/engine.py:136-140` loads the newest candles and calls `evaluate` with no age check; `strategies/ml_swing.py:107` takes `as_of` from the newest bar | no buy decision from a stale bar | two strict xfails (`raises=AssertionError`) with passing fresh-candle controls: `test_a_stale_candle_must_not_feed_a_v1_buy` (a STUB strategy that says BUY to anything, so it proves the engine hands a stale bar's BUY on) and `test_the_real_ml_swing_strategy_must_not_say_buy_on_a_stale_bar` (the real `MLSwingStrategy.evaluate` on a 12-day-old bar, model and market-context loaders replaced by fixed stand-ins; it says BUY) | **GAP** |
| c1 | Drawdown of 15% or more halts new buys, with a plain reason | `services/risk.py:683-691`, `:174` `current_drawdown` | DRAWDOWN rejection | `test_portfolio_risk_layer.py:528` (`test_drawdown_brake_fires_on_todays_value_not_yesterdays_snapshot`); `test_no_trade_missing_risk.py::test_the_halt_blocks_a_buy_*` (16% blocked, 10% not) | Pass |
| c2 | Exits still work during a halt | `services/risk.py` (entries only) | exits not blocked | `test_portfolio_risk_layer.py:673` | Pass |
| c3 | Snapshot job stopped (stale snapshot) | `services/portfolio.py:350-369` `drawdown_peak` | halt still fires from the last known peak | `test_no_trade_missing_risk.py::test_a_stale_equity_snapshot_still_halts_new_entries` (40 days old) | Pass |
| c4 | No snapshot ever | `services/risk.py:190-193`; `portfolio.py:347,368` return no peak | (rule says: no more aggressive) | drawdown reads 0.0 and entries are not halted, on BOTH paths (no trial date, and the production path with `PAPER_TRIAL_START_DATE` set, via `_trial_peak`): `test_no_snapshot_at_all_*` and `test_no_snapshot_at_all_with_the_paper_trial_date_set_*` pin it, with a control (one pre-trial snapshot) where the halt fires | **Observed limit** (see below) |
| d1 | Simulation: NO_NEW_TRADES, unknown mode, or a session missing from the modes buys nothing | `simulation/ledger.py:294-296,312-313` | zero fills; each pick blocked with its reason | `test_simulation_app_rules.py:63,94` | Pass |

Re-run for this note (dev4b): `test_bad_data_drills.py`, `test_simulation_app_rules.py`, the three halt tests of
`test_portfolio_risk_layer.py` and the new file: **101 passed, 2 xfailed** (the b4 gap, as two strict xfails), with `test_brain_m10_judge.py` added.

## Gaps and limits for the owner

- **Gap b4 (one line):** the version 1 daily scan scores whatever newest candle is stored, however old, and hands its
  BUY to the order path. Expected: it should refuse a bar older than the last closed session. Not fixed (frozen engine,
  needs owner approval; see #344/#353). Defect not filed by me; the lead files it.
- **Limit c4 (one line):** with no equity snapshot ever recorded the 15% halt cannot fire (with or without the paper trial date), so a wiped snapshot table would
  silently lift the halt. A possible hardening (not applied): treat the account's starting capital as the floor peak when
  no snapshot exists. Needs the owner's approval because it touches the risk path.
- **Design b3:** unknown market context allows 30% invested instead of stopping. Say if you want it to stop instead.

## Not covered here

The Brain's practice-mode limit waiver (`services/testing_mode.py`) is checked in the #217 audit and is not re-tested. Real
brokers, live trading and production were not touched.
