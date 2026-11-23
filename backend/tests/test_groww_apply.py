"""Groww sync -> Groww Tracker: apply complete syncs, keep every overwritten value in history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


# --- fix round 1 ---------------------------------------------------------------------------


def test_confirm_empty_rejects_when_a_newer_complete_sync_exists(db_session, user):
    inst = _inst(db_session, "PIDILITIND")
    item = _item(db_session, user, "PIDILITIND", quantity=2, buy_price=2500.0)
    empty = _sync(db_session, [], status=SYNC_EMPTY)
    newer = _sync(db_session, [("INE318A01026", inst, 2, 2500.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, newer, user_id=user.id)
    with pytest.raises(ValueError):
        gapply.confirm_empty(db_session, user_id=user.id, sync_id=empty.id)
    db_session.refresh(item)
    db_session.refresh(empty)
    assert empty.status == SYNC_EMPTY
    assert item.held_state == HELD and item.quantity == 2


def test_confirm_empty_rejects_when_any_newer_sync_exists(db_session, user):
    empty = _sync(db_session, [], status=SYNC_EMPTY)
    db_session.add(GrowwSync(trigger="manual", status="failed", error_code="auth"))
    db_session.flush()
    with pytest.raises(ValueError):
        gapply.confirm_empty(db_session, user_id=user.id, sync_id=empty.id)


def _snapshot(db, item):
    db.refresh(item)
    return (item.quantity, item.buy_price, item.held_state, item.groww_isin, item.added_at, item.removed_at)


def test_same_isin_twice_in_one_sync_is_not_applied(db_session, user):
    inst = _inst(db_session, "GAIL")
    item = _item(db_session, user, "GAIL", quantity=10, buy_price=180.0)
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE129A01019", inst, 10, 180.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    before = _snapshot(db_session, item)
    history_before = len(_history(db_session, item))
    rows = [
        ("INE129A01019", inst, 6, 180.0, MATCH_CONFIRMED),
        ("INE129A01019", inst, 4, 180.0, MATCH_CONFIRMED),
    ]
    for _ in range(2):  # a second identical sync stays a no-op
        counts = gapply.apply_sync(db_session, _sync(db_session, rows), user_id=user.id)
        assert counts["needs_matching"] == 2 and counts["not_held"] == 0 and counts["pending_sale"] == 0
    assert _snapshot(db_session, item) == before
    assert len(_history(db_session, item)) == history_before
    assert gapply.pending_sale_qty(db_session, item) is None


def test_two_isins_matched_to_one_stock_are_not_applied(db_session, user):
    inst = _inst(db_session, "IOC")
    item = _item(db_session, user, "IOC", quantity=5, buy_price=150.0)
    gapply.apply_sync(
        db_session, _sync(db_session, [("INE242A01010", inst, 5, 150.0, MATCH_CONFIRMED)]), user_id=user.id
    )
    before = _snapshot(db_session, item)
    history_before = len(_history(db_session, item))
    rows = [
        ("INE242A01010", inst, 5, 150.0, MATCH_CONFIRMED),
        ("INE999X01010", inst, 3, 155.0, MATCH_CONFIRMED),
    ]
    for _ in range(2):
        counts = gapply.apply_sync(db_session, _sync(db_session, rows), user_id=user.id)
        assert counts["needs_matching"] == 2 and counts["updated"] == 0 and counts["not_held"] == 0
    assert _snapshot(db_session, item) == before
    assert len(_history(db_session, item)) == history_before


def test_conflicting_rows_never_create_a_new_row(db_session, user):
    inst = _inst(db_session, "BPCL")
    rows = [
        ("INE029A01011", inst, 1, 300.0, MATCH_CONFIRMED),
        ("INE029A01011", inst, 2, 300.0, MATCH_CONFIRMED),
    ]
    gapply.apply_sync(db_session, _sync(db_session, rows), user_id=user.id)
    assert db_session.query(UserWatchlistItem).filter_by(user_id=user.id, symbol="BPCL").count() == 0


def test_isin_rematched_to_another_stock_unlinks_old_row(db_session, user):
    old = _inst(db_session, "OLDSTOCK")
    new = _inst(db_session, "NEWSTOCK")
    item = _item(db_session, user, "OLDSTOCK", quantity=4, buy_price=50.0, note="kept")
    sync = _sync(db_session, [("INE777Q01011", old, 4, 50.0, MATCH_CONFIRMED)])
    gapply.apply_sync(db_session, sync, user_id=user.id)
    db_session.refresh(item)
    assert item.groww_isin == "INE777Q01011" and item.held_state == HELD

    gapply.confirm_match(db_session, user_id=user.id, isin="INE777Q01011", instrument_id=new.id)

    db_session.refresh(item)
    assert item.held_state == NOT_HELD and item.groww_isin is None
    assert item.removed_at is None and item.note == "kept"
    isin_hist = _history(db_session, item, "groww_isin")
    assert (isin_hist[-1].old_value, isin_hist[-1].new_value) == ("INE777Q01011", None)
    moved = db_session.query(UserWatchlistItem).filter_by(user_id=user.id, symbol="NEWSTOCK").one()
    assert moved.groww_isin == "INE777Q01011" and moved.quantity == 4 and moved.held_state == HELD

    # Re-applying the same sync changes nothing more.
    count_before = db_session.query(UserWatchlistItemChange).count()
    gapply.apply_sync(db_session, sync, user_id=user.id)
    assert db_session.query(UserWatchlistItemChange).count() == count_before


# --- #388 backend: confirming part of a drop keeps asking for the rest ---------------


def _step(db, user, isin, inst, qty):
    """One complete sync that shows `qty` shares of `inst`, applied to the owner's tracker."""
    gapply.apply_sync(db, _sync(db, [(isin, inst, qty, 100.0, MATCH_CONFIRMED)]), user_id=user.id)


