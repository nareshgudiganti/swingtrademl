# ruff: noqa: E501
"""The 15-day lab runner enforces the start conditions ITSELF (date + Phase B terminal record + tags + clean tree +
frozen files), through the SAME code the wrapper uses, on every entry point: `run.main` (the CLI) and `run.run`
(a direct call). Pure tests: fake git, fake clock, synthetic data, no database, nothing real is started."""

from __future__ import annotations

import ast
import inspect
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from test_selection_lab_run import (  # noqa: F401  (bars and repo are fixtures)
    EXTRA,
    FIRST,
    GOOD_STATE,
    LAST,
    MID,
    USED,
    bars,
    foresight,
    repo,
)
from test_selection_lab_start import FakeGit, write_phase_b_record

from swing_trade_ml.brain import selection_lab_run as run
from swing_trade_ml.brain import selection_lab_start as start

IST = ZoneInfo("Asia/Kolkata")
OK_DAY = datetime(2026, 12, 5, 0, 0, tzinfo=IST)
EARLY = datetime(2026, 12, 4, 23, 59, tzinfo=IST)


class FakeDatetime(datetime):
    """`datetime.now(UTC)` inside the guard returns a fixed instant."""

    fixed = OK_DAY

    @classmethod
    def now(cls, tz=None):
        return cls.fixed.astimezone(tz) if tz else cls.fixed


@pytest.fixture
def world(repo, monkeypatch):
    """A synthetic repo, a fake git that holds a valid Phase B record, a fake clock, and the runner's two git helpers
    faked. Everything else (the shared start check, the audit line, the runner) is the REAL code."""
    git = FakeGit()
    e = SimpleNamespace(git=git, root=repo, now=OK_DAY)
    write_phase_b_record(e)
    git.tags.add(run.TAG)
    git.ancestors.add(run.TAG)
    git.head_blobs.update({p: f"h{i}" for i, p in enumerate(run.FROZEN_FILES)})
    git.tag_blobs.update(git.head_blobs)
    FakeDatetime.fixed = OK_DAY
    monkeypatch.setattr(start, "datetime", FakeDatetime)
    monkeypatch.setattr(start, "make_git", lambda root: git)
    monkeypatch.setattr(run, "git_state", lambda root: GOOD_STATE)
    monkeypatch.setattr(run, "_repo", lambda: repo)
    e.audit = lambda: [
        json.loads(x) for x in (repo / start.AUDIT_REL).read_text(encoding="utf-8").splitlines()
    ] if (repo / start.AUDIT_REL).exists() else []
    return e


def real_run(world, bars, candidate="S0", **kw):
    """`run.run` exactly as production calls it: NO start_check argument."""
    return run.run(
        candidate,
        repo_root=world.root,
        collect_fn=kw.pop("collect_fn", lambda: (bars, USED, EXTRA)),
        model_scores_fn=foresight(bars),
        mid_fn=lambda: MID,
        state=GOOD_STATE,
        first=FIRST,
        last=LAST,
        today=date(2026, 12, 6),
        **kw,
    )


def never_collect():
    raise AssertionError("data was read although the start conditions were not met")


def ledger_text(world):
    return (world.root / "docs/brain/EXPOSURE-LEDGER.md").read_text(encoding="utf-8")


# ---- the direct call `run.run` is guarded


def test_a_valid_start_passes_the_real_default_guard_and_writes_the_run(world, bars):
    d = real_run(world, bars)
    assert (d / "metrics.json").exists()
    lines = world.audit()
    assert [x["event"] for x in lines] == ["runner_start_check"]
    assert lines[0]["via"] == "run" and lines[0]["decision"] == "permitted" and lines[0]["candidate"] == "S0"


def test_direct_run_refuses_before_5_december_and_reads_nothing(world, bars):
    FakeDatetime.fixed = EARLY
    with pytest.raises(run.RunRefusedError, match="Too early") as ei:
        real_run(world, bars, collect_fn=never_collect)
    assert "nothing was trained or scored" in str(ei.value)
    assert f"{run.PROTOCOL} S0," not in ledger_text(world)
    assert world.audit()[-1]["decision"] == "refused"


