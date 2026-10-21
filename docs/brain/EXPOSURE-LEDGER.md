# Exposure ledger — which dates have been looked at

**Why this exists (audit F-18).** A test period only proves something if nobody looked at its results
before the test. Once results from a period have been seen, or used to choose a model, input, rule or
threshold, that period is **development data** for good. This file records every such use, so a clean
("held-out") period can be named honestly.

**Rule for adding to it.** Before an experiment, add one row: the dates, what was looked at, and what it
decided. Add the row even if the result was "no change". Never delete a row.

Dates are IST trading days. "Outcomes" means trade results (did a pick hit target or stop).

## Local data (development database)

Local daily candles: 2021-08 to **2026-09-07** for the 49 watchlist stocks (306 stocks in all).
INDIA VIX and 16 NIFTY sector indices run to 2026-09-09 (context only, no stock outcomes).

| Dates | Looked at | Used for / decided | Date of use | Source |
|---|---|---|---|---|
| 2021-08 to 2026-09 (all history) | Model training, features, M04 situation labels, M05 memory, M12 setups and delivery rules | Built the models and rules; M12 "breakdown" kept out of avoid rules | Sept – Oct 2026 | `ml/train.py`, `docs/brain/evidence/m04_*.py`, `m05_*.py`, `m12_*.py` |
| 2023-05 to 2025-04 | 5-fold walk-forward of the barrier label (hit rate, AUC per fold) | Chose the +8% / -4% / 15-day label (already the settled rule) | 2026-10-08 | `retrain_real_question_20261008.md` |
| **2023-07-01 to 2025-01-31** | **Frozen walk-forward confirmation (wf-protocol-v1), run once** | **Verdict: fail on skill and on profit.** Period is now spent. | 2026-10-12 | `wf_v1/` |
| 2024-08 to 2026-08 (five periods) | Extra inputs (delivery %, ranks) and market-mood tests | Decided **not** to add those inputs | 2026-10-12 | `input_and_regime_spike_2026-10-12.md` |
| 2024-08 to 2026-08 (five periods) | Buying after weakness (Experiment A) | Nothing adopted (inside the error) | 2026-10-12 | `weakness_experiment_2026-10-12.md` |
| 2025-02-03 to 2025-06-30 | Horizon grid (15 target/stop/holding settings) | Confirmed +8 / -4 / 15 days as least bad; nothing changed | 2026-10-12 | `horizon_grid_2025-02-03_*` |
| 2025-08-01 to 2025-12-31 | Horizon grid | Same | 2026-10-12 | `horizon_grid_2025-08-01_*` |
| 2026-05-01 to 2026-08-14 | Horizon grid | Same | 2026-10-12 | `horizon_grid_2026-05-01_*` |
| 2025-02-01 to 2026-08-15 | Ranking diagnostics (does the score rank stocks) | Found no ranking; the 0.8+ score band looked positive (after looking, so not evidence) | 2026-10-12 | `ranking_diag/` |
| 2025-10-01 to 2026-08-15 | First walk-forward; score reliability | Display of "what a score really meant" on idea cards | 2026-10-11 / 12 | `walk_forward_2025-10-01_*`, `score_reliability*` |
| 2025-10-01 to 2026-09-17 | Portfolio replay of walk-forward picks | Drawdown policy comparison; 15% halt kept | 2026-10-12 | `portfolio_replay_*` |
| 2025-11-02 to 2026-08-16 | Calibrated model reliability (held-out window of that training run) | Calibration shown for mid and small caps | 2026-10-09 | `real_question_calibrated_models_20261009.md` |
| 2026-07-13 to 2026-08-14 | As-of brain replay; trial-journal replay demo | Model picks no better than random; tool demo only | 2026-10-11 / 13 | `asof_replay_*`; audit session |
| 2021-08 to 2026-08-14 (49 stocks) | Label vs next-open entry agreement (F-06) | No change; effect small | 2026-10-13 | `AUDIT-2026-10-13.md` F-06 |
| 2021-08 to 2026-09 (306 stocks) | Large one-day moves (F-07) | Classification only; no rule changed | 2026-10-13 | `AUDIT-2026-10-13.md` F-07 |

**Conclusion for local data:** every period up to 2026-09-07 is development data. There is no untouched
local period.

## Production data (only on the server)

Prod candles continue to the latest trading day (2026-10-12 when this was written).

| Dates | Looked at | Used for / decided | Date of use | Source |
|---|---|---|---|---|
| 2026-09-25 to 2026-10-09 | Brain decisions and their outcomes (519 scored); v1 ideas since 09-28 (121) | Found the zero-ideas bug and the tester-book bug; owner decisions on top 5 a day and sectors | 2026-10-09 | memory: two-week review; `EXPERT-TRADER-PLAN.md` |
| 2026-10-13 | Prod configuration only: active models, risk limits, account counts | Audit findings F-02, F-11, F-17; no outcomes seen | 2026-10-13 | `AUDIT-2026-10-13.md` |
| 2026-10-14 onward (prod, forward trial) | Trial-period results were DISPLAYED from ~2026-10-15/16: Observatory 'Results this month' (`/brain/observatory/outcomes`) and the daily check record's trial section (hit rate, average result, edge). Whether anyone looked: UNKNOWN | Nothing decided. Recorded so the trial is not assumed fully blind; results to be sealed (amendment 1, A4) | 2026-10-21 | amendment 1; owner decision 2026-10-21 |

## What is still clean

| Period | Status | Why |
|---|---|---|
| 2026-09-09 to 2026-09-24 (prod) | **Probably clean for stock outcomes**, not certain | No recorded look at outcomes. But ideas made on these days finish inside 09-25 to 10-09, which was reviewed, so some of their results were seen indirectly. Treat as **not clean**. |
| 2026-09-25 to 2026-10-09 (prod) | **Not clean** | Outcomes reviewed on 2026-10-09. |
| **2026-10-14 onward (prod)** | **Clean today** | Nothing looked at yet. This is where the forward practice trial and any hold-out should start. |

2026-10-21: exposure of the trial period since ~15–16 Oct is UNKNOWN (see Production data); treat as
possibly seen until the owner says otherwise.

**Decided (owner, 2026-10-13):** the forward trial and "Hold-out A" (layer-2 draft, section 4) start on
**2026-10-14**, not 2026-09-09. The trial journal is run as
`python -m swing_trade_ml.brain.trial_journal --from 2026-10-14`. Anyone who looks at results from that period before the planned evaluation must add a row
here, and that stretch then becomes development data.
