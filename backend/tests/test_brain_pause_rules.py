"""ps7: pre-set rules that put the brain back into practice by themselves.

They may only ever step the brain BACK to practice, only once it is outside practice, and only when the
owner has set a number. A rule that cannot be checked counts as crossed.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

from brain_m18_fixtures import DAY, at, brain_strategy, instrument, run, signal
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.services import trial_seal
from swing_trade_ml.services.brain_golive import pause_rules, stage
from swing_trade_ml.services.brain_golive.pause_rules import PauseRules, crossed, trailing_failures, trailing_losses

SINCE = DAY - timedelta(days=40)


@pytest.fixture(autouse=True)
def _unsealed(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", False)


def _stage(db, stage_name: str, previous: str, day=SINCE) -> None:
    db.add(
        BrainStageChange(
            stage=stage_name, previous_stage=previous, changed_by="owner", reason="r", changed_at=at(day, 17, 0)
        )
    )
    db.flush()


def _losses(db, n: int, *, start=SINCE + timedelta(days=1)) -> None:
    s = brain_strategy(db, name="pause-brain")
    for i in range(n):
        inst = instrument(db, f"PAUSE{i}", 917000 + i)
        signal(db, s, inst, start + timedelta(days=i), outcome="STOP_LOSS_HIT", outcome_pct=-0.04)


# --- pure ---------------------------------------------------------------------------------------


def test_trailing_losses_counts_only_the_newest_run_of_losses():
    assert trailing_losses([0.08, -0.04, -0.04]) == 2
    assert trailing_losses([-0.04, -0.04, 0.02]) == 0
    assert trailing_losses([]) == 0


def test_trailing_failures_counts_from_the_newest_run():
    assert trailing_failures(["failed", "failed", "done", "failed"]) == 2
    assert trailing_failures(["done", "failed"]) == 0


def test_every_rule_is_off_until_the_owner_sets_a_number():
    off = PauseRules()
    assert not off.any_on
    assert crossed(off, streak=99, gate={"finished": 99, "beats_random": False}, failed_runs=99) == []


def test_each_rule_names_itself_in_plain_words():
    rules = PauseRules(losing_streak=5, behind_after_ideas=20, failed_nightly_runs=3)
    reasons = crossed(rules, streak=5, gate={"finished": 20, "beats_random": False}, failed_runs=3)
    assert len(reasons) == 3
    assert "5 brain ideas in a row lost money" in reasons[0]
    assert "behind buying every stock" in reasons[1]
    assert "3 nightly brain runs in a row failed" in reasons[2]
    assert crossed(rules, streak=4, gate={"finished": 19, "beats_random": False}, failed_runs=2) == []
    assert crossed(rules, streak=0, gate={"finished": 25, "beats_random": True}, failed_runs=0) == []


# --- with the database --------------------------------------------------------------------------


def test_nothing_happens_while_the_brain_is_in_practice(db_session):
    """The forward trial runs in practice: the rules must not touch it."""
    for i in range(5):
        run(db_session, f"pause-fail-{i}", DAY - timedelta(days=i), status="failed")
    assert pause_rules.apply(db_session, PauseRules(failed_nightly_runs=1)) is None
    assert stage.current_stage(db_session) == "shadow"


def test_nothing_happens_when_every_rule_is_off(db_session):
    _stage(db_session, "approval", "shadow")
    for i in range(5):
        run(db_session, f"pause-off-{i}", DAY - timedelta(days=i), status="failed")
    assert pause_rules.apply(db_session, PauseRules()) is None
    assert stage.current_stage(db_session) == "approval"


def test_failed_nightly_runs_put_the_brain_back_in_practice(db_session):
    _stage(db_session, "approval", "shadow")
    run(db_session, "pause-ok", DAY - timedelta(days=3), status="done")
    for i in range(3):
        run(db_session, f"pause-f-{i}", DAY - timedelta(days=i), status="failed")

    message = pause_rules.apply(db_session, PauseRules(failed_nightly_runs=3))

    assert message and "Brain paused" in message
    assert stage.current_stage(db_session) == "shadow"
    latest = db_session.query(BrainStageChange).order_by(BrainStageChange.id.desc()).first()
    assert (latest.changed_by, latest.previous_stage) == (pause_rules.PAUSE_BY, "approval")
    assert "3 nightly brain runs in a row failed" in latest.reason


def test_a_losing_streak_since_leaving_practice_pauses_auto(db_session):
    _stage(db_session, "approval", "shadow")
    _stage(db_session, "auto", "approval", day=SINCE + timedelta(days=1))
    _losses(db_session, 4)

    assert pause_rules.apply(db_session, PauseRules(losing_streak=5)) is None
    assert stage.current_stage(db_session) == "auto"

    more = brain_strategy(db_session, name="pause-brain-2")
    signal(
        db_session, more, instrument(db_session, "PAUSEX", 917900), SINCE + timedelta(days=10),
        outcome="STOP_LOSS_HIT", outcome_pct=-0.04,
    )
    assert pause_rules.apply(db_session, PauseRules(losing_streak=5))
    assert stage.current_stage(db_session) == "shadow"


def test_losses_from_before_leaving_practice_do_not_count(db_session):
    _losses(db_session, 6, start=SINCE - timedelta(days=20))
    _stage(db_session, "approval", "shadow")
    assert pause_rules.apply(db_session, PauseRules(losing_streak=5)) is None
    assert stage.current_stage(db_session) == "approval"


def test_a_rule_that_cannot_be_checked_pauses_the_brain(db_session, monkeypatch):
    _stage(db_session, "approval", "shadow")

    def boom(db, limit):
        raise RuntimeError("database read failed")

    monkeypatch.setattr(pause_rules, "_nightly_statuses", boom)
    assert pause_rules.apply(db_session, PauseRules(failed_nightly_runs=2))
    assert stage.current_stage(db_session) == "shadow"


def test_sealed_trial_keeps_the_reason_counts_only(db_session, monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", True)
    _stage(db_session, "approval", "shadow")
    for i in range(2):
        run(db_session, f"pause-s-{i}", DAY - timedelta(days=i), status="failed")
    message = pause_rules.apply(db_session, PauseRules(failed_nightly_runs=2))
    assert pause_rules.SEALED_REASON in message
    assert "nightly brain runs" not in message


def test_the_pause_rules_only_ever_ask_for_practice():
    """Static guard: every set_stage call in pause_rules.py asks for "shadow"."""
    src = Path(pause_rules.__file__).read_text(encoding="utf-8")
    calls = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "set_stage"
    ]
    assert calls
    for call in calls:
        assert isinstance(call.args[1], ast.Constant) and call.args[1].value == "shadow"


def test_settings_default_to_off():
    assert not pause_rules.rules_from_settings().any_on


# --- owner's checks: pause only, audit trail, safe to repeat, never resumes ----------------------


def _changes(db) -> list[BrainStageChange]:
    return db.query(BrainStageChange).order_by(BrainStageChange.id).all()


def _crossed_in_approval(db) -> PauseRules:
    _stage(db, "approval", "shadow")
    for i in range(2):
        run(db, f"pause-own-{i}", DAY - timedelta(days=i), status="failed")
    return PauseRules(failed_nightly_runs=2)


def test_a_pause_leaves_one_audit_row_saying_who_from_where_and_why(db_session):
    rules = _crossed_in_approval(db_session)
    before = len(_changes(db_session))

    assert pause_rules.apply(db_session, rules)

    rows = _changes(db_session)
    assert len(rows) == before + 1
    row = rows[-1]
    assert row.stage == "shadow"
    assert row.previous_stage == "approval"
    assert row.changed_by == pause_rules.PAUSE_BY
    assert "2 nightly brain runs in a row failed" in row.reason
    assert row.changed_at is not None


def test_running_the_check_again_after_a_pause_changes_nothing(db_session):
    """The daily check may run twice (retry, manual re-run): one crossing = one pause row, one message."""
    rules = _crossed_in_approval(db_session)
    assert pause_rules.apply(db_session, rules)
    after_first = len(_changes(db_session))

    for _ in range(3):
        assert pause_rules.apply(db_session, rules) is None

    assert len(_changes(db_session)) == after_first
    assert stage.current_stage(db_session) == "shadow"


def test_a_paused_brain_never_resumes_by_itself(db_session):
    """Once paused, healthy days and switched-off rules must not move the brain forward again."""
    rules = _crossed_in_approval(db_session)
    assert pause_rules.apply(db_session, rules)
    after_pause = len(_changes(db_session))

    for i in range(5):
        run(db_session, f"pause-healthy-{i}", DAY + timedelta(days=i + 1), status="done")
    strictest = PauseRules(losing_streak=1, behind_after_ideas=1, failed_nightly_runs=1)
    for later in (rules, PauseRules(), strictest):
        assert pause_rules.apply(db_session, later) is None
        assert pause_rules.evaluate(db_session, later)["reasons"] == []

    assert stage.current_stage(db_session) == "shadow"
    assert len(_changes(db_session)) == after_pause


def test_a_pause_places_no_orders(db_session):
    from swing_trade_ml.db.models.trading import Order

    rules = _crossed_in_approval(db_session)
    orders_before = db_session.query(Order).count()
    assert pause_rules.apply(db_session, rules)
    assert db_session.query(Order).count() == orders_before


def test_evaluate_is_read_only(db_session):
    """evaluate() only reports; the stage changes only through apply()."""
    rules = _crossed_in_approval(db_session)
    before = len(_changes(db_session))
    assert pause_rules.evaluate(db_session, rules)["reasons"]
    assert len(_changes(db_session)) == before
    assert stage.current_stage(db_session) == "approval"
