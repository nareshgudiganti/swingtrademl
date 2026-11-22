# ruff: noqa: E501 (long plain-English test sentences)
"""#388 Groww Tracker: integration tests through the real routes, the real sync, apply and tracker.

Only the HTTP transport (an httpx MockTransport) and Redis (a small fake) are faked. Every holding, stock,
person and number below is invented. No test can reach the network: the transport is a mock, the real
httpx transport and socket connects raise, and the only requests ever built are the token and holdings
requests (checked after every test).

Spec sections 6 and 8 of docs/superpowers/specs/2026-11-21-groww-sync-design.md; the frozen API contract is
in the lead's #388 contract. A test that shows a defect is a strict expected failure with its reason.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pyotp
import pytest
from sqlalchemy import func, select, update

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.groww import GrowwSync
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import (
    UserWatchlistItem,
    UserWatchlistItemChange,
    UserWatchlistSale,
)
from swing_trade_ml.services import plans as plan_service
from swing_trade_ml.services import service_keys
from swing_trade_ml.services import watchlist_tracker as tracker_rules
from swing_trade_ml.services.groww import client as groww_client

API = "/api/v1"
OWNER = "gwi-owner"
OWNER2 = "gwi-second-owner"
SHARED_KEY = "test-api-key"  # the placeholder the test environment pins (tests/_env_safety.py)

TOKEN_REQUEST = ("POST", "api.groww.in", "/v1/token/api/access")
HOLDINGS_REQUEST = ("GET", "api.groww.in", "/v1/holdings/user")

ALPHA, BRAVO, CHARLIE, ECHO, DELTA = "ALPHA", "BRAVO", "CHARLIE", "ECHO", "DELTA"
ISIN = {
    ALPHA: "INE0AAA01011",
    BRAVO: "INE0BBB01012",
    CHARLIE: "INE0CCC01013",
    ECHO: "INE0EEE01015",
}
OLD_BUY_DAY = datetime(2026, 10, 1, tzinfo=IST)
DELTA_BUY_DAY = datetime(2026, 9, 15, tzinfo=IST)


# ------------------------------------------------------------------ the fakes (transport and Redis only)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def eval(self, script, numkeys, key, token):
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class FakeGroww:
    """The Groww HTTP API as a mock transport. `holdings` is what the next holdings call returns."""

    def __init__(self) -> None:
        self.holdings: list[dict] = []
        self.mode = "ok"  # ok | http500 | auth401 | raw
        self.raw_body = b""
        self.requests: list[tuple[str, str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.host, request.url.path))
        if request.url.path == TOKEN_REQUEST[2]:
            return httpx.Response(200, json={"token": "gwi-fake-access-token"})
        if request.url.path == HOLDINGS_REQUEST[2]:
            if self.mode == "http500":
                return httpx.Response(500, json={"status": "FAILURE"})
            if self.mode == "auth401":
                return httpx.Response(401, json={"status": "FAILURE"})
            if self.mode == "raw":
                return httpx.Response(200, content=self.raw_body, headers={"content-type": "application/json"})
            return httpx.Response(200, json={"status": "SUCCESS", "payload": {"holdings": self.holdings}})
        return httpx.Response(404)  # never expected; the post-test check fails on it


def holding(name: str, qty, avg, *, isin: str | None = None, symbol: str | None = None, **extra) -> dict:
    return {
        "isin": isin or ISIN.get(name, "INE0ZZZ01019"),
        "trading_symbol": symbol or f"{name}-EQ",
        "quantity": qty,
        "average_price": avg,
        **extra,
    }


def _no_network(*args, **kwargs):
    raise AssertionError("a test tried to reach the network")


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _real_connect(original):
    """Loopback is allowed (asyncio's own wake-up socket pair uses it); any other address fails the test."""

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            _no_network()
        return original(self, address, *args, **kwargs)

    return guarded


def _real_create_connection(original):
    def guarded(address, *args, **kwargs):
        if address[0] not in _LOOPBACK:
            _no_network()
        return original(address, *args, **kwargs)

    return guarded


@pytest.fixture(autouse=True)
def groww(monkeypatch):
    """The fakes, the settings and the network guard. After the test, only the two allowed requests were built."""
    fake = FakeGroww()
    redis = FakeRedis()
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", f"{OWNER}, {OWNER2}")
    monkeypatch.setattr(settings, "GROWW_TOTP_TOKEN", "gwi-api-key")
    monkeypatch.setattr(settings, "GROWW_TOTP_SECRET", pyotp.random_base32())
    monkeypatch.setattr(groww_client, "_get_redis", lambda: redis)
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(groww_client, "_transport", lambda: transport)
    # The guard: the real httpx transport and any socket connect fail the test.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _no_network)
    monkeypatch.setattr(socket.socket, "connect", _real_connect(socket.socket.connect))
    monkeypatch.setattr(socket, "create_connection", _real_create_connection(socket.create_connection))
    fake.redis = redis
    yield fake
    allowed = {TOKEN_REQUEST, HOLDINGS_REQUEST}
    assert set(fake.requests) <= allowed, f"a request outside token and holdings was built: {set(fake.requests) - allowed}"


# ------------------------------------------------------------------ helpers

_tokens = iter(range(970_001, 971_000))


def stock(db, symbol: str) -> Instrument:
    inst = Instrument(instrument_token=next(_tokens), tradingsymbol=symbol, name=f"{symbol} Ltd", exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


def person(db, name: str, role: str = "member", plan: str = "free") -> tuple[User, dict[str, str]]:
    user = User(username=name, hashed_password="x", is_active=True, role=role, plan=plan)
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def key(db, scope: str) -> dict[str, str]:
    _, raw = service_keys.create_key(db, name=f"gwi-{scope}", scope=scope, created_by="test")
    return {"X-API-Key": raw}


def manual_row(db, user, symbol: str, *, note=None, buy=None, qty=None, added=OLD_BUY_DAY) -> UserWatchlistItem:
    row = UserWatchlistItem(user_id=user.id, symbol=symbol, added_at=added, note=note, buy_price=buy, quantity=qty)
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def lab(db_session, client, groww):
    """The Groww owner, a second owner, five stocks, and the owner's three manual rows."""
    db = db_session
    owner, owner_h = person(db, OWNER, "owner")
    second, second_h = person(db, OWNER2, "owner")
    stocks = {name: stock(db, name) for name in (ALPHA, BRAVO, CHARLIE, ECHO, DELTA)}
    manual_row(db, owner, ALPHA, note="my note", buy=50.0, qty=5)
    manual_row(db, owner, BRAVO, note="watching")
    manual_row(db, owner, DELTA, note="delta note", buy=70.0, qty=2, added=DELTA_BUY_DAY)
    return SimpleNamespace(
        db=db, c=client, owner=owner, h=owner_h, second=second, second_h=second_h, stocks=stocks, groww=groww
    )


def age_syncs(db) -> None:
    """Make every earlier sync look old enough that Refresh is not rate-limited (60 seconds)."""
    db.execute(update(GrowwSync).values(started_at=GrowwSync.started_at - timedelta(minutes=5)))
    db.flush()


def refresh(lab, holdings=None, *, headers=None, age=True):
    if holdings is not None:
        lab.groww.holdings = holdings
    if age:
        age_syncs(lab.db)
    return lab.c.post(API + "/groww/sync", headers=headers or lab.h)


def tracker(lab, headers=None) -> dict:
    r = lab.c.get(API + "/me/watchlist/tracker", headers=headers or lab.h)
    assert r.status_code == 200, r.text
    return r.json()


def rows_of(lab, headers=None) -> dict[str, dict]:
    return {i["symbol"]: i for i in tracker(lab, headers)["items"]}


def db_row(lab, symbol: str, user=None) -> UserWatchlistItem:
    row = lab.db.scalar(
        select(UserWatchlistItem).where(
            UserWatchlistItem.user_id == (user or lab.owner).id, UserWatchlistItem.symbol == symbol
        )
    )
    assert row is not None, symbol
    lab.db.refresh(row)
    return row


def snapshot(lab, symbols: tuple[str, ...]) -> dict[str, tuple]:
    """What a person typed into the tracker: note, buy date, and (for never-linked rows) price and quantity."""
    out = {}
    for s in symbols:
        r = db_row(lab, s)
        out[s] = (r.note, r.added_at, r.removed_at)
    return out


def history(lab, symbol: str) -> list[tuple[str, str | None, str | None, str]]:
    item = db_row(lab, symbol)
    return [
        (c.field, c.old_value, c.new_value, c.changed_by)
        for c in lab.db.scalars(
            select(UserWatchlistItemChange)
            .where(UserWatchlistItemChange.item_id == item.id)
            .order_by(UserWatchlistItemChange.id)
        )
    ]


def change_count(lab) -> int:
    return lab.db.scalar(select(func.count()).select_from(UserWatchlistItemChange))


def confirm_baseline(lab):
    """A confirmed first state: four Groww holdings, the three matches confirmed. ALPHA/BRAVO/CHARLIE are linked."""
    r = refresh(lab, [holding(ALPHA, 10, 100.5), holding(BRAVO, 4, 200.0), holding(CHARLIE, 7, 300.0)])
    assert r.status_code == 200 and r.json()["status"] == "complete", r.text
    r = lab.c.post(API + "/groww/matching/confirm-all", headers=lab.h)
    assert r.status_code == 200 and r.json() == {"confirmed": 3}, r.text


def pending(lab, symbol: str):
    return rows_of(lab)[symbol]["pending_sale_qty"]


def stamp_sale_now(lab) -> None:
    """The test runs in one transaction, so the database's now() is the start of the test: stamp the sale rows
    with the real time (the same step test_groww_apply.py takes), as separate requests would have done."""
    lab.db.execute(update(UserWatchlistSale).values(created_at=datetime.now(UTC)))
    lab.db.flush()


def today():
    return tracker_rules.today_ist()


# ================================================================== a. the full journey


def test_full_journey_first_sync_matches_topup_partial_sale_zero_and_rebuy(lab):
    c, h = lab.c, lab.h
    delta_before = snapshot(lab, (DELTA,))

    # 1. First sync: four holdings recorded; nothing is applied until the owner confirms matches.
    lab.groww.holdings = [
        holding(ALPHA, 10, 100.5),
        holding(BRAVO, 4, 200.0),
        holding(CHARLIE, 7, 300.0),
        holding(ECHO, 3, 400.0, symbol="ECHOX-EQ"),  # no stock is called ECHOX: needs matching
    ]
    r = refresh(lab)
    assert r.status_code == 200 and (r.json()["status"], r.json()["holdings_count"]) == ("complete", 4)
    seen = rows_of(lab)
    assert (seen[ALPHA]["quantity"], seen[ALPHA]["buy_price"]) == (5, 50.0)  # untouched: not confirmed yet
    assert ECHO not in seen and CHARLIE not in seen
    items = c.get(API + "/groww/matching", headers=h).json()["items"]
    by_isin = {i["isin"]: i for i in items}
    assert {i["match_state"] for i in items if i["isin"] != ISIN[ECHO]} == {"suggested"}
    assert by_isin[ISIN[ALPHA]]["suggested_symbol"] == ALPHA
    assert by_isin[ISIN[ALPHA]]["suggested_instrument_id"] == lab.stocks[ALPHA].id
    assert by_isin[ISIN[ECHO]]["match_state"] == "needs_matching"
    assert by_isin[ISIN[ECHO]]["suggested_symbol"] is None and by_isin[ISIN[ECHO]]["suggested_instrument_id"] is None

    # 2. Confirm the suggestions: manual rows take Groww's quantity and price; date and note stay.
    r = c.post(API + "/groww/matching/confirm-all", headers=h)
    assert r.status_code == 200 and r.json() == {"confirmed": 3}
    seen = rows_of(lab)
    assert (seen[ALPHA]["quantity"], seen[ALPHA]["buy_price"], seen[ALPHA]["held_state"]) == (10, 100.5, "held")
    assert db_row(lab, ALPHA).note == "my note" and db_row(lab, ALPHA).added_at == OLD_BUY_DAY
    assert db_row(lab, BRAVO).note == "watching" and (seen[BRAVO]["quantity"], seen[BRAVO]["buy_price"]) == (4, 200.0)
    assert seen[CHARLIE]["source"] == "groww" and seen[CHARLIE]["quantity"] == 7
    assert tracker_rules.ist_date(db_row(lab, CHARLIE).added_at) == today()  # a new row: bought on the sync day
    assert db_row(lab, CHARLIE).note is None
    assert seen[ALPHA]["groww_synced_at"] is not None
    assert ECHO not in seen  # still waiting for the owner
    assert [i["isin"] for i in c.get(API + "/groww/matching", headers=h).json()["items"]] == [ISIN[ECHO]]
    assert snapshot(lab, (DELTA,)) == delta_before
    overwritten = [(f, o, n) for f, o, n, _ in history(lab, ALPHA) if f in ("quantity", "buy_price")]
    assert overwritten == [("quantity", "5.0", "10.0"), ("buy_price", "50.0", "100.5")]

    # 3. The owner matches the unknown one by hand.
    r = c.post(API + f"/groww/matching/{ISIN[ECHO]}", json={"instrument_id": lab.stocks[ECHO].id}, headers=h)
    assert r.status_code == 200 and r.json() == {"isin": ISIN[ECHO], "instrument_id": lab.stocks[ECHO].id}
    assert rows_of(lab)[ECHO]["quantity"] == 3
    assert c.get(API + "/groww/matching", headers=h).json() == {"items": []}

    # 4. Top-up: more shares at a new average. The buy date does not restart.
    base = [holding(BRAVO, 4, 200.0), holding(CHARLIE, 7, 300.0), holding(ECHO, 3, 400.0, symbol="ECHOX-EQ")]
    r = refresh(lab, [holding(ALPHA, 15, 110.0), *base])
    assert r.json()["status"] == "complete"
    seen = rows_of(lab)
    assert (seen[ALPHA]["quantity"], seen[ALPHA]["buy_price"]) == (15, 110.0)
    assert db_row(lab, ALPHA).added_at == OLD_BUY_DAY and db_row(lab, ALPHA).note == "my note"
    assert ("quantity", "10.0", "15.0", "groww_sync") in history(lab, ALPHA)
    assert pending(lab, ALPHA) is None

    # 5. Partial sale: 15 -> 9. The quantity follows Groww and the screen prompts; no sale is recorded yet.
    r = refresh(lab, [holding(ALPHA, 9, 110.0), *base])
    assert r.json()["status"] == "complete"
    assert rows_of(lab)[ALPHA]["quantity"] == 9 and pending(lab, ALPHA) == 6.0
    assert db_row(lab, ALPHA).note == "my note"
    assert lab.db.scalar(select(func.count()).select_from(UserWatchlistSale)) == 0
    too_many = c.post(API + f"/me/watchlist/{ALPHA}/sold", json={"sell_price": 120.0, "quantity": 7}, headers=h)
    assert too_many.status_code == 409
    nothing = c.post(API + f"/me/watchlist/{BRAVO}/sold", json={"sell_price": 210.0}, headers=h)
    assert nothing.status_code == 409  # a linked stock with no shares gone: nothing to confirm

    # 6. Confirm the sale at the owner's price. It is recorded for 6 shares, the row stays listed.
    r = c.post(API + f"/me/watchlist/{ALPHA}/sold", json={"sell_price": 120.0, "quantity": 6}, headers=h)
    assert r.status_code == 200, r.text
    sale = lab.db.scalars(select(UserWatchlistSale)).one()
    assert (sale.symbol, sale.quantity, sale.sell_price) == (ALPHA, 6.0, 120.0)
    stamp_sale_now(lab)
    assert ALPHA in rows_of(lab) and pending(lab, ALPHA) is None

    # 7. Zero: Groww no longer lists it. The row stays, marked not held; the unconfirmed sale is flagged.
    r = refresh(lab, base)
    assert r.json()["status"] == "complete"
    seen = rows_of(lab)
    assert seen[ALPHA]["held_state"] == "not_held" and seen[ALPHA]["quantity"] == 0
    assert pending(lab, ALPHA) == 9.0
    assert db_row(lab, ALPHA).note == "my note" and db_row(lab, ALPHA).added_at == OLD_BUY_DAY
    assert seen[BRAVO]["held_state"] == "held"
    assert lab.db.scalar(select(func.count()).select_from(UserWatchlistSale)) == 1  # no sale without a confirmation

    # 8. Re-buy: back in Groww. A new holding: held again, the Day count restarts, the note stays.
    r = refresh(lab, [holding(ALPHA, 3, 130.0), *base])
    assert r.json()["status"] == "complete"
    seen = rows_of(lab)
    assert (seen[ALPHA]["held_state"], seen[ALPHA]["quantity"], seen[ALPHA]["buy_price"]) == ("held", 3, 130.0)
    assert tracker_rules.ist_date(db_row(lab, ALPHA).added_at) == today()
    assert db_row(lab, ALPHA).note == "my note"

    # Never touched: the stock Groww never held.
    assert snapshot(lab, (DELTA,)) == delta_before
    assert rows_of(lab)[DELTA]["held_state"] == "unknown" and rows_of(lab)[DELTA]["source"] == "manual"


def test_status_route_follows_the_journey(lab):
    assert lab.c.get(API + "/groww/status", headers=lab.h).json() == {
        "configured": True,
        "last_success_at": None,
        "last_status": None,
        "last_attempt_at": None,
        "last_sync_id": None,
    }
    confirm_baseline(lab)
    s = lab.c.get(API + "/groww/status", headers=lab.h).json()
    assert s["last_status"] == "complete" and s["last_success_at"] and s["last_attempt_at"] and s["last_sync_id"]


# ================================================================== b. nothing a person typed is ever lost


def _protected(lab):
    return snapshot(lab, (ALPHA, BRAVO, DELTA))


def _linked_numbers(lab):
    return {s: (rows_of(lab)[s]["quantity"], rows_of(lab)[s]["buy_price"]) for s in (ALPHA, BRAVO, CHARLIE)}


def _status(lab):
    return lab.c.get(API + "/groww/status", headers=lab.h).json()


def test_a_partial_sync_changes_nothing_and_keeps_the_last_good_result(lab):
    confirm_baseline(lab)
    kept, numbers, good = _protected(lab), _linked_numbers(lab), _status(lab)["last_success_at"]
    bad = {"isin": ISIN[ALPHA], "trading_symbol": "ALPHA-EQ", "quantity": 99}  # no average price
    r = refresh(lab, [bad, holding(BRAVO, 1, 1.0), holding(CHARLIE, 1, 1.0)])
    assert r.status_code == 200 and r.json()["status"] == "partial"
    assert _protected(lab) == kept and _linked_numbers(lab) == numbers
    s = _status(lab)
    assert s["last_status"] == "partial" and s["last_success_at"] == good
    assert db_row(lab, ALPHA).quantity == 10  # not 99


@pytest.mark.parametrize("mode", ["http500", "auth401"])
def test_a_failed_sync_changes_nothing_and_says_so(lab, mode):
    confirm_baseline(lab)
    kept, numbers, good = _protected(lab), _linked_numbers(lab), _status(lab)["last_success_at"]
    lab.groww.mode = mode
    r = refresh(lab, [holding(ALPHA, 1, 1.0)])
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert _protected(lab) == kept and _linked_numbers(lab) == numbers
    s = _status(lab)
    assert s["last_status"] == "failed" and s["last_success_at"] == good and s["last_attempt_at"]


def test_an_empty_sync_waits_for_the_owner_then_marks_linked_rows_not_held_and_nothing_else(lab):
    confirm_baseline(lab)
    kept, numbers = _protected(lab), _linked_numbers(lab)
    r = refresh(lab, [])
    assert r.json()["status"] == "empty_unconfirmed" and r.json()["holdings_count"] == 0
    sync_id = _status(lab)["last_sync_id"]
    assert _protected(lab) == kept and _linked_numbers(lab) == numbers  # suspicious: nothing applied
    assert _status(lab)["last_status"] == "empty_unconfirmed"

    r = lab.c.post(API + f"/groww/syncs/{sync_id}/confirm-empty", headers=lab.h)
    assert r.status_code == 200 and r.json() == {"sync_id": sync_id, "status": "complete"}
    seen = rows_of(lab)
    assert {seen[s]["held_state"] for s in (ALPHA, BRAVO, CHARLIE)} == {"not_held"}
    assert _protected(lab) == kept  # notes and buy dates survive
    assert (seen[DELTA]["held_state"], seen[DELTA]["quantity"], seen[DELTA]["buy_price"]) == ("unknown", 2, 70.0)
    again = lab.c.post(API + f"/groww/syncs/{sync_id}/confirm-empty", headers=lab.h)
    assert again.status_code == 409  # a second click is refused, nothing is applied twice


def test_a_repeated_sync_writes_no_history_and_no_duplicate(lab):
    confirm_baseline(lab)
    changes, kept = change_count(lab), _protected(lab)
    count = lab.db.scalar(select(func.count()).select_from(UserWatchlistItem))
    for _ in range(3):
        assert refresh(lab).json()["status"] == "complete"
    assert change_count(lab) == changes
    assert lab.db.scalar(select(func.count()).select_from(UserWatchlistItem)) == count
    assert _protected(lab) == kept


def test_a_renamed_stock_follows_its_isin_and_adds_no_second_row(lab):
    confirm_baseline(lab)
    kept = _protected(lab)
    count = lab.db.scalar(select(func.count()).select_from(UserWatchlistItem))
    renamed = holding(ALPHA, 12, 104.0, symbol="ALPHANEW-EQ")  # same ISIN, Groww now calls it something else
    r = refresh(lab, [renamed, holding(BRAVO, 4, 200.0), holding(CHARLIE, 7, 300.0)])
    assert r.json()["status"] == "complete"
    assert lab.db.scalar(select(func.count()).select_from(UserWatchlistItem)) == count
    assert rows_of(lab)[ALPHA]["quantity"] == 12 and rows_of(lab)[ALPHA]["held_state"] == "held"
    assert _protected(lab) == kept
    assert c_matching_empty(lab)


def c_matching_empty(lab) -> bool:
    return lab.c.get(API + "/groww/matching", headers=lab.h).json() == {"items": []}


def test_a_match_that_moves_to_another_stock_keeps_the_old_rows_manual_data(lab):
    confirm_baseline(lab)
    kept = _protected(lab)
    # The owner decides ALPHA's ISIN is really the ECHO stock: the old ALPHA row is unlinked and marked not held,
    # its note and buy date stay, and the ECHO stock gets its own row.
    r = lab.c.post(
        API + f"/groww/matching/{ISIN[ALPHA]}", json={"instrument_id": lab.stocks[ECHO].id}, headers=lab.h
    )
    assert r.status_code == 200
    assert _protected(lab) == kept
    assert rows_of(lab)[ALPHA]["held_state"] == "not_held"
    assert db_row(lab, ALPHA).groww_isin is None
    assert rows_of(lab)[ECHO]["quantity"] == 10


def test_a_stock_with_no_nse_listing_goes_to_needs_matching_and_is_never_dropped(lab):
    other = Instrument(instrument_token=next(_tokens), tradingsymbol="BONLY", name="B Only", exchange="BSE")
    lab.db.add(other)
    lab.db.flush()  # the same name exists, but only on another exchange: no NSE suggestion
    r = refresh(lab, [holding("BONLY", 5, 50.0, isin="INE0TTT01017", symbol="BONLY-EQ")])
    assert r.json()["status"] == "complete" and r.json()["holdings_count"] == 1
    items = lab.c.get(API + "/groww/matching", headers=lab.h).json()["items"]
    assert [(i["isin"], i["match_state"], i["suggested_symbol"]) for i in items] == [
        ("INE0TTT01017", "needs_matching", None)
    ]
    assert "BONLY" not in rows_of(lab)


def test_the_two_stocks_that_share_one_isin_row_are_left_alone(lab):
    confirm_baseline(lab)
    kept, numbers = _protected(lab), _linked_numbers(lab)
    dup = holding(ALPHA, 99, 1.0)
    r = refresh(lab, [holding(ALPHA, 10, 100.5), dup, holding(BRAVO, 4, 200.0), holding(CHARLIE, 7, 300.0)])
    assert r.json()["status"] == "complete"
    assert _protected(lab) == kept and _linked_numbers(lab) == numbers  # ambiguous: touch nothing


def test_the_groww_page_cannot_edit_a_linked_rows_quantity_or_price(lab):
    confirm_baseline(lab)
    for body in ({"quantity": 3}, {"buy_price": 9.5}, {"quantity": 3, "buy_price": 9.5}):
        r = lab.c.patch(API + f"/me/watchlist/{ALPHA}", json=body, headers=lab.h)
        assert r.status_code == 409, body
    r = lab.c.patch(API + f"/me/watchlist/{ALPHA}", json={"note": "changed"}, headers=lab.h)
    assert r.status_code == 200 and db_row(lab, ALPHA).note == "changed"
    r = lab.c.patch(API + f"/me/watchlist/{DELTA}", json={"quantity": 3}, headers=lab.h)
    assert r.status_code == 200  # a hand-entered row is still hand-editable


# ================================================================== c. who may call what

GROWW_ROUTES = [
    ("post", "/groww/sync", None),
    ("get", "/groww/status", None),
    ("get", "/groww/matching", None),
    ("post", "/groww/matching/confirm-all", None),
    ("post", f"/groww/matching/{ISIN[ALPHA]}", {"instrument_id": 1}),
    ("post", "/groww/syncs/1/confirm-empty", None),
]
WRITES = [r for r in GROWW_ROUTES if r[0] == "post"]
READS = [r for r in GROWW_ROUTES if r[0] == "get"]


def call(lab, route, headers):
    method, path, body = route
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    return getattr(lab.c, method)(API + path, **kwargs)


def callers(lab) -> dict[str, dict[str, str]]:
    db = lab.db
    _, free_h = person(db, "gwi-free", "member", "free")
    _, pro_h = person(db, "gwi-pro", "member", "pro")
    _, tester_h = person(db, "gwi-tester", "tester")
    _, plain_h = person(db, "gwi-plain-owner", "owner")  # an owner who is not in REAL_ACCOUNT_USERS
    return {
        "member-free": free_h,
        "member-pro": pro_h,
        "tester": tester_h,
        "plain-owner": plain_h,
        "key-read_status": key(db, "read_status"),
        "key-read_ops": key(db, "read_ops"),
        "key-read_all": key(db, "read_all"),
    }


@pytest.mark.parametrize("plans_on", [False, True])
@pytest.mark.parametrize("route", GROWW_ROUTES, ids=[f"{m}{p}" for m, p, _ in GROWW_ROUTES])
def test_everyone_but_the_groww_owner_is_refused_on_every_route(lab, plans_on, route):
    plan_service.set_plans_enabled(lab.db, plans_on)
    for who, headers in callers(lab).items():
        r = call(lab, route, headers)
        assert r.status_code == 403, f"plans {'on' if plans_on else 'off'}, {who}: {route[0]} {route[1]} -> {r.status_code}"
    anonymous = call(lab, route, {})
    assert anonymous.status_code == 401


def test_a_second_owners_groww_writes_are_refused_and_change_nothing(lab):
    confirm_baseline(lab)
    age_syncs(lab.db)  # so a one-minute limit cannot answer before the owner check
    for route in WRITES:
        assert call(lab, route, lab.second_h).status_code == 403, route
    assert db_row(lab, ALPHA).quantity == 10  # nothing moved


def test_d2_a_second_owner_gets_403_on_every_groww_route_reads_included(lab):
    confirm_baseline(lab)
    age_syncs(lab.db)
    for route in GROWW_ROUTES:
        r = call(lab, route, lab.second_h)
        assert r.status_code == 403, f"{route[0]} {route[1]} -> {r.status_code}"


def test_d2_a_second_owner_is_refused_before_409_429_and_503(lab, monkeypatch):
    confirm_baseline(lab)
    # 429: a sync just ran (no age_syncs).
    assert call(lab, WRITES[0], lab.second_h).status_code == 403
    # 409: another refresh holds the lock.
    age_syncs(lab.db)
    lab.groww.redis.store["groww:sync_lock"] = "someone-else"
    assert call(lab, WRITES[0], lab.second_h).status_code == 403
    lab.groww.redis.store.pop("groww:sync_lock")
    # 503: not configured.
    monkeypatch.setattr(settings, "GROWW_TOTP_TOKEN", "")
    assert call(lab, WRITES[0], lab.second_h).status_code == 403
    # 409 on confirm-empty (not an empty sync) and 404 on an unknown stock also come after the owner check.
    assert call(lab, ("post", "/groww/syncs/1/confirm-empty", None), lab.second_h).status_code == 403
    assert call(lab, ("post", f"/groww/matching/{ISIN[ALPHA]}", {"instrument_id": 987_654_321}), lab.second_h).status_code == 403


def test_d2_a_second_owners_tracker_has_no_groww_key(lab):
    confirm_baseline(lab)
    body = tracker(lab, lab.second_h)
    assert "groww" not in body and body["items"] == []


def test_d2_with_no_groww_owner_account_found_nobody_signed_in_gets_access(lab, monkeypatch):
    # The first name in REAL_ACCOUNT_USERS has no account: there is no Groww owner. The two real owners
    # that do exist are signed-in people, so they get nothing: 403 on every route, no key in the tracker.
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", f"gwi-nobody, {OWNER}, {OWNER2}")
    for headers in (lab.h, lab.second_h):
        for route in GROWW_ROUTES:
            r = call(lab, route, headers)
            assert r.status_code == 403, f"{route[0]} {route[1]} -> {r.status_code}"
        assert "groww" not in tracker(lab, headers)


def test_d2_the_legacy_shared_key_is_unchanged_even_with_no_groww_owner_account(lab, monkeypatch):
    shared = {"X-API-Key": SHARED_KEY}
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "gwi-nobody")
    for route in READS:
        assert call(lab, route, shared).status_code == 200, route
    r = refresh(lab, [holding(ALPHA, 1, 1.0)], headers=shared)
    assert r.status_code == 409  # no owner account to update, as before


def test_no_groww_key_or_row_reaches_another_persons_tracker(lab):
    confirm_baseline(lab)
    db = lab.db
    free, free_h = person(db, "gwi-free-2", "member", "free")
    tester, tester_h = person(db, "gwi-tester-2", "tester")
    plain, plain_h = person(db, "gwi-plain-2", "owner")
    for user in (free, tester, plain):
        manual_row(db, user, BRAVO, note=f"{user.username} note", buy=10.0, qty=1)
    for plans_on in (False, True):
        plan_service.set_plans_enabled(db, plans_on)
        for who, headers in (("free", free_h), ("tester", tester_h), ("plain-owner", plain_h)):
            body = tracker(lab, headers)
            assert "groww" not in body, who
            assert {i["symbol"] for i in body["items"]} == {BRAVO}, who
            item = body["items"][0]
            assert (item["source"], item["held_state"], item["quantity"], item["buy_price"]) == (
                "manual",
                "unknown",
                1,
                10.0,
            ), who
            assert item["groww_synced_at"] is None and item["pending_sale_qty"] is None
    # A service key is not a person: the tracker refuses it.
    for scope in ("read_status", "read_ops", "read_all"):
        assert lab.c.get(API + "/me/watchlist/tracker", headers=key(db, scope)).status_code == 403
    # The second owner never sees the Groww owner's rows (and, since D2, no groww key: see the D2 tests).
    assert tracker(lab, lab.second_h)["items"] == []


def test_the_groww_owner_alone_gets_the_groww_status_in_the_tracker(lab):
    body = tracker(lab)
    assert set(body["groww"]) == {"configured", "last_success_at", "last_status", "last_attempt_at", "last_sync_id"}


def test_the_shared_owner_key_may_use_the_routes_and_updates_the_groww_owners_tracker(lab):
    shared = {"X-API-Key": SHARED_KEY}
    assert call(lab, READS[0], shared).status_code == 200
    r = refresh(lab, [holding(ALPHA, 10, 100.5)], headers=shared)
    assert r.status_code == 200 and r.json()["status"] == "complete"
    assert lab.c.post(API + "/groww/matching/confirm-all", headers=shared).json() == {"confirmed": 1}
    assert rows_of(lab)[ALPHA]["quantity"] == 10  # the Groww owner's tracker, not a nameless one


# ================================================================== d. the frozen contract


def _keys(obj: dict, expected: set[str]) -> None:
    assert set(obj) == expected, f"{sorted(set(obj) ^ expected)}"


def _iso_or_none(value) -> None:
    assert value is None or (isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None)


STATUS_KEYS = {"configured", "last_success_at", "last_status", "last_attempt_at", "last_sync_id"}
MATCH_KEYS = {
    "isin",
    "trading_symbol",
    "quantity",
    "average_price",
    "match_state",
    "suggested_symbol",
    "suggested_instrument_id",
}


def test_every_success_response_matches_the_contract(lab):
    c, h = lab.c, lab.h
    status = c.get(API + "/groww/status", headers=h).json()  # nothing yet: every value but configured is null
    _keys(status, STATUS_KEYS)
    assert status["configured"] is True and all(status[k] is None for k in STATUS_KEYS - {"configured"})

    r = refresh(lab, [holding(ALPHA, 10, 100.5), holding(ECHO, 3, 400.0, symbol="ECHOX-EQ")])
    sync = r.json()
    _keys(sync, {"status", "holdings_count", "finished_at"})
    assert sync["status"] in {"complete", "partial", "failed", "empty_unconfirmed"}
    assert isinstance(sync["holdings_count"], int)
    _iso_or_none(sync["finished_at"])

    status = c.get(API + "/groww/status", headers=h).json()
    _keys(status, STATUS_KEYS)
    assert isinstance(status["configured"], bool) and isinstance(status["last_sync_id"], int)
    _iso_or_none(status["last_success_at"])
    _iso_or_none(status["last_attempt_at"])
    assert status["last_status"] in {"complete", "partial", "failed", "empty_unconfirmed"}

    matching = c.get(API + "/groww/matching", headers=h).json()
    _keys(matching, {"items"})
    assert len(matching["items"]) == 2
    for item in matching["items"]:
        _keys(item, MATCH_KEYS)
        assert item["match_state"] in {"suggested", "needs_matching"}
        assert isinstance(item["quantity"], (int, float)) and isinstance(item["average_price"], (int, float))
        if item["match_state"] == "suggested":
            assert isinstance(item["suggested_symbol"], str) and isinstance(item["suggested_instrument_id"], int)
        else:
            assert item["suggested_symbol"] is None and item["suggested_instrument_id"] is None

    one = c.post(API + f"/groww/matching/{ISIN[ECHO]}", json={"instrument_id": lab.stocks[ECHO].id}, headers=h)
    _keys(one.json(), {"isin", "instrument_id"})
    everything = c.post(API + "/groww/matching/confirm-all", headers=h).json()
    _keys(everything, {"confirmed"})
    assert isinstance(everything["confirmed"], int)

    body = tracker(lab)
    _keys(body["groww"], STATUS_KEYS)
    item = body["items"][0]
    for extra in ("source", "held_state", "groww_synced_at", "pending_sale_qty"):
        assert extra in item, extra
    assert item["source"] in {"manual", "groww"} and item["held_state"] in {"unknown", "held", "not_held"}
    _iso_or_none(item["groww_synced_at"])
    assert item["pending_sale_qty"] is None or isinstance(item["pending_sale_qty"], (int, float))

    empty = refresh(lab, [])
    _keys(empty.json(), {"status", "holdings_count", "finished_at"})
    sync_id = c.get(API + "/groww/status", headers=h).json()["last_sync_id"]
    confirmed = c.post(API + f"/groww/syncs/{sync_id}/confirm-empty", headers=h).json()
    _keys(confirmed, {"sync_id", "status"})
    assert confirmed == {"sync_id": sync_id, "status": "complete"}


def test_a_failed_refresh_still_answers_in_the_contract_shape_with_nullable_fields(lab):
    lab.groww.mode = "http500"
    r = refresh(lab)
    assert r.status_code == 200
    _keys(r.json(), {"status", "holdings_count", "finished_at"})
    assert r.json()["status"] == "failed"
    _iso_or_none(r.json()["finished_at"])
    assert r.json()["holdings_count"] is None or isinstance(r.json()["holdings_count"], int)
    status = lab.c.get(API + "/groww/status", headers=lab.h).json()
    assert status["last_status"] == "failed" and status["last_success_at"] is None


def _detail(r) -> str:
    assert isinstance(r.json().get("detail"), str), r.text
    return r.json()["detail"]


def test_every_refusal_matches_the_contract(lab, monkeypatch):
    c, h = lab.c, lab.h
    # 429: a second refresh inside a minute.
    assert refresh(lab, [holding(ALPHA, 1, 1.0)]).status_code == 200
    again = refresh(lab, age=False)
    assert again.status_code == 429 and _detail(again)
    # 409: another refresh holds the lock.
    lab.groww.redis.store["groww:sync_lock"] = "someone-else"
    busy = refresh(lab)
    assert busy.status_code == 409 and _detail(busy) == "already refreshing"
    lab.groww.redis.store.pop("groww:sync_lock")
    # 409: no owner account to update (the shared key has no person behind it).
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "gwi-nobody")
    no_owner = refresh(lab, headers={"X-API-Key": SHARED_KEY})
    assert no_owner.status_code == 409 and _detail(no_owner)
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", f"{OWNER}, {OWNER2}")
    # 404: a stock that does not exist.
    nope = c.post(API + f"/groww/matching/{ISIN[ALPHA]}", json={"instrument_id": 987_654_321}, headers=h)
    assert nope.status_code == 404 and _detail(nope)
    # 409: confirm-empty on a result that is not an empty one waiting.
    sync_id = c.get(API + "/groww/status", headers=h).json()["last_sync_id"]
    not_empty = c.post(API + f"/groww/syncs/{sync_id}/confirm-empty", headers=h)
    assert not_empty.status_code == 409 and _detail(not_empty)
    # 409: an old empty result once a newer refresh exists.
    refresh(lab, [])
    old_empty = c.get(API + "/groww/status", headers=h).json()["last_sync_id"]
    refresh(lab, [holding(ALPHA, 1, 1.0)])
    stale = c.post(API + f"/groww/syncs/{old_empty}/confirm-empty", headers=h)
    assert stale.status_code == 409 and _detail(stale)
    # 503: not configured.
    monkeypatch.setattr(settings, "GROWW_TOTP_TOKEN", "")
    off = refresh(lab)
    assert off.status_code == 503 and _detail(off)
    assert c.get(API + "/groww/status", headers=h).json()["configured"] is False