def _sale(db, user, symbol, quantity, when):
    db.add(
        UserWatchlistSale(
            user_id=user.id, symbol=symbol, bought_on=ORIGINAL_ADDED.date(), entry_price=100.0,
            entry_source="your_price", quantity=quantity, sell_price=110.0,
            sold_on=datetime(2026, 11, 22).date(), created_at=when,
        )
    )
    db.flush()


def test_confirming_part_of_a_drop_leaves_the_rest_to_confirm(db_session, user):
    inst = _inst(db_session, "PARTSALE")
    item = _item(db_session, user, "PARTSALE", quantity=10, buy_price=100.0)
    _step(db_session, user, "INE0PS001011", inst, 10)
    _step(db_session, user, "INE0PS001011", inst, 4)
    assert gapply.pending_sale_qty(db_session, item) == 6
    _sale(db_session, user, "PARTSALE", 4, datetime.now(UTC) + timedelta(seconds=1))
    assert gapply.pending_sale_qty(db_session, item) == 2
    _sale(db_session, user, "PARTSALE", 2, datetime.now(UTC) + timedelta(seconds=2))
    assert gapply.pending_sale_qty(db_session, item) is None


def test_a_sale_larger_than_the_drop_never_leaves_a_negative_pending(db_session, user):
    inst = _inst(db_session, "BIGSALE")
    item = _item(db_session, user, "BIGSALE", quantity=10, buy_price=100.0)
    _step(db_session, user, "INE0BS001011", inst, 10)
    _step(db_session, user, "INE0BS001011", inst, 8)
    _sale(db_session, user, "BIGSALE", 5, datetime.now(UTC))  # after the drop, before the next sync
    assert gapply.pending_sale_qty(db_session, item) is None
    _step(db_session, user, "INE0BS001011", inst, 7)
    assert gapply.pending_sale_qty(db_session, item) == 1


def test_a_sale_with_no_quantity_clears_everything_before_it(db_session, user):
    inst = _inst(db_session, "NOQTY")
    item = _item(db_session, user, "NOQTY", quantity=10, buy_price=100.0)
    _step(db_session, user, "INE0NQ001011", inst, 10)
    _step(db_session, user, "INE0NQ001011", inst, 3)
    _sale(db_session, user, "NOQTY", None, datetime.now(UTC) + timedelta(seconds=1))
    assert gapply.pending_sale_qty(db_session, item) is None


# --- #388 owner decision D1: a stock removed or sold by hand and held again restarts its buy date --

REBUY_START = datetime(2026, 12, 2, 4, 0, tzinfo=UTC)
REBUY_DAY = datetime(2026, 12, 2, tzinfo=IST)


def _held_again(db, user, symbol, isin, inst, qty=3, avg=130.0, started=REBUY_START):
    sync = _sync(db, [(isin, inst, qty, avg, MATCH_CONFIRMED)], started=started)
    gapply.apply_sync(db, sync, user_id=user.id)


def test_a_removed_row_held_again_restarts_the_buy_date_with_history(db_session, user):
    inst = _inst(db_session, "REBUYONE")
    removed = datetime(2026, 11, 1, tzinfo=UTC)
    item = _item(db_session, user, "REBUYONE", removed_at=removed, quantity=1, buy_price=50.0, note="mine")
    _held_again(db_session, user, "REBUYONE", "INE0RB001011", inst)
    db_session.refresh(item)
    assert item.removed_at is None and item.held_state == HELD
    assert item.added_at == REBUY_DAY
    assert item.note == "mine"
    (moved,) = _history(db_session, item, "added_at")
    assert (moved.old_value, moved.new_value) == (ORIGINAL_ADDED.isoformat(), REBUY_DAY.isoformat())


