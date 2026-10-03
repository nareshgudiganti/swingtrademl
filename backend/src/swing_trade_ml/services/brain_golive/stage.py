"""M18: the owner's switch between practice (shadow), approval and automatic.

Only `set_stage` writes a change, and only the owner endpoint calls it
(PUT /brain/stage). Nothing switches the brain on by itself
(test_nothing_but_the_stage_service_writes_a_stage_change)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.services.brain_golive.compare import NEEDED_FINISHED, finished_brain_ideas

STAGES = ("shadow", "approval", "auto")
NAMES = {"shadow": "practice (shadow)", "approval": "approval", "auto": "automatic"}
PLAIN = {
    "shadow": "Practice: the brain's ideas are recorded and scored next to version 1. Nothing is bought.",
    "approval": (
        "Your OK needed: each brain idea waits on the Brain page. Nothing is bought until you press Approve."
    ),
    "auto": (
        "Automatic: the brain's ideas are bought without asking, through version 1's normal safety checks. "
        "You can switch back to practice at any time."
    ),
}


class StageRefusedError(ValueError):
    """The message is shown to the owner as-is."""


def _latest(db: Session) -> BrainStageChange | None:
    return db.execute(
        select(BrainStageChange)
        .order_by(BrainStageChange.changed_at.desc(), BrainStageChange.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def current_stage(db: Session) -> str:
    row = _latest(db)
    return row.stage if row is not None else "shadow"


def set_stage(db: Session, stage: str, by: str, reason: str) -> BrainStageChange:
    if stage not in STAGES:
        raise StageRefusedError(f"{stage} is not a stage. Choose shadow, approval or auto.")
    reason = reason.strip()
    if not reason:
        raise StageRefusedError("Say why you are changing the stage.")
    now = current_stage(db)
    if stage == now:
        raise StageRefusedError(f"The brain is already in {NAMES[now]} mode.")
    if stage != "shadow":
        finished = finished_brain_ideas(db)
        if finished < NEEDED_FINISHED:
            raise StageRefusedError(
                f"Only {finished} of {NEEDED_FINISHED} brain ideas have finished so far. The brain stays in "
                f"practice until {NEEDED_FINISHED} have, so there is enough evidence to judge it."
            )
    if stage == "auto" and now != "approval":
        raise StageRefusedError(
            "Automatic trading can only follow the approval stage: approve the brain's ideas by hand first."
        )
    row = BrainStageChange(stage=stage, previous_stage=now, changed_by=by, reason=reason)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def stage_overview(db: Session, history_limit: int = 20) -> dict:
    stage = current_stage(db)
    finished = finished_brain_ideas(db)
    history = db.execute(
        select(BrainStageChange)
        .order_by(BrainStageChange.changed_at.desc(), BrainStageChange.id.desc())
        .limit(history_limit)
    ).scalars()
    return {
        "stage": stage,
        "plain": PLAIN[stage],
        "finished": finished,
        "needed": NEEDED_FINISHED,
        "ready": finished >= NEEDED_FINISHED,
        "history": [
            {
                "stage": h.stage,
                "previous_stage": h.previous_stage,
                "changed_by": h.changed_by,
                "reason": h.reason,
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            }
            for h in history
        ],
    }
