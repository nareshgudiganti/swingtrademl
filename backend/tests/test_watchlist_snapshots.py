"""Point-in-time watchlist snapshots (Service 1 #4)."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.universe import brain_universe, brain_universe_live
from swing_trade_ml.db.models.market import Instrument, WatchlistSnapshot
from swing_trade_ml.services.watchlist_snapshots import record_watchlist_snapshot, watchlist_as_of

AS_OF = date(2026, 9, 20)


def _inst(db, symbol: str, token: int, *, watch: bool = False) -> Instrument:
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True
    )
    db.add(inst)
    db.flush()
    return inst


def test_replay_universe_uses_snapshot_not_todays_watchlist(db_session):
    _inst(db_session, "OLDSNAP", 995001, watch=False)
    _inst(db_session, "NEWSNAP", 995002, watch=True)
    db_session.add(WatchlistSnapshot(snapshot_date=AS_OF, symbol="OLDSNAP"))
    db_session.commit()

    live = set(brain_universe_live(db_session))
    replay = set(brain_universe(db_session, as_of=AS_OF))

    assert "NEWSNAP" in live and "OLDSNAP" not in live
    assert "OLDSNAP" in replay and "NEWSNAP" not in replay


def test_watchlist_as_of_returns_empty_without_snapshot(db_session):
    assert watchlist_as_of(db_session, AS_OF) == ()


def test_record_watchlist_snapshot_writes_today(db_session):
    _inst(db_session, "SNAPW", 995003, watch=True)
    db_session.commit()
    n = record_watchlist_snapshot(db_session, on=date(2026, 10, 1))
    assert n == 1
    assert watchlist_as_of(db_session, date(2026, 10, 1)) == ("SNAPW",)


def test_dated_reader_replay_uses_snapshot(db_session):
    from datetime import UTC, datetime

    _inst(db_session, "READSNAP", 995004, watch=True)
    db_session.add(WatchlistSnapshot(snapshot_date=date(2026, 9, 1), symbol="READSNAP"))
    db_session.commit()
    as_of = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    assert "READSNAP" in DatedReader(db_session, as_of=as_of, live=False).universe()
