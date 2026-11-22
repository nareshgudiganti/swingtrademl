"""Groww sync: completeness check, ISIN matching, sync log, lock."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from swing_trade_ml.db.models.groww import (
    MATCH_CONFIRMED,
    MATCH_NEEDS,
    MATCH_SUGGESTED,
    SYNC_COMPLETE,
    SYNC_EMPTY,
    SYNC_FAILED,
    SYNC_PARTIAL,
    GrowwHolding,
    GrowwSync,
    StockAlias,
)
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.groww import sync as gsync
from swing_trade_ml.services.groww.client import GrowwAuthError, GrowwUnavailable


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.deleted = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def eval(self, script, numkeys, key, token):
        if self.store.get(key) == token:
            self.deleted.append(key)
            del self.store[key]
            return 1
        return 0


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(gsync, "_get_redis", lambda: fake)
    return fake


_token = 900000


def _inst(db, symbol, exchange="NSE"):
    global _token
    _token += 1
    inst = Instrument(instrument_token=_token, tradingsymbol=symbol, exchange=exchange)
    db.add(inst)
    db.flush()
    return inst


def _row(isin="INE002A01018", symbol="RELIANCE-EQ", qty=10, avg=100.5, **extra):
    return {"isin": isin, "trading_symbol": symbol, "quantity": qty, "average_price": avg, **extra}


def _raises(exc):
    def fn():
        raise exc

    return fn


def test_clean_symbol():
    assert gsync.clean_symbol("RELIANCE-EQ") == "RELIANCE"
    assert gsync.clean_symbol("m&m") == "M&M"
    assert gsync.clean_symbol("abc-BE") == "ABC"
    assert gsync.clean_symbol("XYZ-BZ") == "XYZ"


def test_classify():
    assert gsync.classify([]) == SYNC_EMPTY
    assert gsync.classify([_row()]) == SYNC_COMPLETE


def test_partial_when_any_row_missing_isin():
    assert gsync.classify([_row(), _row(isin="")]) == SYNC_PARTIAL
    assert gsync.classify([_row(), _row(isin=None)]) == SYNC_PARTIAL
    assert gsync.classify([_row(avg=None)]) == SYNC_PARTIAL
    assert gsync.classify([_row(qty="ten")]) == SYNC_PARTIAL


def test_partial_sync_stores_parsable_rows(db_session, monkeypatch):
    _inst(db_session, "RELIANCE")
    bad = {"isin": "INE999Z01011", "quantity": 3}
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [_row(), bad])
    sync = gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert sync.status == SYNC_PARTIAL
    rows = db_session.query(GrowwHolding).filter_by(sync_id=sync.id).order_by(GrowwHolding.id).all()
    assert len(rows) == 2
    assert rows[1].match_state == MATCH_NEEDS
    assert rows[1].average_price is None and rows[1].trading_symbol is None
    assert rows[1].quantity == 3


def test_failed_sync_recorded_and_holdings_untouched(db_session, monkeypatch):
    monkeypatch.setattr(gsync, "fetch_holdings", _raises(GrowwAuthError("secret Bearer abc")))
    sync = gsync.run_sync(db_session, user_id=1, trigger="scheduled")
    assert sync.status == SYNC_FAILED and sync.error_code == "auth"
    assert sync.finished_at is not None and sync.finished_at.tzinfo is not None
    assert db_session.query(GrowwHolding).filter_by(sync_id=sync.id).count() == 0

    monkeypatch.setattr(gsync, "fetch_holdings", _raises(GrowwUnavailable("x")))
    assert gsync.run_sync(db_session, user_id=1, trigger="scheduled").error_code == "unavailable"


def test_empty_sync_changes_nothing_until_confirmed(db_session, monkeypatch):
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [])
    sync = gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert sync.status == SYNC_EMPTY
    assert sync.holdings_count == 0
    assert db_session.query(GrowwHolding).filter_by(sync_id=sync.id).count() == 0


def test_saved_alias_reused_by_isin_when_symbol_changes(db_session):
    inst_a = _inst(db_session, "OLDNAME")
    db_session.add(StockAlias(provider="groww", external_id="INE111A01011", instrument_id=inst_a.id))
    db_session.flush()
    out = gsync.match_rows(db_session, [_row(isin="INE111A01011", symbol="NEWNAME")])
    assert out[0][1] == inst_a.id and out[0][2] == MATCH_CONFIRMED


def test_suggested_and_needs_matching(db_session):
    inst = _inst(db_session, "TCS")
    _inst(db_session, "NOPE", exchange="BSE")
    rows = [_row(isin="I1", symbol="tcs-EQ"), _row(isin="I2", symbol="NOPE"), _row(isin="I3", symbol="ZZZ")]
    out = gsync.match_rows(db_session, rows)
    assert out[0][1:] == (inst.id, MATCH_SUGGESTED)
    assert out[1][1:] == (None, MATCH_NEEDS)
    assert out[2][1:] == (None, MATCH_NEEDS)


def test_two_instruments_same_symbol_goes_to_needs_matching(db_session):
    # The DB normally forbids this; drop the constraint inside the test transaction (rolled back).
    db_session.execute(text("ALTER TABLE instruments DROP CONSTRAINT uq_instruments_exchange_symbol"))
    _inst(db_session, "DUPE")
    _inst(db_session, "DUPE")
    out = gsync.match_rows(db_session, [_row(isin="I9", symbol="DUPE")])
    assert out[0][1:] == (None, MATCH_NEEDS)


def test_repeat_sync_idempotent(db_session, monkeypatch):
    inst = _inst(db_session, "RELIANCE")
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [_row(pledge_quantity=2)])
    first = gsync.run_sync(db_session, user_id=1, trigger="manual")
    second = gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert first.id != second.id and first.status == second.status == SYNC_COMPLETE

    def shape(sync):
        return [
            (h.isin, h.quantity, h.average_price, h.match_state, h.instrument_id)
            for h in db_session.query(GrowwHolding).filter_by(sync_id=sync.id)
        ]

    assert shape(first) == shape(second) == [("INE002A01018", 10, 100.5, MATCH_SUGGESTED, inst.id)]
    held = db_session.query(GrowwHolding).filter_by(sync_id=first.id).one()
    assert held.extra == {"pledge_quantity": 2}
    assert db_session.query(GrowwSync).count() == 2


def test_lock_held_raises_and_is_not_released(db_session, monkeypatch, fake_redis):
    fake_redis.store["groww:sync_lock"] = "1"
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [])
    with pytest.raises(gsync.SyncAlreadyRunning):
        gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert fake_redis.deleted == []
    assert db_session.query(GrowwSync).count() == 0


def test_lock_released_after_run_even_on_failure(db_session, monkeypatch, fake_redis):
    monkeypatch.setattr(gsync, "fetch_holdings", _raises(GrowwUnavailable("x")))
    gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert fake_redis.deleted == ["groww:sync_lock"]


def test_redis_down_proceeds_without_lock(db_session, monkeypatch):
    monkeypatch.setattr(gsync, "_get_redis", _raises(ConnectionError("down")))
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [])
    assert gsync.run_sync(db_session, user_id=1, trigger="manual").status == SYNC_EMPTY


def test_release_does_not_delete_a_lock_taken_by_another_run(db_session, monkeypatch, fake_redis):
    def fetch():
        fake_redis.store["groww:sync_lock"] = "someone-else"  # our lock expired, another run took it
        return []

    monkeypatch.setattr(gsync, "fetch_holdings", fetch)
    gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert fake_redis.store["groww:sync_lock"] == "someone-else"
    assert fake_redis.deleted == []


def test_non_list_fetch_result_is_failed_unavailable(db_session, monkeypatch):
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: None)
    sync = gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert sync.status == SYNC_FAILED and sync.error_code == "unavailable"


def test_store_error_records_failed_sync_with_store_code(db_session, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("insert failed with details")

    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [_row()])
    monkeypatch.setattr(gsync, "_store_rows", boom)
    sync = gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert sync.status == SYNC_FAILED and sync.error_code == "store"
    assert db_session.query(GrowwSync).count() == 1
    assert db_session.query(GrowwHolding).count() == 0


# --- #388 backend review: no exception text (it can hold holdings or secrets) in the logs ---------------


def test_failure_logs_carry_no_exception_text(db_session, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(gsync, "fetch_holdings", _raises(RuntimeError("leak-token-123 in fetch")))
    with caplog.at_level(logging.DEBUG):
        sync = gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert sync.status == SYNC_FAILED and sync.error_code == "unexpected"
    assert "leak-token-123" not in caplog.text

    def boom(*args, **kwargs):
        raise RuntimeError("leak-holding-456 in store")

    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [_row()])
    monkeypatch.setattr(gsync, "_store_rows", boom)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        sync = gsync.run_sync(db_session, user_id=1, trigger="manual")
    assert sync.error_code == "store"
    assert "leak-holding-456" not in caplog.text
