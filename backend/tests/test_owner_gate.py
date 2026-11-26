"""Tests for the owner gate (.github/scripts/owner_gate.py): which PRs need the owner's tick."""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("owner_gate", REPO / ".github/scripts/owner_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

FROZEN = {"backend/src/swing_trade_ml/brain/modules/m08_decide/engine.py"}


def _ticked_body(paths):
    found = gate.sensitive_files(paths, FROZEN)
    return gate.with_block("My PR", gate.render_block(found, ticked=True))


def test_routine_pr_passes_without_touching_body():
    passed, new_body, _ = gate.decide("opened", ["frontend/src/pages/Today.tsx", "docs/x.md"], "hi", FROZEN)
    assert passed and new_body is None


def test_each_sensitive_area_is_caught():
    for path in [
        "backend/alembic/versions/20261127_1200_new.py",
        ".github/workflows/test.yml",
        "infra/deploy/release.sh",
        "docker-compose.prod.yml",
        "backend/Dockerfile",
        "backend/src/swing_trade_ml/api/v1/endpoints/auth.py",
        "backend/src/swing_trade_ml/services/auth_tokens.py",
        "backend/src/swing_trade_ml/services/admin_mfa.py",
        "backend/src/swing_trade_ml/services/billing/service.py",
        "backend/src/swing_trade_ml/brokers/kite.py",
        "backend/src/swing_trade_ml/services/limits.py",
        "backend/src/swing_trade_ml/services/risk.py",
        "backend/src/swing_trade_ml/brain/modules/m07_risk/allocator.py",
        "backend/src/swing_trade_ml/ml/registry.py",
        "backend/src/swing_trade_ml/services/model_promotion.py",
        "backend/tests/trial_freeze.json",
        "backend/src/swing_trade_ml/brain/modules/m08_decide/engine.py",
    ]:
        assert path in gate.sensitive_files([path], FROZEN), path


def test_sensitive_pr_fails_and_gets_unticked_checkbox():
    paths = ["backend/src/swing_trade_ml/services/limits.py"]
    passed, new_body, msg = gate.decide("opened", paths, "Body", FROZEN)
    assert not passed
    assert new_body.startswith("Body")
    assert "- [ ] **Owner approval**" in new_body and "services/limits.py" in new_body
    assert "limits.py" in msg


def test_box_ticked_when_opened_does_not_count():
    paths = ["backend/alembic/versions/x.py"]
    passed, new_body, _ = gate.decide("opened", paths, _ticked_body(paths), FROZEN)
    assert not passed and "- [ ] **Owner approval**" in new_body


def test_owner_tick_on_edit_passes_and_leaves_body_alone():
    paths = ["backend/alembic/versions/x.py"]
    passed, new_body, _ = gate.decide("edited", paths, _ticked_body(paths), FROZEN)
    assert passed and new_body is None


def test_new_commits_untick_the_box():
    paths = ["backend/alembic/versions/x.py"]
    passed, new_body, msg = gate.decide("synchronize", paths, _ticked_body(paths), FROZEN)
    assert not passed and "- [ ] **Owner approval**" in new_body
    assert "New commits reset" in msg


def test_tick_outside_the_gate_block_does_not_count():
    body = "- [x] **Owner approval** I approve"
    passed, _, _ = gate.decide("edited", [".github/workflows/deploy.yml"], body, FROZEN)
    assert not passed


def test_block_is_rewritten_not_duplicated_when_files_change():
    first = _ticked_body(["backend/alembic/versions/a.py"])
    paths = ["backend/alembic/versions/a.py", "infra/x.sh"]
    _, new_body, _ = gate.decide("synchronize", paths, first, FROZEN)
    assert new_body.count(gate.START) == 1 and "infra/x.sh" in new_body


def test_frozen_files_read_from_trial_freeze(tmp_path):
    f = tmp_path / "trial_freeze.json"
    f.write_text(json.dumps({"files": {"brain/module.py": "abc"}}), encoding="utf-8")
    assert gate.frozen_files(f) == {"backend/src/swing_trade_ml/brain/module.py"}
    assert gate.frozen_files(tmp_path / "missing.json") == set()


def test_real_trial_freeze_file_is_readable():
    assert len(gate.frozen_files(REPO / "backend/tests/trial_freeze.json")) > 10
