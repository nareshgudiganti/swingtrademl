"""Tenant isolation (#414): one customer's data never reaches another account.

Everything here goes through the real HTTP routes with real credentials (bearer tokens for people, the legacy
shared key, and scoped service keys). Each test seeds two members (alice, bob), a tester, an owner who is NOT
the named real-account user, and checks what each can read or change. Application code is not touched: these
tests only prove the rules the app already has. Areas covered:

  1. Watchlist, Groww Tracker and sold list (/me/watchlist...)
  2. Plan and billing (/me/plan, /billing/me, cancel, checkout, admin grants)
  3. Account deletion and the account export (/account/...)
  4. Owner-private strategies, positions, real holdings and tax export
  5. Service keys (only their allowed GETs) and the legacy shared key on every person-only route
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from swing_trade_ml.api.deps import SELF_SERVICE_ROUTES, TESTER_PRIVATE_PREFIXES
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position, Signal, Strategy
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem, UserWatchlistSale
from swing_trade_ml.services import service_keys
from swing_trade_ml.services.billing import service as billing
from swing_trade_ml.services.billing.fake import FakeProvider
from swing_trade_ml.services.email import LogEmailSender, set_sender_for_tests
from swing_trade_ml.services.plans import set_plans_enabled

API = "/api/v1"
PW = "correct horse battery staple"
LEGACY_KEY = {"X-API-Key": "test-api-key"}
# Hashed once: hashing the password for every user in every test made the module several minutes slow.
PW_HASH = hash_password(PW)


# ---------------------------------------------------------------------------- setup


@pytest.fixture(autouse=True)
def _switches_on(monkeypatch):
    """Billing (fake provider) and account deletion (log mail) on; the real-account user is someone else."""
    monkeypatch.setattr(settings, "BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "BILLING_ACCEPT_NEW_CHECKOUTS", True)
    monkeypatch.setattr(settings, "BILLING_PROVIDER", "fake")
    monkeypatch.setattr(settings, "ALLOW_LIVE_BILLING", False)
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_ENABLED", True)
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_GRACE_DAYS", 14)
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.test")
    # The only real-account user is "sudeeksha"; none of the accounts below is that person.
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "sudeeksha")
    billing.set_provider(FakeProvider())
    sender = LogEmailSender()
    set_sender_for_tests(sender)
    yield sender
    billing.set_provider(None)
    set_sender_for_tests(None)


@pytest.fixture()
def mail(_switches_on) -> LogEmailSender:
    """The log mail sender in use: what would have been emailed, in order."""
    return _switches_on


def _link_token(mail: LogEmailSender, path: str) -> str:
    link = next(w for w in mail.outbox[-1].text.split() if f"/{path}?token=" in w)
    return link.split("token=")[1]


def make_user(db, name: str, *, role: str = "member", plan: str = "free") -> tuple[User, dict[str, str]]:
    user = User(
        username=name,
        email=f"{name}@example.com",
        full_name=f"Full {name}",
        hashed_password=PW_HASH,
        auth_provider="local",
        is_active=True,
        role=role,
        plan=plan,
        is_superuser=(role == "owner"),
    )
    db.add(user)
    db.flush()
    token = create_access_token(user.username, {"uid": user.id, "tv": user.token_version or 0})
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def people(db_session):
    """alice and bob (members), a tester, and an owner who is not the real-account user."""
    alice, a = make_user(db_session, "iso-alice")
    bob, b = make_user(db_session, "iso-bob")
    _, t = make_user(db_session, "iso-tester", role="tester")
    _, o = make_user(db_session, "iso-owner", role="owner")
    return {"alice": alice, "bob": bob, "a": a, "b": b, "t": t, "o": o}


@pytest.fixture()
def stocks(db_session):
    rows = [
        Instrument(instrument_token=991_101, tradingsymbol="ISOALPHA", name="Iso Alpha", exchange="NSE"),
        Instrument(instrument_token=991_102, tradingsymbol="ISOBETA", name="Iso Beta", exchange="NSE"),
        Instrument(instrument_token=991_103, tradingsymbol="ISOSHARED", name="Iso Shared", exchange="NSE"),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def _forbidden(r) -> bool:
    return r.status_code in (401, 403)


# ----------------------------------------------------------- 1. watchlist, tracker, sold


def test_each_person_sees_only_their_own_list_tracker_and_sold(client, db_session, people, stocks):
    a, b = people["a"], people["b"]
    assert (
        client.post(
            f"{API}/me/watchlist", json={"symbol": "ISOALPHA", "note": "alice secret"}, headers=a
        ).status_code
        == 201
    )
    assert client.post(f"{API}/me/watchlist", json={"symbol": "ISOBETA"}, headers=b).status_code == 201
    client.patch(f"{API}/me/watchlist/ISOALPHA", json={"buy_price": 123.45, "quantity": 7}, headers=a)
    assert (
        client.post(f"{API}/me/watchlist/ISOALPHA/sold", json={"sell_price": 130}, headers=a).status_code
        == 200
    )

    # Bob never sees Alice's stock, note, price, quantity or sale, in any of the three views.
    for path in ("/me/watchlist", "/me/watchlist/tracker", "/me/watchlist/sold"):
        text = client.get(f"{API}{path}", headers=b).text
        for secret in ("ISOALPHA", "alice secret", "123.45"):
            assert secret not in text, (path, secret)
    # ...and Alice's own views do hold her data.
    assert "ISOALPHA" in client.get(f"{API}/me/watchlist", headers=a).text
    assert "ISOALPHA" in client.get(f"{API}/me/watchlist/sold", headers=a).text
    assert "ISOBETA" in client.get(f"{API}/me/watchlist/tracker", headers=b).text


@pytest.mark.parametrize("other", ["b", "t", "o"])
def test_nobody_can_change_alices_rows(client, db_session, people, stocks, other):
    a, who = people["a"], people[other]
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOALPHA"}, headers=a)
    client.patch(
        f"{API}/me/watchlist/ISOALPHA", json={"buy_price": 50, "quantity": 3, "note": "mine"}, headers=a
    )

    assert client.delete(f"{API}/me/watchlist/ISOALPHA", headers=who).status_code == 404
    assert (
        client.patch(
            f"{API}/me/watchlist/ISOALPHA", json={"buy_price": 1, "note": "hacked"}, headers=who
        ).status_code
        == 404
    )
    assert (
        client.post(f"{API}/me/watchlist/ISOALPHA/sold", json={"sell_price": 9}, headers=who).status_code
        == 404
    )

    db_session.expire_all()
    alice_id = people["alice"].id
    row = db_session.execute(
        select(UserWatchlistItem).where(UserWatchlistItem.user_id == alice_id)
    ).scalar_one()
    assert (row.buy_price, row.quantity, row.note, row.removed_at) == (50, 3, "mine", None)
    assert (
        db_session.execute(select(UserWatchlistSale).where(UserWatchlistSale.user_id == alice_id)).first()
        is None
    )


def test_the_same_stock_on_two_lists_stays_independent(client, db_session, people, stocks):
    a, b = people["a"], people["b"]
    for h in (a, b):
        assert client.post(f"{API}/me/watchlist", json={"symbol": "ISOSHARED"}, headers=h).status_code == 201
    client.patch(f"{API}/me/watchlist/ISOSHARED", json={"buy_price": 10}, headers=a)
    client.patch(f"{API}/me/watchlist/ISOSHARED", json={"buy_price": 20}, headers=b)
    assert (
        client.post(f"{API}/me/watchlist/ISOSHARED/sold", json={"sell_price": 11}, headers=a).status_code
        == 200
    )

    items_b = client.get(f"{API}/me/watchlist", headers=b).json()["items"]
    assert [(i["symbol"], i["buy_price"], i["removed_at"]) for i in items_b] == [("ISOSHARED", 20, None)]
    assert client.get(f"{API}/me/watchlist/sold", headers=b).json()["items"] == []
    assert len(client.get(f"{API}/me/watchlist/sold", headers=a).json()["items"]) == 1


def test_a_user_id_in_the_request_is_never_trusted(client, db_session, people, stocks):
    """The owner of a row comes from the credential alone, never from a query string or body."""
    alice, a, b = people["alice"], people["a"], people["b"]
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOALPHA"}, headers=a)

    r = client.get(f"{API}/me/watchlist?user_id={alice.id}&username=iso-alice", headers=b)
    assert r.status_code == 200 and r.json()["items"] == []
    r = client.post(f"{API}/me/watchlist", json={"symbol": "ISOBETA", "user_id": alice.id}, headers=b)
    assert r.status_code == 201
    db_session.expire_all()
    rows = (
        db_session.execute(select(UserWatchlistItem).where(UserWatchlistItem.symbol == "ISOBETA"))
        .scalars()
        .all()
    )
    assert [x.user_id for x in rows] == [people["bob"].id]  # on Bob's list, not Alice's
    assert "ISOBETA" not in client.get(f"{API}/me/watchlist", headers=a).text


@pytest.mark.parametrize("method,path", sorted(SELF_SERVICE_ROUTES))
def test_no_machine_credential_reaches_a_persons_watchlist(client, db_session, people, method, path):
    """The legacy shared key and every service key scope are refused on the person-only routes."""
    url = f"{API}{path}".replace("{symbol}", "ISOALPHA")
    body = {"json": {"symbol": "ISOALPHA", "sell_price": 1}} if method in ("POST", "PATCH") else {}
    creds = [LEGACY_KEY]
    for scope in service_keys.SCOPES:
        _, raw = service_keys.create_key(db_session, name=f"iso-{scope}", scope=scope, created_by="owner")
        creds.append({"X-API-Key": raw})
    for h in creds:
        r = client.request(method, url, headers=h, **body)
        assert r.status_code == 403, (method, path, h, r.status_code)
    assert client.request(method, url, **body).status_code in (401, 403)  # no credential at all


@pytest.mark.parametrize("who", ["o", "t"])
def test_the_owner_and_the_tester_see_only_their_own_list_tracker_and_sold(
    client, db_session, people, stocks, who
):
    """The owner and the tester each have a list of their own: no one else's rows leak in or theirs out."""
    a, b, me = people["a"], people["b"], people[who]
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOALPHA", "note": "alice secret"}, headers=a)
    client.patch(f"{API}/me/watchlist/ISOALPHA", json={"buy_price": 123.45, "quantity": 7}, headers=a)
    client.post(f"{API}/me/watchlist/ISOALPHA/sold", json={"sell_price": 130}, headers=a)
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOBETA", "note": "bob secret"}, headers=b)
    assert client.post(f"{API}/me/watchlist", json={"symbol": "ISOSHARED"}, headers=me).status_code == 201

    for path in ("/me/watchlist", "/me/watchlist/tracker", "/me/watchlist/sold"):
        text = client.get(f"{API}{path}", headers=me).text
        for secret in ("ISOALPHA", "ISOBETA", "alice secret", "bob secret", "123.45"):
            assert secret not in text, (who, path, secret)
    assert "ISOSHARED" in client.get(f"{API}/me/watchlist", headers=me).text
    # and what they added is on nobody else's list
    assert "ISOSHARED" not in client.get(f"{API}/me/watchlist", headers=a).text
    assert "ISOSHARED" not in client.get(f"{API}/me/watchlist", headers=b).text


