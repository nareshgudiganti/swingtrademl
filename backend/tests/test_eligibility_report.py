# ruff: noqa: N812
"""Weekly training-eligibility report: pure verdict logic, no database, no git, no clock."""

from __future__ import annotations

from datetime import date, timedelta

from swing_trade_ml.brain import eligibility_report as E


def _day(i: int) -> date:
    return date(2026, 11, 2) + timedelta(days=i)


def _rows(group: str, day: date, *, eligible: int = 12, picks: int = 5, trade: str = "expiry", repeat=0):
    out = []
    for k in range(eligible):
        out.append(
            {
                "group": group,
                "signal_day": day,
                "status": "scored",
                "selected": k < picks,
                "repeat_blocked": k < repeat,
                "trade_status": trade if k < picks else "expiry",
                "label_status": "evaluated",
            }
        )
    return out


def test_matured_day_needs_10_eligible_and_a_finished_counted_pick():
    rows = _rows("large", _day(0)) + _rows("large", _day(1), eligible=9)  # too few eligible
    rows += _rows("large", _day(2), trade="pending")  # nothing finished yet
    rows += _rows("large", _day(3), picks=5, repeat=5)  # all picks are repeats: none counted
    rows += _rows("mid", _day(4))  # other group
    c = E.count_h05_matured(rows, "large")
    assert c["matured_days"] == 1
    assert c["signal_days"] == 4
    assert c["counted_picks_matured"] == 5


def test_unresolved_is_not_matured_and_not_scored_rows_ignored():
    rows = _rows("small", _day(0), trade="unresolved")
    rows.append({**rows[0], "status": "not_scored", "signal_day": _day(1)})
    assert E.count_h05_matured(rows, "small")["matured_days"] == 0


def test_counts_never_touch_outcome_values():
    row = _rows("large", _day(0))[0]
    assert "net_return" not in row and "label_hit" not in row
    assert E.count_h05_matured([row] * 12, "large")["signal_days"] == 1


def _facts(**kw):
    base = {
        "h05_rows": [],
        "h05_enabled": True,
        "h05_accepted": True,
        "h05_run_started": True,
        "tags": set(),
        "amendment3_signed": False,
    }
    base.update(kw)
    return base


def _by_lane(report):
    return {x["lane"]: x for x in report["lanes"]}


def test_h05_is_observe_only_and_cites_forty_days():
    rows = []
    for i in range(41):
        rows += _rows("large", _day(i))
    r = _by_lane(E.build_report(date(2026, 11, 10), _facts(h05_rows=rows)))
    assert r["5D large"]["verdict"] == "OBSERVE_ONLY"
    assert r["5D large"]["matured"] == 41 and r["5D large"]["needed"] == 40
    assert r["5D large"]["evidence_met"] is True
    assert r["5D mid"]["matured"] == 0 and r["5D mid"]["evidence_met"] is False
    assert r["5D small"]["verdict"] == "OBSERVE_ONLY"
    assert "retrain" in r["5D large"]["note"].lower()


def test_h05_unmet_gates_are_listed_but_verdict_stays_observe_only():
    r = _by_lane(
        E.build_report(
            date(2026, 11, 10), _facts(h05_enabled=False, h05_accepted=False, h05_run_started=False)
        )
    )
    x = r["5D mid"]
    assert x["verdict"] == "OBSERVE_ONLY"
    assert x["blocking"] == ["h05 lane enabled", "protocol hash accepted by owner", "run 1 started"]


def test_h05_db_unavailable_says_unknown_not_zero():
    r = _by_lane(E.build_report(date(2026, 11, 10), _facts(h05_rows=None)))
    assert r["5D large"]["matured"] is None
    assert "unavailable" in r["5D large"]["note"].lower()


def test_10d_not_applicable():
    r = _by_lane(E.build_report(date(2026, 11, 10), _facts()))
    assert r["10D"]["verdict"] == "NOT_APPLICABLE"
    assert "deferred" in r["10D"]["note"].lower() and "no slot" in r["10D"]["note"].lower()


