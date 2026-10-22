# Costs check, October 2026

Checked on 2026-10-17 against Zerodha's published charges page (zerodha.com/charges, equity delivery column).
Nothing in the app was changed. `backend/tests/test_costs_audit.py` now pins today's numbers, so any later change shows up as a failing test.

**Bottom line:** every number we use is equal to or slightly higher than what Zerodha publishes. That is the cautious direction. The gaps are pennies to under one rupee per trade.

## What Zerodha publishes (delivery)

Brokerage 0. Tax on buy and sell (STT) 0.1% each. Exchange charge 0.00307%. SEBI fee 10 rupees per crore. Stamp duty 0.015% on buy only. GST 18% on the exchange and SEBI charges. Depository (DP) fee 15.34 rupees per stock sold (any quantity).

Adding these up: buy about 11.874 bps, sell about 10.374 bps (1 bps = 0.01%).

## Buy leg

| Item | Our number | Zerodha | Diff on Rs 40,000 | Diff on Rs 1,00,000 | Errs |
|---|---|---|---|---|---|
| Percentage charges | 11.9 bps | about 11.874 bps | +Rs 0.10 | +Rs 0.26 | Too high (cautious) |
| Brokerage | 0 | 0 | 0 | 0 | Equal |

## Sell leg

| Item | Our number | Zerodha | Diff on Rs 40,000 | Diff on Rs 1,00,000 | Errs |
|---|---|---|---|---|---|
| Percentage charges | 10.4 bps | about 10.374 bps | +Rs 0.10 | +Rs 0.26 | Too high (cautious) |
| DP fee (flat) | Rs 15.93 | Rs 15.34 | +Rs 0.59 | +Rs 0.59 | Too high (cautious) |
| Brokerage | 0 | 0 | 0 | 0 | Equal |

Note: our config comment lists the exchange charge as 0.297 bps; Zerodha now shows 0.307 bps. The 11.9 / 10.4 rounding still covers it. The earlier note of "11.862 vs 11.9" used the old 0.297 figure.

## Slippage

We assume 5 bps (0.05%) per leg, both buy and sell. This is an assumption about fill prices, not a charge anyone publishes. Rs 20 on a Rs 40,000 trade, Rs 50 on Rs 1,00,000, each way.

## Where costs are used

- Paper trades: `services/execution.py` (via the paper broker `brokers/paper.py`).
- Real report: `services/real_report.py` (same cost function, checked by a test).
- Trial journal scoring: `brain/replay_scoring.py` (`strict_score`).
- Also: backtest, risk sizing, brain money block (`m08_decide/money.py`), brain portfolio simulation, observatory baselines, tester paper.

## Not checked

Zerodha can change these numbers. Re-check this page every few months. Rates for other segments (intraday, F&O) are irrelevant: the app trades delivery only.