def test_a_person_reads_and_changes_their_own_rows(client, db_session, people, stocks):
    """The positive control: the person whose list it is can add, change, mark sold and remove."""
    a = people["a"]
    assert client.post(f"{API}/me/watchlist", json={"symbol": "ISOALPHA"}, headers=a).status_code == 201
    r = client.patch(
        f"{API}/me/watchlist/ISOALPHA", json={"buy_price": 50, "quantity": 3, "note": "mine"}, headers=a
    )
    assert r.status_code == 200
    listed = client.get(f"{API}/me/watchlist", headers=a).json()["items"]
    row = next(i for i in listed if i["symbol"] == "ISOALPHA")
    assert (row["buy_price"], row["quantity"], row["note"]) == (50, 3, "mine")
    sold = client.post(f"{API}/me/watchlist/ISOALPHA/sold", json={"sell_price": 55}, headers=a)
    assert sold.status_code == 200
    assert len(client.get(f"{API}/me/watchlist/sold", headers=a).json()["items"]) == 1

    assert client.post(f"{API}/me/watchlist", json={"symbol": "ISOBETA"}, headers=a).status_code == 201
    assert client.delete(f"{API}/me/watchlist/ISOBETA", headers=a).status_code in (200, 204)
    items = client.get(f"{API}/me/watchlist", headers=a).json()["items"]
    assert not [i for i in items if i["symbol"] == "ISOBETA" and i["removed_at"] is None]


