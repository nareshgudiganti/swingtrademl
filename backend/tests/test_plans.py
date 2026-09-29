"""Free / Plus / Pro plans — see core/plans.py.

The owner (superuser or X-API-Key) is never limited. Everyone else reaches
only the routes a feature in their plan opens, and sees only the base
model's picks unless the plan includes every model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Signal, Strategy

API_KEY = {"X-API-Key": "test-api-key"}


def _user(db_session, username, *, plan="free", owner=False) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, is_superuser=owner, plan=plan)
    db_session.add(user)
    db_session.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def _strategy(db_session, name, model_name=None, strategy_type="ml_swing") -> Strategy:
    strat = Strategy(
        name=name,
        strategy_type=strategy_type,
        mode="paper",
        is_active=True,
        params={"model_name": model_name} if model_name else {},
    )
    db_session.add(strat)
    db_session.flush()
    return strat


def _buy(db_session, strategy, symbol, confidence, *, age_days=0) -> Signal:
    inst = db_session.query(Instrument).filter_by(tradingsymbol=symbol).one_or_none()
    if inst is None:
        token = abs(hash(symbol)) % 10_000_000
        inst = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE")
        db_session.add(inst)
        db_session.flush()
    sig = Signal(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        signal_type="BUY",
        mode="paper",
        price=100.0,
        confidence=confidence,
        stop_loss=95.0,
        take_profit=108.0,
        generated_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db_session.add(sig)
    db_session.flush()
    return sig


@pytest.fixture()
def book(db_session):
    """A large-cap base-model strategy with 7 BUYs, a mid-cap one with 2,
    and the owner's hand-bought real_trading book with 1."""
    base = _strategy(db_session, "ml_swing_main")
    mid = _strategy(db_session, "ml_swing_mid", "swing_classifier_midcap")
    real = _strategy(db_session, "real_trading")
    for i in range(7):
        _buy(db_session, base, f"LARGE{i}", 0.70 + i / 100)
    _buy(db_session, mid, "MID0", 0.95)
    _buy(db_session, mid, "MID1", 0.94)
    _buy(db_session, real, "MINE", 0.99)
    _buy(db_session, base, "OLDPICK", 0.99, age_days=10)
    return base


# ------------------------------------------------------------- access gate --


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/ml/predictions"),
        ("get", "/api/v1/strategies"),
        ("post", "/api/v1/strategies/scan-all"),
        ("post", "/api/v1/backtest"),
        ("get", "/api/v1/portfolio/holdings"),
        ("get", "/api/v1/risk/limits"),
        ("get", "/api/v1/safety/state"),
        ("get", "/api/v1/finance/transactions"),
        ("get", "/api/v1/status"),
        ("get", "/api/v1/signals/buy-list"),
    ],
)
def test_free_user_is_refused_everything_outside_the_plan(client, db_session, method, path):
    headers = _user(db_session, "free1")
    resp = getattr(client, method)(path, headers=headers)
    assert resp.status_code == 403, resp.text


def test_free_user_reaches_their_features(client, db_session, book):
    headers = _user(db_session, "free2")
    assert client.get("/api/v1/signals/picks", headers=headers).status_code == 200
    assert client.get("/api/v1/signals/track-record", headers=headers).status_code == 200


def test_plus_cannot_read_the_owners_real_book(client, db_session):
    headers = _user(db_session, "plus1", plan="plus")
    assert client.get("/api/v1/portfolio/trades?book=bot", headers=headers).status_code == 200
    assert client.get("/api/v1/portfolio/trades?book=real", headers=headers).status_code == 403
    assert client.get("/api/v1/portfolio/trades", headers=headers).status_code == 403


def test_owner_and_api_key_see_everything(client, db_session):
    owner = _user(db_session, "boss", owner=True)
    for headers in (owner, API_KEY):
        assert client.get("/api/v1/strategies", headers=headers).status_code == 200
        assert client.get("/api/v1/signals/buy-list", headers=headers).status_code == 200


# ------------------------------------------------------------------ picks --