# ================================================================== e. the network guard


def test_the_guard_stops_a_real_request(lab):
    with pytest.raises(AssertionError, match="network"):
        httpx.Client().get("https://api.groww.in/v1/holdings/user")
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("api.groww.in", 443))
    with pytest.raises(AssertionError, match="network"):
        socket.socket().connect(("203.0.113.9", 443))  # a documentation address, never routed


def test_the_client_builds_only_the_token_and_holdings_requests(lab):
    allowed_paths = set(groww_client.ALLOWED_PATHS)
    assert allowed_paths == {TOKEN_REQUEST[2], HOLDINGS_REQUEST[2]}
    assert not any("order" in p for p in groww_client.ALLOWED_PATHS)
    for path in ("/v1/order/create", "/v1/orders/list", "/v1/holdings/user/extra"):
        with pytest.raises(groww_client.GrowwUnavailable):
            groww_client._send(httpx.Request("GET", "https://api.groww.in" + path))
    assert lab.groww.requests == []  # a blocked path never reached the transport


def test_a_whole_journey_builds_exactly_the_two_allowed_requests(lab):
    confirm_baseline(lab)
    refresh(lab, [holding(ALPHA, 9, 110.0)])
    assert set(lab.groww.requests) == {TOKEN_REQUEST, HOLDINGS_REQUEST}
    assert lab.groww.requests.count(TOKEN_REQUEST) == 1  # the token is cached for the rest of the day


