"""Shadow lanes: the frozen stock lists, and the owner-chosen (never auto-picked) model per slot."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

import swing_trade_ml.brain.ten_day  # noqa: F401  (first: replay_scoring has an import cycle that only resolves from here)

from swing_trade_ml.core.config import REPO_ROOT, settings  # isort: skip
from swing_trade_ml.shadow_lanes import lane_job  # isort: skip
from swing_trade_ml.shadow_lanes import lane_universe as universe  # isort: skip

USED = [f"U{i:02d}" for i in range(49)]
REJECT = [f"R{i:03d}" for i in range(129)]
MID = [f"M{i:02d}" for i in range(14)]


def mk_repo(tmp_path, data=None, split_note_ok=True):
    split = tmp_path / "docs/brain/evidence/stock_split"
    split.mkdir(parents=True)
    js = split / "stock_split_ev15.json"
    js.write_text(
        json.dumps({"used_49": USED, "extra_training_set": ["X1"], "reject_set": REJECT}), encoding="utf-8"
    )
    sha = hashlib.sha256(js.read_bytes()).hexdigest() if split_note_ok else "0" * 64
    (split / "stock_split_ev15.md").write_text(f"| SHA-256 of file | `{sha}` |\n", encoding="utf-8")
    if data is not None:
        p = tmp_path / universe.UNIVERSE_FILE
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def good():
    return universe.build(USED, REJECT, [*MID, *REJECT[:10]])


def test_the_hash_ignores_order_and_changes_with_any_stock():
    assert universe.universe_sha(["B", "A"], ["D", "C"]) == universe.universe_sha(["A", "B"], ["C", "D"])
    assert universe.universe_sha(["A", "B"], ["C", "D"]) != universe.universe_sha(["A", "B"], ["C", "E"])


def test_build_removes_the_held_back_stocks_from_the_mid_list():
    data = good()
    assert data["large"] == sorted(USED) and data["mid"] == sorted(MID)
    assert not set(data["mid"]) & set(REJECT) and data["mid_model_training_symbols_n"] == 24


@pytest.mark.parametrize(
    ("large", "mid", "needle"),
    [
        (USED[:-1], MID, "not exactly the locked 49"),
        (USED, [*MID, REJECT[0]], "held-back"),
        (USED, [*MID, USED[0]], "shares 1 stock"),
        (USED, MID[:9], "fewer than 10"),
        (USED, [*MID, MID[0]], "duplicates"),
    ],
)
def test_the_rules_name_each_way_a_universe_can_be_wrong(large, mid, needle):
    assert any(needle in p for p in universe.problems(large, mid, USED, REJECT))


def test_build_refuses_a_mid_list_that_is_too_small_after_removing_the_held_back():
    with pytest.raises(universe.UniverseError, match="fewer than 10"):
        universe.build(USED, REJECT, [*MID[:5], *REJECT[:10]])


def test_a_good_frozen_file_loads(tmp_path):
    data = good()
    repo = mk_repo(tmp_path, data)
    got = universe.load_universe(repo)
    assert got["sha256"] == data["sha256"] and universe.group_symbols(got, "mid") == sorted(MID)
    assert universe.group_symbols(got, "large") == sorted(USED)
    with pytest.raises(universe.UniverseError, match="unknown cap group"):
        universe.group_symbols(got, "small")


def test_a_missing_file_means_a_lane_run_records_nothing(tmp_path):
    with pytest.raises(universe.UniverseError, match="has not been frozen"):
        universe.load_universe(mk_repo(tmp_path))


def test_a_changed_list_with_the_old_hash_is_refused(tmp_path):
    data = good()
    data["mid"] = [*data["mid"][:-1], "SNEAKY"]
    with pytest.raises(universe.UniverseError, match="recorded hash"):
        universe.load_universe(mk_repo(tmp_path, data))


def test_a_held_back_stock_added_with_a_matching_hash_is_still_refused(tmp_path):
    data = good()
    data["mid"] = [*data["mid"], REJECT[3]]
    data["sha256"] = universe.universe_sha(data["large"], data["mid"])
    with pytest.raises(universe.UniverseError, match="held-back"):
        universe.load_universe(mk_repo(tmp_path, data))


def test_a_locked_split_that_no_longer_matches_its_note_is_refused(tmp_path):
    with pytest.raises(universe.UniverseError, match="locked stock split"):
        universe.load_universe(mk_repo(tmp_path, good(), split_note_ok=False))


def test_the_committed_universe_file_is_valid_against_the_real_locked_split():
    data = universe.load_universe(REPO_ROOT)
    assert len(data["large"]) == 49 and len(data["mid"]) == 14
    reject = set(
        json.loads((REPO_ROOT / "docs/brain/evidence/stock_split/stock_split_ev15.json").read_text("utf-8"))[
            "reject_set"
        ]
    )
    assert not (set(data["large"]) | set(data["mid"])) & reject and not set(data["mid"]) & set(data["large"])


def test_the_write_command_never_overwrites_an_existing_file(capsys):
    assert (REPO_ROOT / universe.UNIVERSE_FILE).exists()
    assert universe.main(["write"]) == 2
    assert "never overwritten" in capsys.readouterr().out


# ---------------------------------------------------------------- the owner chooses each slot's model


def test_the_configured_models_come_only_from_the_owners_setting(monkeypatch):
    monkeypatch.setattr(settings, "LANE_SHADOW_MODELS", "")
    assert lane_job.configured_model_ids() == {}
    monkeypatch.setattr(settings, "LANE_SHADOW_MODELS", "not json")
    assert lane_job.configured_model_ids() == {}
    monkeypatch.setattr(settings, "LANE_SHADOW_MODELS", json.dumps({"10d-large": 7, "15d-midcap": "9"}))
    assert lane_job.configured_model_ids() == {"10d-large": 7, "15d-midcap": 9}
    assert settings.__class__.model_fields["LANE_SHADOW_MODELS"].default == ""


def test_a_run_with_no_universe_records_nothing_and_says_why(monkeypatch):
    calls = []
    monkeypatch.setattr(lane_job.S, "record_day", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(lane_job.S, "evaluate_matured", lambda *a, **k: {})

    def boom():
        raise universe.UniverseError("not frozen")

    monkeypatch.setattr(lane_job.lane_universe, "load_universe", boom)
    out = lane_job.run_daily(None, now=datetime(2026, 12, 8, 14, 0, tzinfo=UTC))
    assert calls == [] and all(v.startswith("no_universe") for v in out["slots"].values())
