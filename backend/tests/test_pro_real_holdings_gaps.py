"""A Pro member must never read the owner's REAL Zerodha holdings through the two
routes the plan opens: /brain/track/{symbol}?book=real and /signals/buy-list."""

from __future__ import annotations

from datetime import date

import pytest

from brain_m18_fixtures import DAY, at, instrument
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainTrack
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position, Signal, Strategy
from swing_trade_ml.services.plans import set_plans_enabled

KEY = {"X-API-Key": "test-api-key"}


def _user(db, name: str, role: str, plan: str = "free") -> dict[str, str]:
    u = User(username=name, hashed_password="x", is_active=True, role=role, plan=plan)
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def _track(db, book: str, symbol: str) -> None:
    db.add(
        BrainTrack(
            book=book,
            symbol=symbol,
            opened_on=date(2026, 11, 2),
            day=date(2026, 11, 3),
            day_n=1,
            ret=0.01,
            status="ON_TRACK",
            reason="",
            stop=96.0,
            band=[],
        )
    )
    db.flush()


def _signal(
    db,
    strat_name: str,
    strat_type: str,
    symbol: str,
    token: int,
    *,
    strat_mode: str = "paper",
    execution_mode: str = "auto",
) -> Strategy:
    strat = Strategy(
        name=strat_name,
        strategy_type=strat_type,
        params={},
        is_active=True,
        mode=strat_mode,
        execution_mode=execution_mode,
    )
    db.add(strat)
    db.flush()
    inst = instrument(db, symbol, token)
    db.add(
        Signal(
            strategy_id=strat.id,
            instrument_id=inst.id,
            signal_type=SignalType.BUY,
            mode="paper",
            price=100.0,
            confidence=0.7,
            stop_loss=96.0,
            take_profit=108.0,
            horizon_days=5,
            generated_at=at(DAY),
            features={},
        )
    )
    db.flush()
    return strat


@pytest.fixture()
def people(db_session, monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)  # the autouse switch only covers test_brain* files
    set_plans_enabled(db_session, True)
    return {
        "free": _user(db_session, "prg-free", "member", "free"),
        "pro": _user(db_session, "prg-pro", "member", "pro"),
        "owner": _user(db_session, "prg-owner", "owner"),
    }


# ---- /brain/track -----------------------------------------------------------------


@pytest.mark.parametrize("who", ["free", "pro"])
@pytest.mark.parametrize("book", ["real", "live", "tester", "all"])
def test_member_cannot_read_non_paper_track(client, db_session, people, who, book):
    _track(db_session, "real", "PRGREAL")
    r = client.get(f"/api/v1/brain/track/PRGREAL?book={book}", headers=people[who])
    assert r.status_code == 403, r.text
    assert "points" not in r.json()


def test_owner_user_reads_real_track(client, db_session, people):
    _track(db_session, "real", "PRGREAL")
    r = client.get("/api/v1/brain/track/PRGREAL?book=real", headers=people["owner"])
    assert r.status_code == 200, r.text
    assert len(r.json()["points"]) == 1


@pytest.mark.parametrize("book", ["real", "live", "tester", "all"])
def test_shared_api_key_refused_for_non_paper_track(client, db_session, people, book):
    # Nothing in the repo calls /brain/track with the key; the key stays paper-only.
    _track(db_session, "real", "PRGREAL")
    r = client.get(f"/api/v1/brain/track/PRGREAL?book={book}", headers=KEY)
    assert r.status_code == 403, r.text


def test_shared_api_key_still_reads_paper_track(client, db_session, people):
    _track(db_session, "paper", "PRGPAPER")
    r = client.get("/api/v1/brain/track/PRGPAPER?book=paper", headers=KEY)
    assert r.status_code == 200, r.text


def test_anonymous_refused_on_track(client):
    assert client.get("/api/v1/brain/track/PRGREAL?book=real").status_code in (401, 403)


def test_pro_member_still_reads_paper_track(client, db_session, people):
    _track(db_session, "paper", "PRGPAPER")
    for url in ("/api/v1/brain/track/PRGPAPER", "/api/v1/brain/track/PRGPAPER?book=paper"):
        r = client.get(url, headers=people["pro"])
        assert r.status_code == 200, r.text
        assert len(r.json()["points"]) == 1


# ---- /signals/buy-list ------------------------------------------------------------


def _seed_buy_list(db, *, rename_real: bool = False):
    """Member-facing rows (model, brain, rule) beside every kind of owner-private row."""
    _signal(db, "prg_model", "ml_swing", "PRGMODEL", 929004)
    _signal(db, "prg_brain", "brain", "PRGBRAIN", 929005, execution_mode="advisory")
    _signal(db, "prg_rules", "rule_based", "PRGRULE", 929003)
    # The owner's real Zerodha book, exactly as import-holdings creates it.
    real = _signal(
        db, "real_trading", "ml_swing", "PRGREALSIG", 929002, strat_mode="live", execution_mode="advisory"
    )
    # Manual paper-testing book.
    tester = _signal(db, "tester_paper", "tester_paper", "PRGTESTER", 929006, execution_mode="auto")
    # A hand book that kept no name or mode marker, only its live positions.
    owned = _signal(db, "prg_owned_live", "ml_swing", "PRGOWNED", 929007, execution_mode="advisory")
    other = instrument(db, "PRGOWNEDPOS", 929008)
    db.add(
        Position(
            strategy_id=owned.id,
            instrument_id=other.id,
            mode="live",
            status="OPEN",
            quantity=1,
            entry_price=100.0,
            entry_at=at(DAY),
        )
    )
    if rename_real:
        real.name = "prg_renamed_real"
        tester.name = "prg_renamed_tester"
    db.flush()


PRIVATE = {"PRGREALSIG", "PRGTESTER", "PRGOWNED"}
SHOWN = {"PRGMODEL", "PRGBRAIN", "PRGRULE"}


def _syms(r):
    return {row["symbol"] for row in r.json() if row["symbol"].startswith("PRG")}


@pytest.mark.parametrize("rename", [False, True])
def test_pro_member_buy_list_keeps_member_signals_and_hides_private(client, db_session, people, rename):
    _seed_buy_list(db_session, rename_real=rename)
    r = client.get("/api/v1/signals/buy-list", headers=people["pro"])
    assert r.status_code == 200, r.text
    assert _syms(r) == SHOWN


def test_free_member_buy_list_denied(client, db_session, people):
    _seed_buy_list(db_session)
    r = client.get("/api/v1/signals/buy-list", headers=people["free"])
    assert r.status_code == 403


@pytest.mark.parametrize("headers_key", ["owner", "key"])
def test_owner_buy_list_unchanged(client, db_session, people, headers_key):
    _seed_buy_list(db_session)
    h = people["owner"] if headers_key == "owner" else KEY
    r = client.get("/api/v1/signals/buy-list", headers=h)
    assert r.status_code == 200, r.text
    assert _syms(r) == SHOWN | PRIVATE
    assert set(r.json()[0]) == {
        "symbol",
        "name",
        "strategy_name",
        "price",
        "confidence",
        "stop_loss",
        "take_profit",
        "reason",
        "generated_at",
    }


def test_anonymous_refused_on_buy_list(client):
    assert client.get("/api/v1/signals/buy-list").status_code in (401, 403)