# ================================================================== D1: a re-bought stock restarts its buy date
# (owner decision, GROWW-388-CONTRACT.md: a stock the owner removed or marked sold by hand, that Groww later shows
# as held again, restarts its buy date at that sync's IST day)


def assert_restarted(lab, symbol: str, old_day) -> None:
    """The buy date and Day count are the sync day's, the old value is in the history, the note is kept."""
    row = db_row(lab, symbol)
    assert row.removed_at is None
    assert tracker_rules.ist_date(row.added_at) == today()
    item = rows_of(lab)[symbol]
    assert item["bought_on"] == today().isoformat() and item["day_number"] == 1
    moves = [(o, n, by) for f, o, n, by in history(lab, symbol) if f == "added_at"]
    assert len(moves) == 1, moves
    old, new, by = moves[0]
    assert by == "groww_sync"
    assert tracker_rules.ist_date(datetime.fromisoformat(old)) == old_day
    assert tracker_rules.ist_date(datetime.fromisoformat(new)) == today()
    assert row.note == "my note"


def test_d1_a_linked_stock_removed_by_hand_and_held_again_restarts_its_buy_date(lab):
    confirm_baseline(lab)
    assert lab.c.delete(API + f"/me/watchlist/{ALPHA}", headers=lab.h).status_code == 200
    assert db_row(lab, ALPHA).removed_at is not None
    assert refresh(lab).json()["status"] == "complete"  # Groww still shows it held
    assert_restarted(lab, ALPHA, OLD_BUY_DAY.date())


