"""Invite-only access (New look wave 4, owner decision 2026-10-25).

People ask for an invite; only the signed-in owner can see, approve or reject requests; an
approved invite's one-time code creates exactly one ordinary member account, while ALLOW_SIGNUP
stays off. A new account never gets the owner's powers, the real account or Admin.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from swing_trade_ml.api import rate_limit
from swing_trade_ml.api.v1.endpoints import invites as invites_ep
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.invites import InviteRequest
from swing_trade_ml.db.models.session import User

API = "/api/v1"
REQ = f"{API}/auth/invite-request"
SIGNUP = f"{API}/auth/signup"


@pytest.fixture(autouse=True)
def _closed_signup(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "inv-owner")


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def _body(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Asha Rao",
        "email": "Asha@Example.com",
        "phone": "+91 98765 43210",
        "experience": "just_starting",
        "language": "telugu",
    }
    body.update(over)
    return body


def _pending(db, email: str) -> list[InviteRequest]:
    return list(
        db.execute(
            select(InviteRequest).where(InviteRequest.email == email, InviteRequest.status == "pending")
        ).scalars()
    )


def _approve(client, owner, invite_id: int) -> dict:
    r = client.post(f"{API}/admin/invites/{invite_id}/approve", json={}, headers=owner)
    assert r.status_code == 200, r.text
    return r.json()


def _request_and_approve(client, db, owner, email: str = "asha@example.com") -> tuple[int, str]:
    assert client.post(REQ, json=_body(email=email)).status_code == 202
    row = _pending(db, email)[0]
    out = _approve(client, owner, row.id)
    return row.id, out["invite_code"]


# ------------------------------------------------------------- asking --


def test_request_is_stored_lower_cased(client, db_session):
    r = client.post(REQ, json=_body())
    assert r.status_code == 202
    assert r.json() == {"message": invites_ep.REQUEST_RECEIVED}
    [row] = _pending(db_session, "asha@example.com")
    assert (row.name, row.phone, row.experience, row.language) == (
        "Asha Rao",
        "+91 98765 43210",
        "just_starting",
        "telugu",
    )
    assert row.decided_at is None and row.code_hash is None and row.user_id is None


def test_duplicate_pending_email_gets_the_same_answer_and_is_not_stored_twice(client, db_session):
    first = client.post(REQ, json=_body())
    second = client.post(REQ, json=_body(email="  ASHA@example.COM ", name="Someone Else"))
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(_pending(db_session, "asha@example.com")) == 1


def test_existing_member_email_gets_the_same_answer(client, db_session):
    db_session.add(User(username="already", email="member@example.com", hashed_password="x", role="member"))
    db_session.flush()
    r = client.post(REQ, json=_body(email="member@example.com"))
    assert r.status_code == 202
    assert r.json() == {"message": invites_ep.REQUEST_RECEIVED}


def test_full_waiting_list_still_gives_the_same_answer(client, db_session, monkeypatch):
    monkeypatch.setattr(invites_ep, "MAX_PENDING", 0)
    r = client.post(REQ, json=_body())
    assert r.status_code == 202 and r.json() == {"message": invites_ep.REQUEST_RECEIVED}
    assert _pending(db_session, "asha@example.com") == []


@pytest.mark.parametrize(
    "over",
    [
        {"email": "not-an-email"},
        {"email": "a@b"},
        {"email": "x" * 250 + "@example.com"},
        {"name": ""},
        {"name": "x" * 81},
        {"phone": "call me maybe"},
        {"phone": "1" * 25},
        {"experience": "expert"},
        {"language": "klingon"},
    ],
)
def test_bad_input_is_refused(client, db_session, over):
    r = client.post(REQ, json=_body(**over))
    assert r.status_code == 422
    assert db_session.execute(select(InviteRequest)).first() is None


def test_phone_is_optional(client, db_session):
    assert client.post(REQ, json=_body(phone="")).status_code == 202
    assert _pending(db_session, "asha@example.com")[0].phone is None


def test_request_is_rate_limited(client, monkeypatch):
    from test_rate_limit import FakeRedis  # sibling import, like brain_fakes

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 2)
    monkeypatch.setattr(rate_limit, "_now", lambda: 1_800_000_030.0)
    rate_limit.set_redis_client(FakeRedis())
    try:
        codes = [client.post(REQ, json=_body(email=f"p{i}@example.com")).status_code for i in range(3)]
    finally:
        rate_limit.set_redis_client(None)
    assert codes == [202, 202, 429]


# ------------------------------------------------------------- who may decide --


@pytest.mark.parametrize("role", ["member", "tester"])
def test_non_owners_cannot_list_or_decide(client, db_session, role):
    client.post(REQ, json=_body())
    row = _pending(db_session, "asha@example.com")[0]
    who = _as(db_session, f"inv-{role}", role)
    assert client.get(f"{API}/admin/invites", headers=who).status_code == 403
    for action in ("approve", "reject", "new-code"):
        assert client.post(f"{API}/admin/invites/{row.id}/{action}", json={}, headers=who).status_code == 403
    assert row.status == "pending"


def test_no_credentials_cannot_list_or_decide(client, db_session):
    client.post(REQ, json=_body())
    row = _pending(db_session, "asha@example.com")[0]
    assert client.get(f"{API}/admin/invites").status_code == 401
    assert client.post(f"{API}/admin/invites/{row.id}/approve", json={}).status_code == 401


def test_api_key_cannot_list_or_decide(client, db_session):
    """The shared API key counts as the owner elsewhere, but invites need a person who signed in."""
    client.post(REQ, json=_body())
    row = _pending(db_session, "asha@example.com")[0]
    key = {"X-API-Key": settings.API_KEY}
    assert client.get(f"{API}/admin/invites", headers=key).status_code == 403
    assert client.post(f"{API}/admin/invites/{row.id}/approve", json={}, headers=key).status_code == 403
    assert row.status == "pending"


def test_owner_lists_approves_and_the_decider_comes_from_the_sign_in(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    client.post(REQ, json=_body())
    listed = client.get(f"{API}/admin/invites", headers=owner)
    assert listed.status_code == 200
    [item] = listed.json()
    assert item["email"] == "asha@example.com" and item["status"] == "pending"
    assert item["has_account"] is False
    assert "code_hash" not in item and "invite_code" not in item

    out = client.post(
        f"{API}/admin/invites/{item['id']}/approve",
        json={"note": "friend of Vijay", "decided_by": "someone-else"},
        headers=owner,
    ).json()
    assert out["status"] == "approved"
    assert out["decided_by"] == "inv-owner"
    assert out["note"] == "friend of Vijay"
    assert len(out["invite_code"]) >= 16
    assert out["signup_path"].startswith("/signup?invite=")
    row = db_session.get(InviteRequest, item["id"])
    assert row.code_hash and out["invite_code"] not in row.code_hash  # only the hash is kept
    assert db_session.execute(select(AuditLog).where(AuditLog.action == "invite.approved")).first()

    # The code is never shown again in the list.
    again = client.get(f"{API}/admin/invites", headers=owner).json()[0]
    assert "invite_code" not in again
    # Approving twice is refused.
    assert client.post(f"{API}/admin/invites/{item['id']}/approve", json={}, headers=owner).status_code == 409


# ------------------------------------------------------------- signing up --


def _signup(client, email: str, code: str | None, username: str = "asha") -> object:
    body = {"username": username, "password": "longenough1", "email": email}
    if code is not None:
        body["invite_code"] = code
    return client.post(SIGNUP, json=body)


def test_approved_invite_signs_up_exactly_once_as_an_ordinary_member(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    invite_id, code = _request_and_approve(client, db_session, owner)

    r = _signup(client, "ASHA@example.com", code)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]

    user = db_session.execute(select(User).where(User.username == "asha")).scalar_one()
    assert user.role == "member" and user.is_superuser is False and user.plan == "free"
    assert user.email == "asha@example.com"
    row = db_session.get(InviteRequest, invite_id)
    assert row.used_at is not None and row.user_id == user.id and row.code_hash is None

    # A second sign-up with the same code is refused, under any username.
    assert _signup(client, "asha@example.com", code, username="asha2").status_code == 403

    # The new person is not the owner and cannot reach owner routes or the real account.
    me = {"Authorization": f"Bearer {token}"}
    plan = client.get(f"{API}/me/plan", headers=me).json()
    assert plan["can_manage_plans"] is False and plan["can_see_real_account"] is False
    assert client.get(f"{API}/admin/invites", headers=me).status_code == 403
    assert client.get(f"{API}/admin/users", headers=me).status_code == 403
    assert client.get(f"{API}/portfolio/holdings", headers=me).status_code == 403
    assert client.get(f"{API}/portfolio/real/account", headers=me).status_code == 403
    assert client.get(f"{API}/safety/state", headers=me).status_code == 403
    assert client.post(f"{API}/safety/halt", json={}, headers=me).status_code == 403


def test_invite_code_only_works_for_its_own_email(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    _, code = _request_and_approve(client, db_session, owner)
    assert _signup(client, "someone-else@example.com", code).status_code == 403
    assert _signup(client, "asha@example.com", code + "x").status_code == 403
    assert _signup(client, "asha@example.com", "made-up-code-123").status_code == 403
    assert db_session.execute(select(User).where(User.username == "asha")).first() is None


def test_signup_without_an_invite_is_refused_while_closed(client, db_session):
    assert _signup(client, "asha@example.com", None).status_code == 403
    client.post(REQ, json=_body())  # asked, but not approved yet
    assert _signup(client, "asha@example.com", None).status_code == 403
    assert db_session.execute(select(User).where(User.username == "asha")).first() is None


def test_pending_request_has_no_working_code(client, db_session):
    client.post(REQ, json=_body())
    row = _pending(db_session, "asha@example.com")[0]
    row.code_hash = invites_ep.hash_code("guessed-code-1234")  # even a hash on a pending row is ignored
    db_session.flush()
    assert _signup(client, "asha@example.com", "guessed-code-1234").status_code == 403


def test_rejected_or_withdrawn_invite_cannot_sign_up(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    invite_id, code = _request_and_approve(client, db_session, owner)
    r = client.post(f"{API}/admin/invites/{invite_id}/reject", json={"note": "no space"}, headers=owner)
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["decided_by"] == "inv-owner"
    assert _signup(client, "asha@example.com", code).status_code == 403

    # A plain rejection of a waiting request.
    client.post(REQ, json=_body(email="bob@example.com"))
    bob = _pending(db_session, "bob@example.com")[0]
    assert client.post(f"{API}/admin/invites/{bob.id}/reject", json={}, headers=owner).status_code == 200
    assert client.post(f"{API}/admin/invites/{bob.id}/approve", json={}, headers=owner).status_code == 409
    assert _signup(client, "bob@example.com", None, username="bob").status_code == 403


def test_used_invite_cannot_be_rejected_or_recoded(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    invite_id, code = _request_and_approve(client, db_session, owner)
    assert _signup(client, "asha@example.com", code).status_code == 201
    assert client.post(f"{API}/admin/invites/{invite_id}/reject", json={}, headers=owner).status_code == 409
    assert client.post(f"{API}/admin/invites/{invite_id}/new-code", json={}, headers=owner).status_code == 409


def test_new_code_replaces_the_old_one(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    invite_id, old = _request_and_approve(client, db_session, owner)
    r = client.post(f"{API}/admin/invites/{invite_id}/new-code", json={}, headers=owner)
    new = r.json()["invite_code"]
    assert new != old
    assert _signup(client, "asha@example.com", old).status_code == 403
    assert _signup(client, "asha@example.com", new).status_code == 201


def test_invite_signup_refuses_an_email_that_already_has_an_account(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    _, code = _request_and_approve(client, db_session, owner)
    db_session.add(User(username="older", email="Asha@Example.com", hashed_password="x", role="member"))
    db_session.flush()
    assert _signup(client, "asha@example.com", code).status_code == 409


def test_open_signup_unchanged_when_allowed_and_still_never_owner(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", True)
    r = client.post(SIGNUP, json={"username": "openperson", "password": "longenough1"})
    assert r.status_code == 201
    user = db_session.execute(select(User).where(User.username == "openperson")).scalar_one()
    assert user.role == "member" and user.is_superuser is False


def test_signup_body_cannot_ask_for_privileges(client, db_session):
    owner = _as(db_session, "inv-owner", "owner")
    _, code = _request_and_approve(client, db_session, owner)
    r = client.post(
        SIGNUP,
        json={
            "username": "asha",
            "password": "longenough1",
            "email": "asha@example.com",
            "invite_code": code,
            "role": "owner",
            "is_superuser": True,
            "plan": "pro",
        },
    )
    assert r.status_code == 201
    user = db_session.execute(select(User).where(User.username == "asha")).scalar_one()
    assert (user.role, user.is_superuser, user.plan) == ("member", False, "free")


# ------------------------------------------------------------- email sign-in --


def test_sign_in_with_email_as_well_as_username(client, db_session):
    db_session.add(
        User(username="mailer", email="Mailer@Example.com", hashed_password=hash_password("longenough1"))
    )
    db_session.flush()
    ok = client.post(f"{API}/auth/login", json={"username": "mailer@example.com", "password": "longenough1"})
    assert ok.status_code == 200
    bad = client.post(f"{API}/auth/login", json={"username": "mailer@example.com", "password": "wrong-pass1"})
    unknown = client.post(f"{API}/auth/login", json={"username": "ghost@example.com", "password": "x"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()  # still one message for every failure