# ---------------------------------------------------------------- 2. plan and billing


def test_a_members_plan_is_their_own_and_a_preview_header_gives_nothing(client, db_session, people):
    _, pro = make_user(db_session, "iso-pro", plan="pro")
    free, free_h = people["alice"], people["a"]
    assert free.plan == "free"
    set_plans_enabled(db_session, True)

    assert client.get(f"{API}/me/plan", headers=pro).json()["plan"] == "pro"
    mine = client.get(f"{API}/me/plan", headers=free_h).json()
    assert mine["plan"] == "free" and mine["unrestricted"] is False and mine["can_manage_plans"] is False
    # Only the owner may preview a plan; a free member asking for pro stays free.
    previewed = client.get(f"{API}/me/plan", headers={**free_h, "X-Preview-Plan": "pro"}).json()
    assert previewed["plan"] == "free" and previewed["previewing"] is False
    assert previewed["features"] == mine["features"]
    # A free member is still refused a Pro-only route when they send the preview header.
    r = client.get(f"{API}/strategies", headers={**free_h, "X-Preview-Plan": "pro"})
    assert r.status_code == 403


def test_billing_state_is_per_person(client, db_session, people):
    a, b = people["a"], people["b"]
    r = client.post(f"{API}/billing/checkout", headers=a)
    assert r.status_code == 200, r.text
    sub_id = r.json()["subscription_id"]

    mine = client.get(f"{API}/billing/me", headers=a).json()
    assert mine["subscription"] is not None
    theirs = client.get(f"{API}/billing/me", headers=b).json()
    assert theirs["subscription"] is None and theirs["plan"] == "free" and theirs["stored_plan"] == "free"
    assert sub_id not in client.get(f"{API}/billing/me", headers=b).text

    # Bob has nothing to cancel; his cancel never reaches Alice's subscription.
    assert client.post(f"{API}/billing/cancel", headers=b).status_code == 404
    still = client.get(f"{API}/billing/me", headers=a).json()["subscription"]
    assert still["status"] == mine["subscription"]["status"] and not still["cancelled_at"]
    # Bob's own checkout makes his own subscription, with a different id, and leaves Alice's alone.
    r2 = client.post(f"{API}/billing/checkout", headers=b)
    assert r2.status_code == 200 and r2.json()["subscription_id"] != sub_id


@pytest.mark.parametrize("who", ["a", "t"])
def test_nobody_but_the_owner_reads_or_edits_billing_grants(client, db_session, people, who):
    bob_id = people["bob"].id
    h = people[who]
    assert client.get(f"{API}/admin/users/{bob_id}/grants", headers=h).status_code in (403, 404)
    r = client.post(
        f"{API}/admin/users/{bob_id}/grants", json={"plan": "pro", "days": 30, "reason": "x"}, headers=h
    )
    assert r.status_code in (403, 404, 422) and r.status_code != 200
    assert client.put(f"{API}/admin/plans/switch", json={"enabled": False}, headers=h).status_code in (
        403,
        404,
        405,
    )


def test_the_plan_catalogue_does_not_carry_anyones_data(client, db_session, people):
    """/billing/plans is the same list for everybody: no subscription or user fields."""
    a, b = people["a"], people["b"]
    client.post(f"{API}/billing/checkout", headers=a)
    for h in (a, b):
        body = client.get(f"{API}/billing/plans", headers=h).json()
        assert set(body) == {"plans", "provider", "sandbox", "checkout_open"}
    assert (
        client.get(f"{API}/billing/plans", headers=a).json()
        == client.get(f"{API}/billing/plans", headers=b).json()
    )