def test_a_row_sold_by_hand_and_held_again_restarts_the_buy_date(db_session, user):
    inst = _inst(db_session, "REBUYTWO")
    item = _item(db_session, user, "REBUYTWO", quantity=2, buy_price=50.0)
    item.removed_at = datetime(2026, 11, 20, tzinfo=UTC)  # what the Sold button does to a hand-entered row
    db_session.flush()
    _held_again(db_session, user, "REBUYTWO", "INE0RB002011", inst)
    db_session.refresh(item)
    assert item.added_at == REBUY_DAY and item.removed_at is None


def test_the_restart_happens_once_and_a_repeated_or_topped_up_sync_never_moves_it(db_session, user):
    inst = _inst(db_session, "REBUYTHREE")
    gone = datetime(2026, 11, 1, tzinfo=UTC)
    item = _item(db_session, user, "REBUYTHREE", removed_at=gone, quantity=1, buy_price=50.0)
    _held_again(db_session, user, "REBUYTHREE", "INE0RB003011", inst, qty=3)
    isin = "INE0RB003011"
    _held_again(db_session, user, "REBUYTHREE", isin, inst, qty=3, started=REBUY_START.replace(day=3))
    later = REBUY_START.replace(day=4)
    _held_again(db_session, user, "REBUYTHREE", isin, inst, qty=9, avg=140.0, started=later)
    db_session.refresh(item)
    assert item.added_at == REBUY_DAY and item.quantity == 9
    assert len(_history(db_session, item, "added_at")) == 1


def test_confirming_a_sale_of_a_listed_linked_row_never_moves_the_buy_date(db_session, user):
    inst = _inst(db_session, "KEEPDATE")
    item = _item(db_session, user, "KEEPDATE", quantity=10, buy_price=100.0)
    _step(db_session, user, "INE0KD001011", inst, 10)
    _step(db_session, user, "INE0KD001011", inst, 4)
    _sale(db_session, user, "KEEPDATE", 6, datetime.now(UTC) + timedelta(seconds=1))
    _step(db_session, user, "INE0KD001011", inst, 4)
    db_session.refresh(item)
    assert item.added_at == ORIGINAL_ADDED and item.removed_at is None
    assert _history(db_session, item, "added_at") == []


# --- a confirmation applies only what it confirmed, and never to a row changed after that sync ----------


def _after(sync):
    return sync.finished_at + timedelta(hours=3)


def _frozen(item):
    return (item.removed_at, item.quantity, item.buy_price, item.added_at, item.held_state, item.groww_isin)


def test_confirm_match_does_not_bring_back_a_row_removed_after_the_sync(db_session, user):
    kept = _inst(db_session, "RESURRECTA")
    other = _inst(db_session, "CONFIRMB")
    sync = _sync(
        db_session,
        [
            ("INE111A01011", kept, 5, 100.0, MATCH_CONFIRMED),
            ("INE222B01022", None, 3, 200.0, MATCH_NEEDS),
        ],
    )
    item = _item(
        db_session, user, "RESURRECTA", quantity=9, buy_price=90.0, groww_isin="INE111A01011",
        held_state=HELD, removed_at=_after(sync),
    )
    before, changes = _frozen(item), len(_history(db_session, item))
    gapply.confirm_match(db_session, user_id=user.id, isin="INE222B01022", instrument_id=other.id)
    db_session.refresh(item)
    assert _frozen(item) == before
    assert len(_history(db_session, item)) == changes
    confirmed = db_session.query(UserWatchlistItem).filter_by(user_id=user.id, symbol="CONFIRMB").one()
    assert confirmed.quantity == 3


def test_confirm_all_suggested_does_not_bring_back_a_row_removed_after_the_sync(db_session, user):
    kept = _inst(db_session, "RESURRECTC")
    a = _inst(db_session, "SUGGESTD")
    sync = _sync(
        db_session,
        [
            ("INE333C01033", kept, 5, 100.0, MATCH_CONFIRMED),
            ("INE444D01044", a, 2, 50.0, MATCH_SUGGESTED),
        ],
    )
    item = _item(
        db_session, user, "RESURRECTC", quantity=9, buy_price=90.0, groww_isin="INE333C01033",
        held_state=HELD, removed_at=_after(sync),
    )
    before = _frozen(item)
    assert gapply.confirm_all_suggested(db_session, user_id=user.id) == 1
    db_session.refresh(item)
    assert _frozen(item) == before
    new = db_session.query(UserWatchlistItem).filter_by(user_id=user.id, symbol="SUGGESTD").one()
    assert new.quantity == 2


