"""The append-only pick record: submit, correct before the cutoff, list what is active.

Every attempt is stored, including refused ones (with the reason), so the record shows everything the owner
tried. Nothing here edits or deletes a row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session, aliased

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.experiments import ExperimentSelection
from swing_trade_ml.db.models.market import Candle, Instrument

from . import rules
from .protocol import PROTOCOL_V1, Protocol, ensure_owner_cohort, protocol_from_row

VALID_HORIZONS = (5, 30)


class TooLateError(Exception):
    """The pick's entry session has passed its cutoff; it can no longer be changed."""


class NotFoundError(Exception):
    pass


def _instrument(db: Session, symbol: str) -> Instrument | None:
    return db.scalar(
        select(Instrument)
        .where(func.upper(Instrument.tradingsymbol) == symbol.upper(), Instrument.exchange == "NSE")
        .order_by(Instrument.is_active.desc(), Instrument.id)
        .limit(1)
    )


def _has_prices(db: Session, instrument_id: int) -> bool:
    return bool(
        db.scalar(select(exists().where(Candle.instrument_id == instrument_id, Candle.interval == "day")))
    )


def _superseded():
    """Replaced by an ACCEPTED correction. A refused correction (typo, duplicate) leaves the original."""
    newer = aliased(ExperimentSelection)
    return exists().where(newer.supersedes_id == ExperimentSelection.id, newer.status == "accepted")


def active_selections(db: Session) -> list[ExperimentSelection]:
    """Accepted picks that no later correction replaced, oldest first."""
    return list(
        db.scalars(
            select(ExperimentSelection)
            .where(ExperimentSelection.status == "accepted", ~_superseded())
            .order_by(ExperimentSelection.id)
        )
    )


def _duplicate(
    db: Session, cohort_id: int, instrument_id: int, entry, protocol: Protocol, ignore_id=None
) -> bool:
    """An active pick of this stock and cohort whose `dedupe_sessions` window has not closed by `entry`."""
    for sel in db.scalars(
        select(ExperimentSelection).where(
            ExperimentSelection.cohort_id == cohort_id,
            ExperimentSelection.instrument_id == instrument_id,
            ExperimentSelection.status == "accepted",
            ~_superseded(),
        )
    ):
        if ignore_id is not None and sel.id == ignore_id:
            continue
        try:
            window_end = rules.session_n(sel.entry_session, protocol.dedupe_sessions)
        except rules.CalendarMissingError:
            return True  # cannot tell when the earlier window ends: treat it as still open
        if entry <= window_end:
            return True
    return False


def _record(db: Session, **fields) -> ExperimentSelection:
    row = ExperimentSelection(**fields)
    db.add(row)
    db.flush()
    return row


def submit(
    db: Session,
    *,
    symbol: str,
    intended_horizon: int | None,
    note: str | None,
    user: str,
    now: datetime,
    protocol: Protocol = PROTOCOL_V1,
    supersedes_id: int | None = None,
    entry_override=None,
) -> ExperimentSelection:
    stored, cohort = ensure_owner_cohort(db, protocol)
    protocol = protocol_from_row(stored)  # the frozen rules, not today's settings
    symbol = (symbol or "").strip().upper()
    base = {
        "cohort_id": cohort.id,
        "symbol_at_entry": symbol,
        "intended_horizon": intended_horizon,
        "note": (note or None),
        "submitted_at": now,
        "submitted_by": user,
        "supersedes_id": supersedes_id,
    }

    def reject(reason: str, **extra) -> ExperimentSelection:
        return _record(db, status="rejected", reject_reason=reason, **base, **extra)

    if intended_horizon is not None and intended_horizon not in VALID_HORIZONS:
        return reject(f"Horizon must be one of {VALID_HORIZONS} trading days.")
    try:
        entry = entry_override or rules.entry_session(now, protocol.cutoff_ist)
        # Only the shortest horizon must be countable now; a longer one waits for its holiday list (scorer).
        rules.session_n(entry, min(protocol.horizons))
    except rules.CalendarMissingError as exc:
        return reject(str(exc))
    if not symbol:
        return reject("No stock given.", entry_session=entry)
    if symbol == settings.BENCHMARK_INDEX_SYMBOL.upper():
        return reject("That is the index used as a benchmark, not a stock.", entry_session=entry)
    inst = _instrument(db, symbol)
    if inst is None or (inst.segment or "").upper() == "INDICES":
        return reject("No NSE stock with this symbol.", entry_session=entry)
    if not _has_prices(db, inst.id):
        return reject(
            "This stock has no daily prices, so it cannot be scored.",
            entry_session=entry,
            instrument_id=inst.id,
        )
    # One pick per stock at a time, even when two requests arrive together: lock this (cohort, stock) pair.
    db.execute(text("SELECT pg_advisory_xact_lock(:c, :i)"), {"c": cohort.id, "i": inst.id})
    if _duplicate(db, cohort.id, inst.id, entry, protocol, ignore_id=supersedes_id):
        return reject(
            f"Already picked within the last {protocol.dedupe_sessions} sessions; one active pick per stock.",
            entry_session=entry,
            instrument_id=inst.id,
        )
    return _record(
        db, status="accepted", reject_reason=None, entry_session=entry, instrument_id=inst.id, **base
    )


def correct(
    db: Session,
    selection_id: int,
    *,
    symbol: str,
    intended_horizon: int | None,
    note: str | None,
    user: str,
    now: datetime,
    protocol: Protocol = PROTOCOL_V1,
) -> ExperimentSelection:
    """A new row that replaces an accepted pick, allowed only before its entry session's cutoff.

    The correction keeps the original entry session, so it cannot move a pick to a better day."""
    stored, _ = ensure_owner_cohort(db, protocol)
    protocol = protocol_from_row(stored)
    original = db.get(ExperimentSelection, selection_id)
    if original is None or original.status != "accepted":
        raise NotFoundError("No accepted pick with that id.")
    already = exists().where(
        ExperimentSelection.supersedes_id == selection_id, ExperimentSelection.status == "accepted"
    )
    if db.scalar(select(already)):
        raise NotFoundError("That pick has already been corrected; correct the newest one.")
    if now >= rules.cutoff_moment(original.entry_session, protocol.cutoff_ist):
        raise TooLateError("The entry session's 09:00 IST cutoff has passed; this pick can no longer change.")
    return submit(
        db,
        symbol=symbol,
        intended_horizon=intended_horizon,
        note=note,
        user=user,
        now=now,
        protocol=protocol,
        supersedes_id=selection_id,
        entry_override=original.entry_session,
    )
