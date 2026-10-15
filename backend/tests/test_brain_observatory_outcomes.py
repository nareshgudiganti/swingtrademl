"""R4, spec 13, evidence plan A3, plan C2/C6/C7/C10: one function, category required and never mixed;
every figure says where it comes from; missing data says 'not available' and why; matched baselines are
evidence-defs-v1 (services/brain_observatory/baselines.trade_level)."""

# ruff: noqa: F811 — `realistic_cohort` is imported as a pytest fixture, then used as an argument
from __future__ import annotations

import time as _time
from datetime import UTC, date, datetime

import pytest

from observatory_fixtures import (  # noqa: F401 — realistic_cohort is a pytest fixture
    count_statements,
    make_decision,
    make_run,
    nightly_as_of,
    realistic_cohort,
    trading_days,
)
from swing_trade_ml.services.brain_observatory import outcomes as o
from swing_trade_ml.services.brain_observatory import queries

COMPARISONS = ("candidate", "every_stock", "random_5", "momentum_5", "nifty_matched")


def test_stored_grades_are_labelled_gross():
    g = o.stored_grades([("target", 0.08), ("stop", -0.04), ("timeout", 0.01)])
    assert g["count"] == 3 and g["by_outcome"] == {"target": 1, "stop": 1, "timeout": 1}
    assert abs(g["avg_gross_return"] - (0.05 / 3)) < 1e-12
    assert "no costs" in g["source"].lower() and g["gross"] is True


def test_no_stored_grades_is_not_zero():
    g = o.stored_grades([])
    assert g["available"] is False and g["avg_gross_return"] is None and g["why"]


def test_sources_name_their_code():
    assert "m09_learn/outcomes.py" in o.SOURCES["stored_grade"]
    assert "services/costs.py" in o.SOURCES["costs"] and "bx5" in o.SOURCES["costs"]
    assert "evidence-defs-v1" in o.SOURCES["nifty_matched"] and "per idea" in o.SOURCES["nifty_matched"]
    assert "computed now" in o.SOURCES["net_after_costs"].lower()


def test_category_is_required_and_validated(db_session):
    assert o.CATEGORIES == ("practice", "backtest", "paper")
    with pytest.raises(ValueError):
        o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "everything")
    paper = o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "paper")
    assert paper["category"] == "paper" and paper["available"] is False and paper["why"]
    assert paper["label"] == "Observed, not proof"


def test_categories_are_never_summed(monkeypatch, db_session):
    seen = []
    monkeypatch.setattr(queries, "stored_grade_rows", lambda db, s, e, live: seen.append(live) or [])
    a = o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "practice")
    b = o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "backtest")
    assert seen == [True, False]
    assert a["category"] == "practice" and b["category"] == "backtest"
    for r in (a, b):
        assert r["label"] == "Observed, not proof" and r["computed"]["defs"] == "evidence-defs-v1"


def test_empty_range_is_unavailable_not_zero(db_session):
    out = o.build(db_session, date(2030, 1, 1), date(2030, 1, 31), "practice")
    c = out["computed"]
    for key in COMPARISONS:
        assert c[key]["available"] is False and c[key]["why"], key
    assert out["stored_grades"]["available"] is False
    assert c["cash"]["available"] is True and c["cash"]["avg_net"] == 0.0


def test_journal_failure_is_honest(monkeypatch, db_session):
    def boom(*_a, **_k):
        raise RuntimeError("no candles at postgresql://user:hunter2@db.example.com/x")

    row = ("target", 0.08, nightly_as_of(date(2026, 10, 14)), "paper")
    monkeypatch.setattr(queries, "daily_bars", boom)
    monkeypatch.setattr(queries, "stored_grade_rows", lambda db, s, e, live: [row])
    monkeypatch.setattr(
        queries,
        "nightly_sessions",
        lambda *a, **k: [
            __import__("swing_trade_ml.brain.trial_journal", fromlist=["x"]).Session(
                date(2026, 10, 14), None, ()
            )
        ],
    )
    out = o.build(db_session, date(2026, 10, 14), date(2026, 10, 15), "practice")
    assert out["stored_grades"]["available"] is True  # the stored record still shows
    for key in COMPARISONS:
        assert out["computed"][key]["available"] is False
        assert "no candles" in out["computed"][key]["why"] and "hunter2" not in out["computed"][key]["why"]