def test_the_owner_grants_a_plan_and_only_that_member_changes(client, db_session, people):
    """The positive control for plans: the owner may grant, and the grant reaches that member alone."""
    alice, bob, o = people["alice"], people["bob"], people["o"]
    r = client.post(f"{API}/admin/users/{bob.id}/grants", json={"reason": "isolation test grant"}, headers=o)
    assert r.status_code == 201, r.text
    assert client.get(f"{API}/admin/users/{bob.id}/grants", headers=o).status_code == 200

    bobs = client.get(f"{API}/billing/me", headers=people["b"]).json()
    alices = client.get(f"{API}/billing/me", headers=people["a"]).json()
    # The grant lifts him; his stored plan is as it was.
    assert bobs["plan"] == "pro" and bobs["stored_plan"] == "free"
    assert alices["plan"] == "free" and alices["stored_plan"] == "free"
    assert client.get(f"{API}/admin/users/{alice.id}/grants", headers=o).json() == []


# ------------------------------------------------------ 3. account deletion and export


def test_account_export_holds_only_the_callers_own_data(client, db_session, people, stocks):
    a, b = people["a"], people["b"]
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOALPHA", "note": "alice-only note"}, headers=a)
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOBETA"}, headers=b)
    sub_id = client.post(f"{API}/billing/checkout", headers=a).json()["subscription_id"]

    mine = client.get(f"{API}/account/export", headers=a)
    assert mine.status_code == 200
    assert "ISOALPHA" in mine.text and "alice-only note" in mine.text and "iso-alice@example.com" in mine.text

    theirs = client.get(f"{API}/account/export", headers=b)
    assert theirs.status_code == 200
    for secret in ("ISOALPHA", "alice-only note", "iso-alice", "Full iso-alice", sub_id):
        assert secret not in theirs.text, secret
    assert "ISOBETA" in theirs.text and "iso-bob@example.com" in theirs.text


def test_one_persons_deletion_request_is_invisible_to_another(client, db_session, people):
    alice, a, b = people["alice"], people["a"], people["b"]
    r = client.post(f"{API}/account/deletion/request", json={"password": PW}, headers=a)
    assert r.status_code == 200, r.text

    assert client.get(f"{API}/account/deletion", headers=a).json()["status"] is not None
    bobs = client.get(f"{API}/account/deletion", headers=b).json()
    assert bobs["status"] is None and bobs["scheduled_for"] is None
    # Bob asking again needs HIS password; Alice's request neither helps nor hurts his account.
    assert (
        client.post(
            f"{API}/account/deletion/request", json={"password": "wrong password"}, headers=b
        ).status_code
        == 400
    )
    db_session.expire_all()
    assert db_session.get(User, people["bob"].id).is_active is True
    assert db_session.get(User, alice.id).is_active is True  # nothing happens before the emailed link is used


def test_a_guessed_or_foreign_deletion_token_deletes_nobody(client, db_session, people):
    for path in ("/account/deletion/confirm", "/account/deletion/cancel"):
        for token in ("not-a-real-token", "x" * 40, "iso-alice"):
            assert client.post(f"{API}{path}", json={"token": token}).status_code == 400
    db_session.expire_all()
    assert db_session.get(User, people["alice"].id).is_active is True


def test_a_valid_deletion_link_affects_only_that_person(client, db_session, people, stocks, mail):
    """The positive control: alice's own emailed links end (and restore) alice's access and nobody else's."""
    a, b = people["a"], people["b"]
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOBETA"}, headers=b)
    assert client.post(f"{API}/account/deletion/request", json={"password": PW}, headers=a).status_code == 200
    assert mail.outbox[-1].to == "iso-alice@example.com"

    confirm = client.post(
        f"{API}/account/deletion/confirm", json={"token": _link_token(mail, "confirm-deletion")}
    )
    assert confirm.status_code == 200, confirm.text
    assert client.get(f"{API}/auth/me", headers=a).status_code == 401  # alice's session is over
    assert client.post(f"{API}/auth/login", json={"username": "iso-alice", "password": PW}).status_code == 401

    # Bob is untouched: still signed in, his list and his status unchanged, and nothing was mailed to him.
    assert client.get(f"{API}/auth/me", headers=b).status_code == 200
    assert "ISOBETA" in client.get(f"{API}/me/watchlist", headers=b).text
    assert client.get(f"{API}/account/deletion", headers=b).json()["status"] is None
    assert all(m.to != "iso-bob@example.com" for m in mail.outbox)

    # Alice's own cancel link brings her back, and only her.
    cancel = client.post(
        f"{API}/account/deletion/cancel", json={"token": _link_token(mail, "cancel-deletion")}
    )
    assert cancel.status_code == 200, cancel.text
    assert client.post(f"{API}/auth/login", json={"username": "iso-alice", "password": PW}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=b).status_code == 200


