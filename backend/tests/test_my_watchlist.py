"""My Watchlist (new look, wave 2): every signed-in person keeps their own list.

The security rule under test (api/deps.py SELF_SERVICE_ROUTES): these few routes
are open to any signed-in person whatever their role or plan, the handlers only
touch the caller's own rows, and the API key (no person behind it) is refused.
Nothing here reaches the bot's global watchlist or any trading path.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, select, text

from swing_trade_ml.api.deps import SELF_SERVICE_ROUTES
from swing_trade_ml.api.v1.endpoints.my_watchlist import MAX_ITEMS
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem

URL = "/api/v1/me/watchlist"
API_KEY = {"X-API-Key": "test-api-key"}


def _as(db, username: str, role: str, plan: str = "free") -> tuple[User, dict[str, str]]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan=plan)
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


@pytest.fixture()
def stocks(db_session):
    rows = [
        Instrument(
            instrument_token=990_001, tradingsymbol="WLTESTA", name="Watch Test Alpha", exchange="NSE"
        ),
        Instrument(instrument_token=990_002, tradingsymbol="WLTESTB", name="Watch Test Beta", exchange="NSE"),
        Instrument(
            instrument_token=990_003, tradingsymbol="WLGONE", name="Delisted", exchange="NSE", is_active=False
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


@pytest.mark.parametrize("role", ["owner", "tester", "member"])
def test_every_role_keeps_its_own_list(client, db_session, stocks, role):
    _, me = _as(db_session, f"wl-{role}", role)
    assert client.get(URL, headers=me).json() == {"items": [], "limit": MAX_ITEMS}

    r = client.post(URL, json={"symbol": " wltesta "}, headers=me)
    assert r.status_code == 201, r.text
    assert r.json()["symbol"] == "WLTESTA" and r.json()["name"] == "Watch Test Alpha"

    items = client.get(URL, headers=me).json()["items"]
    assert [i["symbol"] for i in items] == ["WLTESTA"] and items[0]["removed_at"] is None

    r = client.delete(f"{URL}/WLTESTA", headers=me)
    assert r.status_code == 200 and r.json()["removed_at"] is not None
    items = client.get(URL, headers=me).json()["items"]
    assert items[0]["removed_at"] is not None  # kept under "Removed"


def test_member_on_free_plan_with_no_features_may_use_it(client, db_session, stocks):
    _, me = _as(db_session, "wl-free", "member", plan="free")
    assert client.post(URL, json={"symbol": "WLTESTB"}, headers=me).status_code == 201
    assert client.get(f"{URL}/search?q=wltest", headers=me).status_code == 200


def test_nobody_sees_or_changes_someone_elses_list(client, db_session, stocks):
    alice, a = _as(db_session, "wl-alice", "member")
    _, b = _as(db_session, "wl-bob", "tester")
    assert client.post(URL, json={"symbol": "WLTESTA"}, headers=a).status_code == 201

    assert client.get(URL, headers=b).json()["items"] == []
    # Bob cannot remove Alice's stock: it is not on HIS list.
    assert client.delete(f"{URL}/WLTESTA", headers=b).status_code == 404
    # A user id in the body is ignored: the row always belongs to the caller.
    assert client.post(URL, json={"symbol": "WLTESTB", "user_id": alice.id}, headers=b).status_code == 201
    mine = db_session.execute(
        select(UserWatchlistItem).where(UserWatchlistItem.user_id == alice.id)
    ).scalars()
    assert [r.symbol for r in mine] == ["WLTESTA"]
    assert client.get(URL, headers=a).json()["items"][0]["removed_at"] is None


def test_api_key_is_refused(client, db_session, stocks):
    assert client.get(URL, headers=API_KEY).status_code == 403
    assert client.post(URL, json={"symbol": "WLTESTA"}, headers=API_KEY).status_code == 403
    assert client.delete(f"{URL}/WLTESTA", headers=API_KEY).status_code == 403
    assert client.get(f"{URL}/search?q=WL", headers=API_KEY).status_code == 403


def test_no_credentials_is_refused(client):
    assert client.get(URL).status_code == 401
    assert client.post(URL, json={"symbol": "WLTESTA"}).status_code == 401


def test_unknown_inactive_or_malformed_symbol_is_refused(client, db_session, stocks):
    _, me = _as(db_session, "wl-bad", "member")
    assert client.post(URL, json={"symbol": "NOSUCHSTOCK"}, headers=me).status_code == 404
    assert client.post(URL, json={"symbol": "WLGONE"}, headers=me).status_code == 404
    assert client.post(URL, json={"symbol": "DROP TABLE;"}, headers=me).status_code == 422
    assert client.get(URL, headers=me).json()["items"] == []


def test_adding_twice_is_harmless_and_re_adding_brings_it_back(client, db_session, stocks):
    _, me = _as(db_session, "wl-twice", "member")
    client.post(URL, json={"symbol": "WLTESTA"}, headers=me)
    assert client.post(URL, json={"symbol": "WLTESTA"}, headers=me).status_code == 201
    client.delete(f"{URL}/WLTESTA", headers=me)
    assert client.delete(f"{URL}/WLTESTA", headers=me).status_code == 404  # already removed
    client.post(URL, json={"symbol": "WLTESTA", "note": "  results soon "}, headers=me)
    items = client.get(URL, headers=me).json()["items"]
    assert len(items) == 1 and items[0]["removed_at"] is None and items[0]["note"] == "results soon"


def test_list_is_capped(client, db_session, stocks):
    user, me = _as(db_session, "wl-full", "member")
    for i in range(MAX_ITEMS):
        db_session.add(UserWatchlistItem(user_id=user.id, symbol=f"FILL{i}"))
    db_session.flush()
    r = client.post(URL, json={"symbol": "WLTESTA"}, headers=me)
    assert r.status_code == 409 and "full" in r.json()["detail"]
    # A removed stock frees a place.
    client.delete(f"{URL}/FILL0", headers=me)
    assert client.post(URL, json={"symbol": "WLTESTA"}, headers=me).status_code == 201


def test_search_finds_active_stocks_by_symbol_or_name(client, db_session, stocks):
    _, me = _as(db_session, "wl-search", "member")
    hits = client.get(f"{URL}/search?q=wltest", headers=me).json()
    assert [h["symbol"] for h in hits] == ["WLTESTA", "WLTESTB"]
    assert [h["symbol"] for h in client.get(f"{URL}/search?q=beta", headers=me).json()] == ["WLTESTB"]
    assert client.get(f"{URL}/search?q=wlgone", headers=me).json() == []  # inactive left out
    assert client.get(f"{URL}/search?q=%25", headers=me).json() == []  # a % is not a wildcard


def test_global_watchlist_is_untouched(client, db_session, stocks):
    _, me = _as(db_session, "wl-global", "member")
    client.post(URL, json={"symbol": "WLTESTA"}, headers=me)
    db_session.refresh(stocks[0])
    assert stocks[0].is_watchlisted is False
    # The bot's global watchlist stays owner-only.
    assert (
        client.put("/api/v1/instruments/watchlist", json={"symbols": ["WLTESTA"]}, headers=me).status_code
        == 403
    )


def test_the_self_service_set_is_only_the_watchlist():
    assert {p for _, p in SELF_SERVICE_ROUTES} <= {
        "/me/watchlist",
        "/me/watchlist/search",
        "/me/watchlist/{symbol}",
        "/me/watchlist/tracker",
        "/me/watchlist/sold",
        "/me/watchlist/{symbol}/sold",
    }


def test_migration_downgrade_then_upgrade(db_session):
    path = Path(__file__).parents[1] / "alembic/versions/20261025_1200_user_watchlist.py"
    spec = spec_from_file_location("user_watchlist_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "a1e7r3s5t2u3"

    conn = db_session.connection()  # inside the test's transaction: rolled back afterwards
    # Later tables (Groww sync history) reference the list; drop them first, as a real downgrade would.
    conn.execute(text("DROP TABLE IF EXISTS user_watchlist_item_changes"))
    migration.op = Operations(MigrationContext.configure(conn))
    migration.downgrade()
    assert "user_watchlist_items" not in inspect(conn).get_table_names()
    migration.upgrade()
    cols = {c["name"] for c in inspect(conn).get_columns("user_watchlist_items")}
    assert {"id", "user_id", "symbol", "added_at", "removed_at", "note"} <= cols


# --- Groww-linked rows (Groww holdings sync) -------------------------------------------------------


def _groww_row(db, user, symbol, **kw):
    from swing_trade_ml.db.models.groww import HELD, SOURCE_GROWW

    kw.setdefault("source", SOURCE_GROWW)
    kw.setdefault("held_state", HELD)
    kw.setdefault("buy_price", 100.0)
    kw.setdefault("quantity", 10)
    item = UserWatchlistItem(user_id=user.id, symbol=symbol, **kw)
    db.add(item)
    db.flush()
    return item


def test_patch_quantity_on_linked_row_refused(client, db_session, stocks):
    owner, me = _as(db_session, "wl-gw-owner", "owner")
    linked = _groww_row(db_session, owner, "WLTESTA")
    # A manual row the person later linked by ISIN is protected too.
    isin_only = _groww_row(db_session, owner, "WLTESTB", source="manual", groww_isin="INE777A01011")
    msg = "This comes from Groww and updates on every sync."
    for sym in ("WLTESTA", "WLTESTB"):
        for body in ({"quantity": 3}, {"buy_price": 50.0}, {"quantity": 3, "note": "x"}):
            r = client.patch(f"{URL}/{sym}", json=body, headers=me)
            assert r.status_code == 409, r.text
            assert r.json()["detail"] == msg
    db_session.refresh(linked)
    db_session.refresh(isin_only)
    assert linked.quantity == 10 and linked.buy_price == 100.0 and linked.note is None
    assert isin_only.quantity == 10
    # The note is still the person's own.
    r = client.patch(f"{URL}/WLTESTA", json={"note": "long term"}, headers=me)
    assert r.status_code == 200 and r.json()["note"] == "long term"


def test_patch_quantity_on_manual_row_still_allowed(client, db_session, stocks):
    _, me = _as(db_session, "wl-manual", "member")
    client.post(URL, json={"symbol": "WLTESTA"}, headers=me)
    r = client.patch(f"{URL}/WLTESTA", json={"quantity": 4, "buy_price": 12.5}, headers=me)
    assert r.status_code == 200 and r.json()["quantity"] == 4 and r.json()["buy_price"] == 12.5


def _groww_drop(db, item, old: float, new: float):
    """Groww showed fewer shares (as a sync would record it), an hour ago."""
    from datetime import UTC, datetime, timedelta

    from swing_trade_ml.db.models.user_watchlist import UserWatchlistItemChange

    db.add(
        UserWatchlistItemChange(
            item_id=item.id,
            field="quantity",
            old_value=str(old),
            new_value=str(new),
            changed_by="groww_sync",
            changed_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    item.quantity = new
    db.flush()


def _sales(db, user):
    from swing_trade_ml.db.models.user_watchlist import UserWatchlistSale

    return db.execute(select(UserWatchlistSale).where(UserWatchlistSale.user_id == user.id)).scalars().all()


def test_sold_with_quantity_keeps_row_on_list(client, db_session, stocks):
    owner, me = _as(db_session, "wl-gw-seller", "owner")
    item = _groww_row(db_session, owner, "WLTESTA", groww_isin="INE778A01011")
    _groww_drop(db_session, item, 10.0, 7.0)
    zero = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 0}, headers=me)
    assert zero.status_code == 422
    r = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 3}, headers=me)
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 3
    db_session.refresh(item)
    assert item.removed_at is None  # still on the list; Groww decides when it is gone
    assert [s.quantity for s in _sales(db_session, owner)] == [3]


def test_linked_sale_cannot_be_confirmed_twice(client, db_session, stocks):
    owner, me = _as(db_session, "wl-gw-twice", "owner")
    item = _groww_row(db_session, owner, "WLTESTA", groww_isin="INE779A01011")
    _groww_drop(db_session, item, 10.0, 6.0)
    first = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0}, headers=me)
    assert first.status_code == 200, first.text
    assert first.json()["quantity"] == 4  # omitted: the shares Groww shows as gone
    for body in ({"sell_price": 110.0}, {"sell_price": 110.0, "quantity": 1}):
        again = client.post(f"{URL}/WLTESTA/sold", json=body, headers=me)
        assert again.status_code == 409
        assert again.json()["detail"] == "There is no unconfirmed sale for this stock."
    assert [s.quantity for s in _sales(db_session, owner)] == [4]


def test_linked_sale_without_a_groww_drop_is_refused(client, db_session, stocks):
    owner, me = _as(db_session, "wl-gw-nodrop", "owner")
    _groww_row(db_session, owner, "WLTESTA", groww_isin="INE780A01011")
    r = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 2}, headers=me)
    assert r.status_code == 409 and r.json()["detail"] == "There is no unconfirmed sale for this stock."
    assert _sales(db_session, owner) == []


def test_linked_sale_over_quantity_refused(client, db_session, stocks):
    owner, me = _as(db_session, "wl-gw-over", "owner")
    item = _groww_row(db_session, owner, "WLTESTA", groww_isin="INE781A01011")
    _groww_drop(db_session, item, 10.0, 7.0)
    r = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 4}, headers=me)
    assert r.status_code == 409 and r.json()["detail"] == "That is more shares than Groww shows as sold."
    assert _sales(db_session, owner) == []
    ok = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 3}, headers=me)
    assert ok.status_code == 200, ok.text


def test_sold_manual_row_still_leaves_the_list(client, db_session, stocks):
    _, me = _as(db_session, "wl-manual-seller", "member")
    client.post(URL, json={"symbol": "WLTESTA"}, headers=me)
    client.patch(f"{URL}/WLTESTA", json={"quantity": 4, "buy_price": 12.5}, headers=me)
    r = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 13.0}, headers=me)
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 4
    items = client.get(URL, headers=me).json()["items"]
    assert items[0]["removed_at"] is not None


# --- Codex review R-Q41-e4b8a192 ------------------------------------------------------------------


def _change(db, item, field: str, old, new, hours_ago: float):
    from datetime import UTC, datetime, timedelta

    from swing_trade_ml.db.models.user_watchlist import UserWatchlistItemChange

    db.add(
        UserWatchlistItemChange(
            item_id=item.id,
            field=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
            changed_by="groww_sync",
            changed_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        )
    )
    db.flush()


def test_linked_sale_retry_with_the_pending_count_it_saw_is_refused(client, db_session, stocks):
    """A lost response must not let a retry eat another part of the same drop: the screen sends the
    pending shares it showed, and the server refuses when that no longer matches."""
    owner, me = _as(db_session, "wl-gw-retry", "owner")
    item = _groww_row(db_session, owner, "WLTESTA", groww_isin="INE782A01011")
    _groww_drop(db_session, item, 10.0, 4.0)
    body = {"sell_price": 110.0, "quantity": 2, "pending_qty": 6}
    first = client.post(f"{URL}/WLTESTA/sold", json=body, headers=me)
    assert first.status_code == 200, first.text
    again = client.post(f"{URL}/WLTESTA/sold", json=body, headers=me)
    assert again.status_code == 409
    assert "changed" in again.json()["detail"]
    assert [s.quantity for s in _sales(db_session, owner)] == [2]
    # Without the count (an older screen) the old rules still apply.
    ok = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 1}, headers=me)
    assert ok.status_code == 200, ok.text


def test_linked_sale_after_a_rebuy_uses_the_sold_holdings_date_and_price(client, db_session, stocks):
    """Sold all four, then Groww showed four bought back at a higher price: the pending sale is of the
    OLD holding, so it keeps the old buy date and price, and its own sell date is allowed."""
    from datetime import UTC, datetime, timedelta

    from swing_trade_ml.services import watchlist_tracker as tracker

    owner, me = _as(db_session, "wl-gw-rebuy", "owner")
    old_added = datetime.now(UTC) - timedelta(days=20)
    new_added = datetime.now(UTC) - timedelta(days=1)
    item = _groww_row(db_session, owner, "WLTESTA", groww_isin="INE783A01011", added_at=old_added)
    item.quantity = 4.0
    _change(db_session, item, "quantity", 4.0, 0.0, hours_ago=72)  # sold: Groww shows none
    _change(db_session, item, "held_state", "held", "not_held", hours_ago=72)
    _change(db_session, item, "added_at", old_added.isoformat(), new_added.isoformat(), hours_ago=24)
    _change(db_session, item, "quantity", 0.0, 4.0, hours_ago=24)  # bought back
    _change(db_session, item, "buy_price", 100.0, 150.0, hours_ago=24)
    item.added_at, item.buy_price = new_added, 150.0
    db_session.flush()

    sold_on = (datetime.now(UTC) - timedelta(days=3)).astimezone(tracker.IST).date()
    r = client.post(
        f"{URL}/WLTESTA/sold", json={"sell_price": 120.0, "sold_on": sold_on.isoformat()}, headers=me
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["quantity"] == 4
    assert out["entry_price"] == 100.0
    assert out["bought_on"] == old_added.astimezone(tracker.IST).date().isoformat()


def test_linked_sale_of_zero_cost_shares_counts_the_whole_price_as_profit(client, db_session, stocks):
    """Groww shows a zero cost for bonus shares, and the sync keeps it as a real price: the sale's profit
    is the whole sale value, never worked out from a market close."""
    owner, me = _as(db_session, "wl-gw-bonus", "owner")
    item = _groww_row(db_session, owner, "WLTESTA", groww_isin="INE784A01011", buy_price=0.0)
    item.quantity = 5.0
    _groww_drop(db_session, item, 5.0, 0.0)
    r = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 120.0}, headers=me)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["entry_price"] == 0.0 and out["entry_source"] == "your_price"
    assert out["profit_amount"] == 600.0
    assert out["invested"] == 0.0
    assert out["return_pct"] is None  # a percentage of nothing is not a number
