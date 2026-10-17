"""Horizon experiments: a research ledger beside the 15-day brain trial (design rev 3).

Owner-selected picks are scored over 5 and 30 trading days from daily candles, with frozen costs and slippage,
against NIFTY, the equal-weight universe and the same stock held. Simulated only.

Isolation is a rule, checked by tests/test_experiments_isolation.py: nothing in this package imports orders,
positions, brokers, risk, execution, portfolio, strategies or the brain. It reads candles, instruments and
corporate-action events, and writes only its own tables.
"""
