"""The kill switch, and the risk-event log.

Every function here reads the database on every call — nothing is cached.
This mirrors the two-latch rule for live trading (`get_broker()` re-reads the
latches on every call): a halt the owner presses must stop the very next entry
decision, not the one after some cache expires or the process restarts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.safety import RiskEvent, SystemState

log = get_logger(__name__)

STATE_ID = 1


def get_state(db: Session) -> SystemState:
    """The single system_state row.

    The migration inserts it, but a database built by `create_all()` (the
    test suite, or the app's no-Alembic fallback) has the table and no row.
    That case returns an unsaved default — entries and exits both on — rather
    than writing: this is called from inside the entry check, which must stay
    free of writes. Failing open here matches what a freshly migrated
    database says anyway; it is logged so a missing row is not invisible.
    """
    state = db.execute(
        select(SystemState).where(SystemState.id == STATE_ID).execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if state is None:
        log.warning("system_state.row_missing_using_defaults")
        return SystemState(id=STATE_ID, new_entries_enabled=True, exits_enabled=True)
    return state


def is_entries_halted(db: Session) -> bool:
    return not get_state(db).new_entries_enabled


def is_exits_disabled(db: Session) -> bool:
    return not get_state(db).exits_enabled


def _get_or_create(db: Session) -> SystemState:
    state = db.get(SystemState, STATE_ID)
    if state is None:
        state = SystemState(id=STATE_ID, new_entries_enabled=True, exits_enabled=True)
        db.add(state)
    return state


def halt(db: Session, reason: str, by: str) -> SystemState:
    """Stop all new entries. Exits keep running — a halt must never trap
    capital in positions that are heading for their stops."""
    state = _get_or_create(db)
    state.new_entries_enabled = False
    state.halt_reason = reason
    state.halted_at = datetime.now(UTC)
    state.halted_by = by
    db.commit()
    log.warning("system_state.entries_halted", reason=reason, by=by)
    return state


def resume(db: Session, by: str) -> SystemState:
    """Allow new entries again. The halt fields are cleared because the row
    describes the current state, not history; who resumed is logged."""
    state = _get_or_create(db)
    state.new_entries_enabled = True
    state.halt_reason = None
    state.halted_at = None
    state.halted_by = None
    db.commit()
    log.warning("system_state.entries_resumed", by=by)
    return state


def disable_exits(db: Session, reason: str, by: str) -> SystemState:
    """Stop the exit sweep. The dangerous switch: while this is off no
    stop-loss, target or time stop fires, so a falling position can lose far
    more than its stop was set to allow.

    It deliberately leaves `new_entries_enabled` and the halt_* fields alone.
    Those three columns describe the entries halt and are cleared by
    `resume()`; writing the exits reason into them would mean resuming
    entries — an unrelated act — silently erased the record of why every
    stop-loss in the book is switched off. Until exits get their own
    reason/at/by columns, the reason lives in this warning line, which is why
    the API requires one.
    """
    state = _get_or_create(db)
    state.exits_enabled = False
    db.commit()
    log.warning(
        "system_state.exits_disabled",
        reason=reason,
        by=by,
        at=datetime.now(UTC).isoformat(),
        message="Exits are switched OFF — open positions are no longer watched for "
        "their stop-loss, target or time stop.",
    )
    return state


def enable_exits(db: Session, by: str) -> SystemState:
    """Let the exit sweep run again. Logged at warning level like its
    counterpart: both directions of this switch are worth finding later."""
    state = _get_or_create(db)
    state.exits_enabled = True
    db.commit()
    log.warning("system_state.exits_enabled", by=by)
    return state


def record_risk_event(
    db: Session,
    *,
    mode: str,
    rule: str,
    reason: str,
    strategy_id: int | None = None,
    instrument_id: int | None = None,
    symbol: str | None = None,
    amount_inr: float | None = None,
) -> RiskEvent:
    """Add (not commit) one RiskEvent — the caller commits alongside the
    signal it is recording, so the two can never disagree."""
    event = RiskEvent(
        ts=datetime.now(UTC),
        mode=mode,
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        symbol=symbol,
        rule=rule,
        reason=reason,
        amount_inr=amount_inr,
    )
    db.add(event)
    return event
