# ruff: noqa: E501 (long test sentences)
# ruff: noqa: F811, F401 (imported fixtures)
# ruff: noqa: N812 (short P / L aliases, as in the h05 tests)
"""#263 completion gate: benchmark reasons, totals from group-day records, failures shown, and agreement with
the h05 report (#254's source) and the weekly report. Synthetic fixtures only; read-only.

DELIBERATE DIFFERENCES between the ledger and the two reports (each is asserted below, not hidden):
  * "completed" needs BOTH the 5th-session label and the shadow trade final. The h05 report counts the label and
    the trade separately, so a pick whose trade is final but whose label could not be evaluated is "finished"
    there and "missing" here.
  * The h05 report's "counted" picks leave out a repeat inside five sessions; the ledger lists it as "blocked".
  * The weekly report counts every SELECTED pick (blocked ones too) and its +2% hits include a blocked pick;
    the ledger gives "passed" only to completed picks.
"""

from __future__ import annotations

from datetime import date

from swing_trade_ml.brain.lanes import h05_report
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Signal
from swing_trade_ml.services import weekly_paper_report
from swing_trade_ml.shadow_lanes import outcome_ledger as L
from test_h05_service import SIGNAL, add_candle, add_stock, after, lane, make_run
from test_outcome_ledger import pick

RESOLVED = ("target", "stop", "expiry")


def group_day(db, run, day, group, selected_n, shortfall=0):
    db.add(
        H05GroupDay(
            run_id=run.id,
            signal_day=day,
            group=group,
            universe_n=10,
            scored_n=10,
            not_scored_n=0,
            selected_n=selected_n,
            shortfall=shortfall,
        )
    )
    db.flush()


def completed(db, run, day, symbol, group="large", rank=1, **kw):
    fields = {
        "label_status": "evaluated",
        "label_hit": 1,
        "label_close5": 103.0,
        "label_day5": after(day, 5),
        "trade_status": "target",
        "entry_day": after(day, 1),
        "exit_day": after(day, 2),
        "entry_fill": 100.0,
        "exit_fill": 102.0,
        "net_return": 0.0185,
        "costs_inr": 40.0,
        "exit_reason": "target",
    } | kw
    return pick(db, run, day, symbol, group=group, rank=rank, **fields)


# ------------------------------------------------------------------ gate 4: an empty benchmark says why


def test_a_completed_pick_without_a_nifty_window_says_why(db_session, lane):
    run = make_run(db_session, {})
    completed(db_session, run, SIGNAL, "NOBARS", rank=1)  # no NIFTY candles stored at all
    row = next(r for r in L.build(db_session)["rows"] if r["symbol"] == "NOBARS")
    assert row["status"] == "completed" and row["benchmark_return"] is None
    assert "not stored" in row["benchmark_reason"]

    nifty = add_stock(db_session, settings.BENCHMARK_INDEX_SYMBOL, price=200.0)  # stored up to the signal day only
    completed(db_session, run, SIGNAL, "NOEXIT", rank=2)
    rows = {r["symbol"]: r for r in L.build(db_session)["rows"] if r["kind"] == "pick"}
    assert rows["NOEXIT"]["benchmark_return"] is None
    assert after(SIGNAL, 1).isoformat() in rows["NOEXIT"]["benchmark_reason"]  # names the missing day

    completed(db_session, run, SIGNAL, "NODAYS", rank=3, entry_day=None, exit_day=None)
    add_candle(db_session, nifty, after(SIGNAL, 1), (200, 200, 200, 200))
    add_candle(db_session, nifty, after(SIGNAL, 2), (200, 212, 200, 210))
    rows = {r["symbol"]: r for r in L.build(db_session)["rows"] if r["kind"] == "pick"}
    assert "not recorded" in rows["NODAYS"]["benchmark_reason"]
    assert rows["NOEXIT"]["benchmark_return"] == 210 / 200 - 1 and rows["NOEXIT"]["benchmark_reason"] is None


