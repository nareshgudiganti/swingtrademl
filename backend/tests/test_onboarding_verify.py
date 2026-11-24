# ruff: noqa: E501 (long plain-English test text)
"""#248: onboarding and paper account setup (verification tests; nothing here changes the app, and no real email is sent).

Findings note: docs/verification/248-onboarding.md. Existing coverage that this file does not repeat and that the note cites:
test_account_auth_email.py (register, verify, login enforcement matrix, the common-password list, same public answer for new
and existing emails), test_invites.py (invite-only sign-up, one use, never an owner), test_google_login_round_trip.py,
test_account_deletion.py (the whole deletion flow), test_p0_member_reads.py (a member is refused the house book),
test_plans.py and #426 / #335 for plan and private-account limits.

Here: the settled defaults, the Google sign-up gates, the first paper account (there is none per person), what a brand-new
member sees, one new person's sign-up never touching another's rows, and what account deletion leaves behind.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.config import Settings, settings
from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem, UserWatchlistSale
from swing_trade_ml.services import account_deletion as deletion
from swing_trade_ml.services.email import LogEmailSender, set_sender_for_tests
from swing_trade_ml.services.limits import limits_for
from swing_trade_ml.services.plans import set_plans_enabled
from test_google_login_round_trip import OWNER_EMAIL, _callback, _fake_google, _Reply

API = "/api/v1"


def _default(name):
    return Settings.model_fields[name].default


@pytest.fixture()
def outbox(monkeypatch):
    sender = LogEmailSender()
    set_sender_for_tests(sender)
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", True)
    yield sender
    set_sender_for_tests(None)


def _member(db, username, plan="free"):
    user = User(username=username, email=f"{username}@example.com", hashed_password=hash_password("Correct-horse-9battery"),
                is_active=True, role="member", plan=plan)
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


# ------------------------------------------------------------------------------- the settled defaults


def test_the_defaults_are_paper_only_closed_sign_up_and_outgoing_mail_off():
    assert _default("TRADING_MODE") == "paper" and _default("ALLOW_LIVE_TRADING") is False
    assert _default("ALLOW_SIGNUP") is False  # public registration is closed until the owner opens it
    assert _default("EMAIL_PROVIDER") == "log"  # mail is only logged, never sent, until a provider is configured
    assert _default("GOOGLE_ALLOWED_EMAILS") == ""  # Google sign-in admits nobody until the owner lists an address
    assert _default("PAPER_STARTING_CAPITAL") == 1_000_000.0


def test_email_verification_is_not_enforced_by_default():
    """OBSERVED: the verified-email decision is a switch (REQUIRE_EMAIL_VERIFICATION) that ships OFF; when it is on, an unverified
    local member is refused at sign-in (test_account_auth_email.py::test_login_enforcement_matrix). The production value was not read."""
    assert _default("REQUIRE_EMAIL_VERIFICATION") is False


def test_a_live_setting_alone_still_gives_the_paper_broker(monkeypatch):
    monkeypatch.setattr(settings, "TRADING_MODE", "live")
    monkeypatch.setattr(settings, "ALLOW_LIVE_TRADING", False)
    assert get_broker().mode == "paper"


# ------------------------------------------------------------------------------- Google sign-up gates


def test_google_refuses_an_address_that_is_not_on_the_allow_list_and_creates_no_account(client, db_session, monkeypatch):
    _fake_google(monkeypatch, email="stranger@example.com")
    monkeypatch.setattr(settings, "GOOGLE_ALLOWED_EMAILS", OWNER_EMAIL)
    client.base_url = "https://testserver"
    from urllib.parse import parse_qs, urlparse

    login = client.get(f"{API}/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    before = db_session.scalar(select(func.count()).select_from(User))
    resp = client.get(f"{API}/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert resp.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(User)) == before


def test_google_refuses_an_address_google_has_not_verified_and_creates_no_account(client, db_session, monkeypatch):
    _fake_google(monkeypatch)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Reply({"sub": "g-9", "email": OWNER_EMAIL, "email_verified": False}))
    client.base_url = "https://testserver"
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(client.get(f"{API}/auth/google/login", follow_redirects=False).headers["location"]).query)["state"][0]
    before = db_session.scalar(select(func.count()).select_from(User))
    assert client.get(f"{API}/auth/google/callback?code=c&state={state}", follow_redirects=False).status_code == 400
    assert db_session.scalar(select(func.count()).select_from(User)) == before


def test_a_new_google_account_is_an_ordinary_free_member_never_an_owner_or_tester(client, db_session, monkeypatch):
    _fake_google(monkeypatch)
    _location, token = _callback(client)
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert (me["role"], me["plan"], me["is_superuser"], me["auth_provider"]) == ("member", "free", False, "google")


# ------------------------------------------------------------------------------- the first paper account


def test_a_brand_new_book_starts_at_the_paper_starting_capital_on_the_matching_ladder_rung(db_session, monkeypatch):
    from swing_trade_ml.services.portfolio import portfolio_value_and_cash

    monkeypatch.setattr(settings, "PAPER_STARTING_CAPITAL", 1_000_000.0)
    value, cash = portfolio_value_and_cash(db_session, "paper")
    assert (value, cash) == (1_000_000.0, 1_000_000.0)
    lim = limits_for(value)
    assert (lim.rung_value, lim.max_positions, lim.sector_cap_pct) == (1_000_000, 8, 0.25)


def test_there_is_no_per_person_paper_account_the_book_tables_have_no_user_column():
    """OBSERVED: positions, orders, trades and strategies belong to the one shared paper book; no table of them carries a user id.
    A new member gets no paper account of their own (multi-user portfolios are planned, not built)."""
    for model in (Position, Order, Trade, Strategy):
        assert "user_id" not in {c.name for c in model.__table__.columns}, model.__tablename__


def test_registering_creates_no_book_rows_no_strategy_and_no_broker_connection(client, db_session, outbox):
    from swing_trade_ml.db.models.session import BrokerSession

    tables = (Strategy, Position, Order, Trade, BrokerSession)
    before = [db_session.scalar(select(func.count()).select_from(t)) for t in tables]
    r = client.post(f"{API}/auth/register", json={"email": "first@example.com", "password": "Correct-horse-9battery", "full_name": "First Person"})
    assert r.status_code == 201, r.text
    assert [db_session.scalar(select(func.count()).select_from(t)) for t in tables] == before


def test_a_new_member_cannot_reach_a_broker_the_real_account_orders_or_the_safety_switches(client, db_session):
    _, h = _member(db_session, "fresh-reach")
    assert client.get(f"{API}/auth/kite/session", headers=h).status_code == 403
    assert client.get(f"{API}/portfolio/summary?book=real", headers=h).status_code == 403
    assert client.get(f"{API}/safety/status", headers=h).status_code in (403, 404)
    assert client.post(f"{API}/auth/kite/auto-login", headers=h).status_code == 403
    assert client.post(f"{API}/portfolio/tester/buy", json={"symbol": "TCS", "quantity": 1}, headers=h).status_code == 403


# ------------------------------------------------------------------------------- what a brand-new member sees first


def test_a_brand_new_member_sees_empty_lists_and_unknown_not_invented_numbers(client, db_session):
    set_plans_enabled(db_session, True)
    _, h = _member(db_session, "fresh-first")
    assert client.get(f"{API}/me/watchlist", headers=h).json() == {"items": [], "limit": 50}
    assert client.get(f"{API}/me/watchlist/tracker", headers=h).json() == {"as_of": None, "horizon_days": 15, "items": []}
    assert client.get(f"{API}/me/watchlist/sold", headers=h).json() == {"items": []}
    assert client.get(f"{API}/signals/picks", headers=h).json() == []
    assert client.get(f"{API}/signals/track-record", headers=h).json() == []
    regime = client.get(f"{API}/market-data/regime", headers=h).json()
    assert regime["regime"] == "unknown" and regime["nifty_close"] is None and regime["sma_200"] is None  # unknown, never a made-up mood
    plan = client.get(f"{API}/me/plan", headers=h).json()
    assert plan["plan"] == "free" and plan["unrestricted"] is False and plan["can_see_real_account"] is False
    assert plan["features"] == ["picks", "regime", "track_record"] and plan["limits"]["picks_per_day"] == 5


def test_with_plans_off_a_brand_new_member_is_refused_the_house_screens_not_shown_them(client, db_session):
    _, h = _member(db_session, "fresh-off")
    for path in ("portfolio/summary", "risk/limits", "strategies", "status"):
        assert client.get(f"{API}/{path}", headers=h).status_code == 403, path


# ------------------------------------------------------------------------------- one new person never touches another's data


def test_one_new_persons_sign_up_verification_and_sign_in_change_nobody_elses_rows(client, db_session, outbox):
    a, _ = _member(db_session, "stays-a")
    db_session.add(Instrument(instrument_token=881_001, tradingsymbol="ISOSIGN", name="Iso Sign Ltd", exchange="NSE"))
    db_session.add(UserWatchlistItem(user_id=a.id, symbol="ISOSIGN", buy_price=10.0, quantity=3))
    db_session.commit()

    def snapshot():
        db_session.expire_all()
        row = db_session.get(User, a.id)
        cols = {c.name: getattr(row, c.name) for c in User.__table__.columns if c.name not in ("updated_at",)}
        items = [(i.symbol, i.buy_price, i.quantity, i.removed_at) for i in db_session.scalars(select(UserWatchlistItem).where(UserWatchlistItem.user_id == a.id))]
        return cols, items

    before = snapshot()
    r = client.post(f"{API}/auth/register", json={"email": "newbie@example.com", "password": "Correct-horse-9battery", "full_name": "New Bie"})
    assert r.status_code == 201
    link = next(w for w in outbox.outbox[-1].text.split() if "/verify-email?token=" in w)
    assert client.post(f"{API}/auth/verify-email", json={"token": link.split("token=")[1].strip(".,)>\"'")}).status_code == 200
    assert client.post(f"{API}/auth/login", json={"username": "newbie@example.com", "password": "Correct-horse-9battery"}).status_code == 200
    assert snapshot() == before  # person A's account row and list are exactly as they were
    newbie = db_session.scalar(select(User).where(User.email == "newbie@example.com"))
    assert newbie.id != a.id and (newbie.role, newbie.plan) == ("member", "free")
    token = create_access_token(newbie.username, {"uid": newbie.id, "tv": 0})
    assert client.get(f"{API}/me/watchlist", headers={"Authorization": f"Bearer {token}"}).json()["items"] == []  # nothing of A's


# ------------------------------------------------------------------------------- account deletion leaves nothing behind


def _sold_record(db, user):
    db.add(UserWatchlistSale(user_id=user.id, symbol="GONESALE", bought_on=datetime(2026, 11, 1, tzinfo=UTC).date(), entry_price=100.0,
                             entry_source="your_price", quantity=5, sell_price=120.0, sold_on=datetime(2026, 11, 10, tzinfo=UTC).date()))
    db.flush()


def test_after_deletion_no_row_points_at_a_missing_person(db_session):
    import swing_trade_ml.db.models  # noqa: F401
    from swing_trade_ml.db.base import Base

    user, _ = _member(db_session, "leaver-fk")
    db_session.add(UserWatchlistItem(user_id=user.id, symbol="LEAVE"))
    db_session.flush()
    deletion.anonymise(db_session, user)
    db_session.flush()
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "users":
                orphans = db_session.scalar(
                    select(func.count()).select_from(table).where(fk.parent.is_not(None), fk.parent.not_in(select(User.id)))
                )
                assert orphans == 0, f"{table.name}.{fk.parent.name}"
    assert db_session.scalar(select(func.count()).select_from(UserWatchlistItem).where(UserWatchlistItem.user_id == user.id)) == 0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: anonymise() clears the list, invites and tokens but not user_watchlist_sales, so a deleted person's sold records "
    "(stock, dates, prices, quantity) stay on the anonymised stub",
)
def test_a_deleted_persons_sold_records_are_removed(db_session):
    user, _ = _member(db_session, "leaver-sales")
    _sold_record(db_session, user)
    deletion.anonymise(db_session, user)
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(UserWatchlistSale).where(UserWatchlistSale.user_id == user.id)) == 0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: the data export lists a person's watchlist items (symbol, buy price) but not their quantity or their sold records",
)
def test_the_data_export_includes_the_persons_sold_records(db_session):
    user, _ = _member(db_session, "exporter")
    _sold_record(db_session, user)
    exported = deletion.export_data(db_session, user)
    assert any(s.get("symbol") == "GONESALE" for s in exported.get("sold_records", exported.get("sales", [])))