def test_forward_gate_failure_is_honest(monkeypatch, db_session):
    def boom(*_a, **_k):
        raise RuntimeError("no candles")

    monkeypatch.setattr(queries, "nightly_sessions", boom)
    g = o.official_forward_gate(db_session, date(2026, 10, 20))
    assert g["word"] == "Insufficient evidence" and "no candles" in g["why"] and g["gate"] is None


def test_forward_gate_never_says_proven():
    assert o.forward_word({"word": "pass", "sessions": 20}) == "Forward gate (not frozen): pass"
    for w in ("too early", "pass", "behind"):
        assert o.forward_word({"word": w}) != "Proven"


def test_stage_on_day_fails_closed_to_shadow():
    assert o.stage_on_day([], date(2026, 10, 14)) == "shadow"
    h = [(datetime(2026, 10, 14, 4, 0, tzinfo=UTC), "approval")]  # 09:30 IST on the 14th
    assert o.stage_on_day(h, date(2026, 10, 13)) == "shadow"
    assert o.stage_on_day(h, date(2026, 10, 14)) == "approval"


# --- sized like production (plan C7) -----------------------------------------------------------------


def test_sessions_loader_equals_the_trial_journal(db_session, realistic_cohort):
    from swing_trade_ml.brain.trial_journal import load_sessions

    start, end = realistic_cohort.start, realistic_cohort.today
    mine = queries.nightly_sessions(db_session, start, end, live=True, book="paper")
    assert len(mine) == len(realistic_cohort.days) > 40
    assert mine == load_sessions(db_session, start, end, live=True)


def test_bounded_bars_give_the_same_journal(db_session, realistic_cohort):
    from swing_trade_ml.brain.trial_journal import journal_for

    start, end = realistic_cohort.start, realistic_cohort.today
    mine, _ctx, err = o._journal(db_session, start, end, live=True, book="paper", stage_filter=None)
    assert err is None
    official = journal_for(db_session, start, end)
    for name in ("brain_trade", "every_stock", "nifty"):
        assert mine["summaries"][name] == official["summaries"][name], name
    assert mine["summaries"]["brain_trade"]["ideas"] > 20  # finished ideas, so the check is not vacuous


def test_forward_gate_ignores_the_page_range(db_session, realistic_cohort):
    today = realistic_cohort.today
    a = o.official_forward_gate(db_session, today)
    o.build(db_session, realistic_cohort.days[10], realistic_cohort.days[20], "practice")  # any page range
    b = o.official_forward_gate(db_session, today)
    assert a == b and a["cohort_from"] == "2026-10-14" and a["cohort_to"] == today.isoformat()
    assert set(a) >= {"word", "why", "cohort_from", "cohort_to", "cohort", "gate"}


def test_forward_gate_equals_the_trial_journal(db_session, realistic_cohort):
    from swing_trade_ml.brain.trial_journal import TRIAL_START, journal_for

    official = journal_for(db_session, TRIAL_START, realistic_cohort.today)["gate"]
    got = o.official_forward_gate(db_session, realistic_cohort.today)
    assert got["gate"] == official
    assert got["gate"]["finished"] > 20 and got["word"] != "Proven"


def test_practice_uses_evidence_defs_v1_baselines(db_session, realistic_cohort):
    out = o.build(db_session, realistic_cohort.start, realistic_cohort.today, "practice")
    c = out["computed"]
    assert out["available"] is True and c["defs"] == "evidence-defs-v1"
    assert out["label"] == "Observed, not proof" and "evidence-defs-v1" in out["note"]
    for key in COMPARISONS:
        assert c[key]["available"] is True and c[key]["source"], key
    assert c["candidate"]["finished"] > 20
    assert c["random_5"]["draws"] > 0
    assert c["cash"]["avg_net"] == 0.0
    assert out["excluded"] == {"other_stage_days": 0, "other_book_runs": 0}


def test_live_book_and_approval_days_are_excluded_not_mixed(db_session, realistic_cohort):
    realistic_cohort.add_live_book_run(db_session)
    realistic_cohort.add_stage_change(db_session, "approval", realistic_cohort.days[5])
    out = o.build(db_session, realistic_cohort.start, realistic_cohort.today, "practice")
    assert out["excluded"]["other_stage_days"] == len(realistic_cohort.days) - 5
    assert out["excluded"]["other_book_runs"] == 1
    # the forward gate is the established cohort: it does not apply the stage filter
    gate = o.official_forward_gate(db_session, realistic_cohort.today)["gate"]
    assert gate["sessions"] == len(realistic_cohort.days)


