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


# ---------------------------------------------------------------- #328: lab candidates get a model card


def _fake_lab_row(tmp_path, name):
    import joblib
    from sklearn.linear_model import LogisticRegression

    path = tmp_path / f"{name}_v1.joblib"
    joblib.dump({"estimator": LogisticRegression(), "feature_names": ["a"]}, path)
    return SimpleNamespace(
        id=7,
        name=name,
        version="v1",
        algorithm="lightgbm",
        artifact_path=str(path),
        feature_names=["a"],
        training_symbols=["U00"],
        train_start=None,
        train_end=None,
        n_samples=1,
        prediction_horizon_days=15,
        target_return_pct=0.08,
        stop_return_pct=0.04,
        label_kind="excess_top30",
        metrics={},
        status="TRAINED",
    )


def test_a_lab_candidate_trains_unchanged_through_the_card_wrapper_and_gets_its_card(tmp_path, monkeypatch):
    from swing_trade_ml.brain import card_trainers, selection_lab, selection_lab_run

    calls = []
    name = F.model_name("S1", CUT)
    row = _fake_lab_row(tmp_path, name)
    before = Path(row.artifact_path).read_bytes()
    monkeypatch.setattr(selection_lab_run, "collect_db", lambda db: ({"bars": 1}, USED, ["X1"], MID))

    def lab(db, **kwargs):
        calls.append(kwargs)
        return row

    monkeypatch.setattr(selection_lab, "train_lab_model", lab)
    got = F.default_trainer(None, "S1", CUT, {"large": USED, "mid": MID}, name)
    assert got is row
    # exactly the arguments lane freezing always passed to the protected trainer
    assert calls == [{"name": name, "cutoff": CUT, "symbols": USED, "candidates": USED, "bars": {"bars": 1}}]
    card = json.loads(card_trainers.sidecar_path(row.artifact_path).read_text(encoding="utf-8"))
    assert card["training"]["invoked_by"] == "shadow_lanes.lane_freeze"
    assert card["artifact_sha256"] == hashlib.sha256(before).hexdigest()
    assert Path(row.artifact_path).read_bytes() == before


def test_a_barrier_candidate_still_goes_straight_to_the_general_trainer(monkeypatch):
    from swing_trade_ml.brain import card_trainers
    from swing_trade_ml.ml import train

    seen = {}
    monkeypatch.setattr(train, "train_model", lambda db, **kw: seen.update(kw) or "model")
    never = lambda *a, **k: pytest.fail("not a lab model")  # noqa: E731
    monkeypatch.setattr(card_trainers, "train_lab_model_with_card", never)
    assert F.default_trainer(None, "S0", CUT, {"large": USED, "mid": MID}, "n") == "model"
    assert seen["auto_activate"] is False and seen["symbols"] == USED