@pytest.mark.parametrize("who", ["o", "t"])
def test_the_owner_and_tester_exports_hold_only_their_own_data(client, db_session, people, stocks, who):
    a, b, me = people["a"], people["b"], people[who]
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOALPHA", "note": "alice-only note"}, headers=a)
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOBETA", "note": "bob-only note"}, headers=b)
    client.post(f"{API}/me/watchlist", json={"symbol": "ISOSHARED", "note": "my own note"}, headers=me)

    mine = client.get(f"{API}/account/export", headers=me)
    assert mine.status_code == 200, (who, mine.status_code)
    assert "ISOSHARED" in mine.text and "my own note" in mine.text
    for secret in ("ISOALPHA", "alice-only note", "iso-alice", "ISOBETA", "bob-only note", "iso-bob"):
        assert secret not in mine.text, (who, secret)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/account/export"),
        ("GET", "/account/deletion"),
        ("POST", "/account/deletion/request"),
        ("GET", "/billing/me"),
        ("POST", "/billing/checkout"),
        ("POST", "/billing/cancel"),
    ],
)
def test_no_machine_credential_reaches_account_or_billing(client, db_session, people, method, path):
    creds = [LEGACY_KEY]
    for scope in service_keys.SCOPES:
        _, raw = service_keys.create_key(db_session, name=f"iso2-{scope}", scope=scope, created_by="owner")
        creds.append({"X-API-Key": raw})
    for h in creds:
        r = client.request(
            method, f"{API}{path}", headers=h, json={"password": PW} if method == "POST" else None
        )
        assert r.status_code == 403, (method, path, h, r.status_code)


# ----------------------------------------- 4. owner-private strategies, positions, holdings


@pytest.fixture()
def owner_book(db_session, stocks):
    """The owner's hand-recorded real book (live, advisory, private), the manual-test book, and a house book
    that members may see; one position and one BUY signal in each."""

    def strat(name, stype, **kw):
        row = db_session.execute(select(Strategy).where(Strategy.name == name)).scalar_one_or_none()
        if row is None:
            row = Strategy(name=name, strategy_type=stype, params={}, is_active=True, **kw)
            db_session.add(row)
            db_session.flush()
        return row

    real = strat("real_trading", "ml_swing", mode="live", execution_mode="advisory", owner_private=True)
    house = strat("iso_house_book", "ml_swing", mode="paper", owner_private=False)
    manual = strat("tester_paper", "tester_paper", mode="paper", owner_private=True)
    out = {"real": real, "house": house, "manual": manual}
    seeded = [
        (real, "ISOREAL", TradingMode.LIVE),
        (house, "ISOHOUSE", TradingMode.PAPER),
        (manual, "ISOMANUAL", TradingMode.PAPER),
    ]
    for n, (strategy, symbol, mode) in enumerate(seeded):
        inst = Instrument(instrument_token=991_200 + n, tradingsymbol=symbol, exchange="NSE")
        db_session.add(inst)
        db_session.flush()
        db_session.add(
            Position(
                strategy_id=strategy.id,
                instrument_id=inst.id,
                mode=mode,
                status=PositionStatus.OPEN,
                quantity=5,
                entry_price=100.0,
                current_price=100.0,
                entry_at=datetime.now(UTC),
            )
        )
        db_session.add(
            Signal(
                strategy_id=strategy.id,
                instrument_id=inst.id,
                signal_type="BUY",
                mode=mode,
                price=100.0,
                confidence=0.9,
                stop_loss=95.0,
                take_profit=108.0,
                generated_at=datetime.now(UTC),
            )
        )
    db_session.flush()
    return out


OWNER_ONLY_GETS = [
    "/strategies",
    "/portfolio/positions",
    "/portfolio/positions?mode=live",
    "/portfolio/holdings",
    "/portfolio/capital-added",
    "/real-report",
    "/real-report/tax",
    "/real-report/tax.csv",
    "/portfolio/real/account",
    "/portfolio/real/orders-status",
    "/safety/state",
    "/finance/transactions",
    "/risk/limits",
]


@pytest.mark.parametrize("plan", ["free", "pro"])
@pytest.mark.parametrize("path", OWNER_ONLY_GETS)
def test_a_member_on_any_plan_cannot_read_the_owners_private_areas(
    client, db_session, owner_book, path, plan
):
    set_plans_enabled(db_session, True)
    _, h = make_user(db_session, f"iso-m-{plan}", plan=plan)
    r = client.get(f"{API}{path}", headers=h)
    assert r.status_code == 403, (path, plan, r.status_code)
    for secret in ("ISOREAL", "ISOMANUAL"):
        assert secret not in r.text


def test_a_member_cannot_open_an_owner_private_strategy_by_id(client, db_session, owner_book):
    set_plans_enabled(db_session, True)
    _, h = make_user(db_session, "iso-m-pro", plan="pro")
    for key in ("real", "manual", "house"):
        sid = owner_book[key].id
        for path in (f"/strategies/{sid}", f"/strategies/{sid}/signals"):
            assert client.get(f"{API}{path}", headers=h).status_code == 403, (key, path)
        assert client.post(f"{API}/strategies/{sid}/deactivate", headers=h).status_code == 403
        assert client.delete(f"{API}/strategies/{sid}", headers=h).status_code == 403