@pytest.mark.parametrize(
    "tag",
    [start.PHASE_B_RESULT_TAG, "evidence-defs-v2", "phase-b-settings"],
)
def test_direct_run_refuses_without_the_phase_b_tags(world, bars, tag):
    world.git.tags.discard(tag)
    world.git.ancestors.discard(tag)
    with pytest.raises(run.RunRefusedError, match=re.escape(f"git tag {tag} does not exist")):
        real_run(world, bars, collect_fn=never_collect)
    assert f"{run.PROTOCOL} S0," not in ledger_text(world)


def test_direct_run_refuses_without_the_phase_b_record_file(world, bars):
    (world.root / start.PHASE_B_RESULT_REL).unlink()
    with pytest.raises(run.RunRefusedError, match="PHASE_B_RESULT.json is missing"):
        real_run(world, bars, collect_fn=never_collect)


def test_direct_run_refuses_a_record_changed_after_the_tag(world, bars):
    world.git.head_blobs[start.PHASE_B_RESULT_REL] = "changed"
    with pytest.raises(run.RunRefusedError, match="differs from the version at tag"):
        real_run(world, bars, collect_fn=never_collect)


def test_direct_run_refuses_on_a_dirty_tree_and_a_changed_frozen_file(world, bars):
    world.git.status = " M x.py\n"
    with pytest.raises(run.RunRefusedError, match="uncommitted or untracked"):
        real_run(world, bars, collect_fn=never_collect)
    world.git.status = ""
    world.git.head_blobs[run.FROZEN_FILES[0]] = "edited"
    with pytest.raises(run.RunRefusedError, match="differs from the tagged version"):
        real_run(world, bars, collect_fn=never_collect)


def test_direct_run_refuses_when_the_audit_line_cannot_be_written(world, bars):
    world.git.ignored = False
    with pytest.raises(run.RunRefusedError, match="audit log could not be written"):
        real_run(world, bars, collect_fn=never_collect)


def test_direct_run_fails_closed_when_the_check_itself_breaks(world, bars, monkeypatch):
    def boom(*a, **k):
        raise OSError("git is gone")

    monkeypatch.setattr(start, "guard_for_runner", boom)
    with pytest.raises(run.RunRefusedError, match="could not be verified: OSError: git is gone"):
        real_run(world, bars, collect_fn=never_collect)


def test_direct_run_refuses_a_git_error_in_the_phase_b_check(world, bars):
    world.git.fail.add("show")
    with pytest.raises(run.RunRefusedError, match="could not be verified"):
        real_run(world, bars, collect_fn=never_collect)


def test_a_no_survivor_start_through_the_runner_prints_the_research_only_notice(world, bars, capsys):
    real_run(world, bars)
    assert "independent experimental research only" in capsys.readouterr().out


def test_the_start_check_hook_is_honoured_for_tests_and_a_refusal_from_it_stops_the_run(world, bars):
    with pytest.raises(run.RunRefusedError, match="stub says no"):
        real_run(world, bars, collect_fn=never_collect, start_check=lambda c, r: ["stub says no"])


# ---- the CLI `run.main` is guarded (and refuses before it touches the database)


def _no_database(monkeypatch):
    import swing_trade_ml.db.session as session

    def boom(*a, **k):
        raise AssertionError("the database was opened although the start conditions were not met")

    monkeypatch.setattr(session, "SessionLocal", boom)


def test_cli_refuses_before_5_december_before_touching_the_database(world, monkeypatch, capsys):
    FakeDatetime.fixed = EARLY
    _no_database(monkeypatch)
    assert run.main(["S0"]) == 2
    out = capsys.readouterr().out
    assert "refused: nothing was trained or scored" in out and "Too early" in out
    assert world.audit()[-1]["via"] == "cli" and world.audit()[-1]["decision"] == "refused"


