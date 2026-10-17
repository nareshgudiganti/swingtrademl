"""A tester (Vijay) keeps his manual paper-testing flow and nothing else."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import tester_paper


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def _open(db, strategy: Strategy, symbol: str) -> Position:
    inst = Instrument(instrument_token=abs(hash(symbol)) % 10_000_000, tradingsymbol=symbol, exchange="NSE")
    db.add(inst)
    db.flush()
    pos = Position(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        mode="paper",
        status="OPEN",
        quantity=1,
        initial_quantity=1,
        entry_price=100.0,
        entry_at=datetime.now(UTC),
    )
    db.add(pos)
    db.flush()
    return pos


def test_tester_cannot_close_a_house_position(client, db_session):
    house = Strategy(name="ml_swing_house_t", strategy_type="ml_swing", mode="paper", is_active=True)
    db_session.add(house)
    db_session.flush()
    pos = _open(db_session, house, "HOUSEPOS")
    r = client.post(
        f"/api/v1/portfolio/positions/{pos.id}/close",
        json={"reason": "MANUAL"},
        headers=_as(db_session, "t-close-house", "tester"),
    )
    assert r.status_code == 403


def test_tester_close_on_a_tester_position_passes_the_guard(client, db_session):
    pos = _open(db_session, tester_paper.get_or_create_strategy(db_session), "TESTPOS")
    r = client.post(
        f"/api/v1/portfolio/positions/{pos.id}/close",
        json={"reason": "MANUAL"},
        headers=_as(db_session, "t-close-own", "tester"),
    )
    assert r.status_code not in (401, 403), r.text  # got past the guards; the close itself may need a price


def test_tester_buy_route_passes_the_guard(client, db_session):
    r = client.post(
        "/api/v1/portfolio/tester/buy",
        json={"symbol": "NOPE", "quantity": 1, "cap_tier": "large"},
        headers=_as(db_session, "t-buy", "tester"),
    )
    assert r.status_code not in (401, 403), r.text  # 404 unknown symbol / disabled is fine


def test_tester_is_refused_every_other_write(client, db_session):
    tester = _as(db_session, "t-other", "tester")
    assert client.post("/api/v1/safety/halt", json={"reason": "x"}, headers=tester).status_code == 403
    assert (
        client.put("/api/v1/brain/stage", json={"stage": "shadow", "reason": "x"}, headers=tester).status_code
        == 403
    )
    assert client.post("/api/v1/portfolio/positions/manual", json={}, headers=tester).status_code == 403


def test_member_cannot_use_tester_routes(client, db_session):
    member = _as(db_session, "m-tester", "member")
    r = client.post(
        "/api/v1/portfolio/tester/buy",
        json={"symbol": "X", "quantity": 1, "cap_tier": "large"},
        headers=member,
    )
    assert r.status_code == 403
