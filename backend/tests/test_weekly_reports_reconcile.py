# ruff: noqa: E501 (long plain-English test text)
"""#254: the weekly report and the paper/shadow reports reconcile with the stored rows they summarise (verification
tests; nothing here changes the app).

Findings note: docs/verification/254-weekly-reports.md. Existing coverage that this file does not repeat and that the
note cites: test_weekly_paper_report.py (counting rules on plain dicts, brain slot kept apart),
test_report_metrics.py and test_report_metrics_snapshot.py (the four paths agree on the same round trips and name where
they differ on purpose), test_real_report.py and #426's tests (private real-account rows).

Here: every figure is derived from rows written to the database and compared with what a plain query of those rows says.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from swing_trade_ml.brain.lanes import h05_report
from swing_trade_ml.core.enums import TradingMode
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import weekly_paper_report as w
from swing_trade_ml.services.portfolio import performance_stats

NOW = datetime(2026, 11, 3, 5, 0, tzinfo=UTC)  # a Tuesday morning, IST: the window is Tue 27 Oct to Mon 2 Nov
START, END = date(2026, 10, 27), date(2026, 11, 2)
_TOKEN = iter(range(870_100_000, 870_200_000))


# ------------------------------------------------------------------------------- helpers


def _strategy(db, name, stype="ml_swing"):
    s = Strategy(name=name, strategy_type=stype, mode="paper", execution_mode="auto", is_active=False, params={})
    db.add(s)
    db.flush()
    return s


def _inst(db, symbol):
    inst = Instrument(instrument_token=next(_TOKEN), tradingsymbol=symbol, exchange="NSE", is_watchlisted=False)
    db.add(inst)
    db.flush()
    return inst


def _utc(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _buy(db, strat, inst, when, *, status="COMPLETE", mode="paper", position=None):
    o = Order(
        strategy_id=strat.id if strat else None, position_id=position.id if position else None,
        instrument_id=inst.id, mode=mode, transaction_type="BUY", quantity=10, status=status,
        average_price=100.0, placed_at=when,
    )
    db.add(o)
    db.flush()
    return o


def _round_trip(db, strat, inst, *, exit_at, net, charges=5.0, mode="paper", reason="TARGET_HIT", sell_status="COMPLETE"):
    """A closed position with its BUY order, SELL order and Trade row, as the engine writes them."""
    entry = exit_at - timedelta(days=2)
    pos = Position(
        strategy_id=strat.id if strat else None, instrument_id=inst.id, mode=mode, status="CLOSED", quantity=10,
        entry_price=100.0, entry_at=entry,
    )
    db.add(pos)
    db.flush()
    _buy(db, strat, inst, entry, mode=mode, position=pos)
    db.add(
        Order(
            strategy_id=strat.id if strat else None, position_id=pos.id, instrument_id=inst.id, mode=mode,
            transaction_type="SELL", quantity=10, status=sell_status, average_price=105.0, placed_at=exit_at,
        )
    )
    db.add(
        Trade(
            position_id=pos.id, strategy_id=strat.id if strat else None, instrument_id=inst.id, mode=mode,
            symbol=inst.tradingsymbol, quantity=10, entry_price=100.0, exit_price=105.0, entry_at=entry,
            exit_at=exit_at, holding_days=2, gross_pnl=net + charges, charges=charges, net_pnl=net,
            return_pct=net / 1000.0, exit_reason=reason, is_win=net > 0,
        )
    )
    db.flush()
    return pos


def _open(db, strat, inst, *, price=102.0, mode="paper", entry_at=None):
    pos = Position(
        strategy_id=strat.id if strat else None, instrument_id=inst.id, mode=mode, status="OPEN", quantity=5,
        entry_price=100.0, current_price=price, entry_at=entry_at or _utc(date(2026, 10, 20)),
    )
    db.add(pos)
    db.flush()
    return pos


def _count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


# ------------------------------------------------------------------------------- counts equal the stored rows


def test_every_count_in_the_week_equals_a_plain_query_of_the_stored_rows(db_session):
    db = db_session
    strat, inst = _strategy(db, "r254_bot"), _inst(db, "R254A")
    inside = [_utc(date(2026, 10, 28)), _utc(date(2026, 10, 30)), _utc(date(2026, 11, 2))]
    for day, net in zip(inside, (120.0, -40.0, 0.0), strict=True):  # a win, a loss, a break-even
        _round_trip(db, strat, inst, exit_at=day, net=net)
    _round_trip(db, strat, inst, exit_at=_utc(date(2026, 10, 20)), net=999.0)  # before the window
    _round_trip(db, strat, inst, exit_at=_utc(date(2026, 11, 4)), net=888.0)  # after the window
    _buy(db, strat, inst, inside[0], status="REJECTED")  # never filled: not a buy
    _buy(db, strat, inst, inside[0], status="PENDING")
    _open(db, strat, inst)
    _open(db, strat, _inst(db, "R254B"), price=98.0)
    report = w.build_report(db, NOW)
    bot = report["bot"]
    since, until = w.datetime.combine(START, w.datetime.min.time(), tzinfo=w.IST), w.datetime.combine(END + timedelta(days=1), w.datetime.min.time(), tzinfo=w.IST)
    paper = (Order.mode == TradingMode.PAPER, Order.placed_at >= since, Order.placed_at < until, Order.status == "COMPLETE")
    trade_rows = list(db.scalars(select(Trade).where(Trade.mode == "paper", Trade.exit_at >= since, Trade.exit_at < until)))
    assert bot["buys"]["orders"] == _count(db, Order, *paper, Order.transaction_type == "BUY")
    assert bot["sells"]["orders"] == _count(db, Order, *paper, Order.transaction_type == "SELL") == 3
    assert bot["sells"]["trade_rows"] == len(trade_rows) == 3
    assert bot["reconciliation"]["sell_orders_equal_trade_rows"] is True
    assert bot["realized_pnl"]["wins"] == sum(1 for t in trade_rows if t.net_pnl > 0) == 1  # break-even is not a win
    assert bot["realized_pnl"]["net"] == round(sum(t.net_pnl for t in trade_rows), 2) == 80.0
    assert bot["realized_pnl"]["charges"] == round(sum(t.charges for t in trade_rows), 2)
    assert round(bot["realized_pnl"]["gross"] - bot["realized_pnl"]["charges"], 2) == bot["realized_pnl"]["net"]
    assert bot["positions"]["open"] == _count(db, Position, Position.mode == "paper", Position.status == "OPEN") == 2
    assert bot["unrealized_pnl"]["amount"] == round((102.0 - 100.0) * 5 + (98.0 - 100.0) * 5, 2) == 0.0
    assert sum(bot["sells"]["exit_reasons"].values()) == bot["sells"]["trade_rows"]


def test_realized_and_open_profit_are_never_added_together_in_the_report(db_session):
    db = db_session
    strat, inst = _strategy(db, "r254_nosum"), _inst(db, "R254N")
    _round_trip(db, strat, inst, exit_at=_utc(date(2026, 10, 29)), net=100.0)
    _open(db, strat, inst, price=130.0)  # +150 on paper, open
    bot = w.build_report(db, NOW)["bot"]
    assert bot["realized_pnl"]["net"] == 100.0 and bot["unrealized_pnl"]["amount"] == 150.0
    assert not any("total" in key for key in bot)


# ------------------------------------------------------------------------------- date filters are by IST session


@pytest.mark.parametrize(
    "exit_at,inside",
    [
        (datetime(2026, 10, 26, 18, 29, 59, tzinfo=UTC), False),  # 23:59:59 IST on Mon 26 Oct: the week before
        (datetime(2026, 10, 26, 18, 30, 0, tzinfo=UTC), True),  # 00:00:00 IST on Tue 27 Oct: first second of the window
        (datetime(2026, 11, 2, 18, 29, 59, tzinfo=UTC), True),  # 23:59:59 IST on Mon 2 Nov: last second
        (datetime(2026, 11, 2, 18, 30, 0, tzinfo=UTC), False),  # 00:00:00 IST on Tue 3 Nov: the next week
    ],
)
def test_orders_and_trades_are_cut_at_midnight_india_time_not_midnight_utc(db_session, exit_at, inside):
    db = db_session
    strat, inst = _strategy(db, f"r254_edge_{exit_at:%d%H%M%S}"), _inst(db, f"R254E{exit_at:%d%H%M}")
    _round_trip(db, strat, inst, exit_at=exit_at, net=10.0)
    bot = w.build_report(db, NOW)["bot"]
    expected = 1 if inside else 0
    assert bot["sells"]["orders"] == bot["sells"]["trade_rows"] == expected


def test_the_week_has_seven_calendar_days_ending_yesterday_india_time():
    assert w.window(NOW) == (START, END)
    late_evening_utc = datetime(2026, 11, 2, 19, 0, tzinfo=UTC)  # already Tue 3 Nov 00:30 in India
    assert w.window(late_evening_utc) == (START, END)


# ------------------------------------------------------------------------------- what is not in a paper figure


def test_live_rows_hand_books_and_other_modes_never_reach_the_paper_report(db_session):
    db = db_session
    inst = _inst(db, "R254M")
    paper, real = _strategy(db, "r254_paper"), _strategy(db, "real_trading")
    live = Strategy(name="r254_live", strategy_type="ml_swing", mode="live", execution_mode="advisory", is_active=False, params={})
    db.add(live)
    db.flush()
    _round_trip(db, paper, inst, exit_at=_utc(date(2026, 10, 29)), net=10.0)
    _round_trip(db, live, inst, exit_at=_utc(date(2026, 10, 29)), net=500.0, mode="live")  # a live trade
    _round_trip(db, real, inst, exit_at=_utc(date(2026, 10, 29)), net=700.0)  # My Holdings / real account book, paper-mode row
    _open(db, live, inst, price=200.0, mode="live")
    report = w.build_report(db, NOW)
    for source in ("bot", "testing"):
        text = str(report[source])
        assert "r254_live" not in text and "real_trading" not in text
    assert report["bot"]["realized_pnl"]["net"] == 10.0 and report["bot"]["positions"]["open"] == 0
    assert report["testing"]["realized_pnl"]["net"] == 0.0


def test_a_row_with_no_strategy_belongs_to_the_bot_never_to_the_testing_book(db_session):
    db = db_session
    inst = _inst(db, "R254NS")
    _round_trip(db, None, inst, exit_at=_utc(date(2026, 10, 29)), net=33.0)
    report = w.build_report(db, NOW)
    assert report["bot"]["realized_pnl"]["net"] == 33.0 and report["testing"]["sells"]["orders"] == 0


def test_the_report_endpoint_is_owner_only_and_the_real_account_rows_are_not_part_of_it():
    """Cited, not re-tested (#426 covers the second-owner refusals): the route carries `require_owner`, and the report's
    own paper books exclude the hand books (previous test)."""
    from swing_trade_ml.api.deps import require_owner
    from swing_trade_ml.api.v1.endpoints.weekly_report import router

    assert any(dep.dependency is require_owner for dep in router.dependencies)


# ------------------------------------------------------------------------------- bot, testing, brain, h05 stay apart


def test_a_testing_book_trade_changes_only_the_testing_numbers(db_session):
    db = db_session
    bot_s, test_s = _strategy(db, "r254_bot2"), _strategy(db, "tester_paper", "tester_paper")
    inst = _inst(db, "R254T")
    _round_trip(db, bot_s, inst, exit_at=_utc(date(2026, 10, 29)), net=50.0)
    before = w.build_report(db, NOW)
    _round_trip(db, test_s, inst, exit_at=_utc(date(2026, 10, 30)), net=-25.0)
    after = w.build_report(db, NOW)
    assert after["bot"] == before["bot"]
    assert (before["testing"]["realized_pnl"]["net"], after["testing"]["realized_pnl"]["net"]) == (0.0, -25.0)
    assert "separate_sources" in after and not any(k.startswith("total") for k in after)


def _h05_run(db):
    run = H05Run(
        run_no=1, protocol_code="t", protocol_hash="x" * 64, status="active", start_day=date(2026, 10, 1),
        end_day=date(2027, 1, 28), models={}, universe={"groups": {}, "excluded": {}}, universe_hash="u" * 64,
    )
    db.add(run)
    db.flush()
    return run


def test_shadow_h05_rows_never_change_a_paper_figure_and_paper_rows_never_change_the_shadow_counts(db_session):
    db = db_session
    strat, inst = _strategy(db, "r254_apart"), _inst(db, "R254H")
    run = _h05_run(db)
    paper_before = w.build_report(db, NOW)["bot"]
    for day in (date(2026, 10, 28), date(2026, 10, 29)):
        db.add(H05GroupDay(run_id=run.id, signal_day=day, group="large", universe_n=10, scored_n=9, not_scored_n=1, selected_n=5, shortfall=0))
    db.add(H05Signal(run_id=run.id, signal_day=date(2026, 10, 28), symbol="SHADOW1", group="large", status="scored", selected=True,
                     label_status="evaluated", label_hit=1, label_day5=date(2026, 11, 2)))
    db.flush()
    with_shadow = w.build_report(db, NOW)
    assert with_shadow["bot"] == paper_before and with_shadow["testing"]["buys"]["orders"] == 0
    shadow_before = with_shadow["h05"]["groups"]
    _round_trip(db, strat, inst, exit_at=_utc(date(2026, 10, 29)), net=77.0)
    assert w.build_report(db, NOW)["h05"]["groups"] == shadow_before


def test_the_h05_section_counts_equal_the_stored_rows_and_the_expected_sessions_are_trading_days(db_session):
    db = db_session
    run = _h05_run(db)
    days = [date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)]  # Tue to Fri
    for day in days:
        db.add(H05GroupDay(run_id=run.id, signal_day=day, group="mid", universe_n=10, scored_n=8, not_scored_n=2, selected_n=5, shortfall=0))
    for i, hit in enumerate((1, 0, None)):
        db.add(H05Signal(run_id=run.id, signal_day=date(2026, 10, 27), symbol=f"MIDX{i}", group="mid", status="scored", selected=True,
                         label_status="evaluated" if hit is not None else "unavailable", label_hit=hit, label_day5=date(2026, 11, 2)))
    db.flush()
    out = w.h05_section(db, START, END)
    mid = out["groups"]["mid"]
    assert mid["signal_days_recorded"] == len(days) == 4 and mid["stocks_scored"] == 32 and mid["picks_made"] == 20
    assert mid["picks_matured"] == 2 and mid["picks_hit_plus_2pct"] == 1  # the pick with no stored result is not a zero
    assert out["sessions_expected_this_week"] == 5  # Tue-Fri and Mon 2 Nov; Sat 31 Oct and Sun 1 Nov are not sessions
    assert out["sessions_recorded_this_week"] == 4 and out["sessions_not_recorded"] == ["2026-11-02"]


# ------------------------------------------------------------------------------- a week with no data says so


def test_an_empty_week_says_so_in_every_part_of_the_report(db_session):
    report = w.build_report(db_session, NOW)
    for source in ("bot", "testing"):
        assert report[source]["data_status"] == "no buys or sells this week"
        assert report[source]["avg_sell_return_pct"] is None and report[source]["unrealized_pnl"]["pct_of_invested"] is None
    assert report["h05"] == {"active": False, "note": "no active h05 run"}
    assert report["brain_paper"]["before_trial"] is None
    assert report["benchmark"]["available"] is False and "NIFTY" in report["benchmark"]["reason"]


def test_the_weekly_message_for_an_empty_week_says_there_was_no_activity(db_session):
    message = w.format_message(w.build_report(db_session, NOW))
    assert "no buys or sells" in message.lower() or "no activity" in message.lower()


# ------------------------------------------------------------------------------- the one P&L definition across reports


def test_the_weekly_bot_figure_equals_portfolio_performance_stats_for_the_same_trades_without_a_brain_slot(db_session, monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", date(2026, 1, 1))
    db = db_session
    strat, inst = _strategy(db, "r254_same"), _inst(db, "R254S")
    for day, net in ((date(2026, 10, 28), 120.0), (date(2026, 10, 30), -40.0)):
        _round_trip(db, strat, inst, exit_at=_utc(day), net=net)
    bot = w.build_report(db, NOW)["bot"]
    stats = performance_stats(db, TradingMode.PAPER, bot_book_only=True)
    assert bot["realized_pnl"]["net"] == round(stats["realized_pnl"], 2) == 80.0
    assert bot["realized_pnl"]["wins"] == stats["winning_trades"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: the weekly report keeps the brain's reserved paper slot out of 'Bot' (its own book, owner rule), but "
    "performance_stats (portfolio summary, Observatory) counts the brain strategy's paper trades in the same bot book, "
    "so the two 'Bot' figures differ as soon as the brain slot has traded",
)
def test_the_bot_figure_is_the_same_in_the_weekly_report_and_the_portfolio_stats_when_the_brain_slot_has_traded(db_session, monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", date(2026, 1, 1))
    db = db_session
    strat, brain, inst = _strategy(db, "r254_bot3"), _strategy(db, "TradeMind brain", "brain"), _inst(db, "R254BR")
    _round_trip(db, strat, inst, exit_at=_utc(date(2026, 10, 29)), net=100.0)
    _round_trip(db, brain, inst, exit_at=_utc(date(2026, 10, 30)), net=700.0)
    bot = w.build_report(db, NOW)["bot"]
    stats = performance_stats(db, TradingMode.PAPER, bot_book_only=True)
    assert bot["realized_pnl"]["net"] == round(stats["realized_pnl"], 2)


# ------------------------------------------------------------------------------- the h05 section against the lane's own report


def _signal(db, run, symbol, *, repeat=False, hit=1, label_day5=date(2026, 11, 2), selected=True):
    db.add(H05Signal(run_id=run.id, signal_day=date(2026, 10, 27), symbol=symbol, group="large", status="scored", selected=selected,
                     repeat_blocked=repeat, label_status="evaluated", label_hit=hit, label_day5=label_day5))


def test_the_weekly_h05_hits_equal_the_lane_reports_counted_picks_when_no_pick_repeats(db_session):
    db = db_session
    run = _h05_run(db)
    _signal(db, run, "L1", hit=1)
    _signal(db, run, "L2", hit=0)
    db.add(H05GroupDay(run_id=run.id, signal_day=date(2026, 10, 27), group="large", universe_n=10, scored_n=8, not_scored_n=2, selected_n=2, shortfall=0))
    db.flush()
    weekly = w.h05_section(db, START, END)["groups"]["large"]
    lane = h05_report.build_report(db, now=NOW)["runs"][0]["groups"]["large"]["endpoint_label"]["counted_picks"]
    assert (weekly["picks_matured"], weekly["picks_hit_plus_2pct"]) == (lane["n"], round(lane["hit_rate"] * lane["n"])) == (2, 1)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: the weekly report counts every selected pick that matured, repeat-blocked ones included; the lane's own report "
    "deliberately leaves repeat-blocked picks out of its counted picks, so the same week gives two different hit counts",
)
def test_a_repeat_blocked_pick_is_counted_the_same_way_in_the_weekly_report_and_the_lane_report(db_session):
    db = db_session
    run = _h05_run(db)
    _signal(db, run, "L1", hit=1)
    _signal(db, run, "L2", hit=1, repeat=True)  # picked again within the repeat window: not a counted pick in the lane
    db.add(H05GroupDay(run_id=run.id, signal_day=date(2026, 10, 27), group="large", universe_n=10, scored_n=8, not_scored_n=2, selected_n=2, shortfall=0))
    db.flush()
    weekly = w.h05_section(db, START, END)["groups"]["large"]
    lane = h05_report.build_report(db, now=NOW)["runs"][0]["groups"]["large"]["endpoint_label"]["counted_picks"]
    assert weekly["picks_matured"] == lane["n"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: the weekly report's h05 event list has a lower bound (signal day >= week start) but no upper bound, so a "
    "report built for an earlier week also lists events from later weeks",
)
def test_the_h05_events_listed_for_a_week_are_that_weeks_only(db_session):
    db = db_session
    run = _h05_run(db)
    db.add(H05Event(run_id=run.id, signal_day=date(2026, 10, 28), kind="missed_session", detail="in the week"))
    db.add(H05Event(run_id=run.id, signal_day=date(2026, 11, 20), kind="missed_session", detail="three weeks later"))
    db.flush()
    days = {e["signal_day"] for e in w.h05_section(db, START, END)["events"]}
    assert days == {"2026-10-28"}
