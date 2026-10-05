"""Phase 0 B0: split/bonus contamination check."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.services.split_check import run_split_contamination_check

IST = ZoneInfo("Asia/Kolkata")
EX_DAY = date(2026, 6, 10)
EX_TS = datetime.combine(EX_DAY, time(0, 0), tzinfo=IST).astimezone(ZoneInfo("UTC"))
PREV_TS = EX_TS - timedelta(days=1)


def _inst(db, symbol: str, token: int) -> Instrument:
    inst = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    return inst


def test_split_check_flags_a_large_move_on_bonus_ex_date(db_session):
    inst = _inst(db_session, "SPLCHK", 994001)
    db_session.add(
        UpcomingEvent(
            symbol="SPLCHK",
            kind="corporate_action",
            event_date=EX_DAY,
            detail="Bonus 1:1",
        )
    )
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=PREV_TS,
            open=100,
            high=100,
            low=100,
            close=100,
            volume=1,
        )
    )
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=EX_TS,
            open=50,
            high=50,
            low=50,
            close=50,
            volume=1,
        )
    )
    db_session.commit()

    report = run_split_contamination_check(db_session, threshold=0.30)

    assert report.hit_count == 1
    assert report.hits[0].symbol == "SPLCHK"
    assert report.hits[0].move_pct == -0.5


def test_results_events_are_not_checked(db_session):
    inst = _inst(db_session, "RESCHK", 994002)
    db_session.add(
        UpcomingEvent(
            symbol="RESCHK",
            kind="results",
            event_date=EX_DAY,
            detail="Results",
        )
    )
    db_session.commit()

    report = run_split_contamination_check(db_session)

    assert report.events_checked == 0
