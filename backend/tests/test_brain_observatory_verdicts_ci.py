"""R6, C1, C9b: the verdict registry must match the frozen artifacts in git, or CI fails (spec 6.1, E0-E4b).

Hashes are taken from git objects (`git show <rev>:<path>`), so line endings in a checkout cannot change
them. Under CI (CI=true) a missing git, history or tag is a failure, never a skip; the checkout needs
`fetch-depth: 0` (.github/workflows/test.yml).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from swing_trade_ml.services.brain_observatory import verdicts as v

REPO = Path(__file__).resolve().parents[2]
ENTRIES = v.load_registry()["entries"]


def _missing(why: str):
    if os.environ.get("CI"):
        pytest.fail(f"effectiveness integrity check cannot run in CI: {why}")
    pytest.skip(why)


def git(*args: str) -> bytes:
    if shutil.which("git") is None:
        _missing("git is not installed")
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True)
    if r.returncode != 0:
        _missing(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def sha(rev: str, path: str) -> str:
    return hashlib.sha256(git("show", f"{rev}:{path}")).hexdigest()


def test_e0_frozen_minimums_match_the_protocol_text():
    for pid, frozen in v.FROZEN_PROTOCOLS.items():
        entry = next(e for e in ENTRIES if e["protocol_id"] == pid)
        text = git("show", f"{entry['tag_commit']}:{entry['protocol_file']}").decode()
        m = frozen["minimums"]
        assert (
            f"at least {m['eligible_folds']} eligible folds and {m['finished_ideas']} finished model ideas"
            in text
        )
        assert f"at least {round(m['share'] * 100)}% of eligible folds" in text


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e1_protocol_file_is_frozen_at_its_commit(entry):
    assert sha(entry["tag_commit"], entry["protocol_file"]) == entry["protocol_sha256"]
    assert sha("HEAD", entry["protocol_file"]) == entry["protocol_sha256"], (
        "committed protocol differs from its tag"
    )


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e1_tag_points_at_the_recorded_commit(entry):
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{entry['tag']}^{{commit}}"],
        cwd=REPO,
        capture_output=True,
    )
    if r.returncode != 0:
        _missing(f"frozen tag {entry['tag']} not present (not on origin, or checkout without tags)")
    assert r.stdout.decode().strip() == entry["tag_commit"]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e2_report_files_are_unchanged(entry):
    for f in entry["report_files"].values():
        assert sha(entry["evidence_commit"], f["path"]) == f["sha256"]
        assert sha("HEAD", f["path"]) == f["sha256"]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e3_registry_numbers_equal_the_report(entry):
    report = json.loads(git("show", f"HEAD:{entry['report_files']['json']['path']}"))
    pooled = report["pooled"]
    extra = {"predictive": pooled["model_edge_low"], "economic": pooled["model"]["avg_net"]}
    for name, part in entry["parts"].items():
        r = report["verdict"][name]
        assert part["recorded_word"] == r["word"]
        assert part["eligible_folds"] == r["eligible_folds"]
        assert part["folds_won"] == r["folds_won"]
        assert part["share"] == r["share"]
        assert part["finished_ideas"] == pooled["model"]["ideas"]
        assert part["extra_check_value"] == extra[name]
    assert report["protocol"] == entry["protocol_id"]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e4_sample_and_independence_record(entry):
    s = entry["sample"]
    protocol = git("show", f"{entry['tag_commit']}:{entry['protocol_file']}").decode()
    assert f"{s['from']} to {s['to']}" in protocol and "Confirmation" in protocol
    if s["independence"] in ("untouched", "exposure_disclosed"):
        git("ls-files", "--error-unmatch", s["audit_path"])  # the audit must be committed
    else:
        assert s["audit_path"] is None and s["audit_sha256"] is None
        assert s["independence_note"], "an uncommitted or missing audit must be explained"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["protocol_id"])
def test_e4b_audit_is_the_committed_blob(entry):
    s = entry["sample"]
    if not s.get("audit_path"):
        pytest.skip(f"{entry['protocol_id']}: no committed audit yet (independence = {s['independence']})")
    assert sha("HEAD", s["audit_path"]) == s["audit_sha256"], "audit differs from the committed blob"
