"""Selection-lab start wrapper: pure tests (fake git, fake clock, fake runner, no database)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.brain import selection_lab_run as real_runner
from swing_trade_ml.brain import selection_lab_start as start

IST = ZoneInfo("Asia/Kolkata")
OK_NOW = datetime(2026, 12, 5, 0, 0, tzinfo=IST)
FILES = ("a.py", "b.py")


class FakeGit:
    def __init__(self):
        self.tags = {"sl-protocol-v1", "wf-protocol-v2", *start.PHASE_B_TAGS}
        self.ancestors = set(self.tags)
        self.status = ""
        self.head_blobs = {"a.py": "h1", "b.py": "h2"}
        self.tag_blobs = {"a.py": "h1", "b.py": "h2"}
        self.fail: set[str] = set()  # command names that return exit 128
        self.ignored = True

    def __call__(self, *a):
        cmd = a[0]
        if cmd in self.fail:
            return 128, ""
        if cmd == "rev-parse":
            if "--verify" in a:
                tag = a[-1].split("/")[-1].split("^")[0]
                return (0, "tagsha\n") if tag in self.tags else (1, "")
            return 0, "headsha\n"
        if cmd == "merge-base":
            tag = a[2].split("/")[-1]
            return (0, "") if tag in self.ancestors else (1, "")
        if cmd == "status":
            return 0, self.status
        if cmd == "ls-tree":
            blobs = self.head_blobs if a[1] == "HEAD" else self.tag_blobs
            p = a[-1]
            return 0, (f"100644 blob {blobs[p]}\t{p}\n" if p in blobs else "")
        if cmd == "check-ignore":
            return (0 if self.ignored else 1), ""
        raise AssertionError(a)


class FakeRunner:
    TAG = "sl-protocol-v1"
    FROZEN_FILES = FILES
    refusal_reasons = staticmethod(real_runner.refusal_reasons)

    def __init__(self, exit_code=0):
        self.calls = []
        self.exit_code = exit_code

    def git_state(self, repo):
        return True, [], False

    def amendment_signed(self, repo):
        return True

    def main(self, argv):
        self.calls.append(list(argv))
        return self.exit_code


@pytest.fixture
def env(tmp_path):
    (tmp_path / "docs" / "brain").mkdir(parents=True)
    rows = "\n".join(start.PHASE_B_LEDGER_MARKER.format(cid=c) for c in start.PHASE_B_CANDIDATES)
    (tmp_path / start.LEDGER).write_text(rows, encoding="utf-8")
    return SimpleNamespace(git=FakeGit(), runner=FakeRunner(), root=tmp_path, now=OK_NOW)


def go(env, *argv, now=None):
    clock = now or env.now
    return start.main(list(argv), runner=env.runner, git=env.git, repo_root=env.root, now_fn=lambda: clock)


def audit_lines(env):
    p = env.root / start.AUDIT_REL
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_all_pass_calls_runner_with_args_unchanged(env):
    assert go(env, "S0", "--technical-rerun") == 0
    assert env.runner.calls == [["S0", "--technical-rerun"]]
    lines = audit_lines(env)
    assert [x["event"] for x in lines] == ["start_attempt", "runner_finished"]
    assert lines[0]["decision"] == "permitted" and lines[1]["exit_code"] == 0
    assert lines[0]["candidate"] == "S0" and lines[0]["git_head"] == "headsha"
    assert lines[0]["tag_commit"] == "tagsha" and "utc" in lines[0] and "ist" in lines[0]


def test_runner_exit_code_is_returned_and_logged(env):
    env.runner.exit_code = 2
    assert go(env, "S0") == 2
    assert audit_lines(env)[-1]["exit_code"] == 2


@pytest.mark.parametrize(
    ("now", "ok"),
    [
        (datetime(2026, 12, 4, 23, 59, tzinfo=IST), False),
        (datetime(2026, 12, 5, 0, 0, tzinfo=IST), True),
        (datetime(2026, 12, 4, 18, 29, tzinfo=UTC), False),
        (datetime(2026, 12, 4, 18, 30, tzinfo=UTC), True),
        (datetime(2026, 11, 3, 12, 0, tzinfo=UTC), False),
    ],
)
def test_date_boundary(now, ok):
    assert start.check_date(now)["ok"] is ok


def test_naive_clock_refuses(env):
    assert go(env, "S0", now=datetime(2026, 12, 6)) == 2
    assert env.runner.calls == []


def refuses(env, *argv):
    assert go(env, *argv) == 2
    assert env.runner.calls == []
    lines = audit_lines(env)
    assert len(lines) == 1 and lines[0]["decision"] == "refused"
    return lines[0]


def test_before_date_refuses(env):
    env.now = datetime(2026, 12, 4, 23, 59, tzinfo=IST)
    rec = refuses(env, "S0")
    assert any(c["check"] == "date" and not c["ok"] for c in rec["checks"])


def test_missing_protocol_tag_refuses(env):
    env.git.tags.discard("sl-protocol-v1")
    refuses(env, "S0")


def test_tag_not_ancestor_refuses(env):
    env.git.ancestors.discard("sl-protocol-v1")
    refuses(env, "S0")


def test_dirty_tree_refuses(env):
    env.git.status = "?? new.txt\n"
    refuses(env, "S0")


def test_changed_frozen_file_refuses(env):
    env.git.head_blobs["a.py"] = "other"
    refuses(env, "S0")


@pytest.mark.parametrize("side", ["head", "tag"])
def test_one_side_absent_refuses(env, side):
    getattr(env.git, f"{side}_blobs").pop("a.py")
    refuses(env, "S0")


def test_absent_in_both_passes_with_warning(env, capsys):
    env.git.head_blobs.pop("a.py")
    env.git.tag_blobs.pop("a.py")
    assert go(env, "S0") == 0
    assert "a.py" in capsys.readouterr().out
    assert audit_lines(env)[0]["checks"][4]["warnings"]


@pytest.mark.parametrize("cmd", ["status", "ls-tree", "merge-base", "rev-parse", "check-ignore"])
def test_git_error_refuses(env, cmd):
    env.git.fail.add(cmd)
    assert go(env, "S0") == 2
    assert env.runner.calls == []


def test_phase_b_lock_tag_missing_refuses(env):
    env.git.tags.discard("wf-protocol-v2")
    env.git.ancestors.discard("wf-protocol-v2")
    rec = refuses(env, "S0")
    assert any(c["check"] == "phase_b_lock" and not c["ok"] for c in rec["checks"])


def test_phase_b_ledger_row_missing_refuses(env):
    (env.root / start.LEDGER).write_text("Phase B candidate B1\n", encoding="utf-8")
    refuses(env, "S0")


def test_phase_b_ledger_unreadable_refuses(env):
    (env.root / start.LEDGER).unlink()
    refuses(env, "S0")


def test_runner_guard_refusal_is_included(env):
    env.runner.amendment_signed = lambda repo: False
    refuses(env, "S0")


def test_runner_helper_exception_refuses(env):
    def boom(repo):
        raise OSError("git gone")

    env.runner.git_state = boom
    refuses(env, "S0")


def test_audit_unwritable_refuses_and_never_calls_runner(env):
    (env.root / "backend").mkdir()
    (env.root / "backend" / "data").write_text("a file, not a folder", encoding="utf-8")
    assert go(env, "S0") == 2
    assert env.runner.calls == []


def test_audit_not_gitignored_refuses(env):
    env.git.ignored = False
    assert go(env, "S0") == 2
    assert env.runner.calls == []
    assert audit_lines(env) == []


def test_check_only_never_calls_runner_and_logs_once(env, capsys):
    assert go(env, "S0", "--check-only") == 0
    assert env.runner.calls == []
    lines = audit_lines(env)
    assert len(lines) == 1 and lines[0]["decision"] == "would_permit" and lines[0]["check_only"]


def test_check_only_prints_every_reason(env, capsys):
    env.now = datetime(2026, 11, 3, tzinfo=UTC)
    env.git.status = "M x\n"
    assert go(env, "S0", "--check-only") == 2
    out = capsys.readouterr().out
    assert "Too early" in out and "uncommitted" in out
    assert env.runner.calls == []


def test_audit_line_written_before_runner_call(env):
    seen = []
    env.runner.main = lambda argv: seen.append(len(audit_lines(env))) or 0
    go(env, "S0")
    assert seen == [1]


def test_every_refusal_writes_exactly_one_line(env):
    env.git.status = "M x"
    go(env, "S0")
    go(env, "S1")
    assert len(audit_lines(env)) == 2


def test_phase_b_constants_match_phase_b():
    import swing_trade_ml.brain.service  # noqa: F401  (import order: phase_b alone has a circular import)
    from swing_trade_ml.brain import phase_b

    assert tuple(t for t in phase_b.REQUIRED_TAGS) == start.PHASE_B_TAGS
    assert start.PHASE_B_LEDGER_MARKER == phase_b.LEDGER_MARKER
    assert tuple(phase_b.CANDIDATES) == start.PHASE_B_CANDIDATES


def test_real_runner_exposes_what_the_wrapper_uses():
    for name in ("TAG", "FROZEN_FILES", "git_state", "amendment_signed", "refusal_reasons", "main"):
        assert hasattr(real_runner, name)


# ---- no direct call path to the frozen runner outside the wrapper

REPO = Path(__file__).resolve().parents[2]
ALLOWED = {
    "backend/src/swing_trade_ml/brain/selection_lab_start.py",
    "backend/src/swing_trade_ml/brain/selection_lab_run.py",
}
# a way of RUNNING the runner (not just importing a helper from it)
DIRECT = re.compile(
    r"-m\s+swing_trade_ml\.brain\.selection_lab_run|selection_lab_run\.main|selection_lab_run\s+import\s+[^\n]*\bmain\b|selection_lab_run\.py"
)


def _scan_files():
    for root in ("backend/src", "scripts", ".github", "backend/scripts", "Makefile", "docker-compose.yml"):
        p = REPO / root
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix in {
                    ".py",
                    ".sh",
                    ".ps1",
                    ".yml",
                    ".yaml",
                    ".toml",
                    ".cfg",
                    ".bat",
                }:
                    yield f


def test_no_code_script_or_workflow_calls_the_runner_directly():
    bad = []
    for f in _scan_files():
        rel = f.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        if DIRECT.search(f.read_text(encoding="utf-8", errors="ignore")):
            bad.append(rel)
    assert bad == [], f"use brain.selection_lab_start instead: {bad}"


def test_non_frozen_docs_point_to_the_wrapper():
    doc = (REPO / "docs/brain/SELECTION-LAB-START.md").read_text(encoding="utf-8")
    assert "selection_lab_start" in doc and "not a hard lock" in doc


def test_console_entry_is_declared():
    toml = (REPO / "backend/pyproject.toml").read_text(encoding="utf-8")
    assert 'selection-lab-start = "swing_trade_ml.brain.selection_lab_start:main"' in toml


@pytest.mark.parametrize(
    "line",
    [
        "python -m swing_trade_ml.brain.selection_lab_run S0",
        "from swing_trade_ml.brain import selection_lab_run; selection_lab_run.main(['S0'])",
        "from swing_trade_ml.brain.selection_lab_run import main",
        "python backend/src/swing_trade_ml/brain/selection_lab_run.py S0",
    ],
)
def test_the_scanner_pattern_catches_direct_calls(line):
    assert DIRECT.search(line)
    assert not DIRECT.search("from swing_trade_ml.brain.selection_lab_run import collect_db")
