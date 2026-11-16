"""Codex audit finding 3: two scans must not both pass the entry risk checks against the same free cash,
the same last position slot, or the same sector room.

`risk.check_entry` is read-only on purpose and the signal/order/position commits come later, so nothing
stopped two entry paths (a manual scan during the 15:45 scan, two processes) from both seeing room and both
buying. The fix is one Postgres advisory lock per trading mode around the whole buy section — from the
cash read to the committed position — so a second entry waits, then sees the first one's position.

The lock is on a dedicated connection (the session commits several times inside an entry, which would
release a transaction-level lock), and it gives up after a timeout: a busy entry is then REJECTED, never
placed (decisions only move toward caution, CLAUDE.md principle 5). Sells never take the lock.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import pytest

from brain_m18_fixtures import brain_strategy, instrument, no_broker, v1_strategy
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.trading import Order
from swing_trade_ml.services import entry_lock as entry_lock_module
from swing_trade_ml.services import execution
from swing_trade_ml.services.entry_lock import EntryLockBusy, entry_lock
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies.base import SignalDecision

BUY = SignalDecision(SignalType.BUY, 100.0, 0.6, "r", stop_loss=96.0, take_profit=108.0, horizon_days=15)
HOLD = SignalDecision(SignalType.HOLD, 100.0, 0.5, "r")
EXIT = SignalDecision(SignalType.EXIT, 100.0, 0.5, "r")


def _hold_in_thread(mode: str, held: threading.Event, release: threading.Event):
    """Hold the entry lock for `mode` on another connection until `release` is set."""

    def run():
        with entry_lock(mode, timeout=5):
            held.set()
            release.wait(10)

    thread = threading.Thread(target=run)
    thread.start()
    assert held.wait(5), "the helper thread never got the lock"
    return thread


# ------------------------------------------------------------------------------ the lock itself


def test_a_second_entry_waits_until_the_first_finishes():
    order: list[str] = []
    first_in = threading.Event()

    def first():
        with entry_lock("paper", timeout=5):
            first_in.set()
            order.append("first-in")
            time.sleep(0.4)
            order.append("first-out")

    thread = threading.Thread(target=first)
    thread.start()
    assert first_in.wait(5)
    with entry_lock("paper", timeout=5):
        order.append("second-in")
    thread.join()
    assert order == ["first-in", "first-out", "second-in"]


def test_a_busy_lock_gives_up_after_the_timeout():
    held, release = threading.Event(), threading.Event()
    thread = _hold_in_thread("paper", held, release)
    try:
        started = time.monotonic()
        with pytest.raises(EntryLockBusy), entry_lock("paper", timeout=0.3):
            pytest.fail("must not enter the block while another entry holds the lock")
        assert 0.25 <= time.monotonic() - started < 3
    finally:
        release.set()
        thread.join()


def test_the_lock_is_released_when_the_block_raises():
    with pytest.raises(ValueError), entry_lock("paper", timeout=5):
        raise ValueError("boom")
    with entry_lock("paper", timeout=1):  # would raise EntryLockBusy if it had leaked
        pass


def test_paper_and_live_entries_do_not_block_each_other():
    held, release = threading.Event(), threading.Event()
    thread = _hold_in_thread("paper", held, release)
    try:
        with entry_lock("live", timeout=0.5):
            pass
    finally:
        release.set()
        thread.join()


def _race(use_lock: bool, threads: int = 8, cap: int = 3) -> int:
    """`threads` entries each check 'is there room?' and then take a slot. Returns slots taken."""
    state = {"taken": 0}
    gate = threading.Barrier(threads)

    def entry():
        gate.wait(10)

        @contextmanager
        def maybe_lock():
            if use_lock:
                with entry_lock("paper", timeout=30):
                    yield
            else:
                yield

        with maybe_lock():
            has_room = state["taken"] < cap  # the risk check
            time.sleep(0.05)  # ...the signal/order/position commits that follow it
            if has_room:
                state["taken"] += 1

    workers = [threading.Thread(target=entry) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    return state["taken"]


def test_without_the_lock_simultaneous_entries_overshoot_the_cap():
    """The control: proves the race is real and that the test below can fail."""
    assert _race(use_lock=False) > 3


def test_with_the_lock_simultaneous_entries_never_overshoot_the_cap():
    assert _race(use_lock=True) == 3


# ------------------------------------------------------------------------- wired into the buy path


def _setup(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))


def test_a_buy_reads_cash_and_checks_risk_while_holding_the_lock(db_session, monkeypatch):
    _setup(monkeypatch)
    state = {"held": False, "modes": [], "seen_by_cash": None, "seen_by_risk": None}

    @contextmanager
    def recording_lock(mode, timeout=None):
        state["modes"].append(mode)
        state["held"] = True
        try:
            yield
        finally:
            state["held"] = False

    def cash(db, mode):
        state["seen_by_cash"] = state["held"]
        return 1_000_000.0, 1_000_000.0

    def check(**kw):
        state["seen_by_risk"] = state["held"]
        return RiskDecision(False, 0, "blocked for this test", rule="OTHER")

    monkeypatch.setattr(execution, "entry_lock", recording_lock)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", cash)
    monkeypatch.setattr(execution.risk, "check_entry", check)
    strategy = v1_strategy(db_session, name="lock-wired")
    inst = instrument(db_session, "LCKA", 919101)

    signal = execution.process_decision(db_session, strategy, inst, BUY)

    assert state["modes"] == [strategy.mode]
    assert state["seen_by_cash"] is True and state["seen_by_risk"] is True
    assert state["held"] is False
    assert signal.rejection_reason == "blocked for this test"


def test_the_lock_is_released_after_a_buy_however_it_ends(db_session, monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(
        execution.risk, "check_entry", lambda **kw: RiskDecision(False, 0, "no room", rule="OTHER")
    )
    strategy = v1_strategy(db_session, name="lock-released")
    inst = instrument(db_session, "LCKB", 919102)
    execution.process_decision(db_session, strategy, inst, BUY)
    with entry_lock(strategy.mode, timeout=1):  # raises EntryLockBusy if the buy leaked it
        pass


def test_when_another_entry_holds_the_lock_the_buy_is_rejected_not_placed(db_session, monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(entry_lock_module, "ENTRY_LOCK_TIMEOUT_SECONDS", 0.3)

    def must_not_run(**kw):
        pytest.fail("risk was checked, and an order could follow, without holding the entry lock")

    monkeypatch.setattr(execution.risk, "check_entry", must_not_run)
    strategy = v1_strategy(db_session, name="lock-busy")
    inst = instrument(db_session, "LCKC", 919103)
    held, release = threading.Event(), threading.Event()
    thread = _hold_in_thread(strategy.mode, held, release)
    try:
        signal = execution.process_decision(db_session, strategy, inst, BUY)
    finally:
        release.set()
        thread.join()

    assert signal is not None and not signal.was_executed
    assert "another entry" in signal.rejection_reason.lower()
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0


@pytest.mark.parametrize("decision", [HOLD, EXIT], ids=["hold", "exit"])
def test_holds_and_exits_never_wait_for_the_entry_lock(db_session, monkeypatch, decision):
    """A stop-loss or exit must never be delayed behind a slow entry."""
    _setup(monkeypatch)

    @contextmanager
    def forbidden(mode, timeout=None):
        pytest.fail("only a BUY may take the entry lock")
        yield

    monkeypatch.setattr(execution, "entry_lock", forbidden)
    strategy = v1_strategy(db_session, name=f"lock-{decision.signal.value}")
    token = 919104 + len(decision.signal.value)
    inst = instrument(db_session, f"LCK{decision.signal.value[:2].upper()}", token)
    execution.process_decision(db_session, strategy, inst, decision)


def test_advisory_and_practice_ideas_do_not_take_the_lock(db_session, monkeypatch):
    """They place no order, so there is no capacity to protect — and the sealed trial's practice-brain
    evidence must not change (a busy lock must never drop or alter a practice idea)."""
    _setup(monkeypatch)
    monkeypatch.setattr(
        execution.risk, "check_entry", lambda **kw: RiskDecision(False, 0, "no room", rule="OTHER")
    )

    @contextmanager
    def forbidden(mode, timeout=None):
        pytest.fail("an advisory/practice idea places no order and must not take the entry lock")
        yield

    monkeypatch.setattr(execution, "entry_lock", forbidden)
    strategy = brain_strategy(db_session, name="lock-practice")
    inst = instrument(db_session, "LCKP", 919110)
    assert execution.is_advisory(strategy)
    signal = execution.process_decision(db_session, strategy, inst, BUY)
    assert signal.rejection_reason is not None


def test_an_unlock_that_is_not_confirmed_drops_the_connection(monkeypatch):
    """pg_advisory_unlock returns false when the lock was not held. That must never pass silently: the
    connection is invalidated so Postgres frees every lock it held."""
    real_connect = entry_lock_module.engine.connect
    state = {"invalidated": False}

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar(self):
            return self.value

    class Conn:
        def __init__(self, conn):
            self.conn = conn

        def execution_options(self, **kw):
            self.conn = self.conn.execution_options(**kw)
            return self

        def execute(self, stmt, params=None):
            if "pg_advisory_unlock" in str(stmt):
                self.conn.execute(stmt, params)  # really release it, then report a failure
                return Result(False)
            return self.conn.execute(stmt, params)

        def invalidate(self):
            state["invalidated"] = True
            self.conn.invalidate()

        def close(self):
            self.conn.close()

    monkeypatch.setattr(entry_lock_module.engine, "connect", lambda: Conn(real_connect()), raising=False)
    with entry_lock("paper", timeout=2):
        pass
    assert state["invalidated"] is True
