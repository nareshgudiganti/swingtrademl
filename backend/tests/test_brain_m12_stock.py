"""M12 stock brain: setups, breakdowns, the stock's profile, delivery and deals."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m12_stock.module import StockBrain
from swing_trade_ml.brain.modules.m12_stock.profile import profile_line
from swing_trade_ml.brain.modules.m12_stock.setups import find_setups
from swing_trade_ml.brain.modules.m12_stock.signals import (
    DealRow,
    deal_signal,
    delivery_signal,
    is_institution,
)
from swing_trade_ml.brain.runner import execute


def _bars(close, volume=None, spread=0.01, open_=None) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    n = len(close)
    volume = np.full(n, 100_000.0) if volume is None else np.asarray(volume, dtype=float)
    prev = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "day": pd.bdate_range("2026-01-01", periods=n).date,
            "open": prev if open_ is None else open_,
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume": volume,
        }
    )


def _labels(bars):
    return [s.label for s in find_setups(bars)]


def _rising(n=120, rate=0.005):
    return 100 * (1 + rate) ** np.arange(n)


def test_a_steady_rise_on_normal_volume_is_no_setup():
    assert _labels(_bars(_rising())) == []


def test_pullback_to_the_20_day_average_in_an_up_trend():
    close = _rising()
    sma20 = pd.Series(close).rolling(20).mean().iloc[-1]
    close[-1] = sma20 * 1.002
    bars = _bars(close)
    bars.loc[bars.index[-1], "low"] = sma20 * 0.999
    (setup,) = find_setups(bars)
    assert setup.label == "pullback in up-trend" and setup.confirming
    assert setup.line == "Setup: pullback to the 20-day average in an up-trend."


def test_breakout_above_the_20_day_high_on_heavy_volume():
    close = np.full(80, 100.0)
    close[-1] = 105.0
    volume = np.full(80, 100_000.0)
    volume[-1] = 200_000.0
    (setup,) = find_setups(_bars(close, volume))
    assert setup.label == "breakout" and setup.confirming
    assert "2.0x" in setup.line


def test_a_breakout_on_ordinary_volume_does_not_count():
    close = np.full(80, 100.0)
    close[-1] = 105.0
    assert "breakout" not in _labels(_bars(close))


def test_zero_volume_is_not_a_breakout():
    close = np.full(80, 100.0)
    close[-1] = 105.0
    assert "breakout" not in _labels(_bars(close, volume=np.zeros(80)))


def test_a_tight_base():
    close = 100 + 0.2 * np.sin(np.arange(80))  # drifting inside a narrow band
    labels = _labels(_bars(close, spread=0.01))
    assert labels == ["base"]


def test_a_breakdown_below_the_20_day_low_on_heavy_volume_is_not_confirming():
    close = np.full(80, 100.0)
    close[-1] = 94.0
    volume = np.full(80, 100_000.0)
    volume[-1] = 250_000.0
    (setup,) = find_setups(_bars(close, volume))
    assert setup.label == "breakdown" and not setup.confirming


def test_short_history_gives_nothing():
    assert find_setups(_bars(_rising(40))) == []
    assert profile_line(_bars(_rising(40))) is None


def test_the_profile_in_plain_words():
    line = profile_line(_bars(_rising(300, rate=0.01)))
    assert line == (
        "Usually moves about 2.0% in a day; opens with a jump of more than 2% on 0% of days; "
        "reached +8% within 15 trading days 100% of the time in the last year (typically in 7 days)."
    )


# --- delivery and deals --------------------------------------------------------------------

TODAY = date(2026, 9, 29)


def _delivery(recent, base=40.0, n=25):
    days = [TODAY - timedelta(days=n - i) for i in range(n)]
    pcts = [base] * (n - len(recent)) + list(recent)
    return list(zip(days, pcts, strict=True))


def test_delivery_above_average_on_most_recent_days():
    assert delivery_signal(_delivery([55, 52, 38, 60, 58])) == (
        "high",
        "Delivery well above its usual level on 4 of the last 5 days (buyers are taking shares home).",
    )


def test_delivery_only_a_little_above_average_is_no_signal():
    """The spec's plain 'above average 3 of 5' fired on 53% of days with no edge
    (18.8% vs 19.1% hit rate, 5 years of watch-list stocks); 1.2x did better."""
    assert delivery_signal(_delivery([45, 46, 44, 47, 45])) == (None, None)


def test_delivery_above_average_only_twice_is_no_signal():
    assert delivery_signal(_delivery([55, 38, 38, 60, 39])) == (None, None)


def test_delivery_needs_enough_history():
    assert delivery_signal(_delivery([55, 52, 58, 60, 58], n=12)) == (None, None)


def test_delivery_ignores_missing_values():
    rows = _delivery([55, 52, 38, 60, 58])
    rows[-1] = (rows[-1][0], None)
    rows[-2] = (rows[-2][0], None)
    assert delivery_signal(rows) == (None, None)  # only 3 of the last 5 days usable; 2 above


@pytest.mark.parametrize(
    "name",
    [
        "HDFC MUTUAL FUND",
        "SBI MUTUAL FUND A/C SBI SMALL CAP FUND",
        "LIFE INSURANCE CORPORATION OF INDIA",
        "GOLDMAN SACHS (SINGAPORE) PTE - ODI",
        "MORGAN STANLEY ASIA (SINGAPORE) PTE.",
        "SOCIETE GENERALE - ODI",
        "GOVERNMENT OF SINGAPORE",
        "ABU DHABI INVESTMENT AUTHORITY",
        "BELGRAVE INVESTMENT FUND",
    ],
)
def test_long_term_institutions_are_recognised(name):
    assert is_institution(name)


@pytest.mark.parametrize(
    "name",
    [
        "QE SECURITIES LLP",
        "HRTI PRIVATE LIMITED",
        "JUMP TRADING FINANCIAL INDIA PRIVATE LIMITED",
        "MATHISYS QUANTCAP LLP",
        "JUNOMONETA FINSOL PRIVATE LIMITED",
        "ASHA KEJRIWAL",
        "SILVERLEAF CAPITAL SERVICES PRIVATE LIMITED",
        "ABC FUNDING LIMITED",
    ],
)
def test_trading_firms_are_not_institutions(name):
    assert not is_institution(name)


def _deal(client, side, day=TODAY, qty=100_000, symbol="ABC"):
    return DealRow(symbol=symbol, day=day, client=client, side=side, quantity=qty)


def test_an_institutional_buy_is_a_positive_signal():
    sign, line = deal_signal([_deal("HDFC MUTUAL FUND", "BUY", qty=120_000)], TODAY)
    assert sign == 1
    assert line == "Big-investor buying: HDFC MUTUAL FUND bought 1,20,000 shares on 29 Sep."


def test_an_institutional_sell_counts_against():
    sign, line = deal_signal([_deal("GOVERNMENT OF SINGAPORE", "SELL")], TODAY)
    assert sign == -1 and line.startswith("Big-investor selling: GOVERNMENT OF SINGAPORE sold")


def test_same_day_round_trips_are_ignored():
    rows = [
        _deal("GOLDMAN SACHS (SINGAPORE) PTE - ODI", "BUY"),
        _deal("GOLDMAN SACHS (SINGAPORE) PTE - ODI", "SELL"),
    ]
    assert deal_signal(rows, TODAY) == (0, None)


def test_trading_firm_deals_and_old_deals_are_ignored():
    rows = [
        _deal("QE SECURITIES LLP", "BUY"),
        _deal("HDFC MUTUAL FUND", "BUY", day=TODAY - timedelta(days=30)),
    ]
    assert deal_signal(rows, TODAY) == (0, None)


# --- the module ------------------------------------------------------------------------------


class StockReader(FakeReader):
    def __init__(self, bars=None, delivery=None, deals=(), events=(), **kw):
        super().__init__(**kw)
        self.as_of = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
        self._bars, self._delivery, self._deals = bars or {}, delivery or {}, list(deals)
        self._events = list(events)

    def event_rows(self, symbols):
        return [e for e in self._events if e.symbol in symbols]

    def ohlcv(self, symbol, n=400):
        return self._bars.get(symbol, super().ohlcv(symbol, n))

    def delivery_rows(self, symbols, days=40):
        return {s: self._delivery[s] for s in symbols if s in self._delivery}

    def deal_rows(self, symbols, days=10):
        return [d for d in self._deals if d.symbol in symbols]


def _breakout_bars():
    close = np.full(80, 100.0)
    close[-1] = 105.0
    volume = np.full(80, 100_000.0)
    volume[-1] = 200_000.0
    return _bars(close, volume)


def _breakdown_bars():
    close = np.full(80, 100.0)
    close[-1] = 94.0
    volume = np.full(80, 100_000.0)
    volume[-1] = 250_000.0
    return _bars(close, volume)


def _run(reader, universe=("ABC", "XYZ")):
    req = c.RunRequest(run_id="t", kind="nightly", as_of=reader.as_of, universe=universe, live=True)
    return execute(req, reader, registry(StockBrain), {"M12": Mode.ON})


def test_m12_is_a_recognise_plugin_that_starts_on_trial():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M12") is StockBrain
    m = StockBrain.manifest
    assert m.step is Step.RECOGNISE and m.kind == "plugin" and m.default_mode is Mode.SHADOW


def test_only_signals_with_evidence_move_the_order():
    """5 years of watch-list stocks: setups did not beat a random day for
    +8% before -4% (pullback 16.7%, breakout 16.4%, base 13.0% vs 17.6%), so
    they carry no tilt and stay off the cards; delivery 1.2x did (22.3%)."""
    reader = StockReader(
        bars={"ABC": _breakout_bars()},
        delivery={"ABC": _delivery([55, 52, 38, 60, 58])},
        deals=[_deal("HDFC MUTUAL FUND", "BUY")],
    )
    ctx = _run(reader)
    (o,) = [o for o in ctx.opinions if o.symbol == "ABC"]
    assert o.source == "setup" and o.stance == pytest.approx(0.4)  # delivery + institution, not the breakout
    assert not any(r.startswith("Setup:") for r in o.reasons)
    assert any(r.startswith("Delivery well above") for r in o.reasons)
    assert any(r.startswith("Big-investor buying") for r in o.reasons)
    assert o.reasons[-1].startswith("Usually moves about")
    (sit,) = ctx.situations
    assert sit.label == "breakout" and sit.evidence[0].startswith(
        "Setup: breakout"
    )  # in the why, not the card
    assert ctx.stocks["ABC"].delivery_signal == "high"


def test_institutional_selling_counts_against_but_a_breakdown_does_not():
    """Breakdowns reached +8% first 20.4% of the time vs 17.6% for any day."""
    reader = StockReader(bars={"ABC": _breakdown_bars()}, deals=[_deal("GOVERNMENT OF SINGAPORE", "SELL")])
    ctx = _run(reader)
    (o,) = [o for o in ctx.opinions if o.symbol == "ABC"]
    assert o.stance == pytest.approx(-0.2)
    assert [s.label for s in ctx.situations] == ["breakdown"]


def test_a_drop_on_an_ex_date_is_not_called_a_breakdown():
    from swing_trade_ml.brain.modules.m13_news.calendar import EventRow

    split = EventRow(symbol="ABC", kind="corporate_action", day=date(2026, 9, 29), detail="Split")
    ctx = _run(StockReader(bars={"ABC": _breakdown_bars()}, events=[split]))
    assert "breakdown" not in [s.label for s in ctx.situations]


def test_a_stock_with_no_bars_gets_nothing():
    ctx = _run(StockReader())
    assert not ctx.opinions and not ctx.situations


def test_setup_opinions_are_modifiers():
    from swing_trade_ml.brain.opinions import MODIFIER_SOURCES

    assert "setup" in MODIFIER_SOURCES


def test_the_reader_keeps_eq_delivery_and_nothing_after_the_run(db_session):
    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.db.models.feeds import BlockDeal, DailyDelivery

    db_session.add_all(
        [
            DailyDelivery(symbol="M12A", series="EQ", trade_date=date(2026, 9, 28), delivery_pct=51.0),
            DailyDelivery(symbol="M12A", series="BE", trade_date=date(2026, 9, 28), delivery_pct=99.0),
            DailyDelivery(
                symbol="M12A", series="EQ", trade_date=date(2026, 9, 30), delivery_pct=70.0
            ),  # later
            BlockDeal(
                deal_key="m12-a",
                trade_date=date(2026, 9, 28),
                symbol="M12A",
                kind="bulk",
                client_name="HDFC MUTUAL FUND",
                side="BUY",
                quantity=1000,
                price=10.0,
            ),
            BlockDeal(
                deal_key="m12-b",
                trade_date=date(2026, 9, 30),
                symbol="M12A",
                kind="bulk",
                client_name="HDFC MUTUAL FUND",
                side="SELL",
                quantity=1000,
                price=10.0,
            ),
        ]
    )
    db_session.flush()
    reader = DatedReader(db_session, datetime(2026, 9, 29, 12, 0, tzinfo=UTC), live=False)
    assert reader.delivery_rows(["M12A"]) == {"M12A": [(date(2026, 9, 28), 51.0)]}
    assert [(d.side, d.day) for d in reader.deal_rows(["M12A"])] == [("BUY", date(2026, 9, 28))]
