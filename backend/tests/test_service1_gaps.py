"""Service 1 P0: snapshots, corrections, split-check."""

from __future__ import annotations

from datetime import UTC, date, datetime

from swing_trade_ml.brain.universe import brain_universe, brain_universe_live
from swing_trade_ml.db.models.market import Candle, CandleCorrection, Instrument, WatchlistSnapshot
from swing_trade_ml.services.ingestion import _upsert_candles
from swing_trade_ml.services.watchlist_snapshots import record_watchlist_snapshot, watchlist_as_of


def test_replay_universe_uses_snapshot_not_today(db_session, monkeypatch):
    inst = Instrument(
        instrument_token=9001,
        tradingsymbol="OLDCO",
        exchange="NSE",
        is_active=True,
        is_watchlisted=True,
    )
    inst2 = Instrument(
        instrument_token=9002,
        tradingsymbol="NEWCO",
        exchange="NSE",
        is_active=True,
        is_watchlisted=True,
    )
    db_session.add_all([inst, inst2])
    db_session.commit()

    db_session.add(WatchlistSnapshot(snapshot_date=date(2026, 6, 1), symbol="OLDCO"))
    db_session.commit()

    live = brain_universe_live(db_session)
    assert "NEWCO" in live
    replay = brain_universe(db_session, as_of=date(2026, 6, 15))
    assert "OLDCO" in replay
    assert "NEWCO" not in replay
    assert watchlist_as_of(db_session, date(2026, 6, 15)) == ("OLDCO",)


def test_candle_upsert_logs_correction(db_session):
    inst = Instrument(instrument_token=9003, tradingsymbol="FIX", exchange="NSE", is_active=True)
    db_session.add(inst)
    db_session.commit()
    ts = datetime(2026, 9, 1, 18, 30, tzinfo=UTC)
    _upsert_candles(
        db_session,
        inst.id,
        "day",
        [{"date": ts, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}],
    )
    _upsert_candles(
        db_session,
        inst.id,
        "day",
        [{"date": ts, "open": 100, "high": 101, "low": 99, "close": 105, "volume": 1000}],
    )
    rows = db_session.query(CandleCorrection).all()
    assert len(rows) == 1
    assert rows[0].old_close == 100.0
    assert rows[0].new_close == 105.0


def test_record_watchlist_snapshot(db_session):
    inst = Instrument(instrument_token=9010, tradingsymbol="AAA", exchange="NSE", is_active=True, is_watchlisted=True)
    inst2 = Instrument(instrument_token=9011, tradingsymbol="BBB", exchange="NSE", is_active=True, is_watchlisted=True)
    db_session.add_all([inst, inst2])
    db_session.commit()
    record_watchlist_snapshot(db_session, on=date(2026, 10, 1))
    assert watchlist_as_of(db_session, date(2026, 10, 5)) == ("AAA", "BBB")
