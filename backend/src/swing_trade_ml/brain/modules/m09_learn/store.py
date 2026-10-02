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
from swing_trade_ml.db.models.brain import BrainProposal


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


def accept(db: Session, proposal_id: int, by: str, note: str = "") -> BrainProposal:
    """Raises ValueError if the proposal is not open (also raised by
    `reject`); raises UnknownProposalError if it does not exist."""
    row = _decide(db, proposal_id, "accepted", by, note)
    if row.kind == "module_mode":
        # Lazy: swing_trade_ml.brain.service imports swing_trade_ml.brain.modules,
        # which (via the M09 module, once registered) would otherwise import
        # this module eagerly and create an import cycle.
        from swing_trade_ml.brain import service

        service.set_mode(db, row.change["module"], row.change["mode"], by=by, note=note or None)
    db.commit()
    return row


def reject(db: Session, proposal_id: int, by: str, note: str = "") -> BrainProposal:
    row = _decide(db, proposal_id, "dismissed", by, note)
    db.commit()
    return row


def accepted_buy_level(db: Session) -> float | None:
    """`change["buy_level"]` of the most recently accepted `buy_level`
    proposal, or None while none has ever been accepted."""
    row = db.execute(
        select(BrainProposal)
        .where(BrainProposal.status == "accepted", BrainProposal.kind == "buy_level")
        .order_by(BrainProposal.decided_at.desc(), BrainProposal.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return None if row is None else row.change.get("buy_level")
