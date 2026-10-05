"""Candle correction log on upsert (Service 1 #13)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from swing_trade_ml.db.models.market import Candle, CandleCorrection, Instrument
from swing_trade_ml.services.ingestion import _upsert_candles

TS = datetime(2026, 5, 1, 18, 30, tzinfo=UTC)


def test_upsert_logs_a_correction_when_ohlcv_changes(db_session):
    inst = Instrument(instrument_token=996001, tradingsymbol="CORR", exchange="NSE", is_active=True)
    db_session.add(inst)
    db_session.flush()
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=TS,
            open=10,
            high=11,
            low=9,
            close=10,
            volume=100,
        )
    )
    db_session.commit()

    _upsert_candles(
        db_session,
        inst.id,
        "day",
        [{"date": TS, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}],
    )

    row = db_session.execute(select(CandleCorrection)).scalar_one()
    assert row.old_close == 10.0 and row.new_close == 10.5
