# ruff: noqa: E501 (long test sentences)
# ruff: noqa: F811, F401 (imported fixtures)
# ruff: noqa: N812 (short L alias, as in the other ledger tests)
"""#263 Codex round Q46: `passed` follows the label, the benchmark follows the trade's own state, and every
record set comes from one database snapshot. Synthetic fixtures only; read-only.
"""

from __future__ import annotations

from sqlalchemy import event, insert

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.lanes import H05GroupDay, H05Signal
from swing_trade_ml.shadow_lanes import outcome_ledger as L
from test_h05_service import SIGNAL, add_candle, add_stock, after, lane, make_run
from test_outcome_ledger import pick
from test_outcome_ledger_reconcile import completed, group_day


def by_symbol(db):
    return {r["symbol"]: r for r in L.build(db)["rows"] if r["kind"] == "pick"}


# ------------------------------------------------------------------ a: `passed` follows the label alone


def test_passed_follows_the_final_label_whatever_the_shadow_trade_did(db_session, lane):
    run = make_run(db_session, {})
    ev = {"label_status": "evaluated", "label_close5": 103.0, "label_day5": after(SIGNAL, 5)}
    pick(db_session, run, SIGNAL, "HITPEND", rank=1, label_hit=1, trade_status="pending", **ev)
    pick(db_session, run, SIGNAL, "MISSUNRES", rank=2, label_hit=0, trade_status="unresolved", trade_note="no candle", **ev)
    pick(db_session, run, SIGNAL, "HITUNRES", rank=3, label_hit=1, trade_status="unresolved", trade_note="no candle", **ev)
    pick(db_session, run, SIGNAL, "BLOCKED", rank=4, label_hit=1, repeat_blocked=True, trade_status="target", **ev)
    pick(db_session, run, SIGNAL, "NOLABEL", rank=5, label_status="not_evaluated", trade_status="target", net_return=0.01)
    pick(db_session, run, SIGNAL, "WAITING", rank=6)
    rows = by_symbol(db_session)
    assert rows["HITPEND"]["passed"] is True and rows["HITPEND"]["status"] == "immature"
    assert rows["MISSUNRES"]["passed"] is False and rows["MISSUNRES"]["status"] == "missing"
    assert rows["HITUNRES"]["passed"] is True
    assert rows["BLOCKED"]["passed"] is None  # a pick that is not counted is never counted as a pass
    assert rows["NOLABEL"]["passed"] is None  # no final label: neither a pass nor a fail
    assert rows["WAITING"]["passed"] is None


# ------------------------------------------------------------------ b: the benchmark follows the trade's own state


def _nifty(db):
    nifty = add_stock(db, settings.BENCHMARK_INDEX_SYMBOL, price=200.0)
    add_candle(db, nifty, after(SIGNAL, 1), (200, 200, 200, 200))
    add_candle(db, nifty, after(SIGNAL, 2), (200, 212, 200, 210))


def test_the_benchmark_is_there_whenever_the_trade_is_final_and_its_reason_is_never_a_false_wait(db_session, lane):
    _nifty(db_session)
    run = make_run(db_session, {})
    # a final trade whose label could not be evaluated: the pick is "missing", but its trade window is known
    completed(db_session, run, SIGNAL, "TRADEOK", rank=1, label_status="not_evaluated", label_hit=None,
              label_close5=None, label_day5=None, label_note="no candle on session 5")
    pick(db_session, run, SIGNAL, "TRADEPEND", rank=2)
    pick(db_session, run, SIGNAL, "TRADEGONE", rank=3, trade_status="unresolved", trade_note="no candle on session 3",
         label_status="not_evaluated", label_note="no candle on session 5")
    completed(db_session, run, SIGNAL, "BLK", rank=4, repeat_blocked=True)
    rows = by_symbol(db_session)
    ok = rows["TRADEOK"]
    assert ok["status"] == "missing" and ok["benchmark_return"] == 210 / 200 - 1 and ok["benchmark_reason"] is None
    assert ok["excess_vs_benchmark"] == ok["net_return"] - ok["benchmark_return"]
    assert "not finished" in rows["TRADEPEND"]["benchmark_reason"]
    gone = rows["TRADEGONE"]["benchmark_reason"]
    assert "could not be worked out" in gone and "no candle on session 3" in gone
    assert "Not counted" in rows["BLK"]["benchmark_reason"]
    for r in rows.values():
        assert r["benchmark_return"] is not None or (r["benchmark_reason"] and "Available once the pick is completed" not in r["benchmark_reason"])
    assert "waiting" not in gone.lower() and "completed" not in gone.lower()


# ------------------------------------------------------------------ c: one database snapshot


def test_all_record_sets_are_read_in_one_statement_so_a_commit_during_the_read_cannot_split_them(db_session, lane):
    run = make_run(db_session, {})
    group_day(db_session, run, SIGNAL, "large", selected_n=1)
    pick(db_session, run, SIGNAL, "ONE", rank=1)
    day2 = after(SIGNAL, 1)
    conn = db_session.connection()
    state = {"fired": False, "busy": False, "reads": 0}

    def after_execute(c, cursor, statement, parameters, context, executemany):
        if state["busy"] or "h05_" not in statement or not statement.lstrip().upper().startswith(("SELECT", "WITH")):
            return
        state["reads"] += 1
        if "h05_signals" in statement and not state["fired"]:
            # a "concurrent commit": a whole recorded day lands right after the picks have been read
            state["fired"] = state["busy"] = True
            try:
                c.execute(
                    insert(H05Signal.__table__).values(
                        run_id=run.id, signal_day=day2, symbol="LATE", group="large", status="scored", selected=True,
                        repeat_blocked=False, label_status="pending", trade_status="pending",
                    )
                )
                c.execute(
                    insert(H05GroupDay.__table__).values(
                        run_id=run.id, signal_day=day2, group="large", universe_n=1, scored_n=1, not_scored_n=0,
                        selected_n=1, shortfall=4,
                    )
                )
            finally:
                state["busy"] = False

    event.listen(conn, "after_cursor_execute", after_execute)
    try:
        out = L.build(db_session)
    finally:
        event.remove(conn, "after_cursor_execute", after_execute)
    assert state["fired"] and state["reads"] == 1  # picks, not-scored rows, events, group-days and runs: one statement
    assert {t["signal_day"] for t in out["totals"]} == {SIGNAL.isoformat()}  # the day that landed later is not half-seen
    assert all(t["reconciles"] for t in out["totals"] if t["group"] is not None)
