"""Codex review of the entry lock: prove it with REAL entry paths on independent database sessions.

Each thread below has its own SQLAlchemy session and connection, the rows are really committed (so the
other sessions can see them), and the real `risk.check_entry` + real `open_position` run. Only the broker
(a paper fill), the account value and the clock are faked. The account is given room for at most
CAP positions; the test then fires more entries than that at the same moment and counts positions.

The control runs the same race with the lock switched off and must overshoot, which proves the race is
real and the assertion can fail. Committed rows are deleted again at the end.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager, suppress
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from brain_m18_fixtures import DAY, at, brain_strategy, decision, instrument, run, signal, v1_strategy
from swing_trade_ml.brokers.base import OrderResult
from swing_trade_ml.core.enums import OrderStatus, PositionStatus, SignalType
from swing_trade_ml.db.base import Base
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services import execution, risk
from swing_trade_ml.services.brain_golive import approvals
from swing_trade_ml.strategies.base import SignalDecision

TUE_OPEN = at(DAY + timedelta(days=1), 10, 0)  # a Tuesday morning, market open
CAP = 2  # the most positions the account may hold (strategy.max_positions overrides the size ladder)
RACERS = 5
BUY = SignalDecision(SignalType.BUY, 100.0, 0.6, "r", stop_loss=96.0, take_profit=108.0, horizon_days=15)


@pytest.fixture()
def committed(db_engine):
    """Commit rows for real; delete everything created through `track()` when the test ends."""
    created = {"strategies": [], "instruments": [], "runs": []}
    session = Session(bind=db_engine, expire_on_commit=False)

    def track(kind, row):
        created[kind].append(row.id)
        return row

    yield SimpleNamespace(session=session, track=track, engine=db_engine)
    session.rollback()
    session.close()
    _cleanup(db_engine, created)


def _cleanup(engine, created) -> None:
    sids, iids, rids = created["strategies"], created["instruments"], created["runs"]
    for _ in range(6):  # retry passes: rows reference each other, so some deletes must wait for others
        failed = False
        with Session(bind=engine) as db:
            for table in reversed(Base.metadata.sorted_tables):
                cols = table.c
                conds = []
                if "strategy_id" in cols and sids:
                    conds.append(cols.strategy_id.in_(sids))
                if "instrument_id" in cols and iids:
                    conds.append(cols.instrument_id.in_(iids))
                if table.name == "brain_decisions" and rids:
                    conds.append(cols.run_id.in_(rids))
                if table.name == "brain_runs" and rids:
                    conds.append(cols.id.in_(rids))
                if table.name == "strategies" and sids:
                    conds.append(cols.id.in_(sids))
                if table.name == "instruments" and iids:
                    conds.append(cols.id.in_(iids))
                if table.name == "brain_stage_changes":
                    conds.append(cols.changed_by == "entry-lock-test")
                for cond in conds:
                    try:
                        db.execute(delete(table).where(cond))
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                        failed = True
        if not failed:
            return
    raise AssertionError("could not remove the rows this test committed")


class _PaperFill:
    mode = "paper"

    def place_order(self, request, db):
        return OrderResult(
            broker_order_id=f"entry-lock-{time.monotonic_ns()}",
            status=OrderStatus.COMPLETE,
            filled_quantity=request.quantity,
            average_price=100.0,
        )

    def get_ltp(self, keys, db):
        return {}


def _slow_real_risk(monkeypatch):
    """The real entry risk check, followed by a pause: a second entry that does not wait for the first
    reads the account in that gap."""
    real = risk.check_entry

    def slow(**kw):
        verdict = real(**kw)
        time.sleep(0.25)
        return verdict

    monkeypatch.setattr(risk, "check_entry", slow)


def _no_lock(monkeypatch, module):
    @contextmanager
    def nothing(mode, timeout=None):
        yield

    monkeypatch.setattr(module, "entry_lock", nothing)


def _race(engine, work, racers=RACERS):
    """Run `work(session, index)` on `racers` threads, each on its own session, released together."""
    gate = threading.Barrier(racers)
    errors: list[BaseException] = []

    def go(i):
        with Session(bind=engine, expire_on_commit=False) as db:
            try:
                gate.wait(15)
                work(db, i)
            except BaseException as exc:  # noqa: BLE001 - reported below, never swallowed
                errors.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(racers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert not errors, errors


def _open_count(engine, strategy_ids) -> int:
    with Session(bind=engine) as db:
        return len(
            db.execute(
                select(Position.id).where(
                    Position.strategy_id.in_(strategy_ids), Position.status == PositionStatus.OPEN
                )
            ).all()
        )


# ------------------------------------------------------------------------------- the scan's buy path


def _scan_setup(committed, monkeypatch):
    monkeypatch.setattr(execution, "get_broker", lambda: _PaperFill())
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    _slow_real_risk(monkeypatch)
    db = committed.session
    strategy = committed.track("strategies", v1_strategy(db, name=f"lock-int-scan-{time.monotonic_ns()}"))
    strategy.max_positions = CAP
    stamp = time.monotonic_ns() % 10_000_000
    inst_ids = [
        committed.track("instruments", instrument(db, f"LKI{stamp}{i}", 940_000_000 + stamp * 10 + i)).id
        for i in range(RACERS)
    ]
    db.commit()
    return strategy.id, inst_ids


def _scan_work(strategy_id, inst_ids):
    def work(db, i):
        strategy = db.get(execution.Strategy, strategy_id)
        inst = db.get(execution.Instrument, inst_ids[i])
        execution.process_decision(db, strategy, inst, BUY)

    return work


def test_scan_entries_on_separate_sessions_never_exceed_the_account_limit(committed, monkeypatch):
    strategy_id, inst_ids = _scan_setup(committed, monkeypatch)
    _race(committed.engine, _scan_work(strategy_id, inst_ids))
    held = _open_count(committed.engine, [strategy_id])
    assert 1 <= held <= CAP, f"{held} positions open, the account limit is {CAP}"


def test_control_the_same_scan_race_without_the_lock_exceeds_the_limit(committed, monkeypatch):
    strategy_id, inst_ids = _scan_setup(committed, monkeypatch)
    _no_lock(monkeypatch, execution)
    _race(committed.engine, _scan_work(strategy_id, inst_ids))
    held = _open_count(committed.engine, [strategy_id])
    assert held > CAP, "the race did not happen, so the test above proves nothing"


# ------------------------------------------------------------------- the Brain approval order path


def _approval_setup(committed, monkeypatch):
    monkeypatch.setattr(execution, "get_broker", lambda: _PaperFill())
    monkeypatch.setattr(approvals, "_now", lambda: TUE_OPEN)
    monkeypatch.setattr(approvals, "current_mode", lambda: "paper")
    monkeypatch.setattr(approvals, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(approvals, "_live_price", lambda db, inst: 100.0)
    monkeypatch.setattr(approvals.notifier, "send_sync", lambda *a, **kw: True)
    _slow_real_risk(monkeypatch)
    db = committed.session
    stamp = time.monotonic_ns() % 10_000_000
    strategy = committed.track("strategies", brain_strategy(db, name=f"lock-int-brain-{stamp}"))
    strategy.max_positions = CAP
    db.add(
        BrainStageChange(stage="approval", previous_stage="shadow", changed_by="entry-lock-test", reason="t")
    )
    # ONE run that looked at every stock: the approval check reads the newest run's decisions.
    rid = f"lock-int-{stamp}"
    r = run(db, rid)
    r.banner_mode = "NORMAL"
    committed.track("runs", r)
    for i in range(RACERS):
        token = 950_000_000 + stamp * 10 + i
        inst = committed.track("instruments", instrument(db, f"LKB{stamp}{i}", token))
        d = decision(db, rid, inst.tradingsymbol, "TRADE")
        d.entry_low, d.entry_high = 98.0, 103.0
        signal(db, strategy, inst, DAY)
    db.commit()
    created = approvals.create_pending(db, DAY)
    mine = [a.id for a in created if a.strategy_id == strategy.id]
    assert len(mine) == RACERS
    return strategy.id, mine


def _approval_work(approval_ids):
    def work(db, i):
        # a refusal is a normal outcome here; only the number of positions matters
        with suppress(approvals.ApprovalError):
            approvals.approve(db, approval_ids[i], by="owner")

    return work


def test_brain_approvals_on_separate_sessions_never_exceed_the_account_limit(committed, monkeypatch):
    strategy_id, approval_ids = _approval_setup(committed, monkeypatch)
    _race(committed.engine, _approval_work(approval_ids))
    held = _open_count(committed.engine, [strategy_id])
    assert 1 <= held <= CAP, f"{held} positions open, the account limit is {CAP}"


def test_control_the_same_approval_race_without_the_lock_exceeds_the_limit(committed, monkeypatch):
    strategy_id, approval_ids = _approval_setup(committed, monkeypatch)
    _no_lock(monkeypatch, approvals)
    _race(committed.engine, _approval_work(approval_ids))
    held = _open_count(committed.engine, [strategy_id])
    assert held > CAP, "the race did not happen, so the test above proves nothing"


# ------------------------------------------------------------------------- the lock reads fresh state


def test_the_position_list_is_read_again_after_waiting_for_the_lock(committed, monkeypatch):
    """The entry we wait for may open this very stock. What the buy section gets must be read AFTER the
    wait, not the empty list read before it (pyramiding decisions and exposure use that list)."""
    from swing_trade_ml.services.entry_lock import entry_lock

    db = committed.session
    strategy = committed.track("strategies", v1_strategy(db, name=f"lock-int-fresh-{time.monotonic_ns()}"))
    stamp = time.monotonic_ns() % 10_000_000
    inst = committed.track("instruments", instrument(db, f"LKF{stamp}", 970_000_000 + stamp))
    db.commit()
    sid, iid = strategy.id, inst.id
    seen: dict = {}

    def capture(db_, strategy_, instrument_, decision_, mode_, existing_positions):
        seen["ids"] = [p.id for p in existing_positions]
        return None

    monkeypatch.setattr(execution, "_process_buy", capture)
    holder_in = threading.Event()

    def other_entry():
        with entry_lock("paper", timeout=10):
            holder_in.set()
            time.sleep(0.4)  # the waiting entry has read "no positions" by now
            with Session(bind=committed.engine) as other:
                position = Position(
                    strategy_id=sid, instrument_id=iid, mode="paper", status=PositionStatus.OPEN,
                    quantity=5, initial_quantity=5, entry_price=100.0, entry_at=at(DAY, 10, 0),
                    stop_loss=96.0, initial_stop_loss=96.0, take_profit=108.0, highest_price=100.0,
                    current_price=100.0, total_charges=0.0,
                )
                other.add(position)
                other.commit()
                seen["new_position"] = position.id

    thread = threading.Thread(target=other_entry)
    thread.start()
    assert holder_in.wait(5)
    with Session(bind=committed.engine, expire_on_commit=False) as mine:
        execution.process_decision(
            mine, mine.get(execution.Strategy, sid), mine.get(execution.Instrument, iid), BUY
        )
    thread.join()
    assert seen["ids"] == [seen["new_position"]]
