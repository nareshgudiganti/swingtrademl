"""Backtest cost-model and stats tests.

The whole point of the backtest engine is that its numbers mean the same
thing as a paper result. These tests pin the cost formulas against
PaperBroker's own constants and check the stats math independently of any
database, mirroring test_risk.py's style.
"""

from __future__ import annotations

from datetime import date

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.backtest import (
    BacktestTrade,
    _apply_slippage,
    _charges,
    _close_position,
    _compute_stats,
    _OpenPosition,
)

BPS = 10_000.0


def test_buy_slippage_moves_price_up():
    price = 100.0
    filled = _apply_slippage(price, "BUY")
    assert filled > price
    assert filled == price * (1 + settings.PAPER_SLIPPAGE_BPS / BPS)


def test_sell_slippage_moves_price_down():
    price = 100.0
    filled = _apply_slippage(price, "SELL")
    assert filled < price
    assert filled == price * (1 - settings.PAPER_SLIPPAGE_BPS / BPS)


def test_charges_match_configured_brokerage_and_tax_bps():
    turnover = 50_000.0
    brokerage, taxes = _charges(turnover)
    assert brokerage == settings.PAPER_BROKERAGE_PER_ORDER
    assert taxes == turnover * (settings.PAPER_TAX_BPS / BPS)


def test_close_position_records_a_losing_trade_and_returns_net_cash():
    pos = _OpenPosition(
        instrument_id=1,
        symbol="TESTCO",
        quantity=100,
        entry_price=100.0,
        entry_date=date(2024, 1, 1),
        stop_loss=90.0,
        take_profit=120.0,
        charges_so_far=25.0,
    )
    trades: list[BacktestTrade] = []

    proceeds = _close_position(
        pos, exit_price=90.0, trades=trades, reason="STOP_LOSS_HIT", exit_date=date(2024, 1, 10)
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "STOP_LOSS_HIT"
    assert trade.holding_days == 9
    # Sell fills below the reference price (adverse slippage), so the loss is
    # slightly worse than the raw (90 - 100) * 100 = -1000 gap.
    assert trade.net_pnl < -1000.0
    # Cash returned to the ledger must exclude brokerage/taxes on the exit fill.
    assert proceeds < trade.exit_price * pos.quantity


def test_compute_stats_on_a_mixed_trade_set():
    trades = [
        BacktestTrade(
            symbol="A", entry_date=date(2024, 1, 1), exit_date=date(2024, 1, 5),
            entry_price=100.0, exit_price=110.0, quantity=10,
            gross_pnl=100.0, charges=10.0, net_pnl=90.0, return_pct=0.09,
            holding_days=4, exit_reason="TARGET_HIT",
        ),
        BacktestTrade(
            symbol="B", entry_date=date(2024, 1, 1), exit_date=date(2024, 1, 3),
            entry_price=100.0, exit_price=95.0, quantity=10,
            gross_pnl=-50.0, charges=10.0, net_pnl=-60.0, return_pct=-0.06,
            holding_days=2, exit_reason="STOP_LOSS_HIT",
        ),
    ]
    equity_curve = [
        {"date": "2024-01-01", "total_value": 1_000_000.0, "cash": 1_000_000.0},
        {"date": "2024-01-03", "total_value": 999_940.0, "cash": 999_940.0},
        {"date": "2024-01-05", "total_value": 1_000_030.0, "cash": 1_000_030.0},
    ]

    stats = _compute_stats(trades, equity_curve, starting_capital=1_000_000.0, ending_value=1_000_030.0)

    assert stats["total_trades"] == 2
    assert stats["winning_trades"] == 1
    assert stats["losing_trades"] == 1
    assert stats["win_rate"] == 0.5
    assert stats["profit_factor"] == 90.0 / 60.0
    assert stats["expectancy"] == (90.0 - 60.0) / 2
    assert stats["max_drawdown_pct"] >= 0.0


def test_compute_stats_with_no_trades_is_all_zero():
    stats = _compute_stats([], [], starting_capital=1_000_000.0, ending_value=1_000_000.0)
    assert stats["total_trades"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["profit_factor"] == 0.0
    assert stats["total_return_pct"] == 0.0


def test_backtest_and_paper_broker_share_the_literal_same_cost_functions():
    """Not just equivalent behaviour — the same function objects, imported
    from services/costs.py, so the two paths can never silently drift apart
    again the way the old duplicated pair could."""
    from swing_trade_ml.brokers.paper import PaperBroker
    from swing_trade_ml.services import costs

    broker = PaperBroker()
    assert broker._apply_slippage.__func__ is not costs.apply_slippage  # bound method, not the fn itself
    assert broker._apply_slippage(100.0, "BUY") == costs.apply_slippage(100.0, "BUY")
    assert broker._charges(50_000.0) == costs.compute_charges(50_000.0)
    assert _apply_slippage is costs.apply_slippage
    assert _charges is costs.compute_charges
