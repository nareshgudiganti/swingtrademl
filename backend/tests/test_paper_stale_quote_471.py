# ruff: noqa: E501 (long plain-English test text)
"""#471: the paper broker never fills a BUY on a stale cached quote, and a quote with no price is never stored as 0.0.

The freshness limit is the one the app already uses for a quote (services/quote_snapshot.py: STALE_AFTER_SECONDS, 15
minutes, same India day, never from the future). Paper mode only; a fresh quote fills exactly as before; no live broker,
sizing, limit or frozen file is involved.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers import paper as paper_module
from swing_trade_ml.brokers.base import OrderRequest
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.brokers.paper import PaperBroker
from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType
from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.market import Candle, Instrument, Quote
from swing_trade_ml.services import ingestion
from swing_trade_ml.services.quote_snapshot import STALE_AFTER_SECONDS

IST = ZoneInfo("Asia/Kolkata")
_TOKEN = iter(range(871_000_000, 871_100_000))


# A fixed clock, so no test depends on the hour it runs: Saturday 12:00 IST (market closed) unless a test moves it.
CLOSED_SATURDAY = datetime(2026, 11, 28, 6, 30, tzinfo=UTC)
OPEN_MONDAY = datetime(2026, 11, 30, 5, 30, tzinfo=UTC)  # Monday 11:00 IST, session open
_clock = {"now": CLOSED_SATURDAY}


@pytest.fixture(autouse=True)
def _no_live_kite(monkeypatch):
    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: False))
    _clock["now"] = CLOSED_SATURDAY
    monkeypatch.setattr(paper_module, "_utcnow", lambda: _clock["now"])


def _stock(db, symbol, *, watchlisted=False):
    inst = Instrument(
        instrument_token=next(_TOKEN),
        tradingsymbol=symbol,
        exchange="NSE",
        is_watchlisted=watchlisted,
        is_active=True,
    )
    db.add(inst)
    db.flush()
    return inst


def _quote(db, inst, price, ts):
    db.add(Quote(instrument_id=inst.id, last_price=price, ts=ts))
    db.flush()


def _close(db, inst, price, day):
    ts = datetime(day.year, day.month, day.day, tzinfo=IST)  # daily bars are stamped IST midnight
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=ts,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1000,
        )
    )
    db.flush()


def _order(symbol, side=TransactionType.BUY):
    return OrderRequest(
        tradingsymbol=symbol,
        exchange="NSE",
        transaction_type=side,
        quantity=10,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        tag="t471",
        own_funds=True,
    )


def _now():
    return _clock["now"]


def _last_day():
    return last_closed_trading_day(_now())


def test_a_fresh_quote_fills_exactly_as_before(db_session):
    inst = _stock(db_session, "Q471FRESH")
    _quote(db_session, inst, 250.0, _now() - timedelta(seconds=60))
    result = PaperBroker().place_order(_order("Q471FRESH"), db_session)
    assert result.status == OrderStatus.COMPLETE and result.filled_quantity == 10
    assert result.average_price == pytest.approx(
        250.0, rel=0.002
    )  # quote price plus the usual small slippage


def test_a_quote_at_the_freshness_limit_is_still_fresh_and_one_just_past_it_is_not(db_session):
    near = _stock(db_session, "Q471EDGE")
    _quote(db_session, near, 250.0, _now() - timedelta(seconds=STALE_AFTER_SECONDS - 5))
    assert PaperBroker().place_order(_order("Q471EDGE"), db_session).status == OrderStatus.COMPLETE
    past = _stock(db_session, "Q471PAST")
    _quote(db_session, past, 250.0, _now() - timedelta(seconds=STALE_AFTER_SECONDS + 60))
    assert PaperBroker().place_order(_order("Q471PAST"), db_session).status == OrderStatus.REJECTED


def test_a_stale_quote_is_refused_for_a_buy_with_a_stated_reason_and_nothing_is_filled(db_session):
    inst = _stock(db_session, "Q471STALE")
    _quote(db_session, inst, 500.0, _now() - timedelta(days=5))
    result = PaperBroker().place_order(_order("Q471STALE"), db_session)
    assert (
        result.status == OrderStatus.REJECTED and result.filled_quantity == 0 and result.average_price is None
    )
    assert "older than 15 minutes" in result.message and "no paper fill was made" in result.message


def test_a_stale_quote_does_not_beat_a_newer_close(db_session):
    """The freshest known price wins (the stock page's rule): a 5-day-old 500.0 quote loses to yesterday's 100.0 close."""
    inst = _stock(db_session, "Q471CLOSE")
    _close(db_session, inst, 100.0, _last_day())
    _quote(db_session, inst, 500.0, _now() - timedelta(days=5))
    assert PaperBroker()._reference_price("Q471CLOSE", "NSE", db_session) == 100.0
    result = PaperBroker().place_order(_order("Q471CLOSE"), db_session)
    assert result.status == OrderStatus.COMPLETE and result.average_price == pytest.approx(100.0, rel=0.002)


def test_a_stale_quote_newer_than_the_last_close_is_still_refused_for_a_buy(db_session):
    inst = _stock(db_session, "Q471OLDCLOSE")
    _close(db_session, inst, 100.0, _last_day() - timedelta(days=10))
    _quote(db_session, inst, 500.0, _now() - timedelta(minutes=40))
    result = PaperBroker().place_order(_order("Q471OLDCLOSE"), db_session)
    assert result.status == OrderStatus.REJECTED and "no newer close" in result.message


def test_a_quote_dated_in_the_future_is_stale(db_session):
    inst = _stock(db_session, "Q471FUTURE")
    _quote(db_session, inst, 250.0, _now() + timedelta(hours=2))
    assert PaperBroker().place_order(_order("Q471FUTURE"), db_session).status == OrderStatus.REJECTED


def test_an_exit_is_never_blocked_by_a_stale_quote_it_uses_the_freshest_known_price(db_session):
    """Refusing a SELL would leave a losing position open, which is the opposite of caution: an exit still fills."""
    inst = _stock(db_session, "Q471SELL")
    _quote(db_session, inst, 480.0, _now() - timedelta(days=3))
    sold = PaperBroker().place_order(_order("Q471SELL", TransactionType.SELL), db_session)
    assert sold.status == OrderStatus.COMPLETE and sold.average_price == pytest.approx(480.0, rel=0.002)
    inst2 = _stock(db_session, "Q471SELL2")
    _close(db_session, inst2, 100.0, _last_day())
    _quote(db_session, inst2, 480.0, _now() - timedelta(days=3))
    sold2 = PaperBroker().place_order(_order("Q471SELL2", TransactionType.SELL), db_session)
    assert sold2.average_price == pytest.approx(100.0, rel=0.002)  # the newer close, as for a buy


def test_a_zero_priced_stored_quote_is_treated_as_no_quote(db_session):
    inst = _stock(db_session, "Q471ZERO")
    _quote(db_session, inst, 0.0, _now())
    assert (
        PaperBroker().place_order(_order("Q471ZERO"), db_session).status == OrderStatus.REJECTED
    )  # no price at all
    inst2 = _stock(db_session, "Q471ZEROC")
    _close(db_session, inst2, 100.0, _last_day())
    _quote(db_session, inst2, 0.0, _now())
    result = PaperBroker().place_order(_order("Q471ZEROC"), db_session)
    assert result.status == OrderStatus.COMPLETE and result.average_price == pytest.approx(100.0, rel=0.002)


def test_with_no_quote_the_last_close_is_used_as_before(db_session):
    inst = _stock(db_session, "Q471NOQ")
    _close(db_session, inst, 100.0, _last_day())
    result = PaperBroker().place_order(_order("Q471NOQ"), db_session)
    assert result.status == OrderStatus.COMPLETE and result.average_price == pytest.approx(100.0, rel=0.002)


def test_a_live_kite_price_is_still_used_first(db_session, monkeypatch):
    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: True))
    monkeypatch.setattr(kite_broker, "get_ltp", lambda keys, db: {keys[0]: 777.0}, raising=False)
    inst = _stock(db_session, "Q471LIVE")
    _quote(db_session, inst, 500.0, _now() - timedelta(days=5))
    assert PaperBroker()._reference_price("Q471LIVE", "NSE", db_session) == 777.0


# ------------------------------------------------------------------------------- a priceless quote is never stored as 0.0


def test_a_quote_with_no_price_is_not_stored_and_does_not_overwrite_the_last_good_one(
    db_session, monkeypatch
):
    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: True))
    inst = _stock(db_session, "Q471NOPRICE", watchlisted=True)
    old = _now() - timedelta(hours=1)
    _quote(db_session, inst, 123.0, old)
    monkeypatch.setattr(
        kite_broker,
        "get_quote",
        lambda keys, db: {inst.symbol_key: {"ohlc": {"close": 100.0}}},
        raising=False,
    )
    ingestion.refresh_quotes(db_session)
    stored = db_session.scalar(select(Quote).where(Quote.instrument_id == inst.id))
    assert stored.last_price == 123.0 and stored.ts == old  # untouched, still honestly old


def test_a_quote_with_a_null_or_zero_price_is_never_a_fresh_zero(db_session, monkeypatch):
    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: True))
    a, b = _stock(db_session, "Q471NULL", watchlisted=True), _stock(db_session, "Q471ZEROP", watchlisted=True)
    monkeypatch.setattr(
        kite_broker,
        "get_quote",
        lambda keys, db: {a.symbol_key: {"last_price": None}, b.symbol_key: {"last_price": 0}},
        raising=False,
    )
    ingestion.refresh_quotes(db_session)
    assert db_session.scalars(select(Quote).where(Quote.instrument_id.in_([a.id, b.id]))).all() == []


def test_a_quote_with_a_price_is_stored_as_before(db_session, monkeypatch):
    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: True))
    inst = _stock(db_session, "Q471GOOD", watchlisted=True)
    monkeypatch.setattr(
        kite_broker,
        "get_quote",
        lambda keys, db: {inst.symbol_key: {"last_price": 321.5, "ohlc": {"close": 300.0}}},
        raising=False,
    )
    assert ingestion.refresh_quotes(db_session) >= 1
    stored = db_session.scalar(select(Quote).where(Quote.instrument_id == inst.id))
    assert stored.last_price == 321.5


# ------------------------------------------------------------------------------- review fixes (P1, P2, P3)
FRIDAY = datetime(2026, 11, 27).date()


def test_a_close_must_be_newer_by_time_not_just_by_date(db_session):
    """A quote taken AFTER Friday's 15:30 close is newer than Friday's close, even on the same date: not a newer close."""
    inst = _stock(db_session, "Q471TIME")
    _close(db_session, inst, 100.0, FRIDAY)
    _quote(db_session, inst, 500.0, datetime(2026, 11, 27, 16, 5, tzinfo=IST))  # 16:05 IST, after the close
    result = PaperBroker().place_order(_order("Q471TIME"), db_session)
    assert result.status == OrderStatus.REJECTED and "no newer close" in result.message
    # The same close IS newer than a quote taken before it.
    inst2 = _stock(db_session, "Q471TIME2")
    _close(db_session, inst2, 100.0, FRIDAY)
    _quote(db_session, inst2, 500.0, datetime(2026, 11, 27, 15, 0, tzinfo=IST))
    assert PaperBroker().place_order(_order("Q471TIME2"), db_session).average_price == pytest.approx(
        100.0, rel=0.002
    )


def test_a_buy_is_refused_while_the_market_is_open_and_the_only_price_is_a_past_close(db_session):
    """Monday 11:00, Friday's last quote and Friday's close: a past close is not a current price."""
    _clock["now"] = OPEN_MONDAY
    inst = _stock(db_session, "Q471MON")
    _close(db_session, inst, 100.0, FRIDAY)
    _quote(db_session, inst, 500.0, datetime(2026, 11, 27, 15, 20, tzinfo=IST))
    result = PaperBroker().place_order(_order("Q471MON"), db_session)
    assert result.status == OrderStatus.REJECTED and result.filled_quantity == 0
    assert "market is open" in result.message and "no paper fill was made" in result.message
    # No quote at all, only a close: the same refusal while the market is open.
    inst2 = _stock(db_session, "Q471MON2")
    _close(db_session, inst2, 100.0, FRIDAY)
    result2 = PaperBroker().place_order(_order("Q471MON2"), db_session)
    assert result2.status == OrderStatus.REJECTED and "market is open" in result2.message


def test_the_same_buy_fills_on_that_close_once_the_market_is_closed(db_session):
    inst = _stock(db_session, "Q471WKND")
    _close(db_session, inst, 100.0, FRIDAY)
    _quote(db_session, inst, 500.0, datetime(2026, 11, 27, 15, 20, tzinfo=IST))
    result = PaperBroker().place_order(_order("Q471WKND"), db_session)  # Saturday
    assert result.status == OrderStatus.COMPLETE and result.average_price == pytest.approx(100.0, rel=0.002)


def test_an_exit_still_fills_while_the_market_is_open_on_a_stale_price(db_session):
    _clock["now"] = OPEN_MONDAY
    inst = _stock(db_session, "Q471MONSELL")
    _close(db_session, inst, 100.0, FRIDAY)
    _quote(db_session, inst, 500.0, datetime(2026, 11, 27, 15, 20, tzinfo=IST))
    sold = PaperBroker().place_order(_order("Q471MONSELL", TransactionType.SELL), db_session)
    assert sold.status == OrderStatus.COMPLETE and sold.average_price == pytest.approx(100.0, rel=0.002)


def test_a_sell_on_a_stale_quote_logs_a_warning_with_the_quote_age(db_session, monkeypatch):
    seen = []
    monkeypatch.setattr(paper_module.log, "warning", lambda event, **kw: seen.append((event, kw)))
    inst = _stock(db_session, "Q471SELLLOG")
    _quote(db_session, inst, 480.0, _now() - timedelta(hours=3))
    sold = PaperBroker().place_order(_order("Q471SELLLOG", TransactionType.SELL), db_session)
    assert sold.status == OrderStatus.COMPLETE
    assert [e for e, _kw in seen if e == "paper.sell.stale_quote"], seen
    kw = next(kw for e, kw in seen if e == "paper.sell.stale_quote")
    assert kw["quote_age_minutes"] == pytest.approx(180.0) and kw["symbol"] == "Q471SELLLOG"
    seen.clear()
    fresh = _stock(db_session, "Q471SELLFRESH")
    _quote(db_session, fresh, 480.0, _now() - timedelta(minutes=2))
    PaperBroker().place_order(_order("Q471SELLFRESH", TransactionType.SELL), db_session)
    assert not [e for e, _kw in seen if e == "paper.sell.stale_quote"]


# ---- the exit side: a stale quote must never stop the exit sweep from looking at a position
def test_get_ltp_keeps_a_stale_price_so_the_exit_sweep_can_still_look(db_session):
    _clock["now"] = OPEN_MONDAY
    inst = _stock(db_session, "Q471LTP")
    _quote(db_session, inst, 480.0, _now() - timedelta(hours=2))  # stale, and no newer close on file
    assert PaperBroker().get_ltp(["NSE:Q471LTP"], db_session) == {"NSE:Q471LTP": 480.0}
    assert PaperBroker()._reference_price("Q471LTP", "NSE", db_session) == 480.0


def test_check_exits_still_checks_and_closes_a_position_on_a_stale_quote(db_session, monkeypatch):
    from swing_trade_ml.core.enums import PositionStatus
    from swing_trade_ml.db.models.trading import Position, Strategy, Trade
    from swing_trade_ml.services import execution

    _clock["now"] = OPEN_MONDAY
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **kw: None)
    inst = _stock(db_session, "Q471EXIT")
    strat = Strategy(name="s471", strategy_type="ml_swing", mode="paper", params={})
    db_session.add(strat)
    db_session.flush()
    _quote(db_session, inst, 90.0, _now() - timedelta(hours=2))  # below the stop, but two hours old
    pos = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        status=PositionStatus.OPEN,
        quantity=10,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=95.0,
        take_profit=108.0,
        highest_price=100.0,
        entry_at=_now() - timedelta(days=2),
    )
    db_session.add(pos)
    db_session.commit()
    closed = execution.check_exits(db_session)
    assert [t.exit_reason for t in closed] == ["STOP_LOSS_HIT"], closed
    assert db_session.get(Position, pos.id).status == PositionStatus.CLOSED
    assert db_session.query(Trade).filter(Trade.instrument_id == inst.id).count() == 1


def test_the_approval_live_price_is_still_the_freshest_known_but_the_buy_itself_is_refused(db_session):
    """approvals._live_price reads get_ltp: a stale price no longer reads as no price, and the order then stops at the broker with a reason."""
    from swing_trade_ml.services.brain_golive import approvals

    _clock["now"] = OPEN_MONDAY
    inst = _stock(db_session, "Q471APPR")
    _quote(db_session, inst, 480.0, _now() - timedelta(hours=2))
    assert approvals._live_price(db_session, inst) == 480.0
    result = PaperBroker().place_order(_order("Q471APPR"), db_session)
    assert result.status == OrderStatus.REJECTED and "market is open" in result.message


# ---- the tester path keeps the stated reason
def test_the_tester_buy_keeps_the_stale_price_reason(db_session, monkeypatch):
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.services import tester_paper

    monkeypatch.setattr(settings, "PAPER_TESTER_ENABLED", True)

    _clock["now"] = OPEN_MONDAY
    inst = _stock(db_session, "Q471TEST")
    _quote(db_session, inst, 480.0, _now() - timedelta(hours=2))
    db_session.commit()
    with pytest.raises(ValueError, match="no paper fill was made") as err:
        tester_paper.paper_buy(db_session, "Q471TEST", 1, "large")
    assert "No price available" not in str(err.value)
