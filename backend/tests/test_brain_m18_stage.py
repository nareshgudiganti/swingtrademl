"""M18 task 6: the owner's stage switch — default shadow, 30 finished ideas
before leaving it, auto only after approval, every change audited, and no code
but the stage service can change it."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from brain_m18_fixtures import DAY, brain_strategy, instrument, signal
from swing_trade_ml.db.models.brain_golive import BrainStageChange
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


def stage_row(db, stage_name: str, previous: str, changed_at: datetime) -> None:
    db.add(
        BrainStageChange(
            stage=stage_name, previous_stage=previous, changed_by="owner", reason="r", changed_at=changed_at
        )
    )
    db.flush()


def test_the_newest_row_wins_even_if_the_clock_stepped_back(db_session):
    """The owner's rollback is the later insert; a clock step backwards must not
    let the older "approval" row look newer and silently undo the switch-off."""
    stage_row(db_session, "approval", "shadow", datetime(2031, 1, 6, 10, 0, tzinfo=UTC))
    stage_row(db_session, "shadow", "approval", datetime(2031, 1, 6, 9, 0, tzinfo=UTC))
    assert stage.current_stage(db_session) == "shadow"
    assert [h["stage"] for h in stage.stage_overview(db_session)["history"]] == ["shadow", "approval"]


def test_an_unknown_stored_stage_counts_as_shadow(db_session, client):
    stage_row(db_session, "nonsense", "shadow", datetime(2031, 1, 6, 10, 0, tzinfo=UTC))
    assert stage.current_stage(db_session) == "shadow"
    r = client.get("/api/v1/brain/stage", headers=HEADERS)
    assert r.status_code == 200 and r.json()["stage"] == "shadow"


def test_nothing_else_touches_the_stage_table():
    """No raw SQL on the table name, no insert/update/delete on the model and no
    `.stage =` on a stage row outside the model, its migration and stage.py."""
    root = Path(__file__).parents[1]
    model = "src/swing_trade_ml/db/models/brain_golive.py"
    service = "src/swing_trade_ml/services/brain_golive/stage.py"
    migration = "alembic/versions/20261004_0900_brain_golive_stage.py"
    paths = [*(root / "src" / "swing_trade_ml").rglob("*.py"), *(root / "alembic" / "versions").glob("*.py")]
    table_names, statements, stage_sets = set(), set(), set()
    for path in paths:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "brain_stage_changes" in node.value
            ):
                table_names.add(rel)
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None))
                in {"insert", "update", "delete"}
                and any(getattr(a, "id", None) == "BrainStageChange" for a in node.args)
            ):
                statements.add(rel)
            if "BrainStageChange" in text and isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Attribute) and t.attr == "stage" for t in targets):
                    stage_sets.add(rel)
    assert table_names == {model, migration}
    assert statements <= {service}
    assert stage_sets <= {service}
