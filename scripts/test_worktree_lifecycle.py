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


# --- Codex round-1 findings -------------------------------------------------------------------------------
def test_ignored_caches_are_regenerable_but_other_ignored_files_are_not():
    for p in ("frontend/node_modules/", "backend/.venv/", "x/__pycache__/a.pyc", "frontend/dist/", ".ruff_cache/",
              "backend/swing_trade_ml.egg-info/", "frontend/test-results/", "frontend/dist-e2e/", "frontend/tsconfig.tsbuildinfo"):
        assert wl.regenerable(p), p
    for p in ("models/swing_v9.joblib", ".env", "backend/.env", "data/export.csv", "notes.md", "distance.txt"):
        assert not wl.regenerable(p), p


def test_ignored_local_file_makes_worktree_uncommitted():
    w = W(in_main=True, dirty=1, ignored_local=1)
    cls, reason = wl.classify(w)
    assert cls == "uncommitted" and "ignored non-cache" in reason


def test_missing_protection_list_loads_as_none(tmp_path):
    wl.PROTECT_FILE = tmp_path / "nope.txt"
    try:
        assert wl.load_protected(tmp_path) is None
    finally:
        wl.PROTECT_FILE = None


def test_apply_refuses_without_protection_list(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "context", lambda root: wl.Context({}, {}, set(), protect_loaded=False))
    monkeypatch.setattr(wl, "collect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not collect")))
    assert wl.cleanup(tmp_path, apply=True, pr=None, log_path=tmp_path / "log.txt") == 1


def test_pr_mode_refuses_unmerged_pr(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "context", lambda root: wl.Context({}, {}, set(), protect_loaded=True))
    monkeypatch.setattr(wl, "collect", lambda *a, **k: [])
    monkeypatch.setattr(wl, "merged_pr_branch", lambda root, pr: None)
    assert wl.cleanup(tmp_path, apply=True, pr=5, log_path=tmp_path / "log.txt") == 1


def test_dry_run_never_calls_git_worktree_commands(tmp_path, monkeypatch):
    target = W(in_main=True)
    target.cls, _ = wl.classify(target)
    target.removable = True
    monkeypatch.setattr(wl, "context", lambda root: wl.Context({}, {}, set(), protect_loaded=True))
    monkeypatch.setattr(wl, "collect", lambda *a, **k: [target])
    calls = []
    monkeypatch.setattr(wl, "git", lambda cwd, *args: calls.append(args) or (0, ""))
    assert wl.cleanup(tmp_path, apply=False, pr=None, log_path=tmp_path / "log.txt") == 0
    assert not [c for c in calls if c[:1] in (("worktree",), ("branch",))]


def test_recheck_rejects_changed_commit(tmp_path, monkeypatch):
    orig = W(path="D:/x/wt", head="aaa", branch="feat/x", in_main=True)
    porcelain = "worktree D:/main\nHEAD 1\nbranch refs/heads/main\n\nworktree D:/x/wt\nHEAD bbb\nbranch refs/heads/feat/x\n"
    monkeypatch.setattr(wl, "git", lambda cwd, *args: (0, porcelain))
    ok, why = wl.recheck(tmp_path, orig, wl.Context({}, {}, set(), True), explicit=False)
    assert not ok and "changed" in why


def test_failed_removal_returns_nonzero(tmp_path, monkeypatch):
    target = W(in_main=True)
    target.cls, _ = wl.classify(target)
    target.removable = True
    monkeypatch.setattr(wl, "context", lambda root: wl.Context({}, {}, set(), protect_loaded=True))
    monkeypatch.setattr(wl, "collect", lambda *a, **k: [target])
    monkeypatch.setattr(wl, "recheck", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(wl, "unlink_links", lambda *a, **k: None)
    monkeypatch.setattr(wl, "git", lambda cwd, *args: (1, "fatal: contains modified files"))
    assert wl.cleanup(tmp_path, apply=True, pr=None, log_path=tmp_path / "log.txt") == 1
