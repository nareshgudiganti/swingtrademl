"""Unit tests for the pure parts of scripts/worktree_lifecycle.py (run: python -m pytest scripts/test_worktree_lifecycle.py)."""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("wl", Path(__file__).with_name("worktree_lifecycle.py"))
wl = importlib.util.module_from_spec(_spec)
sys.modules["wl"] = wl  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(wl)


def W(**kw):
    base = {"path": "D:/x/wt", "head": "abc", "branch": "feat/x", "exists": True, "last_activity_days": 30.0}
    base.update(kw)
    return wl.Worktree(**base)


def test_dirty_is_uncommitted_even_if_merged():
    assert wl.classify(W(dirty=3, in_main=True))[0] == "uncommitted"


def test_unpushed_wins_over_active():
    assert wl.classify(W(unpushed=2, live_session=True, last_activity_days=0.1))[0] == "unpushed"


def test_squash_merged_pr_head_counts_as_merged_even_with_unpushed_flag():
    w = W(unpushed=4, merged_pr=101)
    assert wl.classify(w) == ("merged-clean", "tip equals merged PR #101")


def test_merged_clean_in_main():
    assert wl.classify(W(in_main=True))[0] == "merged-clean"


def test_active_by_recency_session_or_open_pr():
    assert wl.classify(W(last_activity_days=1))[0] == "active"
    assert wl.classify(W(live_session=True))[0] == "active"
    assert wl.classify(W(open_pr=7))[0] == "active"


def test_abandoned_requires_long_idle_and_pushed():
    assert wl.classify(W(last_activity_days=40))[0] == "abandoned"
    assert wl.classify(W(last_activity_days=8))[0] == "unknown"


def test_missing_or_prunable_is_unknown():
    assert wl.classify(W(exists=False))[0] == "unknown"
    assert wl.classify(W(prunable=True))[0] == "unknown"


def test_removal_requires_merged_clean_and_no_lock_protect_live_main():
    ok = W(in_main=True)
    ok.cls, _ = wl.classify(ok)
    assert wl.removal_ok(ok)
    for change in ({"locked": "x"}, {"protected": True}, {"live_session": True}, {"is_main": True}):
        w = W(in_main=True, **change)
        w.cls, _ = wl.classify(w)
        assert not wl.removal_ok(w), change


def test_recent_checkout_kept_unless_its_merged_pr_is_named():
    w = W(in_main=True, recent_checkout=True)
    w.cls, _ = wl.classify(w)
    assert w.cls == "merged-clean"
    assert not wl.removal_ok(w)
    assert wl.removal_ok(w, explicit_pr=True)


def test_explicit_pr_never_overrides_dirty_lock_or_live():
    for change in ({"dirty": 1}, {"locked": "x"}, {"live_session": True}, {"protected": True}):
        w = W(in_main=True, recent_checkout=True, **change)
        w.cls, _ = wl.classify(w)
        assert not wl.removal_ok(w, explicit_pr=True), change


def test_uncommitted_or_unpushed_never_removable():
    for w in (W(dirty=1, in_main=True), W(unpushed=1)):
        w.cls, _ = wl.classify(w)
        assert not wl.removal_ok(w)


def test_parse_porcelain_marks_first_as_main_and_reads_lock():
    text = (
        "worktree D:/repo\nHEAD 111\nbranch refs/heads/main\n\n"
        "worktree D:/wt1\nHEAD 222\nbranch refs/heads/feat/a\nlocked keep me\n\n"
        "worktree D:/wt2\nHEAD 333\ndetached\nprunable gitdir file points to non-existent location\n"
    )
    wts = wl.parse_worktrees(text)
    assert [w.is_main for w in wts] == [True, False, False]
    assert wts[1].branch == "feat/a" and wts[1].locked == "keep me"
    assert wts[2].branch is None and wts[2].prunable