def test_backtest_reads_replays_only(db_session):
    days = trading_days(date(2026, 8, 3), date(2026, 8, 14))
    for k, d in enumerate(days):
        db_session.add(make_run(f"bt{k}", as_of=nightly_as_of(d), live=False))
    db_session.flush()
    for k in range(len(days)):
        db_session.add(
            make_decision(f"bt{k}", "ZZNOPRICE", word="WAIT", outcome="target", outcome_return=0.08)
        )
    db_session.flush()
    back = o.build(db_session, days[0], days[-1], "backtest")
    assert back["category"] == "backtest" and back["stored_grades"]["count"] == len(days)
    assert back["stored_grades"]["gross"] is True
    practice = o.build(db_session, days[0], days[-1], "practice")
    assert practice["stored_grades"]["available"] is False


def test_outcomes_processing_is_bounded(db_session, realistic_cohort):
    counter = count_statements(db_session)
    t0 = _time.perf_counter()
    o.build(db_session, realistic_cohort.start, realistic_cohort.today, "practice")
    o.official_forward_gate(db_session, realistic_cohort.today)
    assert counter.n <= 12, counter.n
    assert counter.control <= 6, counter.control
    # Wall-clock is only a guard against a real blow-up (per-day queries would take minutes). The 1,000 random
    # draws of evidence-defs-v1 are CPU work (about 5 s on a busy dev machine), so the deterministic bound is
    # the statement count above, not this.
    assert _time.perf_counter() - t0 < 12.0


def test_the_computed_shape_is_what_the_page_reads():
    """The page (frontend/src/trademind/pages/Observatory.tsx, FIGURES + edge) reads exactly these keys; a
    mismatch once blanked the whole page, so the contract is pinned here."""
    from pathlib import Path

    from swing_trade_ml.services.brain_observatory import outcomes as o

    shape = o._unavailable_all("pinned")
    for key in (
        "candidate",
        "every_stock",
        "random_5",
        "momentum_5",
        "nifty_matched",
        "cash",
        "edge",
        "costs",
    ):
        assert key in shape, key
    page = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "trademind" / "pages" / "Observatory.tsx"
    ).read_text(encoding="utf-8")
    for key in ("candidate", "every_stock", "random_5", "momentum_5", "nifty_matched", "cash"):
        assert f"['{key}'," in page, f"the page does not read '{key}'"
    assert "brain_trade" not in page and "'nifty'" not in page


# --- review finding 2: a real database error must not poison the rest of the request ---------------


def test_a_real_sql_error_inside_the_journal_is_not_a_500(db_session, monkeypatch):
    from sqlalchemy import text

    def bad_bars(db, *_a, **_k):
        db.execute(text("SELECT 1 / 0"))  # a real Postgres error, which aborts the transaction

    monkeypatch.setattr(o.queries, "daily_bars", bad_bars)
    out = o.build(db_session, date(2026, 10, 1), date(2026, 10, 15), "practice")
    assert out["computed"]["candidate"]["available"] is False
    assert "division by zero" in out["computed"]["candidate"]["why"].lower()
    assert isinstance(out["excluded"]["other_book_runs"], int)  # a later statement still ran
    assert out["stored_grades"]["available"] is False  # and the stored grades were still read


# --- review finding 3: stored grades are shown by word, TRADE apart ---------------------------------


def test_stored_grades_are_broken_down_by_word_with_trade_apart():
    rows = [
        ("target", 0.08, None, "paper", "TRADE"),
        ("stop", -0.04, None, "paper", "TRADE"),
        ("timeout", 0.01, None, "paper", "AVOID"),
        ("timeout", 0.02, None, "paper", "WAIT"),
    ]
    g = o.stored_grades(rows)
    assert g["count"] == 4 and g["all_words_note"]
    assert g["by_word"]["TRADE"]["count"] == 2
    assert g["by_word"]["TRADE"]["avg_gross_return"] == pytest.approx(0.02)
    assert g["by_word"]["AVOID"]["count"] == 1
    assert g["trade"]["count"] == 2 and g["trade"]["avg_gross_return"] == pytest.approx(0.02)


def test_no_trade_grades_is_unavailable_not_zero():
    g = o.stored_grades([("timeout", 0.01, None, "paper", "AVOID")])
    assert g["trade"]["available"] is False and g["trade"]["avg_gross_return"] is None
