"""#470: a daily candle's trading day is its IST date (stamped 18:30 UTC the day before).

The coverage endpoint and the backtest window labelled it with the UTC date, a day early. These failed on
`5de3b9c` and pass with the fix. Nothing here is frozen or stored: a backtest is computed on demand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from itertools import count
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.services import backtest
from swing_trade_ml.strategies.base import SignalDecision

IST = ZoneInfo("Asia/Kolkata")
KEY = {"X-API-Key": "test-api-key"}
_tokens = count(970_000)


def stamp(day: date) -> datetime:
    """How Kite stamps a daily bar: midnight India time, i.e. 18:30 UTC the day before."""
    return datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)


def stock(
    db, symbol: str, days: list[date], *, watchlisted: bool = True, lows: dict[date, float] | None = None
) -> Instrument:
    inst = Instrument(
        instrument_token=next(_tokens),
        tradingsymbol=symbol,
        exchange="NSE",
        is_active=True,
        is_watchlisted=watchlisted,
    )
    db.add(inst)
    db.flush()
    for n, day in enumerate(days):
        price = 100.0 + n
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=stamp(day),
                open=price,
                high=price + 1,
                low=(lows or {}).get(day, price - 1),
                close=price,
                volume=1000,
            )
        )
    db.commit()
    return inst


# ---------------------------------------------------- the coverage endpoint
def test_coverage_reports_the_india_date_of_the_first_and_newest_bar(client, db_session):
    stock(db_session, "IST470COV", [date(2026, 11, 30), date(2026, 12, 1)])
    rows = client.get("/api/v1/market-data/coverage", headers=KEY).json()
    row = next(r for r in rows if r["symbol"] == "IST470COV")
    assert (row["from"], row["to"]) == ("2026-11-30", "2026-12-01"), row  # UTC labels read 11-29 and 11-30


# ---------------------------------------------------- the backtest window
def test_the_day_helper_gives_the_india_date_for_bars_stamped_at_india_midnight():
    ts = pd.Series(pd.to_datetime([stamp(date(2026, 11, 30)), stamp(date(2026, 12, 1))], utc=True))
    assert list(backtest._ist_dates(ts)) == [date(2026, 11, 30), date(2026, 12, 1)]
    assert list(backtest._ist_dates(ts.dt.tz_localize(None))) == [
        date(2026, 11, 30),
        date(2026, 12, 1),
    ]  # naive = UTC


def test_a_window_that_names_the_first_and_last_india_day_keeps_both_bars(db_session):
    days = [date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 2)]  # Mon, Tue, Wed
    stock(db_session, "IST470BT", days)
    result = backtest.run_backtest(db_session, "sma_crossover", ["IST470BT"], start=days[0], end=days[-1])
    assert [p["date"] for p in result.equity_curve] == ["2026-11-30", "2026-12-01", "2026-12-02"]


def test_a_one_day_window_keeps_that_days_bar_and_no_other(db_session):
    days = [date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 2)]
    stock(db_session, "IST470ONE", days)
    result = backtest.run_backtest(db_session, "sma_crossover", ["IST470ONE"], start=days[1], end=days[1])
    assert [p["date"] for p in result.equity_curve] == ["2026-12-01"]


def test_the_window_end_never_includes_a_later_india_day(db_session):
    days = [date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 2)]
    stock(db_session, "IST470END", days)
    with pytest.raises(ValueError, match="No candles fall inside"):
        backtest.run_backtest(
            db_session, "sma_crossover", ["IST470END"], start=date(2026, 12, 3), end=date(2026, 12, 4)
        )


# ------------------------------------- the single-site checks (each fails if only that site regresses)
class _BuyOnFirstBar:
    """Buys on the first bar it sees (100, stop 98) and never signals again."""

    def min_bars_required(self) -> int:
        return 1

    def evaluate(self, df, instrument, db):
        if len(df) == 1:
            return SignalDecision(signal=SignalType.BUY, price=100.0, confidence=0.9, stop_loss=98.0)
        return None


DAYS = [date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 2)]  # closes 100, 101, 102


def test_last_close_is_the_close_of_that_india_day_not_of_a_later_bar():
    df = pd.DataFrame({"ts": [stamp(d) for d in DAYS], "close": [100.0, 101.0, 102.0]})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    assert backtest._last_close(df, date(2026, 11, 30)) == 100.0  # a UTC cut finds nothing and says 0.0
    assert backtest._last_close(df, date(2026, 12, 1)) == 101.0  # a UTC cut reaches the 12-02 bar: 102.0


def test_an_open_position_is_valued_at_each_days_own_close(db_session, monkeypatch):
    monkeypatch.setattr(backtest, "get_strategy", lambda _row: _BuyOnFirstBar())
    stock(db_session, "IST470HOLD", DAYS)
    result = backtest.run_backtest(db_session, "sma_crossover", ["IST470HOLD"], start=DAYS[0], end=DAYS[-1])
    held = [round(p["total_value"] - p["cash"], 2) for p in result.equity_curve]
    qty = round(held[0] / 100.0)
    assert qty >= 1, held
    assert held == [qty * 100.0, qty * 101.0, qty * 102.0], held
    assert [t.exit_reason for t in result.trades] == ["BACKTEST_END"]
    assert result.trades[0].exit_date == DAYS[-1]
    assert 101.0 < result.trades[0].exit_price < 102.0  # sold near the last close


def test_a_stop_is_judged_on_that_days_own_bar(db_session, monkeypatch):
    monkeypatch.setattr(backtest, "get_strategy", lambda _row: _BuyOnFirstBar())
    stock(db_session, "IST470STOP", DAYS, lows={DAYS[2]: 50.0})  # only the 12-02 bar pierces the stop
    result = backtest.run_backtest(db_session, "sma_crossover", ["IST470STOP"], start=DAYS[0], end=DAYS[-1])
    assert [(t.exit_reason, t.exit_date) for t in result.trades] == [("STOP_LOSS_HIT", DAYS[2])]


def test_the_india_day_is_computed_once_per_instrument_not_per_day_or_position(db_session, monkeypatch):
    monkeypatch.setattr(backtest, "get_strategy", lambda _row: _BuyOnFirstBar())
    calls = []
    real = backtest._ist_dates
    monkeypatch.setattr(backtest, "_ist_dates", lambda ts: calls.append(1) or real(ts))
    stock(db_session, "IST470PERF", DAYS)
    backtest.run_backtest(db_session, "sma_crossover", ["IST470PERF"], start=DAYS[0], end=DAYS[-1])
    assert len(calls) <= 1, f"_ist_dates ran {len(calls)} times for one instrument over {len(DAYS)} days"