def test_cli_refuses_without_the_phase_b_record(world, monkeypatch, capsys):
    world.git.tags.discard(start.PHASE_B_RESULT_TAG)
    world.git.ancestors.discard(start.PHASE_B_RESULT_TAG)
    _no_database(monkeypatch)
    assert run.main(["S0M"]) == 2
    assert "phase-b-result does not exist" in capsys.readouterr().out


def test_cli_with_the_technical_rerun_flag_is_guarded_too(world, monkeypatch, capsys):
    FakeDatetime.fixed = EARLY
    _no_database(monkeypatch)
    assert run.main(["S0", "--technical-rerun"]) == 2
    assert "Too early" in capsys.readouterr().out


def test_cli_passes_the_guard_and_then_opens_the_database(world, monkeypatch):
    """Once every start condition holds, main goes on to the database (stubbed to stop there)."""
    import swing_trade_ml.db.session as session

    class Stop(Exception):
        pass

    def opened(*a, **k):
        raise Stop

    monkeypatch.setattr(session, "SessionLocal", opened)
    with pytest.raises(Stop):
        run.main(["S0"])
    assert world.audit()[-1]["decision"] == "permitted"


# ---- the wrapper still works and shares the code


def test_the_wrapper_and_the_runner_use_the_same_check_function():
    src_run = inspect.getsource(run.start_conditions)
    assert "guard_for_runner" in src_run
    guard = inspect.getsource(start.guard_for_runner)
    assert "evaluate(runner, git, repo_root, now_fn, candidate)" in guard
    assert "evaluate(runner, git, repo_root, now_fn, candidate)" in inspect.getsource(start.main)


def test_the_wrapper_start_check_only_still_passes_on_a_valid_world(world, capsys):
    code = start.main(["S0", "--check-only"], runner=run, git=world.git, repo_root=world.root, now_fn=lambda: OK_DAY)
    assert code == 0, capsys.readouterr().out


def test_the_wrapper_and_runner_reach_the_same_verdict_on_every_refusal_case(world):
    """Same inputs, same reasons: the runner's guard and the wrapper's evaluate cannot drift apart."""
    cases = [
        lambda: setattr(FakeDatetime, "fixed", EARLY),
        lambda: world.git.tags.discard(start.PHASE_B_RESULT_TAG),
        lambda: setattr(world.git, "status", " M x\n"),
    ]
    for break_it in cases:
        FakeDatetime.fixed = OK_DAY
        world.git.tags.add(start.PHASE_B_RESULT_TAG)
        world.git.status = ""
        break_it()
        now = FakeDatetime.fixed
        wrapper = [r for res in start.evaluate(run, world.git, world.root, lambda: now, "S0") for r in res["reasons"]]
        runner = start.guard_for_runner("S0", runner=run, repo_root=world.root, git=world.git, now_fn=lambda: now)
        assert wrapper and wrapper == runner


# ---- the guard cannot be silently removed


def _calls(fn, name):
    return any(
        isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == name
        for n in ast.walk(ast.parse(inspect.getsource(fn)))
    )


def test_both_entry_points_call_the_shared_start_check():
    assert _calls(run.run, "start_conditions") or "start_conditions" in inspect.getsource(run.run)
    assert _calls(run.main, "start_conditions")
    # and the check comes before anything is read: in `run` it is the first statement after the docstring
    body = ast.parse(inspect.getsource(run.run)).body[0].body
    first_code = next(s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)))
    assert "start_conditions" in ast.dump(first_code) or "start_check" in ast.dump(first_code)


def test_the_start_module_is_part_of_the_frozen_set():
    rel = "backend/src/swing_trade_ml/brain/selection_lab_start.py"
    assert rel in run.FROZEN_FILES
    assert (Path(__file__).resolve().parents[2] / rel).is_file()


def test_there_is_no_environment_override_in_the_shared_check():
    assert "os.environ" not in inspect.getsource(start.guard_for_runner)
    assert "os.environ" not in inspect.getsource(run.start_conditions)


def test_the_real_clock_default_is_not_bypassable_by_arguments():
    sig = inspect.signature(run.main)
    assert list(sig.parameters) == ["argv"]  # main takes no clock, git or check argument