def test_free_picks_are_five_base_model_large_caps(client, db_session, book):
    rows = client.get("/api/v1/signals/picks", headers=_user(db_session, "free3")).json()
    assert len(rows) == 5
    assert {r["strategy_name"] for r in rows} == {"ml_swing_main"}
    assert all(r["cap_tier"] == "large" for r in rows)
    # Highest confidence first, and a 10-day-old BUY is not today's pick.
    assert [r["symbol"] for r in rows] == ["LARGE6", "LARGE5", "LARGE4", "LARGE3", "LARGE2"]


def test_pro_picks_include_every_model_but_never_the_real_book(client, db_session, book):
    rows = client.get("/api/v1/signals/picks", headers=_user(db_session, "pro1", plan="pro")).json()
    symbols = {r["symbol"] for r in rows}
    assert {"MID0", "MID1", "LARGE0"} <= symbols
    assert "MINE" not in symbols
    assert "OLDPICK" not in symbols


def test_owner_picks_are_unlimited(client, db_session, book):
    rows = client.get("/api/v1/signals/picks", headers=API_KEY).json()
    assert len(rows) == 10  # 7 large + 2 mid + the owner's own real_trading BUY


def test_free_track_record_is_base_model_only(client, db_session, book):
    rows = client.get("/api/v1/signals/track-record", headers=_user(db_session, "free4")).json()
    assert rows and {r["strategy_name"] for r in rows} == {"ml_swing_main"}
    assert all(r["trade_net_pnl"] is None for r in rows)


# ---------------------------------------------------------------- preview --


def test_owner_can_preview_free(client, db_session, book):
    owner = _user(db_session, "boss2", owner=True)
    preview = {**owner, "X-Preview-Plan": "free"}
    assert client.get("/api/v1/strategies", headers=preview).status_code == 403
    assert len(client.get("/api/v1/signals/picks", headers=preview).json()) == 5
    me = client.get("/api/v1/me/plan", headers=preview).json()
    assert me["plan"] == "free" and me["previewing"] is True
    # Previewing never locks the owner out of the Plans Manager.
    assert client.get("/api/v1/admin/plans", headers=preview).status_code == 200


def test_preview_header_is_ignored_for_plan_users(client, db_session):
    headers = {**_user(db_session, "free5"), "X-Preview-Plan": "pro"}
    me = client.get("/api/v1/me/plan", headers=headers).json()
    assert me["plan"] == "free" and me["previewing"] is False


# ---------------------------------------------------------- plans manager --


def test_admin_routes_are_owner_only(client, db_session):
    headers = _user(db_session, "pro2", plan="pro")
    assert client.get("/api/v1/admin/plans", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.put("/api/v1/admin/users/1/plan", json={"plan": "pro"}, headers=headers).status_code == 403


def test_editing_a_plan_changes_access_at_once(client, db_session, book):
    free = _user(db_session, "free6")
    assert client.get("/api/v1/ml/models", headers=free).status_code == 403

    plans = {p["key"]: p for p in client.get("/api/v1/admin/plans", headers=API_KEY).json()}
    features = {**plans["free"]["features"], "model_lab": True}
    limits = {**plans["free"]["limits"], "picks_per_day": 2}
    body = {"features": features, "limits": limits}
    resp = client.put("/api/v1/admin/plans/free", json=body, headers=API_KEY)
    assert resp.status_code == 200, resp.text

    assert client.get("/api/v1/ml/models", headers=free).status_code == 200
    assert len(client.get("/api/v1/signals/picks", headers=free).json()) == 2


def test_unknown_plan_keys_are_refused(client):
    resp = client.put(
        "/api/v1/admin/plans/free",
        json={"features": {"teleport": True}, "limits": {}},
        headers=API_KEY,
    )
    assert resp.status_code == 422


def test_assigning_a_user_to_a_plan(client, db_session, book):
    headers = _user(db_session, "mover")
    user_id = db_session.query(User).filter_by(username="mover").one().id
    resp = client.put(f"/api/v1/admin/users/{user_id}/plan", json={"plan": "pro"}, headers=API_KEY)
    assert resp.status_code == 200 and resp.json()["plan"] == "pro"
    assert client.get("/api/v1/me/plan", headers=headers).json()["plan"] == "pro"
    bad = client.put(f"/api/v1/admin/users/{user_id}/plan", json={"plan": "gold"}, headers=API_KEY)
    assert bad.status_code == 422
