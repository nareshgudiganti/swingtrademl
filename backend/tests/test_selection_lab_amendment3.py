# ruff: noqa: E501 (long test sentences)
"""Amendment 3 (`sl-protocol-v1.1`): the protocol name, the stricter signed-marker check, the frozen-file regression
(a design document added after the tag), and the start wrapper's check-only against a fixture git repo.
All pure: a throw-away git repo in tmp_path, a fake clock, no database, no candidate is run."""

from __future__ import annotations

import importlib.util
import inspect
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.brain import selection_lab as sl
from swing_trade_ml.brain import selection_lab_run as run

IST = ZoneInfo("Asia/Kolkata")
WRAPPER = Path("D:/machine learning/lab-start-wt/backend/src/swing_trade_ml/brain/selection_lab_start.py")
GOOD_MARKER = (
    "# Evidence plan, Amendment 3: SIGNED\n\n"
    'SIGNED by the owner on 2026-12-05 (instruction "test").\n'
    "See docs/superpowers/specs/2026-11-04-evidence-plan-amendment-3.md. Protocol sl-protocol-v1.1.\n"
)


# ---------------------------------------------------------------- names


def test_the_protocol_name_tag_and_markers():
    assert run.PROTOCOL == "sl-protocol-v1.1" and run.TAG == run.PROTOCOL
    assert run.LEDGER_MARKER.startswith(run.PROTOCOL + " ") and run.RERUN_MARKER.startswith(
        run.PROTOCOL + " "
    )
    old = "sl-protocol-v1 {cand}, {first} to {last}"
    assert old.format(cand="S0", first="a", last="b") not in run.LEDGER_MARKER.format(
        cand="S0", first="a", last="b"
    )
    assert run.LEDGER_MARKER.format(cand="S0", first="a", last="b") == "sl-protocol-v1.1 S0, a to b"
    assert run.AMENDMENT.endswith("sl_v1/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md")
    assert run.AMENDMENT_2.endswith("sl_v1/EVIDENCE_PLAN_AMENDMENT_SIGNED.md")


