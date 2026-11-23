"""Date filters of the reports run in SQL, and what still loads full history on purpose (#322 slice 2).

How it is proven: rows are written, the session's identity map is cleared, then each report is built while
the ORM counts the rows it really loads (the model "load" event) and the SQL it emits is recorded. A row
outside the date window that is NOT needed for correctness must never be loaded.

Full history is loaded on purpose, by definition, where the figure needs it:
  * real_report: a sale in the period is matched first-bought-first-sold against buys from any earlier
    time, so fills from before the period start are loaded. Fills AFTER the period end cannot change an
    earlier match and are not loaded.
  * performance_stats (behind the Observatory's paper evidence and /portfolio/summary): top-ups before
    the trial (opening equity) and the open positions (a state, not a date) are read in full; trades and
    snapshots are bounded by the trial start in SQL.
  * weekly h05 section: "picks made so far" and "matured so far" are all-time counts by their own
    definition.
IST day edges are tested at 00:00 IST and at the 18:30 UTC stamp (= 00:00 IST the next day).
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, event

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.db.models.lanes import H05GroupDay
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import real_report
from swing_trade_ml.services import weekly_paper_report as w
from swing_trade_ml.services.brain_observatory import evidence

IST = ZoneInfo("Asia/Kolkata")


@contextmanager
def watching(db_session, *models):
    """Clear the identity map, then count rows loaded per model and record the SQL emitted."""
    db_session.flush()
    db_session.expunge_all()
    loaded: Counter[str] = Counter()
    statements: list[tuple[str, object]] = []

    def on_load(target, _context):
        loaded[type(target).__name__] += 1

    def on_execute(_conn, _cursor, statement, parameters, _context, _executemany):
        statements.append((statement, parameters))

    for model in models:
        event.listen(model, "load", on_load)
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield loaded, statements
    finally:
        for model in models:
            event.remove(model, "load", on_load)
        event.remove(engine, "before_cursor_execute", on_execute)


def sql_of(statements, table: str) -> list[str]:
    return [s for s, _ in statements if f"FROM {table}" in s]


# ------------------------------------------------------------------------------------------ real_report


def _fill(n, symbol, side, qty, price, moment):
    return BrokerFill(
        trade_id=f"sqlf-{n}", symbol=symbol, side=side, quantity=qty, price=price, executed_at=moment
    )


def _ist(day: date, hh=10, mm=30, ss=0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=IST)


@pytest.fixture()
def fills(db_session):
    db_session.execute(delete(BrokerFill))
    rows = [
        _fill(1, "AAA", "BUY", 10, 100.0, _ist(date(2026, 10, 1))),  # history: needed to match the sale below
        _fill(2, "AAA", "SELL", 4, 110.0, _ist(date(2026, 11, 3))),  # in the period
        _fill(3, "BBB", "BUY", 5, 50.0, _ist(date(2026, 11, 4))),
        _fill(4, "BBB", "SELL", 5, 55.0, _ist(date(2026, 11, 5), 23, 59, 59)),  # last second of the period
        _fill(5, "CCC", "BUY", 7, 10.0, datetime(2026, 11, 5, 18, 30, 0, tzinfo=UTC)),  # 00:00 IST on the 6th
        _fill(6, "AAA", "SELL", 6, 120.0, _ist(date(2026, 11, 20))),  # long after the period
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


PERIOD = (date(2026, 11, 3), date(2026, 11, 5))


def test_real_report_loads_no_fill_after_the_period_end(db_session, fills):
    with watching(db_session, BrokerFill) as (loaded, statements):
        report = real_report.build_report(db_session, *PERIOD, None)
    assert (
        loaded["BrokerFill"] == 4
    )  # fills 1-4; the one at 00:00 IST on the 6th and the one on the 20th stay out
    assert any("executed_at <" in s for s in sql_of(statements, "broker_fills"))
    assert [f["symbol"] for f in report["fills"]] == ["BBB", "BBB", "AAA"]  # period fills only, newest first


def test_real_report_still_loads_history_before_the_start_because_matching_needs_it(db_session, fills):
    """The sale on 3 Nov is matched to the buy of 1 Oct: that buy is loaded and the sale has its profit."""
    with watching(db_session, BrokerFill) as (loaded, _statements):
        report = real_report.build_report(db_session, date(2026, 11, 3), date(2026, 11, 3), None)
    assert loaded["BrokerFill"] >= 2  # the 1 Oct buy and the 3 Nov sale
    assert [c["symbol"] for c in report["closed"]] == ["AAA"] and report["unmatched_sales"] == []
    assert report["closed"][0]["buy_price"] == 100.0 and report["closed"][0]["sell_price"] == 110.0


def test_real_report_filtered_numbers_equal_the_unfiltered_ones_cut_to_the_period(db_session, fills):
    full = real_report.build_report(db_session, None, None, None)
    cut = real_report.build_report(db_session, *PERIOD, None)

    def inside(moment):
        return PERIOD[0] <= moment.astimezone(IST).date() <= PERIOD[1]

    assert cut["closed"] == [c for c in full["closed"] if inside(c["sell_date"])]
    assert cut["fills"] == [f for f in full["fills"] if inside(f["executed_at"])]
    assert cut["summary"]["realized_pnl"] == round(sum(c["net_pnl"] for c in cut["closed"]), 2)
    assert cut["records"] == full["records"]  # the totals of the whole record are all-time by definition


@pytest.mark.parametrize(
    ("moment", "period", "inside"),
    [
        (
            _ist(date(2026, 11, 5), 0, 0, 0),
            (date(2026, 11, 5), date(2026, 11, 5)),
            True,
        ),  # 00:00 IST: the 5th
        (_ist(date(2026, 11, 4), 23, 59, 59), (date(2026, 11, 5), date(2026, 11, 5)), False),
        (
            datetime(2026, 11, 4, 18, 29, 59, tzinfo=UTC),
            (date(2026, 11, 4), date(2026, 11, 4)),
            True,
        ),  # 23:59:59 IST
        (datetime(2026, 11, 4, 18, 29, 59, tzinfo=UTC), (date(2026, 11, 5), date(2026, 11, 5)), False),
        (
            datetime(2026, 11, 4, 18, 30, 0, tzinfo=UTC),
            (date(2026, 11, 5), date(2026, 11, 5)),
            True,
        ),  # candle stamp
        (datetime(2026, 11, 4, 18, 30, 0, tzinfo=UTC), (date(2026, 11, 4), date(2026, 11, 4)), False),
    ],
)
def test_real_report_ist_day_edges(db_session, moment, period, inside):
    db_session.execute(delete(BrokerFill))
    db_session.add_all([_fill(1, "EDGE", "BUY", 1, 10.0, moment)])
    db_session.flush()
    report = real_report.build_report(db_session, *period, None)
    assert report["summary"]["buy_count"] == (1 if inside else 0)
    assert len(report["fills"]) == (1 if inside else 0)


# --------------------------------------------------------------------------------------- weekly report


@pytest.fixture()
def book(db_session):
    inst = Instrument(instrument_token=994_401, tradingsymbol="SQLWK", exchange="NSE", is_watchlisted=False)
    strat = Strategy(
        name="sql_bot",
        strategy_type="ml_swing",
        mode="paper",
        execution_mode="auto",
        is_active=False,
        params={},
    )
    db_session.add_all([inst, strat])
    db_session.flush()
    pos = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        status="CLOSED",
        quantity=1,
        entry_price=100.0,
        entry_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    db_session.add(pos)
    db_session.flush()
    return inst, strat, pos


WEEK = (date(2026, 10, 27), date(2026, 11, 2))
# (label, stamp, belongs to the week)
STAMPS = [
    ("23:59:59 IST the day before", datetime(2026, 10, 26, 18, 29, 59, tzinfo=UTC), False),
    ("00:00 IST on the first day (18:30 UTC stamp)", datetime(2026, 10, 26, 18, 30, 0, tzinfo=UTC), True),
    ("23:59:59 IST on the last day", datetime(2026, 11, 2, 18, 29, 59, tzinfo=UTC), True),
    ("00:00 IST the day after (18:30 UTC stamp)", datetime(2026, 11, 2, 18, 30, 0, tzinfo=UTC), False),
    ("a week later", datetime(2026, 11, 10, 6, 0, 0, tzinfo=UTC), False),
    ("a month earlier", datetime(2026, 9, 26, 6, 0, 0, tzinfo=UTC), False),
]


def _seed(db_session, book):
    inst, strat, pos = book
    db_session.execute(delete(Trade))
    db_session.execute(delete(Order))
    for _label, stamp, _inside in STAMPS:
        db_session.add(
            Order(
                strategy_id=strat.id,
                position_id=pos.id,
                instrument_id=inst.id,
                mode="paper",
                transaction_type="SELL",
                quantity=1,
                status="COMPLETE",
                average_price=105.0,
                placed_at=stamp,
            )
        )
        db_session.add(
            Trade(
                position_id=pos.id,
                strategy_id=strat.id,
                instrument_id=inst.id,
                mode="paper",
                symbol="SQLWK",
                quantity=1,
                entry_price=100.0,
                exit_price=105.0,
                entry_at=stamp - timedelta(days=2),
                exit_at=stamp,
                holding_days=2,
                gross_pnl=5.0,
                charges=1.0,
                net_pnl=4.0,
                return_pct=0.04,
                exit_reason="TARGET_HIT",
                is_win=True,
            )
        )
    db_session.flush()


def test_weekly_collect_loads_only_the_weeks_orders_and_trades(db_session, book):
    _seed(db_session, book)
    inside = sum(1 for _l, _s, ok in STAMPS if ok)
    with watching(db_session, Order, Trade) as (loaded, statements):
        books = w.collect(db_session, *WEEK)
    assert (loaded["Order"], loaded["Trade"]) == (inside, inside)
    assert any("placed_at <" in s for s in sql_of(statements, "orders"))
    assert any("exit_at <" in s for s in sql_of(statements, "trades"))
    out = w.summarise_book(**books["bot"], start=WEEK[0], end=WEEK[1])
    assert out["sells"]["orders"] == inside and out["sells"]["trade_rows"] == inside


@pytest.mark.parametrize(("label", "stamp", "belongs"), STAMPS)
def test_weekly_ist_day_edges(db_session, book, label, stamp, belongs):
    inst, strat, pos = book
    db_session.execute(delete(Order))
    db_session.add(
        Order(
            strategy_id=strat.id,
            position_id=pos.id,
            instrument_id=inst.id,
            mode="paper",
            transaction_type="BUY",
            quantity=1,
            status="COMPLETE",
            average_price=100.0,
            placed_at=stamp,
        )
    )
    db_session.flush()
    books = w.collect(db_session, *WEEK)
    out = w.summarise_book(**books["bot"], start=WEEK[0], end=WEEK[1])
    assert out["buys"]["orders"] == (1 if belongs else 0), label


def test_weekly_h05_group_days_are_filtered_in_sql_but_all_time_pick_counts_stay_full(db_session):
    from test_weekly_paper_report import _h05_world  # sibling import: the same small h05 world

    _h05_world(db_session)  # group days on 2 Nov and 3 Nov, one scored pick per group
    with watching(db_session, H05GroupDay) as (loaded, _statements):
        out = w.h05_section(db_session, date(2026, 11, 3), date(2026, 11, 3))
    assert loaded["H05GroupDay"] == 3  # the 3 Nov rows only, not the 2 Nov ones
    assert all(g["signal_days_recorded"] == 1 for g in out["groups"].values())
    # All-time by definition: the pick made on 2 Nov is still counted in the "so far" status.
    assert all(
        "picks matured" in g["outcomes_status"] or "no outcomes yet" in g["outcomes_status"]
        for g in out["groups"].values()
    )


# -------------------------------------------------------------- Observatory: paper evidence (already SQL)


def test_paper_evidence_bounds_trades_by_the_trial_start_in_sql(db_session, book, monkeypatch):
    """No change was needed: performance_stats already puts the trial window in the query. This proves it."""
    inst, strat, pos = book
    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", date(2026, 11, 1))
    db_session.execute(delete(Trade))
    for n, moment in enumerate(
        [
            datetime(2026, 9, 1, 6, tzinfo=UTC),
            datetime(2026, 10, 15, 6, tzinfo=UTC),  # before the trial
            datetime(2026, 11, 3, 6, tzinfo=UTC),
            datetime(2026, 11, 4, 6, tzinfo=UTC),
        ]  # inside it
    ):
        db_session.add(
            Trade(
                position_id=pos.id,
                strategy_id=strat.id,
                instrument_id=inst.id,
                mode="paper",
                symbol=f"T{n}",
                quantity=1,
                entry_price=100.0,
                exit_price=105.0,
                entry_at=moment - timedelta(days=1),
                exit_at=moment,
                holding_days=1,
                gross_pnl=5.0,
                charges=1.0,
                net_pnl=4.0,
                return_pct=0.04,
                exit_reason="TARGET_HIT",
                is_win=True,
            )
        )
    db_session.add(
        Position(
            strategy_id=strat.id,
            instrument_id=inst.id,
            mode="paper",
            status=PositionStatus.OPEN,
            quantity=1,
            entry_price=100.0,
            current_price=101.0,
            entry_at=datetime(2026, 11, 2, tzinfo=UTC),
        )
    )
    db_session.flush()
    with watching(db_session, Trade, Position) as (loaded, statements):
        data = evidence.paper(db_session).data
    assert loaded["Trade"] == 2 and data["total_trades"] == 2  # the two trial trades only
    assert any("trades.exit_at >=" in s for s in sql_of(statements, "trades"))
    # Open positions are a state, not a date: read in full by definition, with no date bound in the query.
    assert loaded["Position"] >= 1
    conditions = [s.split("WHERE", 1)[1] for s in sql_of(statements, "positions") if "WHERE" in s]
    assert conditions and not any("positions.entry_at" in c for c in conditions)
    assert data["mode"] == TradingMode.PAPER


def test_real_report_survives_the_largest_possible_end_date(db_session, fills):
    """end + 1 day would overflow at date.max: no upper bound is needed then, so none is sent."""
    with watching(db_session, BrokerFill) as (loaded, statements):
        report = real_report.build_report(db_session, None, date.max, None)
    assert loaded["BrokerFill"] == len(fills)
    assert not any("executed_at <" in s for s in sql_of(statements, "broker_fills"))
    assert report["summary"]["buy_count"] + report["summary"]["sell_count"] == len(fills)
