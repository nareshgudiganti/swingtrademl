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
from swing_trade_ml.db.models.trading import Signal, Strategy
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


def _signal(db, strat_name: str, strat_type: str, symbol: str, token: int) -> None:
    strat = Strategy(name=strat_name, strategy_type=strat_type, params={}, is_active=True, mode="paper")
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


@pytest.mark.parametrize("headers_key", ["owner", "key"])
def test_owner_and_api_key_read_real_track(client, db_session, people, headers_key):
    _track(db_session, "real", "PRGREAL")
    h = people["owner"] if headers_key == "owner" else KEY
    r = client.get("/api/v1/brain/track/PRGREAL?book=real", headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()["points"]) == 1


def test_anonymous_refused_on_track(client):
    assert client.get("/api/v1/brain/track/PRGREAL?book=real").status_code in (401, 403)


def test_pro_member_still_reads_paper_track(client, db_session, people):
    _track(db_session, "paper", "PRGPAPER")
    for url in ("/api/v1/brain/track/PRGPAPER", "/api/v1/brain/track/PRGPAPER?book=paper"):
        r = client.get(url, headers=people["pro"])
        assert r.status_code == 200, r.text
        assert len(r.json()["points"]) == 1


# ---- /signals/buy-list ------------------------------------------------------------


def _seed_buy_list(db):
    _signal(db, "prg_real_trading", "ml_swing", "PRGHAND", 929001)
    _signal(db, "real_trading", "ml_swing", "PRGREALSIG", 929002)
    _signal(db, "prg_rules", "rule_based", "PRGRULE", 929003)
    _signal(db, "prg_model", "ml_swing", "PRGMODEL", 929004)


def _syms(r):
    return {row["symbol"] for row in r.json() if row["symbol"].startswith("PRG")}


def test_pro_member_buy_list_excludes_real_and_non_model(client, db_session, people):
    _seed_buy_list(db_session)
    r = client.get("/api/v1/signals/buy-list", headers=people["pro"])
    assert r.status_code == 200, r.text
    syms = _syms(r)
    assert "PRGREALSIG" not in syms and "PRGRULE" not in syms
    assert "PRGMODEL" in syms  # normal bot-model idea still shown


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
    assert _syms(r) == {"PRGHAND", "PRGREALSIG", "PRGRULE", "PRGMODEL"}
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
