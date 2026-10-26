"""M18: the owner's switch between practice (shadow), approval and automatic.

Only `set_stage` writes a change. The owner endpoint (PUT /brain/stage) is the
only caller that can move the brain forward; switching the brain strategy off and
the owner's pause rules (pause_rules.py, ps7) can only move it back to practice.
Nothing switches the brain on by itself
(test_nothing_but_the_stage_service_writes_a_stage_change)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain_golive import BrainApproval, BrainStageChange
from swing_trade_ml.services import trial_seal
from swing_trade_ml.services.brain_golive.compare import (
    NEEDED_FINISHED,
    finished_blocked_brain_ideas,
    finished_brain_ideas,
)

STAGES = ("shadow", "approval", "auto")
AUTO_BY = "automatic stage"  # decided_by on an OK the automatic stage gave (approvals.py)
ROLLBACK_NOTE = (
    "Switched back to practice mode (shadow), so this idea will not be bought. Nothing was bought. "
    "Stocks the brain already holds keep version 1's normal stop, target and time-stop exits."
)
HANDED_BACK_NOTE = (
    "The automatic stage approved this, but it was switched off before the market opened, "
    "so it is waiting for your OK again."
)
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


def trial_gate(db: Session) -> dict:
    """The forward trial's agreed pass rule (layer-2 protocol 5a), from the trial journal: sessions and
    finished brain TRADE ideas counted from the trial's start, profit after costs, and beating every
    stock. Its "word" is "too early", "pass" or "behind". Before 2026-10-14 the switch only counted 30
    finished ideas over all history, so ideas from before the trial could have opened it."""
    from swing_trade_ml.brain.trial_journal import IST, TRIAL_START, journal_for

    today = datetime.now(IST).date()
    return journal_for(db, TRIAL_START, max(today, TRIAL_START))["gate"]


def _trial_gate_or_closed(db: Session) -> dict:
    """A gate that cannot be worked out is a gate that stays shut."""
    try:
        return trial_gate(db)
    except Exception as exc:  # noqa: BLE001 - fail closed: the switch must never open on an error
        return {"word": "error", "error": str(exc)}


def _trial_refusal(g: dict) -> str:
    if g["word"] == "error":
        return (
            "The trial result could not be checked just now, so the brain stays in practice. "
            "Try again later; nothing was changed."
        )
    if trial_seal.active():
        # The blind trial (services/trial_seal.py): say only the counts, never why the gate refused.
        return f"{trial_seal.GATE_SEALED_TEXT} {trial_seal.gate_counts_text(g)} The brain stays in practice."
    yes_no = {True: "yes", False: "no"}
    facts = (
        f"{g.get('sessions', 0)} of 15 trial sessions, {g.get('finished', 0)} of {NEEDED_FINISHED} finished "
        f"brain ideas since the trial started; profit after costs: {yes_no[bool(g.get('profit'))]}; "
        f"beats buying every stock: {yes_no[bool(g.get('beats_random'))]}."
    )
    if g["word"] == "behind":
        missing = [] if g.get("profit") else ["made no profit after costs"]
        if not g.get("beats_random"):
            missing.append("did not beat buying every stock")
        why = " and ".join(missing) or "is behind"
        return f"The trial is complete, but the brain {why}. {facts} It stays in practice."
    return f"The forward trial has not passed yet: {facts} The brain stays in practice until it does."


def _latest(db: Session) -> BrainStageChange | None:
    """Newest by insert order (id), never by changed_at: the app clock can step
    back, and an older "auto" row must never outrank a later rollback."""
    return db.execute(
        select(BrainStageChange).order_by(BrainStageChange.id.desc()).limit(1)
    ).scalar_one_or_none()


def current_stage(db: Session) -> str:
    row = _latest(db)
    return row.stage if row is not None and row.stage in STAGES else "shadow"  # fail closed


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
        gate = _trial_gate_or_closed(db)
        if gate["word"] != "pass":
            raise StageRefusedError(_trial_refusal(gate))
    if stage == "auto" and now != "approval":
        raise StageRefusedError(
            "Automatic trading can only follow the approval stage: approve the brain's ideas by hand first."
        )
    _settle_approvals(db, stage, now, by)
    row = BrainStageChange(stage=stage, previous_stage=now, changed_by=by, reason=reason)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


SWITCHED_OFF_REASON = "Brain strategy switched off"


def brain_strategy_switched_off(db: Session, by: str = "owner") -> None:
    """Deactivating the brain strategy also returns the stage to practice, so
    switching it back on never silently resumes approval or automatic buying.
    Positions already held keep version 1's exits."""
    now = current_stage(db)
    if now == "approval" or now == "auto":
        set_stage(db, "shadow", by=by, reason=SWITCHED_OFF_REASON)


def _settle_approvals(db: Session, stage: str, previous: str, by: str) -> None:
    """Rollback stops NEW buys only (owner decision 2): ideas waiting for an OK
    and OKs not yet bought expire; open brain positions are left to v1's exits.
    Leaving the automatic stage hands its not-yet-bought OKs back to the owner."""
    if stage == "shadow":
        db.execute(
            update(BrainApproval)
            .where(BrainApproval.status.in_(("pending", "waiting")))
            .values(status="expired", decided_by=by, decided_at=datetime.now(UTC), decided_note=ROLLBACK_NOTE)
            .execution_options(synchronize_session="fetch")
        )
    elif previous == "auto":
        db.execute(
            update(BrainApproval)
            .where(BrainApproval.status == "waiting", BrainApproval.decided_by == AUTO_BY)
            .values(
                status="pending",
                decided_by=None,
                decided_at=None,
                decided_note=None,
                result_note=HANDED_BACK_NOTE,
            )
            .execution_options(synchronize_session="fetch")
        )


def stage_overview(db: Session, history_limit: int = 20) -> dict:
    stage = current_stage(db)
    finished = finished_brain_ideas(db)
    gate = _trial_gate_or_closed(db)
    history = db.execute(
        select(BrainStageChange).order_by(BrainStageChange.id.desc()).limit(history_limit)
    ).scalars()
    sealed = trial_seal.active()
    if sealed:
        # Blind trial: show only the counts. "ready" says the counts are met, never that the trial
        # passed; set_stage still applies the full gate and refuses with the sealed text if it is not met.
        shown = trial_seal.sealed_gate(gate)
        ready = finished >= NEEDED_FINISHED and bool(shown.get("counts_met"))
        if gate["word"] == "error":
            plain = _trial_refusal(gate)
        else:
            plain = f"{trial_seal.gate_counts_text(shown)} {trial_seal.SEALED_TEXT}"
    else:
        shown = gate
        # Ready only when both hold: the 30 finished ideas and the forward trial's pass rule.
        ready = finished >= NEEDED_FINISHED and gate["word"] == "pass"
        plain = None if gate["word"] == "pass" else _trial_refusal(gate)
    return {
        "stage": stage,
        "plain": PLAIN[stage],
        "finished": finished,
        "finished_blocked": finished_blocked_brain_ideas(db),
        "needed": NEEDED_FINISHED,
        "ready": ready,
        "sealed": sealed,
        "trial": shown,
        "trial_plain": plain,
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
