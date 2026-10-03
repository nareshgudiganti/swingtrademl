"""M18 task 6: the owner's stage switch — default shadow, 30 finished ideas
before leaving it, auto only after approval, every change audited, and no code
but the stage service can change it."""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

from brain_m18_fixtures import DAY, brain_strategy, instrument, signal
from swing_trade_ml.services.brain_golive import stage

HEADERS = {"X-API-Key": "test-api-key"}


def finished_ideas(db, n: int) -> None:
    s = brain_strategy(db, name="m18-history")
    inst = instrument(db, "M18HIS", 918900)
    for i in range(n):
        signal(db, s, inst, DAY - timedelta(days=60 - i), outcome="TARGET_HIT", outcome_pct=0.08)


def test_the_stage_starts_in_shadow(db_session):
    assert stage.current_stage(db_session) == "shadow"


def test_leaving_shadow_needs_30_finished_ideas(db_session):
    finished_ideas(db_session, 29)
    with pytest.raises(stage.StageRefusedError, match="Only 29 of 30"):
        stage.set_stage(db_session, "approval", by="owner", reason="Looks good")
    assert stage.current_stage(db_session) == "shadow"


def test_auto_only_after_the_approval_stage(db_session):
    finished_ideas(db_session, 30)
    with pytest.raises(stage.StageRefusedError, match="approval stage"):
        stage.set_stage(db_session, "auto", by="owner", reason="Skip ahead")
    stage.set_stage(db_session, "approval", by="owner", reason="Enough evidence")
    stage.set_stage(db_session, "auto", by="owner", reason="Approvals went well")
    assert stage.current_stage(db_session) == "auto"


def test_every_change_is_recorded_with_who_when_and_why(db_session):
    finished_ideas(db_session, 30)
    stage.set_stage(db_session, "approval", by="owner", reason="Enough evidence")
    stage.set_stage(db_session, "shadow", by="owner", reason="Market looks rough")
    history = stage.stage_overview(db_session)["history"]
    assert [(h["previous_stage"], h["stage"], h["changed_by"], h["reason"]) for h in history] == [
        ("approval", "shadow", "owner", "Market looks rough"),
        ("shadow", "approval", "owner", "Enough evidence"),
    ]
    assert all(h["changed_at"] for h in history)


def test_a_reason_is_required_and_the_same_stage_is_refused(db_session):
    with pytest.raises(stage.StageRefusedError, match="Say why"):
        stage.set_stage(db_session, "shadow", by="owner", reason="  ")
    with pytest.raises(stage.StageRefusedError, match="already"):
        stage.set_stage(db_session, "shadow", by="owner", reason="again")


def test_nothing_but_the_stage_service_writes_a_stage_change():
    """No job, scan or endpoint may switch the brain on by itself."""
    src = Path(__file__).parents[1] / "src" / "swing_trade_ml"
    writers = set()
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BrainStageChange":
                writers.add(path.relative_to(src).as_posix())
    assert writers == {"services/brain_golive/stage.py"}


def test_stage_endpoints(client):
    r = client.get("/api/v1/brain/stage", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert (body["stage"], body["finished"], body["needed"], body["ready"]) == ("shadow", 0, 30, False)
    r = client.put("/api/v1/brain/stage", json={"stage": "approval", "reason": "try"}, headers=HEADERS)
    assert r.status_code == 409 and "Only 0 of 30" in r.json()["detail"]
    assert (
        client.put(
            "/api/v1/brain/stage", json={"stage": "approval", "reason": " "}, headers=HEADERS
        ).status_code
        == 422
    )
    assert (
        client.put("/api/v1/brain/stage", json={"stage": "live", "reason": "x"}, headers=HEADERS).status_code
        == 422
    )
