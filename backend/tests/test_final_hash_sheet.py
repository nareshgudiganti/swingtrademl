"""Tests for backend/scripts/final_hash_sheet.py (synthetic inputs; no database, no model)."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from swing_trade_ml.ml import sector_walkforward as wf
from swing_trade_ml.ml.sector_reconcile import keys_sha256

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "final_hash_sheet.py"
REPO = Path(__file__).resolve().parents[2]
EVID = REPO / "docs" / "brain" / "evidence" / "sector_prep"

_spec = importlib.util.spec_from_file_location("final_hash_sheet", SCRIPT)
fhs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fhs)


def _git(repo: Path, *a: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture()
def tmp_repo(tmp_path: Path):
    r = tmp_path / "repo"
    ev = r / fhs.EVID_REL
    ev.mkdir(parents=True)
    (r / "backend").mkdir()
    (r / "backend" / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.9.9"\n', "utf-8")
    rows = ["AAA|2020-01-02", "BBB|2020-01-02", "AAA|2020-01-03"]
    with gzip.open(ev / "sx5_47_rows_v3.txt.gz", "wt", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(rows) + "\n")
    with gzip.open(ev / "sx10_47_rows_v3.txt.gz", "wt", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(rows[:2]) + "\n")
    for h in (5, 10):
        (ev / f"excluded_rows_h{h}_v2.csv").write_text("symbol,decision_date\nAAA,2020-01-01\n", "utf-8")
    (ev / "events_input_v2.csv").write_bytes(b"a,b\n1,2\n")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


def test_manifests_two_hashes_and_known_values():
    m = fhs.manifests()
    assert {a: v["n_columns"] for a, v in m.items()} == {"A_53": 53, "R_37": 37, "C_56": 56}
    assert m["A_53"]["feature_list_sha256"].startswith("3bd35e85")
    assert m["R_37"]["feature_list_sha256"].startswith("b00fc707")
    assert m["C_56"]["feature_list_sha256"].startswith("123aa67a")
    assert m["A_53"]["manifest_sha256"].startswith("f5a8d398")
    assert m["R_37"]["manifest_sha256"].startswith("0615e2fb")
    assert m["C_56"]["manifest_sha256"].startswith("1a691d7d")
    for v in m.values():
        assert v["feature_list_sha256"] != v["manifest_sha256"]
        assert v["feature_list_sha256"] == wf.feature_list_sha256(v["columns"])


def test_independent_recomputation_matches_the_harness():
    cols = ["a", "b", "c"]
    expect = hashlib.sha256(b'["a","b","c"]').hexdigest()
    assert fhs.canonical_feature_list_sha256(cols) == wf.feature_list_sha256(cols) == expect
    assert fhs.plain_manifest_sha256(cols) == hashlib.sha256(b'["a", "b", "c"]').hexdigest()
    assert fhs.canonical_feature_list_sha256(cols[::-1]) != expect  # order matters


def test_manifest_file_equals_what_the_code_produces():
    p = EVID / "feature_manifests_v3.json"
    if not p.is_file():
        pytest.skip("feature_manifests_v3.json not present")
    assert json.loads(p.read_text("utf-8"))["arms"] == fhs.manifests()


def test_commit_must_be_full_40_hex_and_equal_head(tmp_repo):
    head = _git(tmp_repo, "rev-parse", "HEAD")
    assert fhs.check_commit_and_clean(tmp_repo, head) == head
    with pytest.raises(fhs.SheetRefused, match="40"):
        fhs.check_commit_and_clean(tmp_repo, head[:12])
    with pytest.raises(fhs.SheetRefused, match="40"):
        fhs.check_commit_and_clean(tmp_repo, head.upper())
    with pytest.raises(fhs.SheetRefused, match="not the repository HEAD"):
        fhs.check_commit_and_clean(tmp_repo, "0" * 40)


def test_dirty_tree_is_refused_modified_and_untracked(tmp_repo):
    head = _git(tmp_repo, "rev-parse", "HEAD")
    (tmp_repo / "new.txt").write_text("x", "utf-8")
    with pytest.raises(fhs.SheetRefused, match="not clean"):
        fhs.check_commit_and_clean(tmp_repo, head)
    (tmp_repo / "new.txt").unlink()
    (tmp_repo / "backend" / "pyproject.toml").write_text("changed", "utf-8")
    with pytest.raises(fhs.SheetRefused, match="not clean"):
        fhs.check_commit_and_clean(tmp_repo, head)


def test_cli_refuses_and_returns_2(tmp_repo, capsys):
    assert fhs.main(["abc", "--repo", str(tmp_repo)]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_sheet_on_synthetic_inputs_is_deterministic_and_correct(tmp_repo):
    head = _git(tmp_repo, "rev-parse", "HEAD")
    proto = tmp_repo / "proto.md"
    proto.write_bytes(b"protocol text")
    kw = dict(symbols=["AAA", "BBB"], protocols={"SX5_protocol": proto})
    s1 = fhs.build_sheet(tmp_repo, head, **kw)
    s2 = fhs.build_sheet(tmp_repo, head, **kw)
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)
    assert s1["commit"] == head and s1["schema"] == fhs.SCHEMA
    c5 = s1["candidates"]["SX5"]
    key = "dataset_rowlist_sha256 (keys_sha256: sorted SYMBOL|YYYY-MM-DD, newline separated)"
    assert c5[key] == keys_sha256(["AAA|2020-01-02", "BBB|2020-01-02", "AAA|2020-01-03"])
    assert c5["rows"] == 3 and s1["candidates"]["SX10"]["rows"] == 2
    assert c5["exclusion_rows"] == 1
    assert c5["exclusion_keys_sha256"] == keys_sha256(["AAA|2020-01-01"])
    assert c5["events_input_sha256"] == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
    assert c5["datasetspec_config_sha256"] != s1["candidates"]["SX10"]["datasetspec_config_sha256"]
    assert c5["dataset_matrix_sha256"] is None  # needs the DB build
    assert s1["protocol_file_sha256"]["SX5_protocol"] == hashlib.sha256(b"protocol text").hexdigest()
    assert s1["protocol_file_sha256"]["SX10_protocol"] == fhs.PLACEHOLDER
    assert s1["environment"]["project_version"] == "9.9.9"
    assert set(s1["environment"]["tracked_library_versions"]) == {
        "lightgbm",
        "scikit-learn",
        "numpy",
        "pandas",
        "scipy",
    }
    assert s1["recipe"]["library_versions"] == s1["environment"]["tracked_library_versions"]


def test_a_changed_input_file_changes_the_sheet(tmp_repo):
    head = "0" * 40
    a = fhs.build_sheet(tmp_repo, head, symbols=["AAA"])
    (tmp_repo / fhs.EVID_REL / "events_input_v2.csv").write_bytes(b"a,b\n1,3\n")
    b = fhs.build_sheet(tmp_repo, head, symbols=["AAA"])
    assert a["candidates"]["SX5"]["events_input_sha256"] != b["candidates"]["SX5"]["events_input_sha256"]


def test_prior_sheet_matrix_hash_is_carried_and_labelled(tmp_repo):
    key = "dataset_matrix_sha256 (sr.matrix_sha256: x)"
    prior = {"candidates": {"SX5": {key: "ab" * 32}}}
    s = fhs.build_sheet(tmp_repo, "0" * 40, symbols=["AAA"], prior=prior)
    assert s["candidates"]["SX5"]["dataset_matrix_sha256"] == "ab" * 32
    assert "CARRIED" in s["candidates"]["SX5"]["dataset_matrix_sha256_status"]


def test_real_repo_files_reproduce_the_verified_v3_hashes():
    prior_p = EVID / "final_hashes_v3.json"
    if not (prior_p.is_file() and (EVID / "sx5_47_rows_v3.txt.gz").is_file()):
        pytest.skip("evidence files not present")
    prior = json.loads(prior_p.read_text("utf-8"))
    s = fhs.build_sheet(REPO, "0" * 40, prior=prior)
    assert s["recipe"]["sx_recipe_sha256"] == prior["recipe"]["sx_recipe_sha256"]
    for cand in ("SX5", "SX10"):
        got, want = s["candidates"][cand], prior["candidates"][cand]
        assert got["datasetspec_config_sha256"] == want["datasetspec_config_sha256"]
        assert got["harness_config_sha256"] == want["harness_config_sha256"]
        assert got["events_input_sha256"] == want["events_input_sha256"]
        assert got["exclusion_file_sha256"] == want["exclusion_file_sha256"]
        k = "fold_definition_sha256_dev_and_holdout (the one bound for a holdout run)"
        assert got[k] == want[k]
        assert (
            got["dataset_rowlist_sha256 (keys_sha256: sorted SYMBOL|YYYY-MM-DD, newline separated)"]
            == want["dataset_rowlist_sha256"]
        )


def test_text_file_hash_is_line_ending_independent(tmp_path):
    lf, crlf = tmp_path / "lf.csv", tmp_path / "crlf.csv"
    lf.write_bytes(b"a,b\n1,2\n")
    crlf.write_bytes(b"a,b\r\n1,2\r\n")  # what a Windows checkout with core.autocrlf=true produces
    assert fhs.sha256_file(lf) == fhs.sha256_file(crlf) == hashlib.sha256(b"a,b\n1,2\n").hexdigest()


def test_gitattributes_pins_hashed_evidence_text_files_to_lf():
    attrs = (REPO / ".gitattributes").read_text("utf-8")
    for rule in ("sector_prep/*.csv text eol=lf", "sector_prep/*.json text eol=lf", "HOLDOUT-REGISTRY.jsonl -text"):
        assert rule in attrs
