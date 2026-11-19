"""Issue #374: /status must not leak the owner's private book counts.

The per-book open-position counts follow the same rule as `deps.book_for`:
- the real-account owner (REAL_ACCOUNT_USERS) and the legacy API key see every book;
- another owner, and a scoped service key, see the bot and testing books, never real;
- a tester sees only the shared testing (practice) book: no bot count, no real count,
  and no `open_positions` (which is the bot book's count);
- a member is refused /status outright (no plan opens it).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from brain_m18_fixtures import instrument, v1_strategy
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services import service_keys

API_KEY = {"X-API-Key": "test-api-key"}
REAL_OWNER = "sbp-realowner"


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def _pos(db, strategy, inst, mode="paper"):
    db.add(
        Position(
            strategy_id=strategy.id,
            instrument_id=inst.id,
            mode=mode,
            status=PositionStatus.OPEN,
            entry_price=100.0,
            quantity=1,
            entry_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    db.flush()


@pytest.fixture
def seeded_books(db_session, monkeypatch):
    """Open positions in all three books: 2 bot, 3 testing, 4 real."""
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", REAL_OWNER)
    advisory = {"execution_mode": "advisory"}
    bot = v1_strategy(db_session, name="sbp-bot")
    testing = v1_strategy(db_session, name="sbp-tester", strategy_type="tester_paper", **advisory)
    real = v1_strategy(db_session, name="real_trading", strategy_type="long_term_value", **advisory)
    for i, (strat, n, mode) in enumerate([(bot, 2, "paper"), (testing, 3, "paper"), (real, 4, "live")]):
        for j in range(n):
            _pos(db_session, strat, instrument(db_session, f"SBP{i}{j}", 970000 + i * 10 + j), mode)
    db_session.commit()


def _status(client, headers) -> dict:
    r = client.get("/api/v1/status", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_tester_sees_only_the_testing_book(client, db_session, seeded_books):
    full = _status(client, API_KEY)["open_positions_by_book"]
    body = _status(client, _as(db_session, "sbp-tester-u", "tester"))
    assert body["open_positions_by_book"] == {"testing": full["testing"]}
    assert "bot" not in body["open_positions_by_book"]
    assert "real" not in body["open_positions_by_book"]
    # The single number is the bot book's count: hidden from a tester.
    assert body["open_positions"] is None
    # The rest of the status still answers (the tester keeps the shared app view).
    assert body["status_level"] and body["trading_mode"] == "paper"


def test_real_account_owner_sees_every_book_unchanged(client, db_session, seeded_books):
    full = _status(client, API_KEY)
    body = _status(client, _as(db_session, REAL_OWNER, "owner"))
    assert set(body["open_positions_by_book"]) == {"bot", "testing", "real"}
    assert body["open_positions_by_book"] == full["open_positions_by_book"]
    assert body["open_positions"] == body["open_positions_by_book"]["bot"]
    assert body["open_positions_by_book"]["real"] >= 4


def test_api_key_still_sees_every_book(client, seeded_books):
    body = _status(client, API_KEY)
    books = body["open_positions_by_book"]
    assert set(books) == {"bot", "testing", "real"}
    assert books["bot"] >= 2 and books["testing"] >= 3 and books["real"] >= 4
    assert body["open_positions"] == books["bot"]


def test_other_owner_does_not_see_the_real_book(client, db_session, seeded_books):
    full = _status(client, API_KEY)
    body = _status(client, _as(db_session, "sbp-owner2", "owner"))
    assert body["open_positions_by_book"] == {
        "bot": full["open_positions_by_book"]["bot"],
        "testing": full["open_positions_by_book"]["testing"],
    }
    assert body["open_positions"] == full["open_positions"]


def test_read_status_service_key_does_not_see_the_real_book(client, db_session, seeded_books):
    _, raw = service_keys.create_key(db_session, name="sbp-watch", scope="read_status", created_by="test")
    db_session.commit()
    body = _status(client, {"X-API-Key": raw})
    assert set(body["open_positions_by_book"]) == {"bot", "testing"}
    assert body["open_positions"] == body["open_positions_by_book"]["bot"]


def test_member_is_still_refused_status(client, db_session, seeded_books):
    r = client.get("/api/v1/status", headers=_as(db_session, "sbp-member", "member"))
    assert r.status_code == 403
    assert "open_positions_by_book" not in r.text


def test_owner_response_is_not_reused_for_a_tester(client, db_session, seeded_books):
    """No cache in front of /status: an owner call first must not shape the tester's answer."""
    owner = _status(client, _as(db_session, REAL_OWNER, "owner"))
    tester = _status(client, _as(db_session, "sbp-tester-2", "tester"))
    again = _status(client, _as(db_session, "sbp-owner-again", "owner"))
    assert set(owner["open_positions_by_book"]) == {"bot", "testing", "real"}
    assert set(tester["open_positions_by_book"]) == {"testing"}
    assert tester["open_positions"] is None
    assert set(again["open_positions_by_book"]) == {"bot", "testing"}