def test_a_pick_whose_trade_has_not_finished_says_its_benchmark_waits_for_the_trade(db_session, lane):
    run = make_run(db_session, {})
    pick(db_session, run, SIGNAL, "WAIT", rank=1)
    row = next(r for r in L.build(db_session)["rows"] if r["symbol"] == "WAIT")
    assert row["benchmark_return"] is None and "not finished" in row["benchmark_reason"]


# ------------------------------------------------------------------ gate 7: totals start from the group-day records


def test_a_group_day_with_no_pick_rows_still_appears_and_reconciles_only_when_the_counts_agree(db_session, lane):
    run = make_run(db_session, {})
    d1 = SIGNAL
    group_day(db_session, run, d1, "large", selected_n=0, shortfall=5)  # honestly no picks that day
    group_day(db_session, run, d1, "mid", selected_n=3, shortfall=2)  # three recorded, only one pick row left
    pick(db_session, run, d1, "MID1", group="mid", rank=1)
    group_day(db_session, run, d1, "small", selected_n=2, shortfall=3)  # two recorded, every pick row lost
    pick(db_session, run, after(d1, 1), "NOREC", group="large", rank=1)  # a pick with no group-day record
    totals = {(t["signal_day"], t["group"]): t for t in L.build(db_session)["totals"]}
    large, mid, small = totals[(d1.isoformat(), "large")], totals[(d1.isoformat(), "mid")], totals[(d1.isoformat(), "small")]
    assert (large["picks"], large["recorded_selected"], large["reconciles"]) == (0, 0, True)
    assert large["shortfall"] == 5
    assert (mid["picks"], mid["recorded_selected"], mid["reconciles"]) == (1, 3, False)
    assert (small["picks"], small["recorded_selected"], small["reconciles"]) == (0, 2, False)
    norec = totals[(after(d1, 1).isoformat(), "large")]
    assert (norec["picks"], norec["recorded_selected"], norec["reconciles"]) == (1, None, False)


# ------------------------------------------------------------------ gate 8: failures and shortfalls are visible, never picks


def test_a_lane_stop_and_a_shortfall_are_shown_with_their_stored_reasons_and_are_not_picks(db_session, lane):
    run = make_run(db_session, {})
    group_day(db_session, run, SIGNAL, "large", selected_n=1, shortfall=4)
    pick(db_session, run, SIGNAL, "ONLY1", rank=1)
    for sym in ("OLD1", "OLD2"):
        db_session.add(
            H05Signal(run_id=run.id, signal_day=SIGNAL, symbol=sym, group="large", status="not_scored",
                      not_scored_reason="too little history", selected=False, repeat_blocked=False)
        )
    db_session.add(H05Event(run_id=run.id, signal_day=after(SIGNAL, 1), kind="lane_stopped_model_check",
                            detail="model 16: file hash is not the frozen one"))
    db_session.flush()
    out = L.build(db_session)
    stop = [e for e in out["events"] if e["kind"] == "lane_stopped_model_check"]
    assert len(stop) == 1 and "frozen one" in stop[0]["detail"] and stop[0]["signal_day"] == after(SIGNAL, 1).isoformat()
    entry = next(t for t in out["totals"] if t["group"] == "large" and t["signal_day"] == SIGNAL.isoformat())
    assert entry["shortfall"] == 4 and entry["not_scored_reasons"] == {"too little history": 2}
    assert entry["picks"] == 1 and sum(out["counts"].values()) == 1  # neither the event nor a not-scored stock is a pick
    assert [r["symbol"] for r in out["rows"] if r["kind"] == "pick"] == ["ONLY1"]


# ------------------------------------------------------------------ gate 10: agreement with the h05 report and the weekly report