def test_15d_blocked_before_date_even_with_tags():
    f = _facts(tags={"phase-b-result", "sl-protocol-v1.1"}, amendment3_signed=True)
    r = _by_lane(E.build_report(date(2026, 12, 4), f))
    for lane in ("15D large", "15D mid"):
        assert r[lane]["verdict"] == "BLOCKED_BY_PROTOCOL"
        assert r[lane]["earliest_date"] == "2026-12-05"
        assert r[lane]["blocking"] == ["not before 2026-12-05 (IST)"]
        assert r[lane]["matured"] is None


def test_15d_blocked_without_tag_or_signature_then_eligible_not_authorised():
    r = _by_lane(E.build_report(date(2026, 12, 5), _facts()))
    b = r["15D large"]["blocking"]
    assert "annotated tag phase-b-result" in b
    assert "tag sl-protocol-v1.1" in b
    assert "Amendment 3 signed marker" in b
    assert r["15D large"]["verdict"] == "BLOCKED_BY_PROTOCOL"
    f = _facts(tags={"phase-b-result", "sl-protocol-v1.1"}, amendment3_signed=True)
    r = _by_lane(E.build_report(date(2026, 12, 5), f))
    assert r["15D large"]["verdict"] == "ELIGIBLE_NOT_AUTHORISED"
    assert r["15D mid"]["verdict"] == "ELIGIBLE_NOT_AUTHORISED"
    assert r["15D mid"]["blocking"] == []


def test_sx5_gates():
    r = _by_lane(E.build_report(date(2026, 12, 3), _facts()))
    assert r["SX5"]["verdict"] == "BLOCKED_BY_PROTOCOL"
    assert r["SX5"]["earliest_date"] == "2026-12-04"
    r = _by_lane(E.build_report(date(2026, 12, 4), _facts()))
    assert r["SX5"]["verdict"] == "ELIGIBLE_NOT_AUTHORISED"  # authorisation is never assumed
    assert "authorisation" in r["SX5"]["note"].lower()


def test_report_text_has_every_lane_and_verdict_and_no_outcome_words():
    rep = E.build_report(date(2026, 11, 10), _facts())
    text = E.render_text(rep)
    for lane in ("5D large", "5D mid", "5D small", "10D", "15D large", "15D mid", "SX5"):
        assert lane in text
    for w in ("hit rate", "win rate", "average return", "edge"):
        assert w not in text.lower()
    assert "trains nothing" in text.lower()
    assert {x["verdict"] for x in rep["lanes"]} <= set(E.VERDICTS)


def test_constants_match_the_code_they_mirror():
    import re
    from pathlib import Path

    from swing_trade_ml.brain import selection_lab_run as slr
    from swing_trade_ml.brain import selection_lab_start as sls
    from swing_trade_ml.brain.lanes import h05_protocol as proto
    from swing_trade_ml.brain.lanes import h05_report

    ev = proto.RUN_VALUES["min_evidence_per_group"]
    assert ev["matured_signal_days"] == E.H05_MIN_MATURED_DAYS
    assert ev["min_eligible_per_day"] == E.H05_MIN_ELIGIBLE
    assert E.H05_RESOLVED == h05_report.RESOLVED
    assert E.LAB_EARLIEST == sls.EARLIEST_START
    assert sls.PHASE_B_RESULT_TAG == "phase-b-result"
    assert slr.TAG == "sl-protocol-v1.1"
    assert E.AMENDMENT3_SIGNED_FILE == slr.AMENDMENT
    script = Path(__file__).resolve().parents[1] / "scripts" / "sx5_run.py"
    m = re.search(r"EARLIEST_REAL_DATE = date\((\d+), (\d+), (\d+)\)", script.read_text(encoding="utf-8"))
    assert date(*map(int, m.groups())) == E.SX5_EARLIEST
