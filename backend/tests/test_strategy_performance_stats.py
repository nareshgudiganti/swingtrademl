"""strategy_performance_stats() — per-strategy win rate for the Strategies
tab. See docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5b."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy, Trade
from swing_trade_ml.services.portfolio import strategy_performance_stats


def _instrument(db_session, tradingsymbol="TEST") -> Instrument:
    inst = Instrument(
        instrument_token=hash(tradingsymbol) % 1_000_000,
        tradingsymbol=tradingsymbol,
        exchange="NSE",
        is_watchlisted=True,
    )
    db_session.add(inst)
    db_session.flush()
    return inst


def _strategy(db_session, name="test_strategy") -> Strategy:
    strat = Strategy(name=name, strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    return strat


def _trade(db_session, *, strategy_id, instrument_id, is_win, net_pnl, exit_at) -> Trade:
    trade = Trade(
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        mode="paper",
        symbol="TEST",
        quantity=10,
        entry_price=100.0,
        exit_price=110.0 if is_win else 90.0,
        entry_at=exit_at - timedelta(days=5),
        exit_at=exit_at,
        holding_days=5,
        gross_pnl=net_pnl,
        charges=0.0,
        net_pnl=net_pnl,
        return_pct=net_pnl / 1000,
        is_win=is_win,
    )
    db_session.add(trade)
    db_session.flush()
    return trade


def test_no_trades_returns_zeroed_stats(db_session):
    strat = _strategy(db_session)
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat.id)

    assert stats == {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}


def test_win_rate_and_profit_factor(db_session):
    strat = _strategy(db_session)
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=200.0, exit_at=now)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=False, net_pnl=-100.0, exit_at=now)
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat.id)

    assert stats["trades"] == 3
    assert stats["win_rate"] == 2 / 3
    assert stats["profit_factor"] == 3.0  # 300 gross profit / 100 gross loss
    assert stats["net_pnl"] == 200.0


def test_since_filters_out_older_trades(db_session):
    strat = _strategy(db_session)
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now - timedelta(days=100))
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=False, net_pnl=-50.0, exit_at=now - timedelta(days=5))
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat.id, since=now - timedelta(days=30))

    assert stats["trades"] == 1
    assert stats["win_rate"] == 0.0


def test_a_different_strategys_trades_are_excluded(db_session):
    strat_a = _strategy(db_session, name="strategy_a")
    strat_b = _strategy(db_session, name="strategy_b")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    _trade(db_session, strategy_id=strat_a.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    _trade(db_session, strategy_id=strat_b.id, instrument_id=inst.id, is_win=False, net_pnl=-100.0, exit_at=now)
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat_a.id)

    assert stats["trades"] == 1
    assert stats["win_rate"] == 1.0
