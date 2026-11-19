"""Issue #373: a Google sign-in must finish in the browser that started it.

/google/login sets a short-lived HttpOnly cookie holding a random browser
secret. /google/callback refuses a state that was not issued to that same
browser (before Google's token exchange is ever called), and the one-time
login code it hands out only redeems with that same cookie. Google is faked.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from swing_trade_ml.api.v1.endpoints import auth as auth_endpoint
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.session import User

OWNER_EMAIL = "owner@example.com"
COOKIE = auth_endpoint.GOOGLE_BIND_COOKIE


class _Reply:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture()
def google(monkeypatch) -> dict[str, int]:
    """Google faked; counts how often its token exchange is called."""
    calls = {"token": 0}

    def _post(*_a, **_k):
        calls["token"] += 1
        return _Reply({"access_token": "g-token"})

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "GOOGLE_ALLOWED_EMAILS", OWNER_EMAIL)
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URL", "http://localhost:8000/api/v1/auth/google/callback")
    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _Reply({"sub": "g-bind-1", "email": OWNER_EMAIL, "email_verified": True}),
    )
    return calls


def _start(client) -> str:
    """Browser presses "Sign in with Google": returns the state sent to Google."""
    resp = client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert resp.status_code in (302, 307), resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def _callback(client, state: str):
    return client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)


def _login_code(resp) -> str:
    assert resp.status_code in (302, 307), resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["login_code"][0]


def _set_cookie_header(resp) -> str:
    headers = [h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{COOKIE}=")]
    assert len(headers) == 1, resp.headers.get_list("set-cookie")
    return headers[0].lower()


# ------------------------------------------------------------------ cookie --


def test_login_sets_an_httponly_lax_expiring_cookie(client, google):
    resp = client.get("/api/v1/auth/google/login", follow_redirects=False)
    header = _set_cookie_header(resp)
    assert "httponly" in header
    assert "samesite=lax" in header
    assert f"max-age={auth_endpoint._STATE_TTL_SECONDS}" in header
    assert "path=/api/v1/auth/google" in header
    assert "secure" not in header  # plain-http local development still works


def test_cookie_is_secure_when_the_site_is_https(client, google, monkeypatch):
    monkeypatch.setattr(
        settings, "GOOGLE_REDIRECT_URL", "https://swingtrademl.com/api/v1/auth/google/callback"
    )
    resp = client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert "secure" in _set_cookie_header(resp)


def test_the_cookie_holds_no_copy_of_the_state(client, google):
    state = _start(client)
    assert client.cookies.get(COOKIE)
    assert client.cookies.get(COOKIE) != state


# ------------------------------------------------------------ same browser --


def test_browser_a_completes_sign_in_and_code_exchange(client, google):
    state = _start(client)
    code = _login_code(_callback(client, state))

    exchanged = client.post("/api/v1/auth/google/exchange", json={"code": code})

    assert exchanged.status_code == 200, exchanged.text
    token = exchanged.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == OWNER_EMAIL
    assert google["token"] == 1
    # The browser secret is spent: the exchange clears it.
    assert any(
        h.startswith(f"{COOKIE}=") and "max-age=0" in h.lower()
        for h in exchanged.headers.get_list("set-cookie")
    )


# ---------------------------------------------------------- other browser --


def test_callback_from_a_browser_without_the_cookie_is_refused_before_google(client, google):
    state = _start(client)
    client.cookies.clear()  # browser B: never started a login

    resp = _callback(client, state)

    assert resp.status_code == 400
    assert "login_code" not in resp.headers.get("location", "")
    assert google["token"] == 0


def test_callback_from_a_browser_with_its_own_login_cookie_is_refused(client, google):
    victim_state = _start(client)  # browser A
    client.cookies.clear()
    _start(client)  # browser B starts its own login, gets its own cookie

    resp = _callback(client, victim_state)

    assert resp.status_code == 400
    assert google["token"] == 0


def test_a_forged_cookie_value_is_refused(client, google):
    state = _start(client)
    client.cookies.clear()
    client.cookies.set(COOKIE, "made-up-value")

    assert _callback(client, state).status_code == 400
    assert google["token"] == 0


def test_login_code_cannot_be_redeemed_from_another_browser(client, google):
    state = _start(client)
    code = _login_code(_callback(client, state))
    browser_a_cookie = client.cookies.get(COOKIE)

    client.cookies.clear()  # browser B, no cookie
    assert client.post("/api/v1/auth/google/exchange", json={"code": code}).status_code == 401
    _start(client)  # browser B with its own login cookie
    assert client.post("/api/v1/auth/google/exchange", json={"code": code}).status_code == 401

    # Browser B's attempts did not burn the code: browser A still signs in.
    client.cookies.clear()
    client.cookies.set(COOKIE, browser_a_cookie)
    assert client.post("/api/v1/auth/google/exchange", json={"code": code}).status_code == 200


# ------------------------------------------------- missing / expired / reused --


def test_missing_state_is_refused(client, google):
    _start(client)
    resp = client.get("/api/v1/auth/google/callback?code=c", follow_redirects=False)
    assert resp.status_code in (400, 422)
    assert google["token"] == 0


def test_unknown_state_is_refused(client, google):
    _start(client)
    assert _callback(client, "never-issued").status_code == 400
    assert google["token"] == 0


def test_expired_state_is_refused(client, google, monkeypatch):
    state = _start(client)
    real = auth_endpoint.time.monotonic
    monkeypatch.setattr(
        auth_endpoint.time, "monotonic", lambda: real() + auth_endpoint._STATE_TTL_SECONDS + 1
    )

    assert _callback(client, state).status_code == 400
    assert google["token"] == 0


def test_reused_state_is_refused(client, google):
    state = _start(client)
    _login_code(_callback(client, state))

    again = _callback(client, state)

    assert again.status_code == 400
    assert google["token"] == 1


def test_reused_login_code_is_refused(client, google):
    code = _login_code(_callback(client, _start(client)))
    assert client.post("/api/v1/auth/google/exchange", json={"code": code}).status_code == 200
    assert client.post("/api/v1/auth/google/exchange", json={"code": code}).status_code == 401


# ------------------------------------------------- existing account checks --


def test_allow_list_still_applies(client, google, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_ALLOWED_EMAILS", "someone-else@example.com")
    assert _callback(client, _start(client)).status_code == 403


def test_disabled_account_still_refused(client, google, db_session):
    db_session.add(
        User(
            username="bound-disabled",
            email=OWNER_EMAIL,
            hashed_password=None,
            auth_provider="google",
            google_id="g-bind-1",
            is_active=False,
        )
    )
    db_session.flush()
    assert _callback(client, _start(client)).status_code == 403