@pytest.mark.parametrize("book", ["real", "all", "tester"])
def test_a_pro_member_cannot_ask_for_another_book(client, db_session, owner_book, book):
    set_plans_enabled(db_session, True)
    _, h = make_user(db_session, "iso-m-pro", plan="pro")
    for path in ("/portfolio/summary", "/portfolio/trades", "/portfolio/positions/detailed"):
        r = client.get(f"{API}{path}?book={book}", headers=h)
        assert r.status_code == 403, (path, book)
        assert "ISOREAL" not in r.text and "ISOMANUAL" not in r.text
    # Even the bot book (the one they may read) never lists the owner's hand books.
    body = client.get(f"{API}/portfolio/positions/detailed?book=bot", headers=h)
    assert body.status_code == 200
    assert "ISOREAL" not in body.text and "ISOMANUAL" not in body.text


def test_a_pro_members_picks_and_buy_list_leave_out_owner_private_books(client, db_session, owner_book):
    set_plans_enabled(db_session, True)
    _, h = make_user(db_session, "iso-m-pro", plan="pro")
    for path in ("/signals/picks", "/signals/buy-list", "/signals/top-picks"):
        r = client.get(f"{API}{path}", headers=h)
        assert r.status_code in (200, 403), (path, r.status_code)
        assert "ISOREAL" not in r.text and "ISOMANUAL" not in r.text, path


def test_a_tester_sees_only_the_manual_test_book(client, db_session, owner_book, people):
    t = people["t"]
    r = client.get(f"{API}/portfolio/positions", headers=t)
    assert r.status_code == 200
    symbols = {p["symbol"] if "symbol" in p else p.get("instrument_id") for p in r.json()}
    text = r.text
    assert "ISOREAL" not in text and "ISOHOUSE" not in text
    assert r.json() == [] or all(p["strategy_id"] == owner_book["manual"].id for p in r.json()), symbols
    # The house book and the real book are refused by name.
    for book in ("bot", "real", "all"):
        assert client.get(f"{API}/portfolio/summary?book={book}", headers=t).status_code == 403
    assert client.get(f"{API}/portfolio/holdings", headers=t).status_code == 403


def test_an_owner_who_is_not_the_named_user_cannot_reach_real_holdings(
    client, db_session, owner_book, people
):
    o = people["o"]
    for path in ("/portfolio/holdings", "/real-report", "/real-report/tax.csv", "/portfolio/real/account"):
        r = client.get(f"{API}{path}", headers=o)
        assert r.status_code == 403, path
        assert "ISOREAL" not in r.text
    # What the app tells the menu agrees: no real account for this owner.
    assert client.get(f"{API}/me/plan", headers=o).json()["can_see_real_account"] is False


def test_the_named_real_account_owner_reads_the_real_book(client, db_session, owner_book, monkeypatch):
    """The positive control: the one person named for the real account does reach it, and a different owner
    (the `people` owner in the tests above) still does not."""
    _, h = make_user(db_session, "iso-realowner", role="owner")
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "iso-realowner")
    assert client.get(f"{API}/me/plan", headers=h).json()["can_see_real_account"] is True
    positions = client.get(f"{API}/portfolio/positions?mode=live", headers=h)
    assert positions.status_code == 200
    assert any(p["strategy_id"] == owner_book["real"].id for p in positions.json())
    for path in ("/real-report/tax", "/real-report/tax.csv"):
        assert client.get(f"{API}{path}", headers=h).status_code == 200, path

    _, other = make_user(db_session, "iso-otherowner", role="owner")
    assert client.get(f"{API}/me/plan", headers=other).json()["can_see_real_account"] is False
    for path in ("/real-report/tax", "/real-report/tax.csv"):
        assert client.get(f"{API}{path}", headers=other).status_code == 403, path


def test_the_owner_and_shared_key_read_the_private_strategies(client, db_session, owner_book, people):
    for h in (people["o"], LEGACY_KEY):
        listed = client.get(f"{API}/strategies", headers=h)
        assert listed.status_code == 200
        for name in ("real_trading", "tester_paper", "iso_house_book"):
            assert name in listed.text, name
        for key in ("real", "manual", "house"):
            assert client.get(f"{API}/strategies/{owner_book[key].id}", headers=h).status_code == 200, key


@pytest.mark.parametrize("prefix", TESTER_PRIVATE_PREFIXES)
def test_private_prefixes_are_closed_to_members_and_testers(client, db_session, people, prefix):
    set_plans_enabled(db_session, True)
    _, pro = make_user(db_session, "iso-m-pro", plan="pro")
    for h in (people["a"], pro, people["t"]):
        for method in ("GET", "POST", "PUT", "DELETE"):
            r = client.request(method, f"{API}{prefix}", headers=h)
            assert r.status_code in (403, 404, 405), (prefix, method, r.status_code)


# ------------------------------------------------------------------- 5. service keys


def _key(db, scope):
    _, raw = service_keys.create_key(db, name=f"iso-{scope}", scope=scope, created_by="owner")
    return {"X-API-Key": raw}


def test_a_status_key_reaches_only_its_listed_gets(client, db_session, owner_book):
    h = _key(db_session, "read_status")
    for path in sorted(service_keys.READ_STATUS_PATHS):
        assert client.get(f"{API}{path}", headers=h).status_code != 403, path
    for path in (
        "/portfolio/positions",
        "/portfolio/summary",
        "/strategies",
        "/signals/picks",
        "/me/watchlist",
        "/me/plan/../billing/me",
        "/account/export",
        "/real-report",
        "/ops/digest",
    ):
        assert client.get(f"{API}{path}", headers=h).status_code in (403, 404), path
    for method, path in (
        ("POST", "/portfolio/snapshot"),
        ("PUT", "/brain/stage"),
        ("DELETE", "/me/watchlist/X"),
    ):
        assert client.request(method, f"{API}{path}", headers=h).status_code == 403, (method, path)


