"""M18: the brain beside version 1, the owner's trading stage, and approvals.

Separate from endpoints/brain.py on purpose: nothing on that router can place
an order, while the approvals here can (only through v1 execution, after the
owner's OK). Same gate: hidden while BRAIN_ENABLED is false."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.api.v1.endpoints.brain import _brain_switched_on
from swing_trade_ml.services.brain_golive import compare, stage

router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])


@router.get("/compare")
def compare_report(db: DbSession, since: date | None = Query(None)) -> dict:
    return compare.report(db, since)


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
def change_stage(payload: StageChange, db: DbSession) -> dict:
    """The owner's switch. Going back to practice (shadow) is always allowed."""
    try:
        stage.set_stage(db, payload.stage, by=payload.by, reason=payload.reason)
    except stage.StageRefusedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return stage.stage_overview(db)
