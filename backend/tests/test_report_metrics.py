"""services/report_metrics.py and the four report paths (#322 slice 1).

(a) On one fixed fixture the paths give identical numbers wherever they mean the same thing.
(c) Where two paths deliberately differ (zero profit, costs, open versus closed, mode, return scale) the
    difference is named here and tested, never silently unified.
(b) is test_report_metrics_snapshot.py: every existing output is frozen there.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.db.models.trading import Position, Trade
from swing_trade_ml.services import real_report
from swing_trade_ml.services import report_metrics as rm
from swing_trade_ml.services.brain_observatory import evidence
from swing_trade_ml.services.portfolio import performance_stats, strategy_performance_stats

# The fixture and the way each path is called live with the snapshot test.
from test_report_metrics_snapshot import WINDOW, _weekly, book  # noqa: F401 (book is a fixture)

# ------------------------------------------------------------------------------------------ pure functions


def test_a_zero_trade_is_neither_a_win_nor_a_strict_loss():
    assert not rm.is_win(0.0) and not rm.is_loss(0.0)
    assert rm.win_count([5.0, 0.0, -1.0]) == 1 and rm.strict_loss_count([5.0, 0.0, -1.0]) == 1


def test_win_loss_follows_the_stored_flag_and_counts_zero_as_not_a_win():
    wl = rm.win_loss([10.0, -4.0, 0.0], [True, False, False])
    assert (wl.wins, wl.not_wins) == (1, 2)
    assert wl.win_rate == pytest.approx(1 / 3)
    assert (wl.gross_profit, wl.gross_loss, wl.profit_factor) == (10.0, 4.0, 2.5)
    assert (wl.avg_win, wl.avg_loss, wl.largest_win, wl.largest_loss) == (10.0, -2.0, 10.0, -4.0)


def test_no_losses_is_an_infinite_profit_factor_and_no_wins_an_average_of_zero():
    assert rm.win_loss([3.0], [True]).profit_factor == float("inf")
    only_losses = rm.win_loss([-3.0], [False])
    assert only_losses.avg_win == 0.0 and only_losses.largest_win == 0.0 and only_losses.profit_factor == 0.0


def test_percent_helpers():
    assert rm.percent_of(5.0, 200.0) == 2.5 and rm.percent_of(5.0, 0.0) == 0.0
    assert rm.fraction_as_percent(0.02) == 2.0
    assert rm.mean([1, 2, 4]) == pytest.approx(7 / 3) and rm.mean_numpy([1, 2, 4]) == pytest.approx(7 / 3)


# ------------------------------------------------------------------- (a) identical numbers across the paths


def _paths(db_session, book):  # noqa: F811
    real = book["report"]["summary"]
    real_closed = book["report"]["closed"]
    weekly = _weekly(db_session)
    stats = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    observatory = evidence.paper(db_session).data
    strategy = strategy_performance_stats(db_session, book["strategy"].id)
    return real, real_closed, weekly, stats, observatory, strategy


def test_all_paths_agree_on_the_same_round_trips(db_session, book):  # noqa: F811
    real, closed, weekly, stats, obs, strategy = _paths(db_session, book)
    # Money, to the paisa.
    assert real["realized_pnl"] == weekly["realized_pnl"]["net"] == round(stats["realized_pnl"], 2)
    assert real["realized_pnl"] == round(strategy["net_pnl"], 2) == round(obs["realized_pnl"], 2)
    assert real["gross_pnl"] == weekly["realized_pnl"]["gross"]
    assert real["charges"] == weekly["realized_pnl"]["charges"] == round(stats["total_charges"], 2)
    # Counts and rate.
    assert real["winning_sales"] == weekly["realized_pnl"]["wins"] == stats["winning_trades"]
    assert stats["winning_trades"] == obs["winning_trades"] == 2
    assert real["losing_sales"] == stats["losing_trades"] == 2  # no zero trade in the fixture
    assert stats["win_rate"] == strategy["win_rate"] == obs["win_rate"]
    assert stats["win_rate"] == rm.win_rate(real["winning_sales"], len(closed))
    assert stats["win_rate"] == rm.win_rate(weekly["realized_pnl"]["wins"], weekly["sells"]["trade_rows"])
    # Returns and holding time (the scales differ on purpose, see the next section).
    assert weekly["avg_sell_return_pct"] == round(stats["avg_return_pct"] * 100, 2)
    assert real["average_holding_days"] == round(stats["avg_holding_days"], 2)


def test_the_observatory_reads_the_same_numbers_as_portfolio_summary(db_session, book, client):  # noqa: F811
    summary = client.get(
        "/api/v1/portfolio/summary?mode=paper&all_time=true", headers={"X-API-Key": "test-api-key"}
    ).json()
    obs = evidence.paper(db_session).data
    for key in (
        "realized_pnl",
        "winning_trades",
        "losing_trades",
        "win_rate",
        "avg_win",
        "avg_loss",
        "profit_factor",
        "avg_return_pct",
        "total_charges",
        "expectancy",
    ):
        assert summary[key] == obs[key], key


# ------------------------------------------------------------------ (c) named differences, never unified


def _paper_trade(db_session, book, **over):  # noqa: F811
    base = db_session.query(Trade).filter(Trade.symbol == "WINA").first() or db_session.query(Trade).first()
    fields = {
        "strategy_id": book["strategy"].id,
        "instrument_id": base.instrument_id,
        "mode": TradingMode.PAPER,
        "symbol": "ZEROZ",
        "quantity": 1,
        "entry_price": 10.0,
        "exit_price": 10.0,
        "entry_at": base.entry_at,
        "exit_at": base.exit_at,
        "holding_days": 1,
        "gross_pnl": 0.0,
        "charges": 0.0,
        "net_pnl": 0.0,
        "return_pct": 0.0,
        "exit_reason": "TIME",
        "is_win": False,
    }
    fields.update(over)
    trade = Trade(**fields)
    db_session.add(trade)
    db_session.flush()
    return trade


def test_difference_zero_profit_is_a_loss_for_performance_stats_but_neither_for_the_others(db_session, book):  # noqa: F811
    before_stats = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    before_weekly = _weekly(db_session)
    _paper_trade(db_session, book)
    stats = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    weekly = _weekly(db_session)
    # performance_stats: "losing" means "not a win", so the zero trade lands there and the rate falls.
    assert stats["losing_trades"] == before_stats["losing_trades"] + 1
    assert stats["winning_trades"] == before_stats["winning_trades"]
    assert stats["win_rate"] == pytest.approx(2 / 5)
    # The weekly report counts only wins and strict losses of its own: the zero trade is not a win.
    assert weekly["realized_pnl"]["wins"] == before_weekly["realized_pnl"]["wins"]
    assert weekly["sells"]["trade_rows"] == before_weekly["sells"]["trade_rows"] + 1
    # real_report's rule, as the shared function states it: neither a win nor a loss.
    assert rm.win_count([0.0]) == 0 and rm.strict_loss_count([0.0]) == 0


def test_difference_costs_real_report_works_charges_out_from_fills_the_others_use_stored_charges(
    db_session,
    book,  # noqa: F811
):
    real_before = real_report.build_report(db_session, None, None, None)["summary"]["charges"]
    trade = db_session.query(Trade).filter(Trade.symbol == "WINA").one()
    trade.charges += 1.0
    trade.net_pnl -= 1.0
    db_session.flush()
    assert real_report.build_report(db_session, None, None, None)["summary"]["charges"] == real_before
    stats = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    assert round(stats["total_charges"] - real_before, 2) == 1.0
    assert _weekly(db_session)["realized_pnl"]["charges"] == round(real_before + 1.0, 2)


def test_difference_open_positions_are_never_part_of_realized_pnl(db_session, book):  # noqa: F811
    before = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    base = db_session.query(Trade).first()
    db_session.add(
        Position(
            strategy_id=book["strategy"].id,
            instrument_id=base.instrument_id,
            mode=TradingMode.PAPER,
            status=PositionStatus.OPEN,
            quantity=10,
            entry_price=100.0,
            current_price=110.0,
            unrealized_pnl=100.0,
            entry_at=datetime(2026, 11, 8, tzinfo=UTC),
        )
    )
    db_session.flush()
    stats = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    assert stats["realized_pnl"] == before["realized_pnl"]  # open money is not realized
    assert stats["unrealized_pnl"] == 100.0
    assert stats["total_pnl"] == stats["realized_pnl"] + stats["unrealized_pnl"]  # by name, the one sum
    weekly = _weekly(db_session)
    assert weekly["unrealized_pnl"]["amount"] == 100.0
    assert weekly["realized_pnl"]["net"] == round(before["realized_pnl"], 2)


def test_difference_mode_a_live_trade_is_in_none_of_the_paper_figures(db_session, book):  # noqa: F811
    before = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    before_weekly = _weekly(db_session)
    _paper_trade(
        db_session, book, mode=TradingMode.LIVE, symbol="LIVEL", net_pnl=500.0, gross_pnl=500.0, is_win=True
    )
    stats = performance_stats(db_session, TradingMode.PAPER, all_time=True)
    assert stats["total_trades"] == before["total_trades"] and stats["realized_pnl"] == before["realized_pnl"]
    assert _weekly(db_session)["realized_pnl"] == before_weekly["realized_pnl"]


def test_difference_return_scale_fraction_in_stats_percent_in_weekly_and_real_report(db_session, book):  # noqa: F811
    _real, closed, weekly, stats, _obs, _strategy = _paths(db_session, book)
    assert abs(stats["avg_return_pct"]) < 1  # a fraction: -0.0112 means -1.12%
    assert weekly["avg_sell_return_pct"] == round(stats["avg_return_pct"] * 100, 2)  # percent: -1.12
    stored = {t.symbol: t.return_pct for t in db_session.query(Trade).all() if t.quantity == 20}
    assert [c["pnl_pct"] for c in closed if c["symbol"] == "LOSEB"] == [round(stored["LOSEB"] * 100, 2)]
    assert WINDOW[0] < WINDOW[1]


# --------------------------------------------------------------------- what the module says about itself


def test_the_module_does_not_claim_to_be_the_only_place_and_names_what_is_not_migrated():
    doc = rm.__doc__
    assert "One place" not in doc and "worked out once" not in doc
    for not_yet in ("services/tester_paper.py", "services/beginner_views.py", "services/insights.py"):
        assert not_yet in doc, not_yet
    assert "not yet migrated" in doc.lower()


def test_the_two_decimal_rounding_difference_is_named_and_real(db_session):
    """real_report rounds every matched slice to 2 decimals before summing; the weekly report rounds a
    total once; performance_stats sums the stored values unrounded. Three sub-paisa amounts show it."""
    assert "2 decimals" in rm.__doc__ or "two decimals" in rm.__doc__
    slices = [0.004, 0.004, 0.004]
    assert round(sum(real_report._r(v) for v in slices), 2) == 0.0  # real_report: each slice rounded first
    assert (
        round(sum(slices), 2) == 0.01
    )  # a total rounded once (weekly report) or kept unrounded (performance_stats)