def _agreement_fixture(db):
    run = make_run(db, {})
    d1, d2 = SIGNAL, after(SIGNAL, 1)
    completed(db, run, d1, "DONEHIT", rank=1)
    completed(db, run, d1, "DONEMISS", rank=2, label_hit=0, label_close5=98.0, trade_status="stop", exit_fill=96.0, net_return=-0.0415, exit_reason="stop")
    completed(db, run, d1, "BLOCKED", rank=3, repeat_blocked=True)  # still evaluated, but recorded-not-counted
    pick(db, run, d1, "WAITING", rank=4)
    pick(db, run, d1, "GONE", rank=5, label_status="not_evaluated", label_note="no candle on session 5",
         trade_status="unresolved", trade_note="no candle on session 3")
    completed(db, run, d2, "HALF", rank=1, label_status="not_evaluated", label_hit=None, label_close5=None, label_day5=None,
              label_note="no candle on session 5", net_return=0.0105)  # trade final, label missing
    # label final and a hit, shadow trade still pending: the label alone decides `passed`
    pick(db, run, d2, "LABELONLY", rank=2, label_status="evaluated", label_hit=1, label_close5=103.0,
         label_day5=after(d2, 5), trade_status="pending")
    group_day(db, run, d1, "large", selected_n=5)
    group_day(db, run, d2, "large", selected_n=2, shortfall=3)
    return run


def test_the_ledger_counts_equal_the_h05_report_and_the_weekly_report_where_they_mean_the_same(db_session, lane):
    run = _agreement_fixture(db_session)
    led = L.build(db_session)
    picks = [r for r in led["rows"] if r["kind"] == "pick"]
    counted = [r for r in picks if r["status"] != "blocked"]
    st = lambda s: sum(1 for r in picks if r["status"] == s)  # noqa: E731

    rep = h05_report.build_report(db_session, run.run_no)["runs"][0]["groups"]["large"]
    assert rep["selected"] == len(picks) == 7
    assert rep["counted_selections"] == len(counted) == 6 and rep["repeat_not_counted"] == st("blocked") == 1
    ep = rep["endpoint_label"]["counted_picks"]
    # `passed` follows the final label alone, so the hit rate is the same number in the ledger and the report
    assert ep["n"] == sum(1 for r in counted if r["passed"] is not None) == 3
    assert ep["hit_rate"] == sum(1 for r in counted if r["passed"]) / ep["n"] == 2 / 3
    trade = rep["shadow_trade"]["counted_picks"]
    final = [r for r in counted if r["trade_status"] in RESOLVED and r["net_return"] is not None]
    assert trade["finished"] == len(final) == 3
    assert trade["pending"] == st("immature") == 2
    assert trade["unresolved"] == sum(1 for r in counted if r["trade_status"] == "unresolved") == 1
    assert abs(trade["mean_net_return"] - sum(r["net_return"] for r in final) / len(final)) < 1e-12
    # deliberate difference 1: "finished" counts the trade alone, the ledger's "completed" needs the label too
    assert trade["finished"] == st("completed") + 1 and st("completed") == 2 and st("missing") == 2

    start, end = date(2026, 10, 12), date(2026, 10, 25)
    wk = weekly_paper_report.h05_section(db_session, start, end)["groups"]["large"]
    assert wk["picks_made"] == len(picks) == 7  # the weekly count includes the blocked pick, as the ledger lists it
    days = {t["signal_day"] for t in led["totals"] if t["group"] == "large"}
    assert wk["signal_days_recorded"] == len(days) == 2
    # the weekly "matured" counts every selected pick whose label is final, blocked or not, whatever its trade did
    assert wk["picks_matured"] == sum(1 for r in picks if r["label_status"] == "evaluated") == 4
    # deliberate difference 3: the weekly hit count includes the blocked pick's hit; the ledger's `passed` does not
    blocked_hits = 1
    assert wk["picks_hit_plus_2pct"] == sum(1 for r in picks if r["passed"]) + blocked_hits == 3
