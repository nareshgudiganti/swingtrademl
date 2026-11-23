"""Three isolated Brain workflows (5D, 10D, 15D): model/horizon match, per-horizon policy, separate history.

Synthetic data only: no database, no broker, no clock.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from swing_trade_ml.brain.horizons import (
    DEFAULT_POLICIES,
    NO_DECISION,
    HorizonStore,
    ModelOutput,
    evaluate_record,
    run_all_horizons,
    run_horizon,
)

SIGNAL = date(2026, 1, 2)
HOLIDAY = date(2026, 1, 8)
SESSIONS = tuple(d for i in range(40) if (d := SIGNAL + timedelta(days=i)).weekday() < 5 and d != HOLIDAY)
CLOSE0 = 100.0


def flat_bars(through: int) -> dict[date, tuple[float, float, float, float]]:
    """Open/high/low/close that never reach any target or stop (moves inside +-1%)."""
    return {SESSIONS[i]: (100.0, 100.9, 99.2, 100.0 + (i % 3) * 0.3) for i in range(through + 1)}


def output(
    horizon: int, *, score: float = 0.9, role: str = "final", forecast: int | None = None
) -> ModelOutput:
    return ModelOutput(
        model_name=f"synthetic_h{horizon}",
        model_version=f"v{horizon}.1",
        forecast_horizon_sessions=horizon if forecast is None else forecast,
        role=role,
        symbol="DEMO",
        input_session=SIGNAL,
        input_close=CLOSE0,
        score=score,
    )


def three_outputs() -> list[ModelOutput]:
    return [output(5), output(10), output(15)]


def statuses(store: HorizonStore, as_of_index: int) -> dict[int, str]:
    bars = flat_bars(as_of_index)
    out = {}
    for h in (5, 10, 15):
        (record,) = store.runs(h)
        out[h] = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[as_of_index]).status
    return out


# ---------------------------------------------------------------- acceptance test


def test_acceptance_each_horizon_completes_on_its_own_session():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")

    assert statuses(store, 4) == {5: "pending", 10: "pending", 15: "pending"}
    assert statuses(store, 5) == {5: "complete", 10: "pending", 15: "pending"}
    assert statuses(store, 10) == {5: "complete", 10: "complete", 15: "pending"}
    assert statuses(store, 15) == {5: "complete", 10: "complete", 15: "complete"}


def test_acceptance_completion_is_a_time_exit_on_the_due_session():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    for h in (5, 10, 15):
        (record,) = store.runs(h)
        result = evaluate_record(record, SESSIONS, flat_bars(15), as_of=SESSIONS[15])
        assert result.exit_reason == "time"
        assert result.exit_session == SESSIONS[h] == record.evaluation_due_session
        assert result.label == 0


def test_acceptance_5d_model_is_refused_for_a_15d_decision():
    record = run_horizon(15, [output(5)], SIGNAL, SESSIONS)
    assert record.decision == NO_DECISION
    assert record.model_version is None
    assert "forecasts 5 sessions" in record.reason
    assert "15" in record.reason


def test_acceptance_running_all_three_on_the_same_day_keeps_all_three():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    kept = {h: store.runs(h) for h in (5, 10, 15)}
    assert {h: len(r) for h, r in kept.items()} == {5: 1, 10: 1, 15: 1}
    assert {r[0].model_version for r in kept.values()} == {"v5.1", "v10.1", "v15.1"}
    assert {r[0].decision_horizon for r in kept.values()} == {5, 10, 15}
    assert all(r[0].input_session == SIGNAL for r in kept.values())


# ---------------------------------------------------------------- the stored record


def test_record_keeps_model_input_horizon_and_due_session_together():
    record = run_horizon(10, [output(10)], SIGNAL, SESSIONS)
    assert record.model_name == "synthetic_h10"
    assert record.model_version == "v10.1"
    assert record.input_session == SIGNAL
    assert record.decision_horizon == 10
    assert record.evaluation_due_session == SESSIONS[10]
    assert record.symbol == "DEMO"


def test_due_session_counts_exchange_sessions_not_calendar_days():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    # 2 Jan (Fri) -> skips two weekends and the 8 Jan holiday
    assert record.evaluation_due_session == date(2026, 1, 12)


def test_policy_applied_is_the_horizons_own():
    for h in (5, 10, 15):
        record = run_horizon(h, [output(h)], SIGNAL, SESSIONS)
        policy = DEFAULT_POLICIES[h]
        assert record.policy_code == policy.code
        assert record.target_pct == policy.target_pct
        assert record.stop_pct == policy.stop_pct
    assert (DEFAULT_POLICIES[5].target_pct, DEFAULT_POLICIES[5].stop_pct) == (0.02, 0.04)
    assert (DEFAULT_POLICIES[10].target_pct, DEFAULT_POLICIES[10].stop_pct) == (0.06, 0.035)
    assert (DEFAULT_POLICIES[15].target_pct, DEFAULT_POLICIES[15].stop_pct) == (0.08, 0.04)
    assert DEFAULT_POLICIES[15].half_out_pct == 0.05


def test_decision_vocabulary_follows_the_score_thresholds():
    p = DEFAULT_POLICIES[5]
    assert run_horizon(5, [output(5, score=p.trade_min_score)], SIGNAL, SESSIONS).decision == "TRADE"
    assert run_horizon(5, [output(5, score=p.watch_min_score)], SIGNAL, SESSIONS).decision == "WATCH"
    assert run_horizon(5, [output(5, score=p.watch_min_score - 0.01)], SIGNAL, SESSIONS).decision == "WAIT"


@pytest.mark.parametrize("h", [5, 10, 15])
def test_no_horizon_accepts_a_prod_marked_model_until_the_owner_approves_it(h):
    """Owner decision D1 (which roles may decide) is still pending, so only a frozen `final` model decides."""
    record = run_horizon(h, [output(h, role="prod")], SIGNAL, SESSIONS)
    assert record.decision == NO_DECISION
    assert "not approved for decisions" in record.reason
    assert DEFAULT_POLICIES[h].eligible_roles == frozenset({"final"})


@pytest.mark.parametrize("h", [10, 15])
def test_10d_and_15d_refuse_a_prod_model(h):
    record = run_horizon(h, [output(h, role="prod")], SIGNAL, SESSIONS)
    assert record.decision == NO_DECISION
    assert "not approved for decisions" in record.reason


@pytest.mark.parametrize("h", [5, 10, 15])
def test_fold_and_unmarked_models_are_refused_everywhere(h):
    for role in ("fold", "unmarked"):
        assert run_horizon(h, [output(h, role=role)], SIGNAL, SESSIONS).decision == NO_DECISION


# ---------------------------------------------------------------- no decision


@pytest.mark.parametrize(
    ("outputs", "reason_part"),
    [
        ([], "no model output"),
        ([output(10, role="candidate")], "not approved for decisions"),
        ([output(10, forecast=15)], "forecasts 15 sessions"),
        ([replace(output(10), input_session=SESSIONS[1])], "input session"),
        ([replace(output(10), score=float("nan"))], "score"),
        ([replace(output(10), input_close=0.0)], "close"),
    ],
)
def test_no_eligible_model_records_no_decision_with_reason(outputs, reason_part):
    record = run_horizon(10, outputs, SIGNAL, SESSIONS, symbol="DEMO")
    assert record.decision == NO_DECISION
    assert record.decision_horizon == 10
    assert record.input_session == SIGNAL
    assert reason_part in record.reason
    assert record.evaluation_due_session == SESSIONS[10]


def test_unapproved_policy_records_no_decision():
    policies = dict(DEFAULT_POLICIES)
    policies[10] = replace(policies[10], approved=False)
    record = run_horizon(10, [output(10)], SIGNAL, SESSIONS, policies=policies)
    assert record.decision == NO_DECISION
    assert "decision policy" in record.reason


def test_no_decision_is_never_evaluated():
    record = run_horizon(15, [output(5)], SIGNAL, SESSIONS)
    result = evaluate_record(record, SESSIONS, flat_bars(15), as_of=SESSIONS[15])
    assert result.status == "no_decision"
    assert result.label is None


def test_two_eligible_models_for_one_horizon_is_refused_not_guessed():
    other = replace(output(10), model_version="v10.2")
    record = run_horizon(10, [output(10), other], SIGNAL, SESSIONS)
    assert record.decision == NO_DECISION
    assert "more than one" in record.reason


def test_missing_due_session_in_calendar_is_no_decision():
    record = run_horizon(15, [output(15)], SIGNAL, SESSIONS[:10])
    assert record.decision == NO_DECISION
    assert "calendar" in record.reason


def test_one_failing_workflow_does_not_stop_the_others():
    store = HorizonStore()
    run_all_horizons(SIGNAL, [output(5), output(15)], SESSIONS, store, symbol="DEMO")
    assert store.runs(5)[0].decision == "TRADE"
    assert store.runs(10)[0].decision == NO_DECISION
    assert store.runs(15)[0].decision == "TRADE"


# ---------------------------------------------------------------- evaluation: next-session-open entry


def test_starting_price_is_the_open_of_the_next_session():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(1)
    bars[SESSIONS[1]] = (110.0, 111.0, 109.5, 110.5)  # gap up: +2% from the input close, not the open
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[1])
    assert result.status == "pending"
    assert (result.entry_session, result.entry_price) == (SESSIONS[1], 110.0)


def test_gap_down_entry_measures_the_stop_from_the_open():
    record = run_horizon(15, [output(15)], SIGNAL, SESSIONS)
    bars = flat_bars(1)
    bars[SESSIONS[1]] = (95.0, 95.5, 94.9, 95.2)  # -4% from the input close, but not from the 95 open
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[1])
    assert result.status == "pending"
    assert result.entry_price == 95.0


def test_entry_session_counts_as_holding_session_one():
    record = run_horizon(10, [output(10)], SIGNAL, SESSIONS)
    bars = flat_bars(1)
    bars[SESSIONS[1]] = (100.0, 106.2, 99.8, 105.0)  # +6% target from the open, on the entry session itself
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[1])
    assert (result.status, result.exit_reason, result.exit_session) == ("complete", "target", SESSIONS[1])


def test_nothing_to_evaluate_before_the_entry_session_closes():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    result = evaluate_record(record, SESSIONS, flat_bars(5), as_of=SIGNAL)
    assert result.status == "pending"
    assert result.entry_price is None


def test_missing_entry_candle_is_unmeasurable():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(5)
    del bars[SESSIONS[1]]
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[5])
    assert result.status == "unmeasurable"
    assert "entry" in result.note


def test_unusable_entry_open_is_unmeasurable():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(5)
    bars[SESSIONS[1]] = (0.0, 100.5, 99.5, 100.0)
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[5])
    assert result.status == "unmeasurable"


# ---------------------------------------------------------------- evaluation (target / stop)


def test_target_hit_completes_early_with_label_one():
    record = run_horizon(10, [output(10)], SIGNAL, SESSIONS)
    bars = flat_bars(3)
    bars[SESSIONS[3]] = (101.0, 106.5, 100.5, 106.0)  # +6% target reached on session 3
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[3])
    assert (result.status, result.exit_reason, result.exit_session, result.label) == (
        "complete",
        "target",
        SESSIONS[3],
        1,
    )


def test_stop_hit_completes_early_with_label_zero():
    record = run_horizon(15, [output(15)], SIGNAL, SESSIONS)
    bars = flat_bars(2)
    bars[SESSIONS[2]] = (99.0, 99.5, 95.9, 96.5)  # -4% stop reached on session 2
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[6])
    assert (result.status, result.exit_reason, result.exit_session, result.label) == (
        "complete",
        "stop",
        SESSIONS[2],
        0,
    )


def test_target_and_stop_on_the_same_session_counts_as_stop():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(1)
    bars[SESSIONS[1]] = (100.0, 102.5, 95.5, 100.0)
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[1])
    assert result.exit_reason == "stop"


def test_same_stock_same_bar_can_hit_the_5d_target_but_not_the_15d_target():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    bars = flat_bars(2)
    bars[SESSIONS[2]] = (100.5, 102.5, 100.0, 102.0)  # +2.5%: only the 5D target (+2%)
    r5 = evaluate_record(store.runs(5)[0], SESSIONS, bars, as_of=SESSIONS[2])
    r15 = evaluate_record(store.runs(15)[0], SESSIONS, bars, as_of=SESSIONS[2])
    assert (r5.status, r5.exit_reason) == ("complete", "target")
    assert r15.status == "pending"


def test_future_bars_beyond_as_of_are_ignored():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(5)
    bars[SESSIONS[4]] = (100.0, 110.0, 100.0, 109.0)  # a target on session 4 that has not happened yet
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[3])
    assert result.status == "pending"


def test_missing_candle_inside_the_window_is_unmeasurable():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(5)
    del bars[SESSIONS[3]]
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[5])
    assert result.status == "unmeasurable"
    assert result.label is None


# ---------------------------------------------------------------- a late candle is not a missing one


def test_a_missing_entry_candle_is_pending_until_a_later_bar_exists():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = {SESSIONS[0]: flat_bars(0)[SESSIONS[0]]}  # the entry session (1) has no candle yet
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[1])
    assert result.status == "pending" and result.label is None and result.exit_reason is None
    bars[SESSIONS[2]] = (100.0, 100.9, 99.2, 100.0)  # a later session has a bar, the entry candle does not
    later = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[2])
    assert later.status == "unmeasurable" and "entry" in later.note


def test_a_missing_candle_inside_the_window_is_pending_on_the_as_of_session():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(2)  # sessions 1 and 2 are there, session 3 is not yet (as_of is session 3)
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[3])
    assert result.status == "pending" and result.entry_price == 100.0


def test_a_bar_after_as_of_never_turns_a_missing_candle_into_unmeasurable():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(5)
    del bars[SESSIONS[3]]  # session 3 missing; sessions 4 and 5 exist but are after as_of
    assert evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[3]).status == "pending"
    assert evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[4]).status == "unmeasurable"


def test_a_missing_session_is_never_filled_from_the_next_bar_or_skipped():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(5)
    del bars[SESSIONS[3]]
    bars[SESSIONS[4]] = (100.0, 103.0, 100.0, 102.5)  # a target on session 4, after the gap
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[5])
    assert (result.status, result.label, result.exit_reason) == ("unmeasurable", None, None)


@pytest.mark.parametrize(
    "bad", [(0.0, 100.5, 99.5, 100.0), (100.0, 99.0, 100.0, 100.0), (float("nan"), 1.0, 1.0, 1.0)]
)
def test_a_present_but_impossible_candle_stays_unmeasurable_even_on_the_as_of_session(bad):
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(2)
    bars[SESSIONS[3]] = bad
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[3])
    assert result.status == "unmeasurable" and "unusable" in result.note


def test_when_the_late_candle_arrives_the_next_check_gives_the_true_result():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    only_input_day = {SESSIONS[0]: flat_bars(0)[SESSIONS[0]]}
    store.evaluate_due(SESSIONS, {"DEMO": only_input_day}, as_of=SESSIONS[1])  # entry candle not in yet
    assert store.evaluation_summary(5) == {"pending": 1} and store.labels(5) == {}
    arrived = flat_bars(5)
    arrived[SESSIONS[2]] = (101.0, 102.6, 100.6, 102.2)  # the 5D +2% target on session 2
    store.evaluate_due(SESSIONS, {"DEMO": arrived}, as_of=SESSIONS[5])
    (ev,) = store.evaluations(5)
    assert (ev.status, ev.exit_reason, ev.exit_session, ev.label) == ("complete", "target", SESSIONS[2], 1)
    assert store.labels(5) == {("DEMO", SIGNAL, "synthetic_h5", "v5.1"): 1}


def test_a_finished_result_is_not_rewritten_when_a_missing_candle_shows_up_later():
    store = HorizonStore()
    run_all_horizons(SIGNAL, [output(5)], SESSIONS, store, symbol="DEMO")
    gappy = flat_bars(5)
    del gappy[SESSIONS[3]]
    store.evaluate_due(SESSIONS, {"DEMO": gappy}, as_of=SESSIONS[5])
    assert store.evaluation_summary(5) == {"unmeasurable": 1}
    fixed = flat_bars(5)
    fixed[SESSIONS[3]] = (100.0, 103.0, 100.0, 102.5)  # the candle turns up, and would be a target
    store.evaluate_due(SESSIONS, {"DEMO": fixed}, as_of=SESSIONS[5])
    assert store.evaluation_summary(5) == {"unmeasurable": 1} and store.labels(5) == {}


# ---------------------------------------------------------------- separate history per horizon


def test_history_labels_and_evaluations_are_kept_per_horizon():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    store.evaluate_due(SESSIONS, {"DEMO": flat_bars(5)}, as_of=SESSIONS[5])

    assert store.labels(5) == {("DEMO", SIGNAL, "synthetic_h5", "v5.1"): 0}
    assert store.labels(10) == {}
    assert store.labels(15) == {}
    assert store.evaluation_summary(5) == {"complete": 1}
    assert store.evaluation_summary(10) == {"pending": 1}
    assert store.evaluation_summary(15) == {"pending": 1}

    store.evaluate_due(SESSIONS, {"DEMO": flat_bars(15)}, as_of=SESSIONS[15])
    assert set(store.labels(10)) == {("DEMO", SIGNAL, "synthetic_h10", "v10.1")}
    assert set(store.labels(15)) == {("DEMO", SIGNAL, "synthetic_h15", "v15.1")}


def test_rerunning_one_horizon_does_not_touch_the_others():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    store.add(run_horizon(5, [replace(output(5), model_version="v5.2")], SIGNAL, SESSIONS))
    assert [r.model_version for r in store.runs(5)] == ["v5.1", "v5.2"]
    assert len(store.runs(10)) == len(store.runs(15)) == 1


def test_store_refuses_a_record_filed_under_the_wrong_horizon():
    store = HorizonStore()
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    with pytest.raises(ValueError, match="horizon"):
        store.add(replace(record, decision_horizon=7))


def test_records_are_returned_as_copies_of_the_history():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    store.runs(5).clear()
    assert len(store.runs(5)) == 1


# ---------------------------------------------------------------- parity + purity


def test_policies_match_the_pinned_lane_and_h05_rules():
    from swing_trade_ml.brain.lanes import h05_protocol
    from swing_trade_ml.services.lane_slots import RULES_VIEW

    p5 = DEFAULT_POLICIES[5]
    assert (p5.target_pct, p5.stop_pct, p5.max_sessions) == (
        h05_protocol.TRADE_TARGET,
        h05_protocol.TRADE_STOP,
        h05_protocol.TRADE_SESSIONS,
    )
    for h in (10, 15):
        p = DEFAULT_POLICIES[h]
        assert {"target": p.target_pct, "stop": p.stop_pct, "half_out": p.half_out_pct} == RULES_VIEW[h]
        assert p.max_sessions == h


def test_package_imports_no_database_broker_or_order_code():
    pkg = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml" / "brain" / "horizons"
    allowed = ("swing_trade_ml.brain.horizons",)
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                if name.startswith("swing_trade_ml"):
                    assert name.startswith(allowed), f"{path.name} imports {name}"
                assert not name.startswith(("sqlalchemy", "kiteconnect", "redis")), (
                    f"{path.name} imports {name}"
                )


# ---------------------------------------------------------------- Codex round 1 (#387)


def test_time_exit_is_the_session_the_supplied_calendar_completed_on_never_beyond_as_of():
    """The record was made on a calendar without a Saturday session; the evaluating calendar has one."""
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    saturday = date(2026, 1, 3)
    with_saturday = tuple(sorted((*SESSIONS, saturday)))
    bars = dict.fromkeys(with_saturday, (100.0, 100.9, 99.2, 100.0))
    fifth = with_saturday[with_saturday.index(SIGNAL) + 5]
    assert fifth != record.evaluation_due_session  # the stored due date is a different day
    result = evaluate_record(record, with_saturday, bars, as_of=fifth)
    assert (result.status, result.exit_reason) == ("complete", "time")
    assert result.exit_session == fifth
    assert result.exit_session <= fifth


def test_labels_for_two_models_with_the_same_version_name_do_not_overwrite_each_other():
    store = HorizonStore()
    first = replace(output(5), model_name="model_a", model_version="v1")
    second = replace(output(5), model_name="model_b", model_version="v1")
    for out in (first, second):
        store.add(run_horizon(5, [out], SIGNAL, SESSIONS))
    bars = flat_bars(5)
    bars[SESSIONS[2]] = (100.0, 100.9, 99.2, 100.0)
    store.evaluate_due(SESSIONS, {"DEMO": bars}, as_of=SESSIONS[5])
    assert len(store.labels(5)) == 2
    assert {key[2:] for key in store.labels(5)} == {("model_a", "v1"), ("model_b", "v1")}


@pytest.mark.parametrize("slot", [1, 2])  # 1 = high, 2 = low
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 0.0, -1.0])
def test_a_candle_with_an_unusable_high_or_low_is_unmeasurable_never_a_time_exit(slot, bad):
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    bars = flat_bars(5)
    day = list(bars[SESSIONS[3]])
    day[slot] = bad
    bars[SESSIONS[3]] = tuple(day)
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[5])
    assert result.status == "unmeasurable"
    assert result.label is None and result.exit_reason is None
    assert "session 3" in result.note


def test_run_all_horizons_stores_the_given_symbol_when_there_is_no_output():
    store = HorizonStore()
    results = run_all_horizons(SIGNAL, [], SESSIONS, store, symbol="ABC")
    assert {r.symbol for r in results.values()} == {"ABC"}
    assert all(r.decision == NO_DECISION for r in results.values())
    assert {r.symbol for h in (5, 10, 15) for r in store.runs(h)} == {"ABC"}


def test_run_all_horizons_needs_an_explicit_symbol():
    with pytest.raises(TypeError):
        run_all_horizons(SIGNAL, [], SESSIONS, HorizonStore())  # type: ignore[call-arg]


def test_run_horizon_with_no_output_and_no_symbol_is_an_error_not_a_demo_stock():
    with pytest.raises(ValueError, match="symbol"):
        run_horizon(5, [], SIGNAL, SESSIONS)


# ---------------------------------------------------------------- Codex round 3 (#387)


def test_a_misrouted_output_for_another_stock_is_refused_not_stored_under_that_stock():
    store = HorizonStore()
    wrong = replace(output(5), symbol="ABC")
    results = run_all_horizons(SIGNAL, [wrong], SESSIONS, store, symbol="XYZ")
    assert {r.symbol for r in results.values()} == {"XYZ"}
    assert all(r.decision == NO_DECISION for r in results.values())
    assert all("ABC" in r.reason and "XYZ" in r.reason for r in results.values())
    assert {r.symbol for h in (5, 10, 15) for r in store.runs(h)} == {"XYZ"}


def test_run_horizon_with_a_matching_symbol_still_decides():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS, symbol="DEMO")
    assert (record.symbol, record.decision) == ("DEMO", "TRADE")


def test_a_rerun_never_changes_the_label_already_exposed_for_a_completed_run():
    store = HorizonStore()
    store.add(run_horizon(5, [output(5)], SIGNAL, SESSIONS))
    quiet = flat_bars(5)
    store.evaluate_due(SESSIONS, {"DEMO": quiet}, as_of=SESSIONS[5])
    key = ("DEMO", SIGNAL, "synthetic_h5", "v5.1")
    assert store.labels(5) == {key: 0}  # a time exit
    # the same model, stock and session is run again, and a corrected candle now touches the +2% target
    store.add(run_horizon(5, [output(5)], SIGNAL, SESSIONS))
    corrected = flat_bars(5)
    corrected[SESSIONS[2]] = (100.0, 103.0, 99.5, 102.0)
    store.evaluate_due(SESSIONS, {"DEMO": corrected}, as_of=SESSIONS[5])
    assert store.labels(5) == {key: 0}  # the first, finished result stays
    first, second = store.evaluations(5)
    assert (first.exit_reason, first.label) == ("time", 0)
    assert (second.exit_reason, second.label) == ("target", 1)  # the rerun is kept as its own record


def test_a_session_high_that_equals_the_target_exactly_is_a_hit_despite_float_rounding():
    record = run_horizon(15, [output(15)], SIGNAL, SESSIONS)  # +8% target
    bars = flat_bars(15)
    bars[SESSIONS[1]] = (110.0, 110.0, 109.0, 110.0)  # entry open 110.0
    assert 110.0 * (1 + 0.08) != 118.8  # the product is 118.80000000000001
    bars[SESSIONS[2]] = (110.0, 118.8, 109.5, 118.0)
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[2])
    assert (result.status, result.exit_reason, result.label) == ("complete", "target", 1)


def test_a_session_low_that_equals_the_stop_exactly_is_a_stop_despite_float_rounding():
    record = run_horizon(15, [output(15)], SIGNAL, SESSIONS)  # -4% stop
    bars = flat_bars(15)
    entry = 110.0
    stop = round(entry * (1 - 0.04), 2)  # 105.6, what a price tick shows
    bars[SESSIONS[1]] = (entry, entry + 0.5, entry - 0.5, entry)
    bars[SESSIONS[2]] = (entry, entry, stop, entry)
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[2])
    assert (result.status, result.exit_reason, result.label) == ("complete", "stop", 0)


def test_a_price_a_whole_tick_short_of_the_target_is_not_a_hit():
    record = run_horizon(15, [output(15)], SIGNAL, SESSIONS)
    bars = flat_bars(15)
    bars[SESSIONS[1]] = (110.0, 110.5, 109.5, 110.0)
    bars[SESSIONS[2]] = (110.0, 118.75, 109.5, 118.0)  # 5 paise short of 118.80
    result = evaluate_record(record, SESSIONS, bars, as_of=SESSIONS[2])
    assert result.status == "pending"


# ---------------------------------------------------------------- Codex round 7 (#387)


def test_a_calendar_that_ends_at_as_of_leaves_the_record_pending_not_unmeasurable():
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    short = SESSIONS[:2]  # the calendar the job could build when only session 1 has closed
    result = evaluate_record(record, short, flat_bars(1), as_of=SESSIONS[1])
    assert result.status == "pending"
    assert result.label is None


def test_a_store_does_not_skip_a_record_forever_after_a_short_calendar():
    store = HorizonStore()
    store.add(run_horizon(5, [output(5)], SIGNAL, SESSIONS))
    store.evaluate_due(SESSIONS[:2], {"DEMO": flat_bars(1)}, as_of=SESSIONS[1])
    assert store.evaluation_summary(5) == {"pending": 1}
    store.evaluate_due(SESSIONS, {"DEMO": flat_bars(5)}, as_of=SESSIONS[5])
    assert store.evaluation_summary(5) == {"complete": 1}
    assert len(store.labels(5)) == 1


@pytest.mark.parametrize(
    "bar",
    [
        (100.0, 95.0, 94.0, 94.5),  # open above the high
        (100.0, 101.0, 100.5, 100.8),  # open below the low
        (100.0, 101.0, 99.0, 102.0),  # close above the high
        (100.0, 101.0, 99.0, 98.0),  # close below the low
        (100.0, 101.0, 99.0, float("nan")),  # unusable close
    ],
)
def test_a_candle_that_contradicts_itself_is_unmeasurable_on_the_entry_session_and_inside_the_window(bar):
    record = run_horizon(5, [output(5)], SIGNAL, SESSIONS)
    entry = flat_bars(5)
    entry[SESSIONS[1]] = bar
    result = evaluate_record(record, SESSIONS, entry, as_of=SESSIONS[5])
    assert result.status == "unmeasurable" and result.label is None
    inside = flat_bars(5)
    inside[SESSIONS[3]] = bar
    result = evaluate_record(record, SESSIONS, inside, as_of=SESSIONS[5])
    assert result.status == "unmeasurable" and result.label is None
    assert "session 3" in result.note


# ---------------------------------------------------------------- a rerun is kept but counted once


def test_the_same_run_twice_is_kept_in_the_history_but_counted_once():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    store.evaluate_due(SESSIONS, {"DEMO": flat_bars(15)}, as_of=SESSIONS[15])

    for h in (5, 10, 15):
        assert len(store.runs(h)) == 2 and len(store.evaluations(h)) == 2  # append-only history
        assert len(store.labels(h)) == 1
        assert store.evaluation_summary(h) == {"complete": 1}
        assert sum(store.evaluation_summary(h).values()) == len(store.labels(h))


def test_a_rerun_before_the_result_is_counted_once_as_pending():
    store = HorizonStore()
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    run_all_horizons(SIGNAL, three_outputs(), SESSIONS, store, symbol="DEMO")
    assert store.evaluation_summary(5) == {"pending": 1}


def test_no_decision_records_rerun_are_counted_once():
    store = HorizonStore()
    for _ in range(2):
        run_all_horizons(SIGNAL, [], SESSIONS, store, symbol="DEMO")
    store.evaluate_due(SESSIONS, {}, as_of=SESSIONS[15])
    assert len(store.runs(5)) == 2
    assert store.evaluation_summary(5) == {"no_decision": 1}


def test_a_different_model_version_is_its_own_count():
    store = HorizonStore()
    store.add(run_horizon(5, [output(5)], SIGNAL, SESSIONS))
    newer = replace(output(5), model_version="v5.2")
    store.add(run_horizon(5, [newer], SIGNAL, SESSIONS))
    store.evaluate_due(SESSIONS, {"DEMO": flat_bars(5)}, as_of=SESSIONS[5])
    assert store.evaluation_summary(5) == {"complete": 2}
    assert len(store.labels(5)) == 2


def test_a_later_completed_rerun_is_counted_complete_when_the_first_was_unmeasurable():
    store = HorizonStore()
    store.add(run_horizon(5, [output(5)], SIGNAL, SESSIONS))
    gappy = flat_bars(5)
    del gappy[SESSIONS[3]]
    store.evaluate_due(SESSIONS, {"DEMO": gappy}, as_of=SESSIONS[5])
    store.add(run_horizon(5, [output(5)], SIGNAL, SESSIONS))
    store.evaluate_due(SESSIONS, {"DEMO": flat_bars(5)}, as_of=SESSIONS[5])
    assert len(store.labels(5)) == 1
    assert store.evaluation_summary(5) == {"complete": 1}  # one key, one count, as labels() has it
