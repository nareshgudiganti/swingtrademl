"""M09 learning loop, task 4: proposals in the database — created, listed,
accepted or rejected, but never applied on their own (constitution C9).
Accepting a `buy_level` proposal needs nothing more here: the reader reads
`accepted_buy_level` itself. Accepting a `module_mode` proposal calls
`service.set_mode` now, under the owner's own accept."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m09_learn.proposals import Draft
from swing_trade_ml.db.models.brain import BrainLearningRun, BrainProposal


class UnknownProposalError(LookupError):
    pass


def create(db: Session, draft: Draft) -> BrainProposal | None:
    """None when an open proposal of the same kind already proposes the same
    change — the learning loop runs weekly and must not pile up duplicates."""
    open_same_kind = db.execute(
        select(BrainProposal).where(BrainProposal.status == "open", BrainProposal.kind == draft.kind)
    ).scalars()
    if any(row.change == draft.change for row in open_same_kind):
        return None
    row = BrainProposal(
        kind=draft.kind, title=draft.title, evidence=draft.evidence, change=dict(draft.change)
    )
    db.add(row)
    db.commit()
    return row


def list_proposals(db: Session, status: str | None = None) -> list[BrainProposal]:
    """Newest first."""
    stmt = select(BrainProposal)
    if status:
        stmt = stmt.where(BrainProposal.status == status)
    return list(db.execute(stmt.order_by(BrainProposal.created_at.desc(), BrainProposal.id.desc())).scalars())


def _decide(db: Session, proposal_id: int, status: str, by: str, note: str) -> BrainProposal:
    row = db.get(BrainProposal, proposal_id)
    if row is None:
        raise UnknownProposalError(f"No proposal {proposal_id}.")
    if row.status != "open":
        raise ValueError(f"Proposal {proposal_id} is not open.")
    row.status = status
    row.decided_by = by
    row.decided_at = datetime.now(UTC)
    row.decided_note = note
    return row


def _dismiss_other_open_buy_level_proposals(db: Session, by: str, except_id: int | None = None) -> None:
    """Accepting (or reverting) a buy level makes every other open
    buy_level proposal moot — there is only ever one buy level in force, so
    an old "raise it to 70%" sitting open next to the one just accepted
    would be a dangling suggestion nobody asked about any more."""
    stmt = select(BrainProposal).where(BrainProposal.status == "open", BrainProposal.kind == "buy_level")
    if except_id is not None:
        stmt = stmt.where(BrainProposal.id != except_id)
    for other in db.execute(stmt).scalars():
        other.status = "dismissed"
        other.decided_by = by
        other.decided_at = datetime.now(UTC)
        other.decided_note = "Replaced by a newer decision."


def accept(db: Session, proposal_id: int, by: str, note: str = "") -> BrainProposal:
    """Raises ValueError if the proposal is not open (also raised by
    `reject`); raises UnknownProposalError if it does not exist."""
    row = _decide(db, proposal_id, "accepted", by, note)
    if row.kind == "buy_level":
        _dismiss_other_open_buy_level_proposals(db, by, except_id=row.id)
    if row.kind == "module_mode":
        # Lazy: swing_trade_ml.brain.service imports swing_trade_ml.brain.modules,
        # which (via the M09 module, once registered) would otherwise import
        # this module eagerly and create an import cycle.
        from swing_trade_ml.brain import service

        try:
            service.set_mode(db, row.change["module"], row.change["mode"], by=by, note=note or None)
        except Exception:
            # The proposal was marked accepted above; undo that so a refused
            # change leaves it open instead of half-decided.
            db.rollback()
            raise
    db.commit()
    return row


def reject(db: Session, proposal_id: int, by: str, note: str = "") -> BrainProposal:
    row = _decide(db, proposal_id, "dismissed", by, note)
    db.commit()
    return row


def accepted_buy_level(db: Session) -> float | None:
    """`change["buy_level"]` of the most recently accepted `buy_level`
    proposal, or None while none has ever been accepted — or the owner's
    most recent decision was to go back to the default (`revert_buy_level`
    stores that as an accepted change of `{"buy_level": None}`)."""
    row = db.execute(
        select(BrainProposal)
        .where(BrainProposal.status == "accepted", BrainProposal.kind == "buy_level")
        .order_by(BrainProposal.decided_at.desc(), BrainProposal.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return None if row is None else row.change.get("buy_level")


def revert_buy_level(db: Session, by: str) -> BrainProposal:
    """The owner's way back to the default buy level: writes an already-
    accepted proposal whose change is null, so `accepted_buy_level` reads
    None again. Dismisses every other open buy_level proposal too, the same
    as a normal accept (constitution C9: this still only happens because
    the owner asked for it, right here)."""
    _dismiss_other_open_buy_level_proposals(db, by)
    row = BrainProposal(
        kind="buy_level",
        title="Go back to the default buy level",
        evidence="The owner chose to return to the default buy level.",
        change={"buy_level": None},
        status="accepted",
        decided_by=by,
        decided_at=datetime.now(UTC),
        decided_note="",
    )
    db.add(row)
    db.commit()
    return row


# --- learning runs (feature drift, checked weekly) ---------------------------


def record_learning_run(
    db: Session, drift: list[dict], drift_lines: list[str], drift_note: str | None
) -> BrainLearningRun:
    """Store one weekly check's drift result so the console can read it back
    without recomputing it (that walks every watch-listed stock's history)."""
    row = BrainLearningRun(drift=drift, drift_lines=drift_lines, drift_note=drift_note)
    db.add(row)
    db.commit()
    return row


def latest_learning_run(db: Session) -> BrainLearningRun | None:
    return db.execute(
        select(BrainLearningRun)
        .order_by(BrainLearningRun.created_at.desc(), BrainLearningRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
