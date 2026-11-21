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
    for p in ("frontend/node_modules/", "backend/.venv/", "x/__pycache__/a.pyc", ".ruff_cache/",
              "backend/swing_trade_ml.egg-info/", "frontend/tsconfig.tsbuildinfo"):
        assert wl.regenerable(p), p
    for p in ("models/swing_v9.joblib", ".env", "backend/.env", "data/export.csv", "notes.md", "distance.txt",
              "frontend/dist/research-export.csv", "frontend/coverage/", "frontend/test-results/x.txt"):
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




# --- Codex round-2 findings -------------------------------------------------------------------------------
def test_git_helper_never_inherits_untracked_files_setting(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd

        class R:
            returncode, stdout = 0, ""
        return R()

    monkeypatch.setattr(wl.subprocess, "run", fake_run)
    wl.git(".", "status", "--porcelain")
    assert seen["cmd"][:3] == ["git", "-c", "status.showUntrackedFiles=all"]


def test_context_does_not_fetch_by_default(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(wl, "git", lambda cwd, *args: calls.append(args) or (0, ""))
    monkeypatch.setattr(wl, "pr_index", lambda root: ({}, {}))
    wl.context(tmp_path)
    assert ("fetch", "-q", "origin") not in calls




def test_recheck_reloads_protection_list(tmp_path, monkeypatch):
    orig = W(path="D:/x/wt", head="aaa", branch="feat/x", in_main=True)
    porcelain = "worktree D:/main\nHEAD 1\nbranch refs/heads/main\n\nworktree D:/x/wt\nHEAD aaa\nbranch refs/heads/feat/x\n"
    monkeypatch.setattr(wl, "git", lambda cwd, *args: (0, porcelain))
    monkeypatch.setattr(wl, "load_protected", lambda root: {"feat/x"})  # owner protected it after the audit
    monkeypatch.setattr(wl, "inspect", lambda w, ctx, live, now: setattr(w, "protected", "feat/x" in ctx.protected)
                        or setattr(w, "cls", "merged-clean"))
    ok, why = wl.recheck(tmp_path, orig, wl.Context({}, {}, set(), True), explicit=False)
    assert not ok and "no longer removable" in why




# --- Codex round-3 findings -------------------------------------------------------------------------------
def test_shell_quote_is_literal_for_dollar_names():
    assert wl.shell_quote("refs/heads/feat/$name") == "'refs/heads/feat/$name'"
    assert wl.shell_quote("it's") == "'it''s'"




# --- Codex round-4: quarantine design ---------------------------------------------------------------------
def _target(**kw):
    t = W(in_main=True, head="abc123", **kw)
    t.cls, _ = wl.classify(t)
    t.removable = True
    return t


def _stub_ctx(monkeypatch, targets, tmp_path):
    monkeypatch.setattr(wl, "context", lambda root: wl.Context({}, {}, set(), protect_loaded=True))
    monkeypatch.setattr(wl, "collect", lambda *a, **k: targets)
    monkeypatch.setattr(wl, "quarantine_dir", lambda root: tmp_path / "q")


def test_apply_moves_to_quarantine_and_never_removes(tmp_path, monkeypatch):
    t = _target(path=str(tmp_path / "wt"))
    _stub_ctx(monkeypatch, [t], tmp_path)
    monkeypatch.setattr(wl, "recheck", lambda *a, **k: (True, "ok"))
    calls = []
    monkeypatch.setattr(wl, "git", lambda cwd, *args: calls.append(args) or (0, ""))
    assert wl.cleanup(tmp_path, apply=True, pr=None, log_path=tmp_path / "log.txt") == 0
    assert [c[:2] for c in calls] == [("worktree", "move")]
    entry = wl.load_manifest(tmp_path)[0]
    assert entry["original"] == t.path and entry["head"] == "abc123"


def test_failed_move_returns_nonzero(tmp_path, monkeypatch):
    t = _target(path=str(tmp_path / "wt"))
    _stub_ctx(monkeypatch, [t], tmp_path)
    monkeypatch.setattr(wl, "recheck", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(wl, "git", lambda cwd, *args: (1, "fatal: locked"))
    assert wl.cleanup(tmp_path, apply=True, pr=None, log_path=tmp_path / "log.txt") == 1
    assert wl.load_manifest(tmp_path) == []


def test_pr_mode_matches_any_of_several_merged_prs_but_not_others(tmp_path, monkeypatch):
    t = _target(path=str(tmp_path / "wt"), branch="feat/reused", recent_checkout=True)
    t.merged_prs = [101, 202]
    _stub_ctx(monkeypatch, [t], tmp_path)
    monkeypatch.setattr(wl, "merged_pr_branch", lambda root, pr: "feat/reused")
    monkeypatch.setattr(wl, "recheck", lambda *a, **k: (True, "ok"))
    calls = []
    monkeypatch.setattr(wl, "git", lambda cwd, *args: calls.append(args) or (0, ""))
    assert wl.cleanup(tmp_path, apply=True, pr=303, log_path=tmp_path / "log.txt") == 0
    assert calls == []
    assert wl.cleanup(tmp_path, apply=True, pr=202, log_path=tmp_path / "log.txt") == 0
    assert [c[:2] for c in calls] == [("worktree", "move")]


def test_purge_respects_quarantine_age(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "context", lambda root: wl.Context({}, {}, set(), protect_loaded=True))
    monkeypatch.setattr(wl, "quarantine_dir", lambda root: tmp_path / "q")
    fresh = wl.dt.datetime.now().isoformat(timespec="seconds")
    wl.save_manifest(tmp_path, [{"original": "D:/x", "quarantined": str(tmp_path / "q" / "x"), "branch": "b",
                                 "head": "h", "in_main": True, "merged_prs": [], "moved_at": fresh}])
    calls = []
    monkeypatch.setattr(wl, "git", lambda cwd, *args: calls.append(args) or (0, ""))
    assert wl.purge(tmp_path, apply=True, older_than_days=7, log_path=tmp_path / "log.txt") == 0
    assert calls == []


def test_branch_kept_when_another_worktree_still_uses_it(tmp_path, monkeypatch):
    porcelain = (
        "worktree D:/main\nHEAD 1\nbranch refs/heads/main\n\n"
        "worktree D:/other\nHEAD h\nbranch refs/heads/feat/x\n"
    )
    monkeypatch.setattr(wl, "load_protected", lambda root: set())
    calls = []
    monkeypatch.setattr(wl, "git", lambda cwd, *args: calls.append(args) or (0, porcelain))
    e = {"branch": "feat/x", "head": "h", "merged_prs": [5]}
    assert wl.delete_branch_if_safe(tmp_path, e, lambda m: None) == 0
    assert not [c for c in calls if c[:1] == ("update-ref",)]


def test_branch_delete_is_atomic_and_needs_merge_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "load_protected", lambda root: set())

    def fake_git(cwd, *args):
        calls.append(args)
        if args[:2] == ("worktree", "list"):
            return 0, "worktree D:/main\nHEAD 1\nbranch refs/heads/main\n"
        if args[:1] == ("merge-base",):
            return rc_anc, ""
        return 0, ""

    monkeypatch.setattr(wl, "git", fake_git)
    for rc_anc, prs, expect_delete, expect_rc in ((0, [], True, 0), (1, [7], True, 0), (1, [], False, 1),
                                                  (128, [7], False, 1)):
        calls = []
        e = {"branch": "feat/x", "head": "abc", "merged_prs": prs}
        assert wl.delete_branch_if_safe(tmp_path, e, lambda m: None) == expect_rc
        deleted = ("update-ref", "-d", "refs/heads/feat/x", "abc") in calls
        assert deleted is expect_delete, (rc_anc, prs)


def test_report_prints_no_raw_removal_commands(tmp_path):
    t = _target(merged_pr=9)
    t.branch_deletable = True
    md = wl.report([t], tmp_path).read_text(encoding="utf-8")
    assert "git worktree remove" not in md and "update-ref" not in md and "git branch -D" not in md
    assert "cleanup --apply" in md and "purge --apply" in md and "`D:/x/wt`" in md