def test_each_key_scope_reads_exactly_what_it_names(client, db_session, owner_book):
    """The positive control for keys: each scope's own routes answer 200 (not merely 'not refused'), and the
    refusals above are not an outage in disguise."""
    status_key = _key(db_session, "read_status")
    for path in ("/status", "/market/session", "/risk/limits"):
        assert client.get(f"{API}{path}", headers=status_key).status_code == 200, path
    ops = client.get(f"{API}/ops/digest", headers=_key(db_session, "read_ops"))
    assert ops.status_code == 200
    house = client.get(f"{API}/portfolio/positions", headers=_key(db_session, "read_all"))
    assert house.status_code == 200
    assert "ISOREAL" not in house.text and "ISOMANUAL" not in house.text


def test_an_ops_key_reaches_only_ops(client, db_session, owner_book):
    h = _key(db_session, "read_ops")
    for path in (
        "/portfolio/positions",
        "/strategies",
        "/status",
        "/me/watchlist",
        "/account/export",
        "/real-report",
    ):
        assert client.get(f"{API}{path}", headers=h).status_code in (403, 404), path


@pytest.mark.parametrize(
    "path",
    [
        "/admin/service-keys",
        "/finance/transactions",
        "/safety/state",
        "/notifications",
        "/brain/approvals",
        "/me/watchlist",
        "/me/watchlist/sold",
        "/me/watchlist/tracker",
    ],
)
def test_even_a_read_all_key_is_kept_out_of_private_and_personal_areas(client, db_session, owner_book, path):
    r = client.get(f"{API}{path}", headers=_key(db_session, "read_all"))
    assert r.status_code in (403, 404), (path, r.status_code)


def test_a_read_all_key_gets_the_house_book_but_never_the_real_account(client, db_session, owner_book):
    h = _key(db_session, "read_all")
    assert client.get(f"{API}/portfolio/holdings", headers=h).status_code == 403
    assert client.get(f"{API}/real-report", headers=h).status_code == 403
    assert client.get(f"{API}/real-report/tax.csv", headers=h).status_code == 403
    r = client.get(f"{API}/portfolio/positions", headers=h)
    assert r.status_code == 200
    assert "ISOREAL" not in r.text and "ISOMANUAL" not in r.text
    assert client.get(f"{API}/portfolio/summary?book=real", headers=h).status_code == 403
    # Read only: no write of any kind.
    assert client.post(f"{API}/portfolio/snapshot", headers=h).status_code == 403


def test_a_revoked_or_unknown_key_is_refused(client, db_session, owner_book):
    row, raw = service_keys.create_key(db_session, name="iso-gone", scope="read_all", created_by="owner")
    row.revoked_at = datetime.now(UTC)
    db_session.flush()
    assert client.get(f"{API}/portfolio/positions", headers={"X-API-Key": raw}).status_code == 401
    assert (
        client.get(f"{API}/portfolio/positions", headers={"X-API-Key": "stk_" + "0" * 40}).status_code == 401
    )


# --------------------------------------------- 6. a brain run's raw trace (owner-only by design)


@pytest.fixture()
def brain_run(db_session, monkeypatch):
    """A finished brain run whose trace holds a risk-gate answer for the owner's account."""
    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)  # the brain's routes answer only while it is on
    from swing_trade_ml.db.models.brain import BrainRun

    run = BrainRun(
        id="iso-trace-run",
        kind="nightly",
        as_of=datetime.now(UTC),
        book="paper",
        live=True,
        status="done",
        trace=[{"module": "m07_risk", "says": "ISO-RISK-GATE-ANSWER for the owner's account"}],
    )
    db_session.add(run)
    db_session.flush()
    return run


TRACE_SECRET = "ISO-RISK-GATE-ANSWER"


@pytest.mark.parametrize(
    ("who", "plans_on"),
    [
        ("a", False),
        ("a", True),
        # KNOWN LEAK, reported to the lead and not fixed here (no application change without approval):
        # with plans OFF a tester is "unrestricted" in require_auth, which returns before the trace-specific
        # gate in brain_route_access, and /brain/runs/{id}/trace is not in TESTER_PRIVATE_PREFIXES.
        # strict: the day this is fixed the test passes and the marker must be removed.
        ("t", False),
        ("t", True),
    ],
)
def test_a_member_or_tester_cannot_read_a_runs_raw_trace(
    client, db_session, people, brain_run, who, plans_on
):
    """Intended rule (core/plans.py brain_route_access, brain.py run_trace): the trace is owner-only."""
    set_plans_enabled(db_session, plans_on)
    r = client.get(f"{API}/brain/runs/{brain_run.id}/trace", headers=people[who])
    assert r.status_code == 403, (who, plans_on, r.status_code)
    assert TRACE_SECRET not in r.text


@pytest.mark.parametrize("plans_on", [False, True])
def test_a_tester_cannot_read_a_runs_alert_preview(client, db_session, people, brain_run, plans_on):
    """The run's Telegram preview is the owner's alert text: owner-only, plans on or off (#414)."""
    set_plans_enabled(db_session, plans_on)
    r = client.get(f"{API}/brain/runs/{brain_run.id}/alerts", headers=people["t"])
    assert r.status_code == 403, (plans_on, r.status_code)


