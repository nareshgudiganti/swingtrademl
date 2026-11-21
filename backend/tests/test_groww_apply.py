"""Groww sync -> Groww Tracker: apply complete syncs, keep every overwritten value in history."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.groww import (
    HELD,
    HELD_UNKNOWN,
    MATCH_CONFIRMED,
    MATCH_NEEDS,
    MATCH_SUGGESTED,
    NOT_HELD,
    SOURCE_GROWW,
    SOURCE_MANUAL,
    SYNC_COMPLETE,
    SYNC_EMPTY,
    GrowwHolding,
    GrowwSync,
    StockAlias,
)
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import (
    UserWatchlistItem,
    UserWatchlistItemChange,
    UserWatchlistSale,
)
from swing_trade_ml.services.groww import apply as gapply
from swing_trade_ml.services.groww import sync as gsync

ORIGINAL_ADDED = datetime(2026, 10, 1, 4, 0, tzinfo=UTC)
# 2026-11-20 20:00 UTC is 2026-11-21 01:30 IST: the sync day must be the IST date.
SYNC_START = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
SYNC_DAY = datetime(2026, 11, 21, tzinfo=IST)

_token = 950000


@pytest.fixture()
def user(db_session):
    u = User(username="groww-owner", hashed_password="x", is_active=True, role="owner", plan="free")
    db_session.add(u)
    db_session.flush()
    return u


def _inst(db, symbol):
    global _token
    _token += 1
    inst = Instrument(instrument_token=_token, tradingsymbol=symbol, exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


def _item(db, user, symbol, **kw):
    kw.setdefault("added_at", ORIGINAL_ADDED)
    item = UserWatchlistItem(user_id=user.id, symbol=symbol, **kw)
    db.add(item)
    db.flush()
    return item


def _sync(db, holdings, status=SYNC_COMPLETE, started=SYNC_START):
    """holdings: (isin, instrument or None, qty, avg, match_state)."""
    sync = GrowwSync(
        started_at=started,
        finished_at=started.replace(minute=1),
        trigger="manual",
        status=status,
        holdings_count=len(holdings),
    )
    db.add(sync)
    db.flush()
    for isin, inst, qty, avg, state in holdings:
        db.add(
            GrowwHolding(
                sync_id=sync.id,
                isin=isin,
                trading_symbol=inst.tradingsymbol if inst else "UNKNOWN-EQ",
                quantity=qty,
                average_price=avg,
                instrument_id=inst.id if inst else None,
                match_state=state,
            )
        )
    db.flush()
    return sync


def _history(db, item, field=None):
    q = db.query(UserWatchlistItemChange).filter_by(item_id=item.id)
    if field:
        q = q.filter_by(field=field)
    return q.order_by(UserWatchlistItemChange.id).all()


def test_confirmed_row_overwrites_qty_and_price_and_keeps_history(db_session, user):
    inst = _inst(db_session, "RELIANCE")
    item = _item(db_session, user, "RELIANCE", quantity=5, buy_price=90.0)
    sync = _sync(db_session, [("INE002A01018", inst, 10, 100.5, MATCH_CONFIRMED)])

    counts = gapply.apply_sync(db_session, sync, user_id=user.id)

    db_session.refresh(item)
    assert item.quantity == 10 and item.buy_price == 100.5
    assert item.groww_isin == "INE002A01018" and item.held_state == HELD
    assert item.groww_synced_at == sync.finished_at
    qty = _history(db_session, item, "quantity")
    price = _history(db_session, item, "buy_price")
    assert [(c.old_value, c.new_value) for c in qty] == [("5.0", "10.0")]
    assert [(c.old_value, c.new_value) for c in price] == [("90.0", "100.5")]
    assert all(c.changed_by == "groww_sync" and c.sync_id == sync.id for c in qty + price)
    assert counts["updated"] == 1 and counts["added"] == 0


def test_buy_date_and_note_never_change(db_session, user):
    inst = _inst(db_session, "TCS")
    item = _item(db_session, user, "TCS", quantity=2, buy_price=3000.0, note="long term")
    sync = _sync(db_session, [("INE467B01029", inst, 4, 3100.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, sync, user_id=user.id)
    db_session.refresh(item)
    assert item.note == "long term"
    assert item.added_at == ORIGINAL_ADDED
    assert _history(db_session, item, "note") == [] and _history(db_session, item, "added_at") == []


def test_topup_keeps_original_buy_date(db_session, user):
    inst = _inst(db_session, "INFY")
    item = _item(db_session, user, "INFY", quantity=10, buy_price=1500.0)
    first = _sync(db_session, [("INE009A01021", inst, 10, 1500.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, first, user_id=user.id)
    topup = _sync(
        db_session,
        [("INE009A01021", inst, 20, 1550.0, MATCH_CONFIRMED)],
        started=datetime(2026, 11, 25, 5, 0, tzinfo=UTC),
    )
    gapply.apply_sync(db_session, topup, user_id=user.id)
    db_session.refresh(item)
    assert item.quantity == 20 and item.buy_price == 1550.0
    assert item.added_at == ORIGINAL_ADDED
    assert gapply.pending_sale_qty(db_session, item) is None


def test_unknown_holding_added_as_groww_source_with_sync_day_buy_date(db_session, user):
    inst = _inst(db_session, "HDFCBANK")
    sync = _sync(db_session, [("INE040A01034", inst, 7, 1600.25, MATCH_CONFIRMED)])
    counts = gapply.apply_sync(db_session, sync, user_id=user.id)
    item = db_session.query(UserWatchlistItem).filter_by(user_id=user.id, symbol="HDFCBANK").one()
    assert item.source == SOURCE_GROWW and item.groww_isin == "INE040A01034"
    assert item.quantity == 7 and item.buy_price == 1600.25
    assert item.added_at == SYNC_DAY
    assert item.held_state == HELD and item.note is None and item.removed_at is None
    assert item.groww_synced_at == sync.finished_at
    created = _history(db_session, item, "created")
    assert len(created) == 1 and created[0].sync_id == sync.id and created[0].changed_by == "groww_sync"
    assert counts["added"] == 1


def test_watch_only_stock_untouched(db_session, user):
    inst = _inst(db_session, "ITC")
    other = _inst(db_session, "WIPRO")
    watched = _item(db_session, user, "WIPRO", note="just watching")
    sync = _sync(db_session, [("INE154A01025", inst, 3, 400.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, sync, user_id=user.id)
    db_session.refresh(watched)
    assert other.id  # instrument exists but Groww does not hold it
    assert watched.quantity is None and watched.buy_price is None
    assert watched.held_state == HELD_UNKNOWN and watched.groww_isin is None
    assert watched.source == SOURCE_MANUAL and watched.groww_synced_at is None
    assert _history(db_session, watched) == []


def test_partial_sale_updates_qty_and_sets_pending_sale(db_session, user):
    inst = _inst(db_session, "SBIN")
    item = _item(db_session, user, "SBIN", quantity=10, buy_price=600.0)
    first = _sync(db_session, [("INE062A01020", inst, 10, 600.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, first, user_id=user.id)
    second = _sync(
        db_session,
        [("INE062A01020", inst, 7, 600.0, MATCH_CONFIRMED)],
        started=datetime(2026, 11, 22, 5, 0, tzinfo=UTC),
    )
    counts = gapply.apply_sync(db_session, second, user_id=user.id)
    db_session.refresh(item)
    assert item.quantity == 7 and item.held_state == HELD
    assert gapply.pending_sale_qty(db_session, item) == 3
    assert db_session.query(UserWatchlistSale).count() == 0
    assert counts["pending_sale"] == 1


def test_pending_sale_counts_only_drops_after_latest_confirmed_sale(db_session, user):
    inst = _inst(db_session, "LT")
    item = _item(db_session, user, "LT", quantity=10, buy_price=3500.0)
    s1 = _sync(db_session, [("INE018A01030", inst, 10, 3500.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, s1, user_id=user.id)
    s2 = _sync(db_session, [("INE018A01030", inst, 6, 3500.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, s2, user_id=user.id)
    assert gapply.pending_sale_qty(db_session, item) == 4
    # Owner confirms that sale (created_at set explicitly: DB now() is the test-transaction start).
    db_session.add(
        UserWatchlistSale(
            user_id=user.id,
            symbol="LT",
            bought_on=ORIGINAL_ADDED.date(),
            entry_price=3500.0,
            entry_source="your_price",
            quantity=4,
            sell_price=3600.0,
            sold_on=datetime(2026, 11, 22).date(),
            created_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    assert gapply.pending_sale_qty(db_session, item) is None
    s3 = _sync(db_session, [("INE018A01030", inst, 5, 3500.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, s3, user_id=user.id)
    assert gapply.pending_sale_qty(db_session, item) == 1


def test_absent_isin_marks_not_held_and_stays_on_list(db_session, user):
    inst = _inst(db_session, "MARUTI")
    keep = _inst(db_session, "ONGC")
    item = _item(db_session, user, "MARUTI", quantity=2, buy_price=11000.0, note="mine")
    first = _sync(db_session, [("INE585B01010", inst, 2, 11000.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, first, user_id=user.id)
    second = _sync(db_session, [("INE213A01029", keep, 1, 250.0, MATCH_CONFIRMED)])
    counts = gapply.apply_sync(db_session, second, user_id=user.id)
    db_session.refresh(item)
    assert item.removed_at is None
    assert item.held_state == NOT_HELD
    assert item.note == "mine" and item.buy_price == 11000.0 and item.added_at == ORIGINAL_ADDED
    assert gapply.pending_sale_qty(db_session, item) == 2  # unconfirmed sale of everything
    assert [(c.old_value, c.new_value) for c in _history(db_session, item, "held_state")][-1] == (
        HELD,
        NOT_HELD,
    )
    assert counts["not_held"] == 1


def test_present_with_zero_quantity_marks_not_held(db_session, user):
    inst = _inst(db_session, "NTPC")
    item = _item(db_session, user, "NTPC", quantity=5, buy_price=300.0)
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE733E01010", inst, 5, 300.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE733E01010", inst, 0, 300.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    db_session.refresh(item)
    assert item.held_state == NOT_HELD and item.removed_at is None


def test_never_linked_row_never_marked_not_held(db_session, user):
    inst = _inst(db_session, "BEL")
    manual = _item(db_session, user, "COALINDIA", quantity=5, buy_price=400.0)
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE263A01024", inst, 1, 200.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    db_session.refresh(manual)
    assert manual.held_state == HELD_UNKNOWN and manual.quantity == 5


def test_suggested_rows_not_applied(db_session, user):
    inst = _inst(db_session, "AXISBANK")
    unknown = _inst(db_session, "KOTAKBANK")
    item = _item(db_session, user, "AXISBANK", quantity=1, buy_price=1000.0)
    sync = _sync(
        db_session,
        [
            ("INE238A01034", inst, 9, 1100.0, MATCH_SUGGESTED),
            ("INE237A01028", None, 4, 1800.0, MATCH_NEEDS),
        ],
    )
    counts = gapply.apply_sync(db_session, sync, user_id=user.id)
    db_session.refresh(item)
    assert item.quantity == 1 and item.buy_price == 1000.0 and item.groww_isin is None
    assert db_session.query(UserWatchlistItem).filter_by(user_id=user.id, symbol="KOTAKBANK").count() == 0
    assert unknown.id and counts["needs_matching"] == 2 and counts["updated"] == 0


def test_rebuy_after_not_held_sets_new_buy_date_with_history(db_session, user):
    inst = _inst(db_session, "TITAN")
    item = _item(db_session, user, "TITAN", quantity=3, buy_price=3200.0, note="keep")
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE280A01028", inst, 3, 3200.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    gapply.apply_sync(db_session, _sync(db_session, []), user_id=user.id)  # owner-confirmed empty
    db_session.refresh(item)
    assert item.held_state == NOT_HELD
    rebuy_start = datetime(2026, 12, 1, 4, 0, tzinfo=UTC)
    gapply.apply_sync(
        db_session,
        _sync(db_session, [("INE280A01028", inst, 2, 3400.0, MATCH_CONFIRMED)], started=rebuy_start),
        user_id=user.id,
    )
    db_session.refresh(item)
    assert item.held_state == HELD and item.quantity == 2 and item.buy_price == 3400.0
    assert item.added_at == datetime(2026, 12, 1, tzinfo=IST)
    assert item.note == "keep"
    added = _history(db_session, item, "added_at")
    assert len(added) == 1
    assert added[0].old_value == ORIGINAL_ADDED.isoformat()
    assert added[0].new_value == datetime(2026, 12, 1, tzinfo=IST).isoformat()


def test_removed_row_held_in_groww_is_re_added_with_history(db_session, user):
    inst = _inst(db_session, "ASIANPAINT")
    removed = datetime(2026, 11, 1, tzinfo=UTC)
    item = _item(db_session, user, "ASIANPAINT", removed_at=removed, quantity=1, buy_price=2800.0)
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE021A01026", inst, 1, 2800.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    db_session.refresh(item)
    assert item.removed_at is None and item.held_state == HELD
    hist = _history(db_session, item, "removed_at")
    assert [(c.old_value, c.new_value) for c in hist] == [(removed.isoformat(), None)]


def test_non_complete_sync_is_never_applied(db_session, user):
    inst = _inst(db_session, "DLF")
    item = _item(db_session, user, "DLF", quantity=1, buy_price=800.0)
    sync = _sync(db_session, [("INE271C01023", inst, 9, 900.0, MATCH_CONFIRMED)], status=SYNC_EMPTY)
    gapply.apply_sync(db_session, sync, user_id=user.id)
    db_session.refresh(item)
    assert item.quantity == 1 and _history(db_session, item) == []


def test_confirm_empty_marks_all_linked_rows_not_held(db_session, user):
    inst = _inst(db_session, "HAL")
    item = _item(db_session, user, "HAL", quantity=2, buy_price=4000.0)
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE066F01020", inst, 2, 4000.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    empty = _sync(db_session, [], status=SYNC_EMPTY)
    db_session.refresh(item)
    assert item.held_state == HELD
    gapply.confirm_empty(db_session, user_id=user.id, sync_id=empty.id)
    db_session.refresh(item)
    db_session.refresh(empty)
    assert empty.status == SYNC_COMPLETE
    assert item.held_state == NOT_HELD and item.removed_at is None


def test_confirm_empty_rejects_a_sync_that_is_not_empty(db_session, user):
    sync = _sync(db_session, [])
    with pytest.raises(ValueError):
        gapply.confirm_empty(db_session, user_id=user.id, sync_id=sync.id)


def test_confirm_match_saves_alias_and_applies(db_session, user):
    inst = _inst(db_session, "BAJFINANCE")
    sync = _sync(db_session, [("INE296A01024", None, 3, 7000.0, MATCH_NEEDS)])
    gapply.confirm_match(db_session, user_id=user.id, isin="INE296A01024", instrument_id=inst.id)
    alias = db_session.query(StockAlias).filter_by(provider="groww", external_id="INE296A01024").one()
    assert alias.instrument_id == inst.id and alias.confirmed_by_user_id == user.id
    assert alias.confirmed_at is not None
    row = db_session.query(GrowwHolding).filter_by(sync_id=sync.id).one()
    assert row.match_state == MATCH_CONFIRMED and row.instrument_id == inst.id
    item = db_session.query(UserWatchlistItem).filter_by(user_id=user.id, symbol="BAJFINANCE").one()
    assert item.quantity == 3 and item.held_state == HELD


def test_confirm_all_suggested(db_session, user):
    a = _inst(db_session, "CIPLA")
    b = _inst(db_session, "DRREDDY")
    sync = _sync(
        db_session,
        [
            ("INE059A01026", a, 1, 1500.0, MATCH_SUGGESTED),
            ("INE089A01031", b, 2, 6000.0, MATCH_SUGGESTED),
            ("INE000X00000", None, 1, 10.0, MATCH_NEEDS),
        ],
    )
    assert gapply.confirm_all_suggested(db_session, user_id=user.id) == 2
    states = {h.isin: h.match_state for h in db_session.query(GrowwHolding).filter_by(sync_id=sync.id)}
    assert states == {
        "INE059A01026": MATCH_CONFIRMED,
        "INE089A01031": MATCH_CONFIRMED,
        "INE000X00000": MATCH_NEEDS,
    }
    assert db_session.query(StockAlias).filter_by(provider="groww").count() == 2
    symbols = {i.symbol for i in db_session.query(UserWatchlistItem).filter_by(user_id=user.id)}
    assert symbols == {"CIPLA", "DRREDDY"}


def test_held_clause_and_held_symbols(db_session, user):
    _item(db_session, user, "HELDG", held_state=HELD, source=SOURCE_GROWW, groww_isin="X1")
    _item(db_session, user, "GONE", held_state=NOT_HELD, source=SOURCE_GROWW, groww_isin="X2")
    _item(db_session, user, "MANUALBUY", buy_price=100.0)
    _item(db_session, user, "WATCHONLY")
    _item(db_session, user, "LINKEDMANUAL", buy_price=100.0, held_state=NOT_HELD, groww_isin="X3")
    held = {
        i.symbol
        for i in db_session.query(UserWatchlistItem)
        .filter(UserWatchlistItem.user_id == user.id, gapply.is_currently_held_clause())
        .all()
    }
    assert held == {"HELDG", "MANUALBUY"}
    assert gapply.groww_held_symbols(db_session) == ["HELDG"]


# --- run_sync wiring -----------------------------------------------------------------------


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def eval(self, script, numkeys, key, token):
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture()
def wired(db_session, monkeypatch, user):
    monkeypatch.setattr(gsync, "_get_redis", _FakeRedis)
    inst = _inst(db_session, "RELIANCE")
    db_session.add(StockAlias(provider="groww", external_id="INE002A01018", instrument_id=inst.id))
    db_session.flush()
    rows = [{"isin": "INE002A01018", "trading_symbol": "RELIANCE-EQ", "quantity": 10, "average_price": 100.5}]
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: rows)
    return inst


def test_two_identical_complete_syncs_are_idempotent(db_session, user, wired):
    item = _item(db_session, user, "RELIANCE", quantity=4, buy_price=95.0, note="n")
    first = gsync.run_sync(db_session, user_id=user.id, trigger="manual")
    db_session.refresh(item)
    after_first = (item.quantity, item.buy_price, item.held_state, item.groww_isin, item.added_at, item.note)
    history_first = [(c.field, c.old_value, c.new_value, c.sync_id) for c in _history(db_session, item)]

    second = gsync.run_sync(db_session, user_id=user.id, trigger="manual")
    db_session.refresh(item)
    after_second = (item.quantity, item.buy_price, item.held_state, item.groww_isin, item.added_at, item.note)
    history_second = [(c.field, c.old_value, c.new_value, c.sync_id) for c in _history(db_session, item)]

    assert first.status == second.status == SYNC_COMPLETE
    assert after_first == after_second == (10, 100.5, HELD, "INE002A01018", ORIGINAL_ADDED, "n")
    assert history_first == history_second
    assert history_first and all(sync_id == first.id for *_, sync_id in history_first)
    assert item.groww_synced_at == second.finished_at


def test_apply_error_keeps_stored_sync_and_never_raises(db_session, user, wired, caplog, monkeypatch):
    item = _item(db_session, user, "RELIANCE", quantity=4, buy_price=95.0)

    def boom(*args, **kwargs):
        db_session.add(UserWatchlistItemChange(item_id=item.id, field="x", changed_by="groww_sync"))
        db_session.flush()
        raise RuntimeError("secret detail in apply")

    monkeypatch.setattr(gapply, "apply_sync", boom)
    sync = gsync.run_sync(db_session, user_id=user.id, trigger="manual")
    assert sync.status == SYNC_COMPLETE
    assert db_session.query(GrowwSync).filter_by(id=sync.id).count() == 1
    assert db_session.query(GrowwHolding).filter_by(sync_id=sync.id).count() == 1
    assert _history(db_session, item) == []  # the failed apply was rolled back
    db_session.refresh(item)
    assert item.quantity == 4
    assert "secret detail" not in caplog.text
