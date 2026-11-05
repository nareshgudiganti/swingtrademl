"""Stock Compare: period returns from daily closes. No database, no network."""

from datetime import date, timedelta

from swing_trade_ml.services import stock_compare as sc


def _daily(start: date, days: int, price) -> list[tuple[date, float]]:
    return [(start + timedelta(days=i), price(i)) for i in range(days)]


def test_returns_use_the_last_close_and_the_close_on_the_target_day():
    rows = _daily(date(2025, 1, 1), 400, lambda i: 100 + i)  # +1 every day
    r = sc.period_returns(rows)
    last = 100 + 399
    assert r["1W"] == round((last / (last - 7) - 1) * 100, 2)
    assert r["1Y"] == round((last / (last - 365) - 1) * 100, 2)


def test_a_period_longer_than_the_history_is_none_not_a_guess():
    r = sc.period_returns(_daily(date(2026, 1, 1), 100, lambda i: 50.0))
    assert r["1M"] == 0.0
    assert r["1Y"] is None and r["5Y"] is None


def test_a_gap_in_the_data_makes_the_period_none():
    rows = _daily(date(2026, 1, 1), 10, lambda i: 10.0) + _daily(date(2026, 6, 1), 10, lambda i: 12.0)
    r = sc.period_returns(rows)
    # 1M back from 10 Jun lands in the hole between 10 Jan and 1 Jun: nothing close enough.
    assert r["1M"] is None


def test_falling_price_is_negative_and_order_does_not_matter():
    rows = _daily(date(2026, 1, 1), 60, lambda i: 200 - i)
    assert sc.period_returns(list(reversed(rows))) == sc.period_returns(rows)
    assert sc.period_returns(rows)["1M"] < 0


def test_empty_or_bad_closes_give_all_none():
    assert set(sc.period_returns([]).values()) == {None}
    assert set(sc.period_returns([(date(2026, 1, 1), 0.0)]).values()) == {None}


def test_every_period_is_always_present_in_order():
    assert list(sc.period_returns([]).keys()) == ["1W", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y"]


def test_parse_symbols_uppercases_dedupes_and_keeps_order():
    assert sc.parse_symbols(" suzlon, eternal ,SUZLON,,bse ") == ["SUZLON", "ETERNAL", "BSE"]
    assert sc.parse_symbols(" , ") == []
