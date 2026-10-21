"""M18: the brain beside version 1, the owner's trading stage, and approvals.

Separate from endpoints/brain.py on purpose: nothing on that router can place
an order, while the approvals here can (only through v1 execution, after the
owner's OK). Same gate: hidden while BRAIN_ENABLED is false."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from swing_trade_ml.api.deps import DbSession, PrincipalDep, actor_name
from swing_trade_ml.api.v1.endpoints.brain import _brain_switched_on
from swing_trade_ml.services.brain_golive import approvals, compare, stage

router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])


@router.get("/compare")
def compare_report(db: DbSession, since: date | None = Query(None)) -> dict:
    return compare.report(db, since)


TRIAL_MAX_DAYS = 200  # one trial is weeks long; a cap keeps one request from reading years of prices


@router.get("/trial-journal")
def trial_journal_report(
    db: DbSession,
    start: date = Query(..., alias="from"),
    end: date | None = Query(None, alias="to"),
) -> dict:
    """The forward trial's journal (layer-2 draft, section 5a): what the brain signalled each session,
    what following it would have done after costs, the baselines and the gate answer. Read-only."""
    from swing_trade_ml.brain.trial_journal import IST, journal_for, plain_report
    from swing_trade_ml.services import trial_seal

    if end is None:
        # Asking before the trial starts is fine: it simply has no sessions yet.
        end = max(datetime.now(IST).date(), start)
    if end < start:
        raise HTTPException(422, "'to' must be on or after 'from'.")
    if (end - start).days > TRIAL_MAX_DAYS:
        raise HTTPException(422, f"Ask for at most {TRIAL_MAX_DAYS} days at a time.")
    # The blind trial (services/trial_seal.py): a range reaching it shows counts only.
    journal = trial_seal.seal_journal(journal_for(db, start, end))
    return {"journal": journal, "report": plain_report(journal)}


class StageChange(BaseModel):
    stage: str = Field(pattern="^(shadow|approval|auto)$")
    reason: str
    by: str = Field(default="owner", min_length=1, max_length=128)

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say why you are changing the stage.")
        return value


@router.get("/stage")
def get_stage(db: DbSession) -> dict:
    return stage.stage_overview(db)


@router.put("/stage")
def change_stage(payload: StageChange, db: DbSession, principal: PrincipalDep) -> dict:
    """The owner's switch. Going back to practice (shadow) is always allowed.
    `payload.by` is accepted for old clients but ignored: the record names the signed-in caller."""
    try:
        stage.set_stage(db, payload.stage, by=actor_name(principal), reason=payload.reason)
    except stage.StageRefusedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return stage.stage_overview(db)


class ApprovalDecision(BaseModel):
    note: str = ""
    by: str = Field(default="owner", min_length=1, max_length=128)


class ApprovalRejection(BaseModel):
    reason: str
    by: str = Field(default="owner", min_length=1, max_length=128)

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say why you are rejecting this idea.")
        return value


@router.get("/approvals")
def list_approvals(
    db: DbSession,
    status: str | None = Query(None, pattern="^(pending|waiting|approved|rejected|expired)$"),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    approvals.expire_stale(db)
    return [approvals.approval_out(a) for a in approvals.list_approvals(db, status, limit)]


def _decide(action) -> dict:
    try:
        return approvals.approval_out(action())
    except approvals.ApprovalNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except approvals.ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: int, payload: ApprovalDecision, db: DbSession, principal: PrincipalDep) -> dict:
    """The owner's OK. Buys at once while the market is open; otherwise waits
    for the next open, where every check runs again (status "waiting")."""
    by = actor_name(principal)
    return _decide(lambda: approvals.approve(db, approval_id, by=by, note=payload.note))


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: int, payload: ApprovalRejection, db: DbSession, principal: PrincipalDep) -> dict:
    by = actor_name(principal)
    return _decide(lambda: approvals.reject(db, approval_id, by=by, reason=payload.reason))
