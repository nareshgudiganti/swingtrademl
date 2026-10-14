"""The Zerodha login keeps only the owner's own account (found in the permissions review, 2026-10-14).

/auth/kite/callback is public (Zerodha's redirect cannot carry our credentials) and used to store
whichever Zerodha account came back as THE broker session, retiring the owner's. Now a client ID other
than KITE_USER_ID is refused and the owner's session is left as it was.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.session import BrokerSession


@pytest.fixture
def zerodha(monkeypatch):
    answer = {"user_id": "AB1234", "user_name": "Owner", "access_token": "tok-new"}
    monkeypatch.setattr(kite_broker._kite, "generate_session", lambda request_token, api_secret: dict(answer))
    monkeypatch.setattr(kite_broker._kite, "set_access_token", lambda token: None)
    monkeypatch.setattr(settings, "KITE_USER_ID", "AB1234")
    return answer


def _owner_session(db) -> BrokerSession:
    s = BrokerSession(broker="zerodha", kite_user_id="AB1234", access_token="tok-old", is_active=True)
    db.add(s)
    db.flush()
    return s


def test_the_owners_own_login_is_kept(db_session, zerodha):
    session = kite_broker.complete_login("req", db_session)
    assert session.kite_user_id == "AB1234" and session.is_active


def test_a_lower_case_client_id_in_settings_never_locks_the_owner_out(db_session, zerodha, monkeypatch):
    monkeypatch.setattr(settings, "KITE_USER_ID", " ab1234 ")
    assert kite_broker.complete_login("req", db_session).kite_user_id == "AB1234"


def test_without_a_configured_client_id_the_login_is_kept_as_before(db_session, zerodha, monkeypatch):
    monkeypatch.setattr(settings, "KITE_USER_ID", None)
    zerodha["user_id"] = "ZZ9999"
    assert kite_broker.complete_login("req", db_session).kite_user_id == "ZZ9999"


def test_someone_elses_zerodha_login_is_refused_and_the_owners_session_kept(db_session, zerodha):
    old = _owner_session(db_session)
    zerodha["user_id"] = "ZZ9999"
    with pytest.raises(PermissionError, match="not the owner's Zerodha account"):
        kite_broker.complete_login("req", db_session)
    db_session.refresh(old)
    assert old.is_active
    active = (
        db_session.execute(select(BrokerSession).where(BrokerSession.is_active.is_(True))).scalars().all()
    )
    assert [s.kite_user_id for s in active] == ["AB1234"]


def test_the_callback_page_says_why_it_refused(client, db_session, zerodha):
    zerodha["user_id"] = "ZZ9999"
    r = client.get("/api/v1/auth/kite/callback?request_token=req")
    assert r.status_code == 400 and "not the owner" in r.text


def test_the_session_status_needs_a_login(client):
    assert client.get("/api/v1/auth/kite/session").status_code in (401, 403)
    assert client.get("/api/v1/auth/kite/session", headers={"X-API-Key": "test-api-key"}).status_code == 200