def test_the_tag_name_is_a_valid_git_ref(tmp_path):
    r = subprocess.run(
        ["git", "check-ref-format", f"refs/tags/{run.TAG}"], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0


def test_the_amendment_text_is_frozen_and_every_frozen_file_exists():
    repo = Path(run.__file__).resolve().parents[4]
    assert run.AMENDMENT_TEXT in run.FROZEN_FILES and run.SPEC in run.FROZEN_FILES
    for rel in run.FROZEN_FILES:
        assert (repo / rel).is_file(), rel


def test_the_lab_writes_the_same_protocol_name_into_every_result():
    assert f'"protocol": "{run.PROTOCOL} (ranking only)"' in inspect.getsource(sl)


def test_the_mismatch_messages_do_not_name_the_wrong_next_version():
    reasons = run.refusal_reasons(
        candidate="S0", tag_on_head=True, changed_since_tag=["x.py"], dirty=False, amendment=True,
        unclassified=[], already_ran=[], comparison_missing=None,
    )  # fmt: skip
    assert reasons == [
        f"x.py differs from the tagged version: a changed rule is a new protocol version, not {run.PROTOCOL}."
    ]
    assert "sl-protocol-v2" not in inspect.getsource(run.plan_attempt)


def test_refusal_reasons_are_otherwise_unchanged():
    r = run.refusal_reasons(
        candidate="S2", tag_on_head=False, changed_since_tag=[], dirty=True, amendment=False,
        unclassified=[("A", date(2024, 1, 2))], already_ran=["p"], comparison_missing="S1",
    )  # fmt: skip
    assert len(r) == 6
    assert (
        r[0]
        == f"The git tag {run.TAG} is not in this commit's history: the protocol is not signed and frozen."
    )
    assert "uncommitted changes" in r[1] and "amendment is not signed" in r[2]
    assert "no written classification" in r[3] and "already exists" in r[4] and "S1" in r[5]


# ---------------------------------------------------------------- amendment_signed


@pytest.fixture()
def markers(tmp_path):
    (tmp_path / run.OUT_DIR).mkdir(parents=True)
    return tmp_path


def put(root, rel, text):
    (root / rel).write_text(text, encoding="utf-8")


def test_signed_false_with_no_files(markers):
    assert run.amendment_signed(markers) is False


def test_signed_false_with_only_the_amendment_2_marker(markers):
    put(markers, run.AMENDMENT_2, "Evidence-plan amendment: SIGNED 2026-11-02\n")
    assert run.amendment_signed(markers) is False


def test_signed_false_when_only_amendment_3_marker_exists(markers):
    put(markers, run.AMENDMENT, GOOD_MARKER)
    assert run.amendment_signed(markers) is False


@pytest.mark.parametrize(
    "text",
    [
        "# Amendment 3: UNSIGNED\n\nAmendment 3 sl-protocol-v1.1 UNSIGNED\n",
        "SIGNED by the owner on <YYYY-MM-DD> Amendment 3 sl-protocol-v1.1\n",  # blank date
        "SIGNED Amendment 3 sl-protocol-v1.1\n",  # SIGNED without the date
        "SIGNED by the owner on 2026-12-05. Protocol sl-protocol-v1.1.\n",  # no 'Amendment 3'
        "SIGNED by the owner on 2026-12-05. Amendment 3.\n",  # no protocol name
        "Amendment 3 sl-protocol-v1.1 (not SIGNED by the owner on 2026-12-05)\n",  # not at the start of a line
        "SIGNED by the owner on 2026-12-05 Amendment 3 sl-protocol-v1\n",  # old protocol name only
    ],
)
def test_signed_false_for_a_marker_that_is_not_exactly_a_signature(markers, text):
    put(markers, run.AMENDMENT_2, "SIGNED 2026-11-02\n")
    put(markers, run.AMENDMENT, text)
    assert run.amendment_signed(markers) is False


def test_signed_true_for_the_proper_marker(markers):
    put(markers, run.AMENDMENT_2, "SIGNED 2026-11-02\n")
    put(markers, run.AMENDMENT, GOOD_MARKER)
    assert run.amendment_signed(markers) is True


# ---------------------------------------------------------------- git fixture: the frozen-file regression


def git(repo, *a):
    p = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "-c", "tag.gpgsign=false", *a],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert p.returncode == 0, p.stderr
    return p.stdout


def write_files(repo, files):
    for rel in files:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"content of {rel}\n", encoding="utf-8", newline="\n")


def build_repo(root, *, at_tag, tag=run.TAG):
    """A repo whose `tag` commit holds `at_tag`; then a later commit adds the rest of the frozen files and the markers."""
    git_dir = root / "fx"
    git_dir.mkdir()
    git(git_dir, "init", "-q")
    write_files(git_dir, at_tag)
    git(git_dir, "add", "-A")
    git(git_dir, "commit", "-q", "-m", "tag commit", "--allow-empty")
    git(git_dir, "tag", "-a", tag, "-m", "fixture")
    write_files(git_dir, [f for f in run.FROZEN_FILES if f not in at_tag])
    (git_dir / run.OUT_DIR).mkdir(parents=True, exist_ok=True)
    put(git_dir, run.AMENDMENT_2, "SIGNED 2026-11-02\n")
    put(git_dir, run.AMENDMENT, GOOD_MARKER)
    git(git_dir, "add", "-A")
    git(git_dir, "commit", "-q", "-m", "after tag")
    return git_dir


def reasons_for(repo):
    tag_on_head, changed, dirty = run.git_state(repo)
    return run.refusal_reasons(
        candidate="S0", tag_on_head=tag_on_head, changed_since_tag=changed, dirty=dirty,
        amendment=run.amendment_signed(repo), unclassified=[], already_ran=[], comparison_missing=None,
    )  # fmt: skip


