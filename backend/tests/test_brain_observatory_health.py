"""R1, R2, C4 and spec 3.2: per-module health from stored records only; flags independent, conflicts
explicit, historical module lists respected, run status respected."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.services.brain_observatory import health

STEP_MAP = {"M01": "perceive", "M06": "reason", "M07": "risk", "M08": "decide", "M09": "learn"}


def line(mid, status, step="perceive", reason=""):
    return {"step": step, "module_id": mid, "status": status, "reason": reason, "ms": 5, "version": "1"}


def row(rows, mid):
    return next(r for r in rows if r["module_id"] == mid)


def test_flags_are_independent():
    rows = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used")], STEP_MAP)
    f = row(rows, "M01")["flags"]
    assert f["executed"] and f["valid_output"] and f["used"] and f["expected"]
    assert not (f["failed"] or f["shadow"] or f["switched_off"] or f["not_observed"])


def test_executed_never_implies_used():
    trace = [line("M06", "shadow", "reason"), line("M01", "fallback", reason="error: x")]
    rows = health.module_rows("nightly", {"M06": "shadow", "M01": "on"}, trace, STEP_MAP)
    assert row(rows, "M06")["flags"]["executed"] and not row(rows, "M06")["flags"]["used"]
    m01 = row(rows, "M01")
    assert m01["flags"]["executed"] and m01["flags"]["failed"] and not m01["flags"]["used"]
    assert m01["failure_messages"] == ["error: x"]


def test_counts_are_per_flag():
    trace = [line("M01", "used"), line("M06", "shadow", "reason")]
    rows = health.module_rows("nightly", {"M01": "on", "M06": "shadow"}, trace, STEP_MAP)
    c = health.flag_counts(rows)
    assert c["executed"] == 2 and c["valid_output"] == 2 and c["used"] == 1 and c["shadow"] == 1


def test_single_source_is_not_a_conflict():
    rows = health.module_rows("nightly", {}, [line("M01", "used")], STEP_MAP)
    assert row(rows, "M01")["corroboration"] == "single_source"
    assert not row(rows, "M01")["flags"]["conflicting"]


def test_listed_module_without_a_line_is_not_observed():
    rows = health.module_rows("nightly", {"M08": "on"}, [], STEP_MAP)
    r = row(rows, "M08")
    assert r["flags"]["not_observed"] and r["inferred"]["not_observed"]
    assert r["corroboration"] == "single_source"


def test_module_added_after_the_run_is_not_missing():
    rows = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used")], STEP_MAP)
    r = row(rows, "M08")
    assert r["flags"]["not_installed_then"] and not r["flags"]["not_observed"] and not r["flags"]["expected"]
    assert r["corroboration"] == "not_installed"


def test_run_without_a_module_list_is_unknown_not_missing():
    rows = health.module_rows("nightly", {}, [], STEP_MAP)
    r = row(rows, "M08")
    assert r["flags"]["unknown"] and not r["flags"]["not_observed"] and r["corroboration"] == "no_record"
    assert r["step_source"] == "current code (inferred)"


def test_disagreeing_sources_conflict():
    rows = health.module_rows("nightly", {"M01": "off"}, [line("M01", "used")], STEP_MAP)
    r = row(rows, "M01")
    assert r["corroboration"] == "conflicting" and r["flags"]["conflicting"]
    assert "mode 'off'" in r["conflicts"][0]


def test_identical_repeated_lines_are_duplicate_not_conflict():
    rows = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used"), line("M01", "used")], STEP_MAP)
    r = row(rows, "M01")
    assert r["flags"]["duplicate"] and not r["flags"]["conflicting"]


def test_different_repeated_lines_conflict():
    trace = [line("M01", "used"), line("M01", "fallback")]
    rows = health.module_rows("nightly", {"M01": "on"}, trace, STEP_MAP)
    assert row(rows, "M01")["flags"]["conflicting"]


def test_switched_off_is_corroborated_when_both_say_off():
    trace = [line("M01", "skipped", reason="switched off")]
    rows = health.module_rows("nightly", {"M01": "off"}, trace, STEP_MAP)
    r = row(rows, "M01")
    assert r["flags"]["switched_off"] and not r["flags"]["expected"] and r["corroboration"] == "corroborated"


def test_not_applicable_for_the_run_kind():
    rows = health.module_rows("intraday", {"M09": "on"}, [], STEP_MAP)
    r = row(rows, "M09")
    assert r["flags"]["not_applicable"] and not r["flags"]["not_observed"]


def test_unknown_module_is_flagged():
    rows = health.module_rows("nightly", {"M99": "on"}, [line("M99", "used")], STEP_MAP)
    assert row(rows, "M99")["flags"]["unknown_module"]


def test_empty_modules_and_trace_do_not_crash():
    rows = health.module_rows("nightly", None, None, STEP_MAP)
    assert {r["module_id"] for r in rows} == set(STEP_MAP)


def test_recorded_lines_of_a_running_run_are_not_hidden():
    rows = health.module_rows("nightly", {}, [line("M01", "used")], STEP_MAP)
    assert row(rows, "M01")["flags"]["executed"]
    assert health.headline("running", rows, []) == "running"


def test_step_fallbacks_listed():
    assert health.step_fallbacks([line("fallback", "fallback", "decide", "no module answered")]) == [
        {"step": "decide", "reason": "no module answered"}
    ]


def test_headline():
    ok = health.module_rows("nightly", {"M01": "on"}, [line("M01", "used")], {"M01": "perceive"})
    assert health.headline("done", ok, []) == "completed"
    assert health.headline("done", ok, [{"step": "decide", "reason": "x"}]) == "degraded"
    assert health.headline("failed", ok, []) == "failed"


def test_m16_m17_m18_rows():
    stamp = datetime(2026, 10, 15, 10, 22, tzinfo=UTC)
    rows = {r["module_id"]: r for r in health.outside_rows("intraday", True, "done", stamp, 0)}
    assert rows["M16"]["state"] == "executed" and "0 alerts" in rows["M16"]["detail"]
    rows = {r["module_id"]: r for r in health.outside_rows("nightly", True, "done", None, 0)}
    assert rows["M16"]["state"] == "unknown"
    rows = {r["module_id"]: r for r in health.outside_rows("why", True, "done", None, 0)}
    assert rows["M16"]["state"] == "not_applicable"
    assert rows["M17"]["state"] == "not_applicable" and rows["M18"]["state"] == "not_applicable"


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("queued", "not_started"),
        ("running", "in_progress"),
        ("failed", "executed_failed"),
        ("done", "executed"),
        ("superseded", "executed"),
        ("weird", "unknown"),
    ],
)
def test_m00_follows_the_run_status(status, state):
    rows = {r["module_id"]: r for r in health.outside_rows("nightly", True, status, None, 0)}
    assert rows["M00"]["state"] == state
    if status in ("queued", "running", "failed"):
        assert rows["M16"]["state"] == "not_applicable"


def test_alerting_kinds_mirror_the_alert_service():
    from swing_trade_ml.brain.alerts.service import ALERTING_KINDS

    assert frozenset(ALERTING_KINDS) == health.ALERTING_KINDS


def test_current_step_map_reads_the_registry():
    m = health.current_step_map()
    assert m["M08"] == "decide" and m["M07"] == "risk"
