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
    item = UserWatchlistItem(user_id=user.id, symbol=symbol, buy_price=100.0, quantity=10, **kw)
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


def test_sold_with_quantity_keeps_row_on_list(client, db_session, stocks):
    from swing_trade_ml.db.models.user_watchlist import UserWatchlistSale

    owner, me = _as(db_session, "wl-gw-seller", "owner")
    item = _groww_row(db_session, owner, "WLTESTA", groww_isin="INE778A01011")
    r = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 3}, headers=me)
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 3
    db_session.refresh(item)
    assert item.removed_at is None  # still on the list; Groww decides when it is gone
    sales = db_session.execute(
        select(UserWatchlistSale).where(UserWatchlistSale.user_id == owner.id)
    ).scalars().all()
    assert [s.quantity for s in sales] == [3]
    zero = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 110.0, "quantity": 0}, headers=me)
    assert zero.status_code == 422


def test_sold_manual_row_still_leaves_the_list(client, db_session, stocks):
    _, me = _as(db_session, "wl-manual-seller", "member")
    client.post(URL, json={"symbol": "WLTESTA"}, headers=me)
    client.patch(f"{URL}/WLTESTA", json={"quantity": 4, "buy_price": 12.5}, headers=me)
    r = client.post(f"{URL}/WLTESTA/sold", json={"sell_price": 13.0}, headers=me)
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 4
    items = client.get(URL, headers=me).json()["items"]
    assert items[0]["removed_at"] is not None
