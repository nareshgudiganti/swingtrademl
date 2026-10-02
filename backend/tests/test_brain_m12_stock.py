"""M12 stock brain: setups, breakdowns, the stock's profile, delivery and deals."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.modules.m12_stock.profile import profile_line
from swing_trade_ml.brain.modules.m12_stock.setups import find_setups
from swing_trade_ml.brain.modules.m12_stock.signals import (
    DealRow,
    deal_signal,
    delivery_signal,
    is_institution,
)


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
        "Delivery above average 4 of the last 5 days (buyers are taking shares home).",
    )


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
