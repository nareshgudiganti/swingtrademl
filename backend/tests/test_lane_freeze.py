"""Shadow lanes: freezing a lane model once, only after its history test passed."""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import swing_trade_ml.brain.ten_day  # noqa: F401  (first: replay_scoring has an import cycle that only resolves from here)

from swing_trade_ml.shadow_lanes import lane_freeze as F  # isort: skip  # noqa: N812
from swing_trade_ml.shadow_lanes import lane_universe  # isort: skip

USED = [f"U{i:02d}" for i in range(49)]
REJECT = [f"R{i:03d}" for i in range(129)]
MID = [f"M{i:02d}" for i in range(14)]
CUT = date(2026, 12, 8)

PASS10 = {"verdict": {"predictive": {"word": "pass"}, "economic": {"word": "pass"}}}


def mk_repo(tmp_path):
    split = tmp_path / "docs/brain/evidence/stock_split"
    split.mkdir(parents=True)
    js = split / "stock_split_ev15.json"
    js.write_text(
        json.dumps({"used_49": USED, "extra_training_set": ["X1"], "reject_set": REJECT}), encoding="utf-8"
    )
    sha = hashlib.sha256(js.read_bytes()).hexdigest()
    (split / "stock_split_ev15.md").write_text(f"| SHA-256 of file | `{sha}` |\n", encoding="utf-8")
    p = tmp_path / lane_universe.UNIVERSE_FILE
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(lane_universe.build(USED, REJECT, [*MID, *REJECT[:10]])), encoding="utf-8")
    return tmp_path


def write_report(tmp_path, data, manifest=None, name="report.json"):
    d = tmp_path / "reports"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(data), encoding="utf-8")
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d / name


def trainer_for(name_prefix, horizon, calls):
    def trainer(db, candidate, cutoff, universe, name):
        calls.append((candidate, cutoff, name, sorted(universe)))
        return SimpleNamespace(
            id=42, name=name, version="v1", status="TRAINED", prediction_horizon_days=horizon
        )

    return trainer


def test_a_passed_10_day_model_is_frozen_once_with_a_full_record(tmp_path):
    repo, calls = mk_repo(tmp_path), []
    rep = write_report(tmp_path, PASS10)
    path = F.freeze(
        None,
        "10d-large",
        "TD10",
        rep,
        repo_root=repo,
        cutoff=CUT,
        trainer=trainer_for("td", 10, calls),
        commit="abc",
    )
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["model_name"] == "td_h10_lane_20261208" and rec["status_at_freeze"] == "TRAINED"
    assert rec["trained_as_of"] == "2026-12-08" and rec["code_commit"] == "abc" and rec["universe_sha256"]
    assert "never activated" in rec["note"] and calls[0][0] == "TD10"
    with pytest.raises(F.FreezeRefusedError, match="frozen once"):
        F.freeze(
            None, "10d-large", "TD10", rep, repo_root=repo, cutoff=CUT, trainer=trainer_for("td", 10, calls)
        )
    assert len(calls) == 1  # the second attempt trained nothing


@pytest.mark.parametrize(
    "verdict",
    [
        {"predictive": {"word": "pass"}, "economic": {"word": "fail"}},
        {"predictive": {"word": "insufficient"}, "economic": {"word": "pass"}},
        {},
    ],
)
def test_a_10_day_model_that_did_not_pass_both_parts_is_never_frozen(tmp_path, verdict):
    repo, calls = mk_repo(tmp_path), []
    rep = write_report(tmp_path, {"verdict": verdict})
    with pytest.raises(F.FreezeRefusedError, match="both must be pass"):
        F.freeze(
            None, "10d-large", "TD10", rep, repo_root=repo, cutoff=CUT, trainer=trainer_for("td", 10, calls)
        )
    assert calls == [] and not F.record_path(repo, "10d-large").exists()


