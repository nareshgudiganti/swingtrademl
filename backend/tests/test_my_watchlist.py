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
from sqlalchemy import inspect, select

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
    }


def test_migration_downgrade_then_upgrade(db_session):
    path = Path(__file__).parents[1] / "alembic/versions/20261025_1200_user_watchlist.py"
    spec = spec_from_file_location("user_watchlist_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "a1e7r3s5t2u3"

    conn = db_session.connection()  # inside the test's transaction: rolled back afterwards
    migration.op = Operations(MigrationContext.configure(conn))
    migration.downgrade()
    assert "user_watchlist_items" not in inspect(conn).get_table_names()
    migration.upgrade()
    cols = {c["name"] for c in inspect(conn).get_columns("user_watchlist_items")}
    assert {"id", "user_id", "symbol", "added_at", "removed_at", "note"} <= cols
