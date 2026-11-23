# ruff: noqa: E501 (long test sentences)
# ruff: noqa: F811, F401 (imported fixtures)
# ruff: noqa: N812 (short P / L aliases, as in the h05 tests)
"""#263 forward outcome ledger: a read-only, owner-only view over the 5-day lane's frozen records.

Synthetic fixtures only. The lane itself (scoring, maturing, the append-only guards) is tested in test_h05_*;
these tests prove the view's contract: statuses, returns, benchmark, reconciliation, read-only, owner-only.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_service
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Signal
from swing_trade_ml.db.models.session import User
from swing_trade_ml.shadow_lanes import outcome_ledger as L
from test_h05_service import (  # sibling test helpers: calendar, stocks, the lane fixture
    NOW,
    SIGNAL,
    add_candle,
    add_stock,
    after,
    future,
    lane,
    make_run,
    rows_of,
)

URL = "/api/v1/research/lanes/outcome-ledger"
MODULE = Path(L.__file__)


def pick(db, run, day, symbol, group="large", rank=1, **kw):
    """One synthetic recorded pick (a selected top-5 row), plus the field overrides in `kw`."""
    fields = {
        "run_id": run.id,
        "signal_day": day,
        "symbol": symbol,
        "group": group,
        "instrument_id": 1,
        "status": "scored",
        "model_id": 2,
        "model_version": "v1",
        "score": 0.8,
        "group_rank": rank,
        "selected": True,
        "repeat_blocked": False,
        "signal_close": 100.0,
        "recorded_at": datetime(day.year, day.month, day.day, 13, tzinfo=UTC),
        **kw,
    }
    row = H05Signal(**fields)
    db.add(row)
    db.flush()
    return row


def day_row(rows, symbol):
    return next(r for r in rows if r["kind"] == "pick" and r["symbol"] == symbol)


# ---------------------------------------------------------------- 1. the four statuses and their reasons


def test_each_pick_has_exactly_one_of_four_statuses_and_a_reason(db_session, lane):
    run = make_run(db_session, {})
    pick(db_session, run, SIGNAL, "DONE", rank=1, label_status="evaluated", label_hit=1, label_close5=103.0,
         label_day5=after(SIGNAL, 5), trade_status="target", entry_day=after(SIGNAL, 1), exit_day=after(SIGNAL, 2),
         entry_fill=100.0, exit_fill=102.0, net_return=0.0185, costs_inr=40.0, exit_reason="target")
    pick(db_session, run, SIGNAL, "WAIT", rank=2)  # label and trade still pending
    pick(db_session, run, SIGNAL, "GONE", rank=3, label_status="not_evaluated", label_note="no candle on session 5",
         trade_status="unresolved", trade_note="no candle on session 3")
    pick(db_session, run, SIGNAL, "REPT", rank=4, repeat_blocked=True)
    rows = L.build(db_session)["rows"]
    got = {r["symbol"]: (r["status"], r["reason"]) for r in rows if r["kind"] == "pick"}
    assert {s: v[0] for s, v in got.items()} == {
        "DONE": "completed",
        "WAIT": "immature",
        "GONE": "missing",
        "REPT": "blocked",
    }
    assert "no candle on session 5" in got["GONE"][1] and "no candle on session 3" in got["GONE"][1]
    assert "five sessions" in got["REPT"][1] and "not happened" in got["WAIT"][1]
    assert all(v[1] for v in got.values())


# ---------------------------------------------------------------- 2. gross, net, benchmark (stored fills and costs)


def _nifty(db, **sessions_):
    nifty = add_stock(db, settings.BENCHMARK_INDEX_SYMBOL, price=200.0)
    for k in range(1, 6):
        add_candle(db, nifty, after(SIGNAL, k), sessions_.get(f"n{k}", (200, 200, 200, 200)))


def test_gross_is_at_least_net_from_the_stored_fills_and_costs_with_a_losing_trade(db_session, lane):
    win = add_stock(db_session, "WIN")
    lose = add_stock(db_session, "LOSE")
    lane.scores.update({"WIN": 0.9, "LOSE": 0.8})
    _nifty(db_session, n1=(200, 200, 200, 200), n2=(200, 212, 200, 210), n5=(205, 205, 205, 205))
    run = make_run(db_session, {"WIN": "large", "LOSE": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    future(db_session, win, n2=(100, 103, 100, 102.5), n5=(103, 103, 103, 103))
    future(db_session, lose, n1=(100, 100, 94, 95))
    h05_service.evaluate(db_session, run)
    rows = L.build(db_session)["rows"]
    w, lo = day_row(rows, "WIN"), day_row(rows, "LOSE")
    for r in (w, lo):
        assert r["status"] == "completed"
        stored = rows_of(db_session, run)[r["symbol"]]
        assert r["gross_return"] == pytest.approx(stored.exit_fill / stored.entry_fill - 1)
        assert r["net_return"] == stored.net_return
        assert r["gross_return"] >= r["net_return"]  # the costs only ever take away
    assert lo["gross_return"] < 0 and lo["net_return"] < lo["gross_return"]  # a negative-return fixture
    assert w["gross_return"] > 0
    assert w["passed"] is True and lo["passed"] is False  # close of session 5 vs the +2% rule
    # benchmark: NIFTY from the open of the entry session to the close of the exit session (n1 open 200 -> n2 close 210)
    assert w["benchmark_return"] == pytest.approx(210 / 200 - 1)
    assert w["excess_vs_benchmark"] == pytest.approx(w["net_return"] - w["benchmark_return"])


# ---------------------------------------------------------------- 3. read only, owner only


def _snapshot(db):
    cols = {t.name: [c.name for c in t.columns] for t in (H05Signal.__table__, H05GroupDay.__table__, H05Event.__table__)}
    out = {}
    for model in (H05Signal, H05GroupDay, H05Event):
        out[model.__tablename__] = sorted(
            tuple(str(getattr(r, c)) for c in cols[model.__tablename__]) for r in db.execute(select(model)).scalars()
        )
    return out


def test_building_the_ledger_writes_nothing(db_session, lane):
    run = make_run(db_session, {})
    pick(db_session, run, SIGNAL, "RO1")
    db_session.add(H05Event(run_id=run.id, signal_day=after(SIGNAL, 1), kind="missed_session", detail="why"))
    db_session.flush()
    before = _snapshot(db_session)
    L.build(db_session)
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert _snapshot(db_session) == before


def _person(db, name, role):
    u = User(username=name, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(u)
    db.flush()
    return {"Authorization": "Bearer " + create_access_token(u.username, {"uid": u.id, "tv": 0})}


def test_the_route_is_owner_only_and_read_only(client, db_session):
    assert client.get(URL).status_code in (401, 403)
    for role in ("member", "tester"):
        assert client.get(URL, headers=_person(db_session, f"ol-{role}", role)).status_code in (401, 403)
    assert client.get(URL, headers=_person(db_session, "ol-owner", "owner")).status_code == 200
    from swing_trade_ml.api.v1.endpoints import lanes

    assert {m for r in lanes.router.routes for m in r.methods} == {"GET"}


# ---------------------------------------------------------------- 5. one row per pick


def test_every_pick_appears_exactly_once(db_session, lane):
    run = make_run(db_session, {})
    for i, s in enumerate(["A1", "A2", "A3"], start=1):
        pick(db_session, run, SIGNAL, s, rank=i)
    pick(db_session, run, after(SIGNAL, 1), "A1", rank=1)
    rows = [r for r in L.build(db_session)["rows"] if r["kind"] == "pick"]
    keys = [(r["run_no"], r["signal_day"], r["symbol"]) for r in rows]
    assert len(keys) == len(set(keys)) == 4


# ---------------------------------------------------------------- 6. no sealed or brain data, and the criteria match the protocol


def test_the_view_reads_no_brain_money_or_sealed_table():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules |= {a.name for a in node.names}
    forbidden = ("swing_trade_ml.brain", "swing_trade_ml.db.models.trading", "swing_trade_ml.db.models.brain", "swing_trade_ml.services")
    assert not [m for m in modules if m.startswith(forbidden)], modules
    assert "trial_seal" not in MODULE.read_text(encoding="utf-8")  # the h05 report has no seal; none is bypassed
    assert "brain.lanes" not in MODULE.read_text(encoding="utf-8")  # the lane's own files stay the only importers


def test_the_criteria_stated_in_the_view_equal_the_protocol():
    assert L.CRITERIA["horizon_sessions"] == P.HORIZON == 5
    assert L.CRITERIA["endpoint_target"] == P.LABEL_TARGET
    assert L.CRITERIA["trade_target"] == P.TRADE_TARGET and L.CRITERIA["trade_stop"] == P.TRADE_STOP


# ---------------------------------------------------------------- 8. repeats yield no duplicates


def test_repeated_reads_and_repeated_maturation_never_duplicate_or_change_rows(db_session, lane):
    inst = add_stock(db_session, "REPEAT")
    lane.scores["REPEAT"] = 0.9
    run = make_run(db_session, {"REPEAT": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    future(db_session, inst, n2=(100, 103, 100, 102.5))
    h05_service.evaluate(db_session, run)
    first = L.build(db_session)
    assert h05_service.evaluate(db_session, run) == {"label": 0, "trade": 0}  # a second maturation changes nothing
    second = L.build(db_session)
    third = L.build(db_session)
    assert first == second == third
    assert len([r for r in first["rows"] if r["kind"] == "pick"]) == 1


# ---------------------------------------------------------------- 9. a missed session stays visible, with its reason


def test_a_missed_session_is_a_missing_row_with_its_stored_reason_even_without_signal_rows(db_session, lane):
    run = make_run(db_session, {})
    gap = after(SIGNAL, 3)
    db_session.add(
        H05Event(run_id=run.id, signal_day=gap, kind="missed_session",
                 detail="data was not ready by the cut-off. Not scored late, not replaced, the run is not extended.")
    )
    db_session.flush()
    out = L.build(db_session)
    row = next(r for r in out["rows"] if r["kind"] == "session")
    assert (row["status"], row["signal_day"], row["symbol"]) == ("missing", gap.isoformat(), None)
    assert "cut-off" in row["reason"] and row["run_no"] == run.run_no
    assert not [r for r in out["rows"] if r["kind"] == "pick"]  # no signal rows exist for that day


# ---------------------------------------------------------------- 10. totals reconcile with the source rows


def test_totals_reconcile_with_the_source_rows_per_group_and_day(db_session, lane):
    run = make_run(db_session, {})
    d1, d2 = SIGNAL, after(SIGNAL, 1)
    pick(db_session, run, d1, "L1", rank=1, label_status="evaluated", label_hit=1, trade_status="target", net_return=0.01,
         entry_fill=100.0, exit_fill=102.0, entry_day=after(d1, 1), exit_day=after(d1, 2))
    pick(db_session, run, d1, "L2", rank=2)
    pick(db_session, run, d1, "L3", rank=3, repeat_blocked=True)
    pick(db_session, run, d1, "M1", group="mid", rank=1, label_status="not_evaluated", trade_status="unresolved")
    pick(db_session, run, d2, "L1", rank=1)
    for day, group, n in ((d1, "large", 3), (d1, "mid", 1), (d2, "large", 1)):
        db_session.add(H05GroupDay(run_id=run.id, signal_day=day, group=group, universe_n=10, scored_n=10,
                                   not_scored_n=0, selected_n=n, shortfall=5 - n))
    db_session.flush()
    out = L.build(db_session)
    source = {}
    for s in db_session.execute(select(H05Signal).where(H05Signal.selected.is_(True))).scalars():
        source[(s.signal_day.isoformat(), s.group)] = source.get((s.signal_day.isoformat(), s.group), 0) + 1
    totals = {(t["signal_day"], t["group"]): t for t in out["totals"] if t["group"] is not None}
    assert {k: t["picks"] for k, t in totals.items()} == source
    for key, t in totals.items():
        assert t["completed"] + t["immature"] + t["missing"] + t["blocked"] == t["picks"], key
        assert t["recorded_selected"] == t["picks"] and t["reconciles"] is True
    rows = [r for r in out["rows"] if r["kind"] == "pick"]
    for status in L.STATUSES:  # the overall counts equal the row counts
        assert out["counts"][status] == sum(1 for r in rows if r["status"] == status)
    assert sum(out["counts"].values()) == len(rows) == sum(source.values())


# ---------------------------------------------------------------- the route returns the same contract


def test_the_route_returns_the_contract(client, db_session, lane):
    run = make_run(db_session, {})
    pick(db_session, run, SIGNAL, "RT1")
    body = client.get(URL, headers=_person(db_session, "ol-owner2", "owner")).json()
    assert set(body) >= {"criteria", "rows", "totals", "counts", "note"}
    assert set(body["rows"][0]) >= set(L.ROW_FIELDS)