SCAN = {
    "ts": "2026-11-19T04:00:00+00:00",
    "strategies_run": 2,
    "instruments_evaluated": 40,
    "signals_generated": 3,
    "buys": 3,
    "exits": 0,
    "executed": 0,
    "errors": 0,
    "blocked": [
        {
            "rule": "POSITION_LIMIT",
            "count": 2,
            "reason": "You already hold 7 positions — the most allowed for an account of ₹9,79,792 is 7",
        },
        {
            "rule": "CASH_FLOOR",
            "count": 1,
            "reason": "Buying would leave less than ₹50,000 in cash … You have ₹61,234 in cash",
        },
    ],
}


def test_scan_block_reasons_quote_owner_money_and_are_hidden_from_a_tester(
    client, db_session, seeded_books, monkeypatch
):
    """Codex review 2026-11-19: the risk layer's sentences carry the bot's position count, account value and
    cash. A tester and an owner see the same seeded scan: the owner gets the sentences, the tester only
    which limit fired and how often."""
    from swing_trade_ml.api.v1.endpoints import system as system_ep

    monkeypatch.setattr(system_ep.heartbeat, "read_last_scan", lambda: SCAN)
    owner = _status(client, _as(db_session, REAL_OWNER, "owner"))["last_scan_result"]
    tester = _status(client, _as(db_session, "sbp-tester-scan", "tester"))["last_scan_result"]

    assert owner["blocked"] == SCAN["blocked"]
    assert tester["blocked"] == [
        {"rule": "POSITION_LIMIT", "count": 2, "reason": None},
        {"rule": "CASH_FLOOR", "count": 1, "reason": None},
    ]
    for private in ("7 positions", "9,79,792", "61,234", "50,000"):
        assert private not in str(tester)
    # Non-money scan totals stay, and the seeded scan object itself is not altered.
    assert tester["buys"] == 3 and tester["executed"] == 0
    assert SCAN["blocked"][0]["reason"].startswith("You already hold")


def test_scan_reasons_stay_for_another_owner_and_a_service_key(client, db_session, seeded_books, monkeypatch):
    from swing_trade_ml.api.v1.endpoints import system as system_ep

    monkeypatch.setattr(system_ep.heartbeat, "read_last_scan", lambda: SCAN)
    _, raw = service_keys.create_key(db_session, name="sbp-scan", scope="read_status", created_by="test")
    db_session.commit()
    assert (
        _status(client, _as(db_session, "sbp-owner-scan", "owner"))["last_scan_result"]["blocked"]
        == SCAN["blocked"]
    )
    assert _status(client, {"X-API-Key": raw})["last_scan_result"]["blocked"] == SCAN["blocked"]


def test_a_tester_with_no_scan_yet_still_gets_null(client, db_session, seeded_books, monkeypatch):
    from swing_trade_ml.api.v1.endpoints import system as system_ep

    monkeypatch.setattr(system_ep.heartbeat, "read_last_scan", lambda: None)
    assert _status(client, _as(db_session, "sbp-tester-none", "tester"))["last_scan_result"] is None
