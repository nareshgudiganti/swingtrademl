"""#227: /signals/picks keeps a BUY for the same 0-4 completed trading sessions as the buy list.

The clock is frozen inside the signals module. Calendar: Tue 24 Nov 2026 is an NSE holiday.
Viewed Mon 30 Nov 2026 10:00 IST the last closed session is Fri 27 Nov; ages: Fri 27 = 0, Thu 26 = 1,
Wed 25 = 2, Mon 23 = 3, Fri 20 = 4, Thu 19 = 5.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.api.v1.endpoints import signals as signals_mod
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy

API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}
_tokens = iter(range(986_000, 986_900))


def _ist(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def _freeze(monkeypatch, now: datetime) -> None:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(signals_mod, "datetime", Frozen)


def _buy(db, strategy, symbol, at: datetime) -> None:
    inst = Instrument(
        instrument_token=next(_tokens),
        tradingsymbol=symbol,
        name=f"{symbol} Ltd",
        exchange="NSE",
        is_active=True,
    )
    db.add(inst)
    db.flush()
    db.add(
        Signal(
            strategy_id=strategy.id,
            instrument_id=inst.id,
            signal_type="BUY",
            mode="paper",
            price=100.0,
            confidence=0.8,
            stop_loss=96.0,
            take_profit=108.0,
            features={},
            generated_at=at.astimezone(UTC),
        )
    )
    db.flush()


@pytest.fixture()
def strategy(db_session):
    s = Strategy(name="s227_picks", strategy_type="ml_swing", mode="paper", is_active=True, params={})
    db_session.add(s)
    db_session.flush()
    return s


def _listed(client) -> set[str]:
    r = client.get(f"{API}/signals/picks", headers=KEY)
    assert r.status_code == 200, r.text
    return {x["symbol"] for x in r.json() if x["symbol"].startswith("PW227")}


def test_picks_no_longer_use_a_calendar_constant():
    assert not hasattr(signals_mod, "PICK_MAX_AGE")


def test_a_buy_across_a_weekend_and_a_holiday_is_kept_through_age_four_and_dropped_at_age_five(
    client, db_session, strategy, monkeypatch
):
    scan = (15, 45)
    _buy(db_session, strategy, "PW227AGE0", _ist(2026, 11, 27, *scan))
    _buy(db_session, strategy, "PW227AGE4", _ist(2026, 11, 20, *scan))  # 10 calendar days old, age 4
    _buy(db_session, strategy, "PW227AGE5", _ist(2026, 11, 19, *scan))
    _freeze(monkeypatch, _ist(2026, 11, 30, 10, 0))
    assert _listed(client) == {"PW227AGE0", "PW227AGE4"}


def test_a_friday_buy_is_still_listed_on_a_tuesday_though_over_five_calendar_days_old(
    client, db_session, strategy, monkeypatch
):
    # Fri 20 Nov scan. Viewed Mon 30 Nov: age 4, listed. The old calendar rule dropped it after 25 Nov.
    _buy(db_session, strategy, "PW227FRI", _ist(2026, 11, 20, 15, 45))
    _freeze(monkeypatch, _ist(2026, 11, 30, 10, 0))
    assert "PW227FRI" in _listed(client)
    _freeze(monkeypatch, _ist(2026, 12, 1, 10, 0))  # last closed = Mon 30: age 5
    assert "PW227FRI" not in _listed(client)


def test_a_weekend_is_not_counted_as_sessions(client, db_session, strategy, monkeypatch):
    # Thu 12 Nov 2026 scan viewed Wed 18 Nov 10:00: 6 calendar days, last closed Tue 17: age 3, listed.
    _buy(db_session, strategy, "PW227WKND", _ist(2026, 11, 12, 15, 45))
    _freeze(monkeypatch, _ist(2026, 11, 18, 10, 0))
    assert "PW227WKND" in _listed(client)
