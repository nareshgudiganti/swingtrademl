"""ps4: how realistic were the recorded fill prices? (services/brain_observatory/fills.py)"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from swing_trade_ml.core.enums import OrderStatus
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Order
from swing_trade_ml.services.brain_observatory import fills, pack

MON, TUE, SAT, NEXT_MON = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 10), date(2026, 1, 12)
BARS = {
    MON: fills.Bar(open=100.0, high=104.0, low=99.0, close=103.0),  # typical price 102
    TUE: fills.Bar(open=105.0, high=106.0, low=101.0, close=102.0),
    NEXT_MON: fills.Bar(open=98.0, high=99.0, low=95.0, close=96.0),
}


def _at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=IST)


def _fill(when: datetime, price: float, side: str = "BUY", mode: str = "paper") -> fills.Fill:
    return fills.Fill(order_id=1, symbol="X", mode=mode, side=side, filled_at=when, price=price)


def test_a_buy_in_market_hours_is_measured_against_the_days_typical_price():
    r = fills.judge(_fill(_at(MON, 11), 101.0), BARS)
    assert r["kind"] == "in_hours" and r["reference"] == 102.0
    assert r["better_by_bps"] == pytest.approx(98.0, abs=0.1)  # bought 1 below 102: flatters by ~0.98%
    assert r["outside_range"] is False


def test_a_price_outside_the_days_range_is_flagged_as_impossible():
    r = fills.judge(_fill(_at(MON, 11), 98.0), BARS)  # the day's low was 99
    assert r["outside_range"] is True


def test_a_buy_after_the_close_is_measured_against_the_next_open():
    """The paper broker fills after-hours orders at the last close (103); a real order meets TUE's 105."""
    r = fills.judge(_fill(_at(MON, 20), 103.0), BARS)
    assert (r["kind"], r["reference_day"], r["reference"]) == ("after_hours", TUE.isoformat(), 105.0)
    assert r["better_by_bps"] == pytest.approx(190.5, abs=0.1)
    assert r["outside_range"] is None


def test_before_the_open_on_a_trading_day_uses_that_days_open():
    r = fills.judge(_fill(_at(TUE, 8), 104.0), BARS)
    assert (r["kind"], r["reference_day"]) == ("after_hours", TUE.isoformat())


def test_a_weekend_fill_uses_the_next_sessions_open():
    r = fills.judge(_fill(_at(SAT, 12), 96.0, side="SELL"), BARS)
    assert r["reference_day"] == NEXT_MON.isoformat()
    # sold at 96 while the next real price was 98: the record is WORSE than reality, below zero
    assert r["better_by_bps"] == pytest.approx(-204.1, abs=0.1)


def test_no_bar_means_no_score_not_a_guess():
    r = fills.judge(_fill(_at(date(2026, 1, 7), 11), 100.0), BARS)
    assert r["better_by_bps"] is None and r["reference"] is None


def test_paper_and_real_orders_are_never_mixed():
    rows = [
        fills.judge(_fill(_at(MON, 11), 101.0), BARS),
        fills.judge(_fill(_at(MON, 20), 103.0), BARS),
        fills.judge(_fill(_at(MON, 11), 102.5, mode="live"), BARS),
    ]
    s = fills.summarise(rows)
    assert set(s) == {"paper", "live"}
    assert s["paper"]["all"]["fills"] == 2 and s["live"]["all"]["fills"] == 1
    assert s["paper"]["in_hours"]["fills"] == 1 and s["paper"]["after_hours"]["fills"] == 1


# --- database: the loader and the monthly pack ------------------------------------------------


def test_the_monthly_pack_reports_fill_quality_from_stored_orders(db_session):
    inst = Instrument(instrument_token=616161, tradingsymbol="FILLX", exchange="NSE", is_watchlisted=False)
    db_session.add(inst)
    db_session.flush()
    for d, b in BARS.items():
        db_session.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=datetime.combine(d, time(0, 0), tzinfo=IST),
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=1000,
            )
        )
    for when, price, status in (
        (_at(MON, 11), 101.0, OrderStatus.COMPLETE),
        (_at(MON, 20), 103.0, OrderStatus.COMPLETE),
        (_at(MON, 12), 100.0, OrderStatus.REJECTED),  # never filled: left out
    ):
        db_session.add(
            Order(
                instrument_id=inst.id,
                mode="paper",
                transaction_type="BUY",
                quantity=1,
                filled_quantity=1,
                average_price=price,
                status=status,
                placed_at=when,
                filled_at=when,
            )
        )
    db_session.flush()

    got = fills.fill_quality(db_session, date(2026, 1, 1), date(2026, 1, 31))
    paper = got["summary"]["paper"]
    assert paper["all"]["fills"] == 2
    assert paper["in_hours"]["avg_better_by_bps"] == pytest.approx(98.0, abs=0.1)
    assert paper["after_hours"]["avg_better_by_bps"] == pytest.approx(190.5, abs=0.1)

    built = pack.build_pack(db_session, "2026-01", date(2026, 2, 15))
    assert built["fills"]["paper"]["all"]["fills"] == 2
    report = pack.plain_report(built)
    assert "## 4. How realistic were the fill prices?" in report
    assert "| paper | outside market hours | 1 | +1.91% |" in report
