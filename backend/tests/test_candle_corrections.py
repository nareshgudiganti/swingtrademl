"""Candle correction log on upsert (Service 1 #13)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from swing_trade_ml.db.models.brain import FeatureSnapshot
from swing_trade_ml.db.models.market import Candle, CandleCorrection, Instrument
from swing_trade_ml.services.ingestion import _upsert_candles

TS = datetime(2026, 5, 1, 18, 30, tzinfo=UTC)
TS2 = datetime(2026, 5, 2, 18, 30, tzinfo=UTC)
BAR1 = date(2026, 5, 2)
BAR2 = date(2026, 5, 3)


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


def test_upsert_correction_invalidates_feature_snapshots_from_bar_date(db_session):
    inst = Instrument(instrument_token=996002, tradingsymbol="CORR2", exchange="NSE", is_active=True)
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
    db_session.add_all(
        [
            FeatureSnapshot(
                symbol="CORR2",
                bar_date=BAR1,
                feature_set_version="v1",
                close=10.0,
                features={"rsi_14": 50.0},
            ),
            FeatureSnapshot(
                symbol="CORR2",
                bar_date=BAR2,
                feature_set_version="v1",
                close=10.5,
                features={"rsi_14": 55.0},
            ),
            FeatureSnapshot(
                symbol="OTHER",
                bar_date=BAR2,
                feature_set_version="v1",
                close=1.0,
                features={"rsi_14": 40.0},
            ),
        ]
    )
    db_session.commit()

    _upsert_candles(
        db_session,
        inst.id,
        "day",
        [{"date": TS, "open": 10, "high": 11, "low": 9, "close": 11.0, "volume": 100}],
    )

    remaining = {
        (r.symbol, r.bar_date)
        for r in db_session.execute(select(FeatureSnapshot)).scalars()
    }
    assert ("CORR2", BAR1) not in remaining
    assert ("CORR2", BAR2) not in remaining
    assert ("OTHER", BAR2) in remaining
