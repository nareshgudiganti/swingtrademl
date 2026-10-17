"""The real Zerodha account (My Holdings, real orders) is private to the named users in
REAL_ACCOUNT_USERS. Other owners, ordinary users and plan users cannot see it, read its totals or
trade it, even when plans are switched off."""

from __future__ import annotations

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User

API = "/api/v1/portfolio"
PRIVATE_READS = [
    f"{API}/holdings",
    f"{API}/real/account",
    f"{API}/real/orders-status",
    f"{API}/real/quote?symbol=X",
    f"{API}/positions/detailed?book=real",
    f"{API}/trades?book=real",
    f"{API}/summary?book=real",
    "/api/v1/real-report",
]
PRIVATE_WRITES = [
    (f"{API}/real/buy", {"symbol": "X", "quantity": 1}),
    (f"{API}/real/positions/1/sell", {"quantity": 1}),
    (f"{API}/positions/import-holdings", None),
    ("/api/v1/real-report/sync", None),
]


def _login(db_session, name: str, owner: bool) -> dict[str, str]:
    user = User(username=name, hashed_password="x", is_active=True, is_superuser=owner, plan="free")
    db_session.add(user)
    db_session.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


@pytest.fixture(autouse=True)
def _named(monkeypatch):
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "sudeeksha")


@pytest.mark.parametrize("name", ["vijay", "naresh"])
def test_another_owner_account_cannot_see_the_real_account(client, db_session, name):
    h = _login(db_session, name, owner=True)
    for url in PRIVATE_READS:
        assert client.get(url, headers=h).status_code == 403, url


def test_an_ordinary_user_cannot_see_it_either(client, db_session):
    h = _login(db_session, "someone", owner=False)
    for url in PRIVATE_READS:
        assert client.get(url, headers=h).status_code == 403, url


@pytest.mark.parametrize("name", ["vijay", "someone"])
def test_nobody_else_can_buy_sell_or_import(client, db_session, name):
    h = _login(db_session, name, owner=name == "vijay")
    for url, body in PRIVATE_WRITES:
        assert client.post(url, json=body, headers=h).status_code == 403, url


def test_the_named_user_gets_past_the_guard(client, db_session):
    h = _login(db_session, "Sudeeksha", owner=True)  # case does not matter
    for url in (f"{API}/real/orders-status", f"{API}/positions/detailed?book=real"):
        assert client.get(url, headers=h).status_code != 403, url


def test_a_named_name_without_owner_rights_still_cannot(client, db_session):
    h = _login(db_session, "sudeeksha", owner=False)
    assert client.get(f"{API}/holdings", headers=h).status_code == 403


def test_totals_for_everyone_else_leave_the_real_book_out(client, db_session):
    h = _login(db_session, "vijay", owner=True)
    for url in (f"{API}/positions/detailed", f"{API}/trades", f"{API}/summary", f"{API}/positions?mode=live"):
        assert client.get(url, headers=h).status_code == 200, url


def test_the_menu_flag_tells_the_app_who_may_see_it(client, db_session):
    other = client.get("/api/v1/me/plan", headers=_login(db_session, "vijay", owner=True)).json()
    mine = client.get("/api/v1/me/plan", headers=_login(db_session, "sudeeksha", owner=True)).json()
    assert other["can_see_real_account"] is False and mine["can_see_real_account"] is True


def test_another_owner_cannot_close_a_real_holding(client, db_session):
    from datetime import UTC, datetime

    from swing_trade_ml.core.enums import PositionStatus, TradingMode
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Position

    inst = Instrument(instrument_token=884_001, tradingsymbol="ZZPRIV", exchange="NSE")
    db_session.add(inst)
    db_session.flush()
    pos = Position(
        instrument_id=inst.id,
        mode=TradingMode.LIVE,
        status=PositionStatus.OPEN,
        quantity=5,
        entry_price=100.0,
        current_price=100.0,
        entry_at=datetime.now(UTC),
    )
    db_session.add(pos)
    db_session.flush()
    h = _login(db_session, "vijay", owner=True)
    assert client.post(f"{API}/positions/{pos.id}/close", json={}, headers=h).status_code == 404
    manual = client.post(f"{API}/positions/{pos.id}/manual-close", json={"exit_price": 1}, headers=h)
    assert manual.status_code == 404
