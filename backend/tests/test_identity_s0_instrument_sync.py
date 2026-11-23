"""#389 step S0: the instrument sync survives a re-issued Kite token (Developer-1's xfail, now a plain test).

Before: the upsert conflicted on `instrument_token` only, so a NEW token for a symbol already stored violated
`uq_instruments_exchange_symbol`, the sync raised, and every other stock in the same batch was lost.
Now: a re-issued token is written onto the stock's existing row (one instrument per symbol, its history and
foreign keys intact) and the rest of the batch is stored.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services import ingestion

_tokens = iter(range(389_100, 389_900))


def _dump(*items: tuple[int, str]) -> list[dict]:
    return [
        {
            "instrument_token": token,
            "exchange_token": token // 256,
            "tradingsymbol": symbol,
            "name": f"{symbol} name",
            "exchange": "NSE",
            "segment": "NSE",
            "instrument_type": "EQ",
            "lot_size": 1,
            "tick_size": 0.05,
        }
        for token, symbol in items
    ]


def _sync(db, monkeypatch, dump: list[dict]) -> IntegrityError | None:
    monkeypatch.setattr(ingestion, "kite_broker", SimpleNamespace(get_instruments=lambda exchange: dump))
    try:
        with db.begin_nested():
            ingestion.sync_instruments(db)
    except IntegrityError as exc:
        return exc
    return None


def _rows(db, *symbols: str) -> dict[str, list[Instrument]]:
    db.expire_all()
    found: dict[str, list[Instrument]] = {s: [] for s in symbols}
    for row in db.execute(select(Instrument).where(Instrument.tradingsymbol.in_(symbols))).scalars():
        found[row.tradingsymbol].append(row)
    return found


def _stored(db, symbol: str, token: int, **kw) -> Instrument:
    row = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_active=True, **kw)
    db.add(row)
    db.flush()
    return row


def test_a_normal_sync_inserts_new_stocks_and_keeps_a_known_token(db_session, monkeypatch):
    _stored(db_session, "S0KEEP", 389_101)
    assert _sync(db_session, monkeypatch, _dump((389_101, "S0KEEP"), (389_102, "S0NEW"))) is None
    found = _rows(db_session, "S0KEEP", "S0NEW")
    assert [r.instrument_token for r in found["S0KEEP"]] == [389_101]
    assert [r.instrument_token for r in found["S0NEW"]] == [389_102]


def test_a_reissued_token_keeps_one_row_and_the_rest_of_the_batch(db_session, monkeypatch):
    old = _stored(db_session, "S0REISSUE", 389_111, is_watchlisted=True)
    old_id = old.id
    assert _sync(db_session, monkeypatch, _dump((389_112, "S0REISSUE"), (389_113, "S0OTHER"))) is None
    found = _rows(db_session, "S0REISSUE", "S0OTHER")
    assert [r.id for r in found["S0REISSUE"]] == [old_id], "the same row, so its history stays attached"
    assert found["S0REISSUE"][0].instrument_token == 389_112
    assert found["S0REISSUE"][0].is_watchlisted is True, "the watchlist flag survives the refresh"
    assert [r.instrument_token for r in found["S0OTHER"]] == [389_113], "the rest of the batch is stored"


def test_the_same_dump_twice_changes_nothing(db_session, monkeypatch):
    _stored(db_session, "S0TWICE", 389_121)
    dump = _dump((389_122, "S0TWICE"), (389_123, "S0TWICEB"))
    assert _sync(db_session, monkeypatch, dump) is None
    def snapshot():
        found = _rows(db_session, "S0TWICE", "S0TWICEB")
        return {s: [(r.id, r.instrument_token) for r in rows] for s, rows in found.items()}

    first = snapshot()
    assert _sync(db_session, monkeypatch, dump) is None
    assert snapshot() == first


def test_a_token_held_by_another_symbol_skips_that_row_and_keeps_the_batch(db_session, monkeypatch):
    """Two stored stocks, and the dump hands stock A the token stock B holds. Ambiguous: nothing is moved, the
    sync does not raise, and the unrelated stock in the batch is still stored."""
    a = _stored(db_session, "S0AMBA", 389_131)
    b = _stored(db_session, "S0AMBB", 389_132)
    a_id, b_id = a.id, b.id
    error = _sync(db_session, monkeypatch, _dump((389_132, "S0AMBA"), (389_133, "S0AMBC")))
    assert error is None
    found = _rows(db_session, "S0AMBA", "S0AMBB", "S0AMBC")
    assert [r.id for r in found["S0AMBA"]] == [a_id] and found["S0AMBA"][0].instrument_token == 389_131
    assert [r.id for r in found["S0AMBB"]] == [b_id] and found["S0AMBB"][0].instrument_token == 389_132
    assert [r.instrument_token for r in found["S0AMBC"]] == [389_133]


def test_a_renamed_symbol_still_updates_by_token_as_before(db_session, monkeypatch):
    row = _stored(db_session, "S0OLDSYM", 389_141)
    row_id = row.id
    assert _sync(db_session, monkeypatch, _dump((389_141, "S0NEWSYM"))) is None
    found = _rows(db_session, "S0OLDSYM", "S0NEWSYM")
    assert found["S0OLDSYM"] == [] and [r.id for r in found["S0NEWSYM"]] == [row_id]
