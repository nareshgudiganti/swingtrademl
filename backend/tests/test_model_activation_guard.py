"""#328 guard: nothing outside ml/promotion.py (and the registry primitive it wraps) may make a model active.

Scans every module under swing_trade_ml with the AST, so a new activation path fails CI. Reads of the active
model (`MLModel.status == ModelStatus.ACTIVE`, `in (...)`) are fine; writes are not. No DB needed.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import swing_trade_ml

PKG = Path(swing_trade_ml.__file__).resolve().parent
FREEZE = Path(__file__).resolve().parent / "trial_freeze.json"

#: The only module allowed to call registry.activate_model.
CALLERS_OF_ACTIVATE = {"ml/promotion.py"}
#: The only module allowed to write ModelStatus.ACTIVE / ARCHIVED (activate_model itself).
STATUS_WRITERS = {"ml/registry.py"}
#: model_role writers and the only value each may write. "final" marks a shadow-lane model (scored, never
#: served); "prod" would be a serving role and is never written by app code.
ROLE_WRITERS = {"shadow_lanes/lane_freeze.py": {"final"}}

_SQL_WRITE = re.compile(r"\bUPDATE\s+ml_models\b|\bINSERT\s+INTO\s+ml_models\b", re.IGNORECASE)


def _modules(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path.relative_to(root).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _compare_children(tree: ast.AST) -> set[int]:
    """ids of every node that sits inside a comparison (a read, not a write)."""
    inside: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            inside.update(id(n) for n in ast.walk(node))
    return inside


def _is_model_status(node: ast.AST, members: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in members
        and isinstance(node.value, ast.Name)
        and node.value.id == "ModelStatus"
    )


def find_activation_writes(root: Path = PKG) -> list[str]:
    found: list[str] = []
    for rel, tree in _modules(root):
        reads = _compare_children(tree)
        for node in ast.walk(tree):
            line = f"{rel}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if name == "activate_model" and rel not in CALLERS_OF_ACTIVATE:
                    found.append(f"{line} calls activate_model")
            if (
                _is_model_status(node, {"ACTIVE", "ARCHIVED"})
                and id(node) not in reads
                and rel not in STATUS_WRITERS
            ):
                found.append(f"{line} writes ModelStatus.{node.attr}")
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "model_role":
                        value = node.value.value if isinstance(node.value, ast.Constant) else None
                        if value not in ROLE_WRITERS.get(rel, set()):
                            found.append(f"{line} writes model_role={value!r}")
            is_text = isinstance(node, ast.Constant) and isinstance(node.value, str)
            if is_text and _SQL_WRITE.search(node.value):
                found.append(f"{line} raw SQL write to ml_models")
    return found


def test_no_activation_path_outside_promotion():
    assert find_activation_writes() == []


def test_the_guard_catches_a_new_bypass(tmp_path):
    """The scanner itself works: each kind of bypass is reported."""
    bad = tmp_path / "pkg"
    bad.mkdir()
    (bad / "sneaky.py").write_text(
        "from swing_trade_ml.core.enums import ModelStatus\n"
        "def f(db, m):\n"
        "    activate_model(db, 1)\n"
        "    m.status = ModelStatus.ACTIVE\n"
        "    db.query(M).update({'status': ModelStatus.ARCHIVED})\n"
        "    m.model_role = 'prod'\n"
        "    db.execute(\"UPDATE ml_models SET status = 'ACTIVE'\")\n"
        "    return m.status == ModelStatus.ACTIVE\n",
        encoding="utf-8",
    )
    found = find_activation_writes(bad)
    assert len(found) == 5, found
    assert not any(":8 " in f for f in found)  # the comparison on line 8 is a read


def test_only_promotion_calls_activate_model_through_the_api_cli_and_trainer():
    for rel in ("api/v1/endpoints/ml.py", "cli.py", "ml/train.py"):
        src = (PKG / rel).read_text(encoding="utf-8")
        assert re.search(r"promotion\.promote\b|\bpromote\(", src), rel


# ------------------------------------------------------------------ known bypass, frozen (reported blocker)


def test_known_bypass_m06_serves_the_newest_saved_combiner_without_promotion():
    """BLOCKER (#328, reported, not fixed): the brain's M06 combiner is put in use by *saving* it.
    `swingtrade brain meta-train` writes brain_meta_vN.joblib and `artifact.load_latest()` serves the newest
    file; the combiner pins its base models by name+version (any status) via `DatedReader.model_bundle`.
    No ml_models status changes, so promote() never sees it. The files are trial-frozen, so they are left
    untouched; M06 runs in shadow. This test fails if that changes, so the gap is re-checked then."""
    import inspect

    from swing_trade_ml.brain.modules.m06_reason import artifact

    frozen = set(json.loads(FREEZE.read_text(encoding="utf-8"))["files"])
    assert {
        "brain/modules/m06_reason/artifact.py",
        "brain/modules/m06_reason/module.py",
        "brain/reader.py",
    } <= frozen
    assert "versions[-1]" in inspect.getsource(artifact.load_latest)
