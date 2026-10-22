"""fx8: who may read /beginner. Signed-in only; the bot's house book (evidence, held stocks) is the
owner's, so a tester is refused it; members have no plan rule for /beginner, so require_auth refuses
them; nothing from the real (My Holdings) book ever appears, whoever asks."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position, Strategy

API_KEY = {"X-API-Key": "test-api-key"}
SYM = "BXACCESS"


@pytest.fixture(autouse=True)
def _read_only_db_is_the_test_session(db_session):
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides[get_readonly_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_readonly_db, None)


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


@pytest.fixture()
def stock(db_session):
    inst = Instrument(instrument_token=889_101, tradingsymbol=SYM, name="Access Co", exchange="NSE")
    db_session.add(inst)
    db_session.flush()
    return inst


def test_no_credentials_is_refused(client, stock):
    for url in ("/beginner/evidence", "/beginner/events", f"/beginner/stock/{SYM}"):
        assert client.get(f"/api/v1{url}").status_code == 401, url


def test_owner_reads_every_beginner_route(client, db_session, stock):
    owner = _as(db_session, "bx-owner", "owner")
    for headers in (owner, API_KEY):
        for url in ("/beginner/evidence", "/beginner/events?scope=held", f"/beginner/stock/{SYM}"):
            assert client.get(f"/api/v1{url}", headers=headers).status_code == 200, url


def test_tester_gets_the_stock_brief_but_not_the_house_book(client, db_session, stock):
    tester = _as(db_session, "bx-tester", "tester")
    assert client.get(f"/api/v1/beginner/stock/{SYM}", headers=tester).status_code == 200
    assert client.get("/api/v1/beginner/events", headers=tester).status_code == 200
    assert client.get(f"/api/v1/beginner/events?symbol={SYM}", headers=tester).status_code == 200
    assert client.get("/api/v1/beginner/evidence", headers=tester).status_code == 403
    assert client.get("/api/v1/beginner/events?scope=held", headers=tester).status_code == 403


def test_member_is_refused_every_beginner_route(client, db_session, stock):
    member = _as(db_session, "bx-member", "member")
    for url in ("/beginner/evidence", "/beginner/events", f"/beginner/stock/{SYM}"):
        assert client.get(f"/api/v1{url}", headers=member).status_code == 403, url


def test_real_book_never_appears_even_for_the_real_account_owner(client, db_session, monkeypatch):
    """A stock held only in the real book (real_trading strategy) never shows in 'held' events,
    for an owner outside REAL_ACCOUNT_USERS and for the real-account owner alike."""
    from swing_trade_ml.db.models.feeds import UpcomingEvent

    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "bx-realowner")
    real = Strategy(name="real_trading", strategy_type="ml_swing", mode="live", is_active=True)
    db_session.add(real)
    db_session.flush()
    inst = Instrument(instrument_token=889_102, tradingsymbol="BXREALONLY", exchange="NSE")
    db_session.add(inst)
    db_session.flush()
    db_session.add(
        Position(
            strategy_id=real.id,
            instrument_id=inst.id,
            mode="paper",
            quantity=3,
            entry_price=100.0,
            entry_at=datetime.now(UTC),
            status=PositionStatus.OPEN,
        )
    )
    db_session.add(
        UpcomingEvent(symbol="BXREALONLY", kind="results", event_date=datetime.now(UTC).date(), detail="Q2")
    )
    db_session.flush()
    for who in ("bx-plainowner", "bx-realowner"):
        r = client.get("/api/v1/beginner/events?scope=held", headers=_as(db_session, who, "owner"))
        assert r.status_code == 200
        assert "BXREALONLY" not in r.text, who
        ev = client.get("/api/v1/beginner/evidence", headers=_as(db_session, who + "-2", "owner"))
        assert ev.status_code == 200 and "BXREALONLY" not in ev.text
