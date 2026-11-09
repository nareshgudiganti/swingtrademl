# ruff: noqa: E501 (long test sentences)
"""Activation is owner-only, audited, and never changes any trading switch. Synthetic rows only."""

from __future__ import annotations

from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Strategy

API_KEY = {"X-API-Key": "test-api-key"}


def _login(db, username, *, role=None):
    user = User(username=username, hashed_password="x", is_active=True, is_superuser=False, plan="free", role=role)
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def _model(db, name, version, status):
    m = MLModel(name=name, version=version, algorithm="lightgbm", status=status, prediction_horizon_days=15, feature_names=["a"])
    db.add(m)
    db.flush()
    return m


def _strategy(db, name="s_audit"):
    s = Strategy(name=name, strategy_type="ml_swing", params={}, is_active=False)
    db.add(s)
    db.flush()
    return s


def _rows(db, action):
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def test_member_tester_and_anonymous_cannot_activate_a_model_or_strategy(client, db_session):
    m = _model(db_session, "swing_classifier", "v1", "TRAINED")
    s = _strategy(db_session)
    for who in (_login(db_session, "mem1"), _login(db_session, "tst1", role="tester"), {}):
        assert client.post(f"/api/v1/ml/models/{m.id}/activate", headers=who).status_code in (401, 403)
        assert client.post(f"/api/v1/strategies/{s.id}/activate", headers=who).status_code in (401, 403)
    db_session.expire_all()
    assert db_session.get(MLModel, m.id).status == "TRAINED"
    assert db_session.get(Strategy, s.id).is_active is False
    assert not _rows(db_session, "model.activate") and not _rows(db_session, "strategy.activate")


def test_owner_model_activation_writes_one_audit_row_with_before_and_after(client, db_session):
    old = _model(db_session, "swing_classifier", "v1", "ACTIVE")
    new = _model(db_session, "swing_classifier", "v2", "TRAINED")
    assert client.post(f"/api/v1/ml/models/{new.id}/activate", headers=API_KEY).status_code == 200
    db_session.expire_all()
    assert db_session.get(MLModel, new.id).status == "ACTIVE" and db_session.get(MLModel, old.id).status == "ARCHIVED"
    rows = _rows(db_session, "model.activate")
    assert len(rows) == 1
    assert rows[0].target_id == str(new.id)
    assert rows[0].before["active_id"] == old.id and rows[0].after["version"] == "v2"


def test_refused_model_activation_still_leaves_no_promotion(client, db_session):
    running = _model(db_session, "swing_classifier", "v1", "ACTIVE")
    failed = _model(db_session, "swing_classifier", "v2", "FAILED")
    assert client.post(f"/api/v1/ml/models/{failed.id}/activate", headers=API_KEY).status_code == 400
    db_session.expire_all()
    assert db_session.get(MLModel, running.id).status == "ACTIVE"
    assert db_session.get(MLModel, failed.id).status == "FAILED"


def test_strategy_activate_and_deactivate_are_audited(client, db_session):
    s = _strategy(db_session, "s_audit2")
    assert client.post(f"/api/v1/strategies/{s.id}/activate", headers=API_KEY).status_code == 200
    assert client.post(f"/api/v1/strategies/{s.id}/deactivate", headers=API_KEY).status_code == 200
    db_session.expire_all()
    on, off = _rows(db_session, "strategy.activate"), _rows(db_session, "strategy.deactivate")
    assert len(on) == 1 and on[0].before == {"is_active": False} and on[0].after["is_active"] is True
    assert len(off) == 1 and off[0].before == {"is_active": True} and off[0].after["is_active"] is False


def test_activating_a_model_changes_no_trading_switch_or_strategy(client, db_session):
    live = (settings.TRADING_MODE, settings.ALLOW_LIVE_TRADING, settings.ALLOW_REAL_HOLDINGS_ORDERS, settings.is_live_trading)
    s = _strategy(db_session, "s_untouched")
    m = _model(db_session, "swing_classifier", "v9", "TRAINED")
    assert client.post(f"/api/v1/ml/models/{m.id}/activate", headers=API_KEY).status_code == 200
    db_session.expire_all()
    assert (settings.TRADING_MODE, settings.ALLOW_LIVE_TRADING, settings.ALLOW_REAL_HOLDINGS_ORDERS, settings.is_live_trading) == live
    assert settings.is_live_trading is False
    assert db_session.get(Strategy, s.id).is_active is False