def test_a_confirmed_stock_removed_after_the_sync_stays_removed(db_session, user):
    inst = _inst(db_session, "REMOVEDE")
    sync = _sync(db_session, [("INE555E01055", None, 4, 70.0, MATCH_NEEDS)])
    item = _item(db_session, user, "REMOVEDE", quantity=1, buy_price=60.0, removed_at=_after(sync))
    before = _frozen(item)
    gapply.confirm_match(db_session, user_id=user.id, isin="INE555E01055", instrument_id=inst.id)
    db_session.refresh(item)
    assert _frozen(item) == before


def test_a_stock_removed_before_the_sync_restarts_when_its_match_is_confirmed(db_session, user):
    inst = _inst(db_session, "REMOVEDF")
    sync = _sync(db_session, [("INE666F01066", None, 4, 70.0, MATCH_NEEDS)])
    item = _item(
        db_session,
        user,
        "REMOVEDF",
        quantity=1,
        buy_price=60.0,
        removed_at=sync.finished_at - timedelta(days=2),
    )
    gapply.confirm_match(db_session, user_id=user.id, isin="INE666F01066", instrument_id=inst.id)
    db_session.refresh(item)
    assert item.removed_at is None and item.quantity == 4 and item.added_at == SYNC_DAY


def test_confirm_empty_does_not_touch_a_row_removed_after_the_sync(db_session, user):
    sync = _sync(db_session, [], status=SYNC_EMPTY)
    item = _item(
        db_session, user, "REMOVEDG", quantity=2, buy_price=10.0, groww_isin="INE777G01077",
        held_state=HELD, source=SOURCE_GROWW, removed_at=_after(sync),
    )
    before = _frozen(item)
    gapply.confirm_empty(db_session, user_id=user.id, sync_id=sync.id)
    db_session.refresh(item)
    assert _frozen(item) == before


def test_a_confirmation_never_marks_an_unrelated_linked_row_not_held(db_session, user):
    other = _inst(db_session, "UNRELATEDH")
    target = _inst(db_session, "CONFIRMI")
    sync = _sync(db_session, [("INE888I01088", None, 2, 30.0, MATCH_NEEDS)])
    linked = _item(
        db_session, user, "UNRELATEDH", quantity=6, buy_price=40.0, groww_isin="INE999H01099",
        held_state=HELD, source=SOURCE_GROWW,
    )
    before = _frozen(linked)
    gapply.confirm_match(db_session, user_id=user.id, isin="INE888I01088", instrument_id=target.id)
    db_session.refresh(linked)
    assert _frozen(linked) == before and other.id and sync.id


# --- #388 follow-ups: removed stocks stop getting prices; pending sales are read in bulk ---


def test_held_symbols_for_prices_leave_out_rows_the_owner_removed(db_session, user):
    _item(db_session, user, "PRICEKEEP", quantity=1, buy_price=1.0, held_state=HELD, source=SOURCE_GROWW)
    _item(
        db_session, user, "PRICEGONE", quantity=1, buy_price=1.0, held_state=HELD, source=SOURCE_GROWW,
        removed_at=datetime(2026, 11, 20, tzinfo=UTC),
    )
    symbols = gapply.groww_held_symbols(db_session)
    assert "PRICEKEEP" in symbols and "PRICEGONE" not in symbols


def _drop(db, item, old, new, when):
    db.add(
        UserWatchlistItemChange(
            item_id=item.id, field="quantity", old_value=str(float(old)), new_value=str(float(new)),
            changed_by="groww_sync", changed_at=when,
        )
    )
    db.flush()


def test_pending_sales_in_bulk_equal_the_row_by_row_answer(db_session, user):
    start = datetime.now(UTC)
    items = []
    for n, symbol in enumerate(("BULKA", "BULKB", "BULKC", "BULKD"), start=1):
        item = _item(db_session, user, symbol, quantity=10 - n, buy_price=100.0, source=SOURCE_GROWW)
        if n >= 2:
            _drop(db_session, item, 10, 10 - n, start)  # Groww showed n shares gone
        if n == 3:
            _sale(db_session, user, symbol, 1, start + timedelta(seconds=1))  # one of them confirmed
        if n == 4:
            _sale(db_session, user, symbol, None, start + timedelta(seconds=1))  # all confirmed
        items.append(item)
    bulk = gapply.pending_sale_qty_for(db_session, items)
    assert bulk == {i.id: gapply.pending_sale_qty(db_session, i) for i in items}
    assert [bulk[i.id] for i in items] == [None, 2, 2, None]
    assert gapply.pending_sale_qty_for(db_session, []) == {}