def test_a_15_day_candidate_needs_its_own_passing_ranking_verdict(tmp_path):
    repo, calls = mk_repo(tmp_path), []
    ok = write_report(tmp_path, {"ranking_verdict": "pass"}, {"Candidate": "S1"})
    path = F.freeze(
        None, "15d-large", "S1", ok, repo_root=repo, cutoff=CUT, trainer=trainer_for("sl", 15, calls)
    )
    assert json.loads(path.read_text(encoding="utf-8"))["model_name"] == "sl1_S1_lane_20261208"
    wrong = write_report(tmp_path, {"ranking_verdict": "pass"}, {"Candidate": "S2"}, "other.json")
    with pytest.raises(F.FreezeRefusedError, match=r"for candidate"):
        F.freeze(
            None, "15d-midcap", "S1M", wrong, repo_root=repo, cutoff=CUT, trainer=trainer_for("sl", 15, calls)
        )


@pytest.mark.parametrize("verdict", ["fail", "insufficient"])
def test_a_15_day_candidate_that_did_not_pass_is_never_frozen(tmp_path, verdict):
    repo, calls = mk_repo(tmp_path), []
    rep = write_report(tmp_path, {"ranking_verdict": verdict}, {"Candidate": "S0"})
    with pytest.raises(F.FreezeRefusedError, match="not 'pass'"):
        F.freeze(
            None, "15d-large", "S0", rep, repo_root=repo, cutoff=CUT, trainer=trainer_for("sl", 15, calls)
        )
    assert calls == []


@pytest.mark.parametrize(
    ("slot", "cand"),
    [
        ("10d-large", "S0"),
        ("15d-large", "TD10"),
        ("15d-large", "S1M"),
        ("15d-midcap", "S2"),
        ("5d-large", "S0"),
    ],
)
def test_a_candidate_may_only_feed_its_own_slot(tmp_path, slot, cand):
    repo, calls = mk_repo(tmp_path), []
    rep = write_report(tmp_path, {**PASS10, "ranking_verdict": "pass"}, {"Candidate": cand})
    with pytest.raises(F.FreezeRefusedError, match=r"does not belong|unknown slot"):
        F.freeze(None, slot, cand, rep, repo_root=repo, cutoff=CUT, trainer=trainer_for("x", 15, calls))
    assert calls == []


def test_no_model_is_trained_when_the_frozen_stock_lists_are_missing_or_changed(tmp_path):
    repo = mk_repo(tmp_path)
    (repo / lane_universe.UNIVERSE_FILE).unlink()
    rep, calls = write_report(tmp_path, PASS10), []
    with pytest.raises(F.FreezeRefusedError, match="stock lists cannot be loaded"):
        F.freeze(
            None, "10d-large", "TD10", rep, repo_root=repo, cutoff=CUT, trainer=trainer_for("td", 10, calls)
        )
    assert calls == []


def test_a_model_the_registry_maps_to_a_different_slot_is_refused_after_training(tmp_path):
    repo = mk_repo(tmp_path)
    rep = write_report(tmp_path, PASS10)

    def wrong(db, candidate, cutoff, universe, name):
        return SimpleNamespace(
            id=1, name="swing_classifier", version="v9", status="ACTIVE", prediction_horizon_days=5
        )

    with pytest.raises(F.FreezeRefusedError, match="not registered for slot"):
        F.freeze(None, "10d-large", "TD10", rep, repo_root=repo, cutoff=CUT, trainer=wrong)
    assert not F.record_path(repo, "10d-large").exists()


def test_model_names_map_to_the_right_slots():
    from swing_trade_ml.services.model_registry import slot_for

    assert slot_for(F.model_name("TD10", CUT), 10) == "10d-large"
    assert slot_for(F.model_name("S1", CUT), 15) == "15d-large"
    assert slot_for(F.model_name("S2M", CUT), 15) == "15d-midcap"


def test_the_tool_never_activates_or_schedules_anything_or_names_the_held_back_set():
    src = Path(F.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not [
        m
        for m in mods
        if any(
            b in m
            for b in (
                "brain.modules",
                "services.risk",
                "execution",
                "brokers",
                "strategies",
                "h05",
                "workers",
            )
        )
    ]
    assert "auto_activate=False" in src and "ACTIVE" not in src.replace("never activated", "")
    assert "reject_set" not in src and "scheduler" not in src.lower()