def test_regression_a_frozen_file_missing_at_the_tag_gives_the_differs_reason(tmp_path):
    """Today's bug: the design document was added after the tag, so the runner could never start."""
    repo = build_repo(tmp_path, at_tag=[f for f in run.FROZEN_FILES if f != run.SPEC])
    reasons = reasons_for(repo)
    assert any(run.SPEC in r and "differs from the tagged version" in r for r in reasons)


def test_a_tag_that_holds_every_frozen_file_gives_no_reason(tmp_path):
    repo = build_repo(tmp_path, at_tag=list(run.FROZEN_FILES))
    assert reasons_for(repo) == []


def test_an_edit_to_a_frozen_file_after_the_tag_is_still_refused(tmp_path):
    repo = build_repo(tmp_path, at_tag=list(run.FROZEN_FILES))
    put(repo, run.SPEC, "edited\n")
    git(repo, "commit", "-q", "-am", "edit")
    assert any(run.SPEC in r and "differs from the tagged version" in r for r in reasons_for(repo))


def test_the_old_tag_alone_does_not_satisfy_the_new_protocol(tmp_path):
    repo = build_repo(tmp_path, at_tag=list(run.FROZEN_FILES), tag="sl-protocol-v1")
    tag_on_head, _, _ = run.git_state(repo)
    assert tag_on_head is False and any("is not in this commit's history" in r for r in reasons_for(repo))


# ---------------------------------------------------------------- the start wrapper, check-only (from its branch, by path)


@pytest.fixture(scope="module")
def wrapper():
    if not WRAPPER.is_file():
        pytest.skip("the start wrapper is not merged yet (branch change/lab-start-wrapper)")
    spec = importlib.util.spec_from_file_location("selection_lab_start_under_test", WRAPPER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def checks(wrapper, repo, now):
    res = wrapper.evaluate(run, wrapper.make_git(repo), repo, lambda: now, "S0")
    return {c["check"]: c for c in res}


def test_wrapper_check_only_before_the_start_date_and_without_a_phase_b_record(wrapper, tmp_path):
    repo = build_repo(tmp_path, at_tag=list(run.FROZEN_FILES))
    c = checks(wrapper, repo, datetime(2026, 12, 4, 23, 59, tzinfo=IST))
    assert not c["date"]["ok"] and not c["phase_b_lock"]["ok"]
    for name in ("protocol_tag", "clean_tree", "frozen_files", "runner_guard"):
        assert c[name]["ok"], (name, c[name])
    assert c["frozen_files"]["warnings"] == []


def test_wrapper_date_passes_on_the_start_day_but_phase_b_still_refuses(wrapper, tmp_path):
    repo = build_repo(tmp_path, at_tag=list(run.FROZEN_FILES))
    c = checks(wrapper, repo, datetime(2026, 12, 5, 10, 0, tzinfo=IST))
    assert c["date"]["ok"] and not c["phase_b_lock"]["ok"]


def test_wrapper_refuses_when_the_design_document_is_absent_at_the_tag(wrapper, tmp_path):
    repo = build_repo(tmp_path, at_tag=[f for f in run.FROZEN_FILES if f != run.SPEC])
    c = checks(wrapper, repo, datetime(2026, 12, 5, 10, 0, tzinfo=IST))
    assert not c["frozen_files"]["ok"] and not c["runner_guard"]["ok"]


def test_wrapper_refuses_with_only_the_amendment_2_marker(wrapper, tmp_path):
    repo = build_repo(tmp_path, at_tag=list(run.FROZEN_FILES))
    (repo / run.AMENDMENT).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "drop marker")
    c = checks(wrapper, repo, datetime(2026, 12, 5, 10, 0, tzinfo=IST))
    assert not c["runner_guard"]["ok"]
