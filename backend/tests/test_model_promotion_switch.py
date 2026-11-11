"""Model promotion is gated by the model_promotion release switch (default off). No DB needed."""

from __future__ import annotations

import argparse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from swing_trade_ml.api.v1.endpoints import ml as ml_ep
from swing_trade_ml.core import release_switches as rs
from swing_trade_ml.core.config import settings


def test_refusal_text_when_off_and_none_when_on(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    assert rs.promotion_refusal() == rs.PROMOTION_OFF_MESSAGE
    assert "ALLOW_MODEL_PROMOTION" in rs.PROMOTION_OFF_MESSAGE
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)
    assert rs.promotion_refusal() is None


def test_activate_endpoint_refuses_before_touching_the_database_when_off(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)

    def boom(*a, **k):
        raise AssertionError("must not reach activate_model while the switch is off")

    monkeypatch.setattr(ml_ep, "activate_model", boom)
    with pytest.raises(HTTPException) as e:
        ml_ep.activate(1, db=None)  # type: ignore[arg-type]
    assert e.value.status_code == 403
    assert e.value.detail == rs.PROMOTION_OFF_MESSAGE


def test_activate_endpoint_proceeds_when_on(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)
    sentinel = object()
    monkeypatch.setattr(ml_ep, "activate_model", lambda db, mid: sentinel)
    monkeypatch.setattr(ml_ep.predict_service, "clear_cache", lambda: None)
    assert ml_ep.activate(7, db=None) is sentinel  # type: ignore[arg-type]


def _train_client():
    app = FastAPI()
    app.include_router(ml_ep.router)
    return TestClient(app)


def test_train_with_auto_activate_is_refused_when_off(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    r = _train_client().post("/ml/train", json={"name": "m", "auto_activate": True})
    assert r.status_code == 403
    assert r.json()["detail"] == rs.PROMOTION_OFF_MESSAGE


def test_train_without_auto_activate_still_works_when_off(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    monkeypatch.setattr(ml_ep.train_service, "train_model", lambda *a, **k: None)
    r = _train_client().post("/ml/train", json={"name": "m", "auto_activate": False})
    assert r.status_code == 202


def test_cli_train_with_activate_refuses_and_trains_nothing_when_off(monkeypatch, capsys):
    from swing_trade_ml import cli

    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    monkeypatch.setattr("swing_trade_ml.ml.train.train_model", lambda *a, **k: pytest.fail("trained"))
    assert cli.cmd_train(argparse.Namespace(activate=True)) == 1
    out = capsys.readouterr().out
    assert "switched off" in out and "Nothing was trained" in out
