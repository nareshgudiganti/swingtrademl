from datetime import UTC, date, datetime

from swing_trade_ml.api.v1.endpoints.system import _build_status
from swing_trade_ml.db.models.market import Candle, Instrument


def test_daily_bar_date_is_read_in_ist_not_utc(db_session):
    inst = Instrument(instrument_token=99001, tradingsymbol="TSTAT", exchange="NSE")
    db_session.add(inst)
    db_session.flush()
    # The 18 Sep bar: Kite stamps it 00:00 IST, i.e. 17 Sep 18:30 UTC.
    db_session.add(
        Candle(
            instrument_id=inst.id, interval="day",
            ts=datetime(2026, 9, 17, 18, 30, tzinfo=UTC),
            open=1, high=1, low=1, close=1, volume=1,
        )
    )
    db_session.flush()

    assert _build_status(db_session).latest_candle_date == date(2026, 9, 18)
