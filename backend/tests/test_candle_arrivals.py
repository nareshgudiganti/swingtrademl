"""F-07: when did each daily bar first reach us? Recorded beside `candles` in `candle_arrivals`, without
changing the v1 candles table (CLAUDE.md rule 8). Later overwrites stay in `candle_corrections`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from swing_trade_ml.db.models.market import CandleArrival, CandleCorrection, Instrument
from swing_trade_ml.services.ingestion import _upsert_candles

TS = datetime(2026, 5, 1, 18, 30, tzinfo=UTC)
TS2 = datetime(2026, 5, 3, 18, 30, tzinfo=UTC)


def _inst(db, token: int) -> Instrument:
    inst = Instrument(instrument_token=token, tradingsymbol=f"ARR{token}", exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    return inst


def _bar(ts, close=10.0):
    return {"date": ts, "open": 10, "high": 11, "low": 9, "close": close, "volume": 100}


def _arrivals(db, inst_id):
    return db.execute(select(CandleArrival).where(CandleArrival.instrument_id == inst_id)).scalars().all()


def test_a_new_bar_records_when_it_arrived(db_session):
    inst = _inst(db_session, 997001)
    before = datetime.now(UTC)
    _upsert_candles(db_session, inst.id, "day", [_bar(TS), _bar(TS2)])
    rows = _arrivals(db_session, inst.id)
    assert sorted(r.ts for r in rows) == [TS, TS2]
    assert all(r.interval == "day" and r.received_at >= before for r in rows)


def test_re_ingesting_the_same_bar_keeps_the_first_arrival(db_session):
    inst = _inst(db_session, 997002)
    _upsert_candles(db_session, inst.id, "day", [_bar(TS)])
    first = _arrivals(db_session, inst.id)[0].received_at
    _upsert_candles(db_session, inst.id, "day", [_bar(TS)])
    rows = _arrivals(db_session, inst.id)
    assert len(rows) == 1 and rows[0].received_at == first


def test_a_corrected_bar_keeps_its_arrival_and_logs_the_correction(db_session):
    inst = _inst(db_session, 997003)
    _upsert_candles(db_session, inst.id, "day", [_bar(TS)])
    first = _arrivals(db_session, inst.id)[0].received_at
    _upsert_candles(db_session, inst.id, "day", [_bar(TS, close=10.5)])
    assert _arrivals(db_session, inst.id)[0].received_at == first
    assert db_session.execute(select(CandleCorrection)).scalar_one().new_close == 10.5