def test_d1_a_hand_entered_stock_marked_sold_by_hand_then_bought_in_groww_restarts_its_buy_date(lab):
    r = lab.c.post(API + f"/me/watchlist/{ALPHA}/sold", json={"sell_price": 60.0}, headers=lab.h)
    assert r.status_code == 200 and db_row(lab, ALPHA).removed_at is not None
    refresh(lab, [holding(ALPHA, 3, 130.0)])
    assert lab.c.post(API + "/groww/matching/confirm-all", headers=lab.h).json() == {"confirmed": 1}
    assert db_row(lab, ALPHA).quantity == 3
    assert_restarted(lab, ALPHA, OLD_BUY_DAY.date())


def test_d1_a_hand_entered_stock_removed_by_hand_then_bought_in_groww_restarts_its_buy_date(lab):
    assert lab.c.delete(API + f"/me/watchlist/{ALPHA}", headers=lab.h).status_code == 200
    refresh(lab, [holding(ALPHA, 3, 130.0)])
    assert lab.c.post(API + "/groww/matching/confirm-all", headers=lab.h).json() == {"confirmed": 1}
    assert_restarted(lab, ALPHA, OLD_BUY_DAY.date())


def _no_buy_date_move(lab, symbol: str) -> None:
    row = db_row(lab, symbol)
    assert row.added_at == OLD_BUY_DAY and row.note == "my note" and row.removed_at is None
    assert not [1 for f, *_ in history(lab, symbol) if f == "added_at"]
    assert rows_of(lab)[symbol]["bought_on"] == OLD_BUY_DAY.date().isoformat()