@pytest.mark.parametrize("plans_on", [False, True])
def test_a_pro_member_cannot_read_a_runs_raw_trace(client, db_session, brain_run, plans_on):
    set_plans_enabled(db_session, plans_on)
    _, h = make_user(db_session, "iso-trace-pro", plan="pro")
    r = client.get(f"{API}/brain/runs/{brain_run.id}/trace", headers=h)
    assert r.status_code == 403 and TRACE_SECRET not in r.text


def test_the_owner_and_the_shared_key_can_read_the_trace(client, db_session, people, brain_run):
    for h in (people["o"], LEGACY_KEY):
        r = client.get(f"{API}/brain/runs/{brain_run.id}/trace", headers=h)
        assert r.status_code == 200 and TRACE_SECRET in r.text


def test_service_keys_and_anonymous_callers_and_the_trace(client, db_session, brain_run):
    url = f"{API}/brain/runs/{brain_run.id}/trace"
    for scope in ("read_status", "read_ops"):
        assert client.get(url, headers=_key(db_session, scope)).status_code == 403, scope
    assert client.get(url).status_code in (401, 403)
    # read_all is the owner's read-only automation key: it may read it, by design (scope_allows).
    assert client.get(url, headers=_key(db_session, "read_all")).status_code == 200


# ------------------------------------------- 6. gaps found when the module was checked against #414


def test_nobody_can_drive_another_persons_subscription_through_the_simulator(client, db_session, people):
    """/billing/fake/simulate takes a subscription id: a foreign id is refused for members and testers, and
    the owner's subscription row is never touched by someone else's call."""
    a, b, t = people["a"], people["b"], people["t"]
    sub_id = client.post(f"{API}/billing/checkout", headers=a).json()["subscription_id"]
    before = client.get(f"{API}/billing/me", headers=a).json()["subscription"]
    for h in (b, t):
        body = {"event": "cancelled", "subscription_id": sub_id}
        r = client.post(f"{API}/billing/fake/simulate", json=body, headers=h)
        assert r.status_code in (403, 404), r.status_code
        assert sub_id not in r.text
    after = client.get(f"{API}/billing/me", headers=a).json()["subscription"]
    assert after["status"] == before["status"] and not after["cancelled_at"]
    # Without an id the call acts on the caller's own subscription, and Bob has none.
    own = client.post(f"{API}/billing/fake/simulate", json={"event": "cancelled"}, headers=b)
    assert own.status_code == 404
    assert client.get(f"{API}/billing/me", headers=a).json()["subscription"]["status"] == before["status"]


def test_a_service_key_principal_is_never_counted_as_a_real_account_user(db_session, people):
    from swing_trade_ml.api.deps import Principal
    from swing_trade_ml.services import idea_report

    for scope in ("read_status", "read_ops", "read_all"):
        assert idea_report.groww_user_ids(db_session, Principal(user=None, service_scope=scope)) == []


@pytest.fixture()
def live_track(db_session, monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)  # the brain's routes answer only while it is on
    from datetime import date

    from swing_trade_ml.db.models.brain import BrainTrack

    for book, symbol in (("live", "ISOREAL"), ("paper", "ISOHOUSE")):
        db_session.add(
            BrainTrack(
                book=book,
                symbol=symbol,
                opened_on=date(2026, 11, 2),
                day=date(2026, 11, 3),
                day_n=1,
                ret=0.01,
                status="ok",
                reason="ISO-TRACK-REASON",
                stop=95.0,
                band=[],
            )
        )
    db_session.flush()


@pytest.mark.parametrize("who", ["pro", "t"])
def test_members_and_testers_cannot_read_the_live_book_track(client, db_session, people, live_track, who):
    """/brain/track/{symbol}?book=live is the day-by-day track of the owner's real holdings."""
    set_plans_enabled(db_session, True)
    if who == "pro":
        _, h = make_user(db_session, "iso-trk-pro", plan="pro")
    else:
        h = people["t"]
    r = client.get(f"{API}/brain/track/ISOREAL?book=live", headers=h)
    assert r.status_code == 403 and "ISO-TRACK-REASON" not in r.text
    # The brain's own paper book stays readable for a plan member (the positive control).
    if who == "pro":
        ok = client.get(f"{API}/brain/track/ISOHOUSE?book=paper", headers=h)
        assert ok.status_code == 200 and "ISO-TRACK-REASON" in ok.text


def test_the_shared_key_and_service_keys_cannot_read_the_live_book_track(client, db_session, live_track):
    for headers in (LEGACY_KEY, _key(db_session, "read_all"), _key(db_session, "read_status")):
        r = client.get(f"{API}/brain/track/ISOREAL?book=live", headers=headers)
        assert r.status_code == 403 and "ISO-TRACK-REASON" not in r.text


def test_the_named_real_account_owner_reads_the_live_book_track(client, db_session, live_track, monkeypatch):
    _, h = make_user(db_session, "iso-trk-realowner", role="owner")
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "iso-trk-realowner")
    r = client.get(f"{API}/brain/track/ISOREAL?book=live", headers=h)
    assert r.status_code == 200 and r.json()["points"]


def test_an_owner_who_is_not_the_named_user_cannot_read_the_live_book_track(
    client, db_session, people, live_track
):
    r = client.get(f"{API}/brain/track/ISOREAL?book=live", headers=people["o"])
    assert r.status_code == 403 and "ISO-TRACK-REASON" not in r.text