def test_d1_a_top_up_never_moves_the_buy_date(lab):
    confirm_baseline(lab)
    refresh(lab, [holding(ALPHA, 15, 110.0), holding(BRAVO, 4, 200.0), holding(CHARLIE, 7, 300.0)])
    assert rows_of(lab)[ALPHA]["quantity"] == 15
    _no_buy_date_move(lab, ALPHA)


def test_d1_a_repeated_sync_never_moves_the_buy_date(lab):
    confirm_baseline(lab)
    for _ in range(3):
        assert refresh(lab).json()["status"] == "complete"
    _no_buy_date_move(lab, ALPHA)


def test_d1_an_ordinary_sync_of_a_listed_row_never_moves_the_buy_date(lab):
    confirm_baseline(lab)
    refresh(lab, [holding(ALPHA, 10, 100.5), holding(BRAVO, 5, 210.0), holding(CHARLIE, 7, 300.0)])
    refresh(lab, [holding(ALPHA, 8, 100.5), holding(BRAVO, 5, 210.0)])  # a partial sale and a stock gone
    assert rows_of(lab)[ALPHA]["quantity"] == 8
    _no_buy_date_move(lab, ALPHA)


def test_d1_a_partial_hand_sale_of_a_linked_row_that_stays_listed_never_moves_the_buy_date(lab):
    confirm_baseline(lab)
    refresh(lab, [holding(ALPHA, 6, 100.5), holding(BRAVO, 4, 200.0), holding(CHARLIE, 7, 300.0)])
    r = lab.c.post(API + f"/me/watchlist/{ALPHA}/sold", json={"sell_price": 120.0, "quantity": 4}, headers=lab.h)
    assert r.status_code == 200 and db_row(lab, ALPHA).removed_at is None
    refresh(lab)
    _no_buy_date_move(lab, ALPHA)


def test_confirming_part_of_a_sale_leaves_the_rest_to_confirm(lab):
    confirm_baseline(lab)
    refresh(lab, [holding(ALPHA, 4, 100.5), holding(BRAVO, 4, 200.0), holding(CHARLIE, 7, 300.0)])
    assert pending(lab, ALPHA) == 6.0
    r = lab.c.post(API + f"/me/watchlist/{ALPHA}/sold", json={"sell_price": 120.0, "quantity": 4}, headers=lab.h)
    assert r.status_code == 200
    stamp_sale_now(lab)
    assert pending(lab, ALPHA) == 2.0


def test_a_holding_with_a_not_a_number_quantity_makes_the_sync_partial(lab):
    body = (
        '{"payload": {"holdings": [{"isin": "INE0AAA01011", "trading_symbol": "ALPHA-EQ", '
        '"quantity": NaN, "average_price": 100.5}]}}'
    )
    lab.groww.mode, lab.groww.raw_body = "raw", body.encode()
    assert refresh(lab).json()["status"] == "partial"
