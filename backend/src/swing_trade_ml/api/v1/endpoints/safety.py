"""The kill switch, and the log of entries the risk layer refused.

Protected, unlike /system's health probes: anyone who can halt the bot can
stop it trading, and anyone who can read risk events can read the book's
sector exposure from them.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.schemas import HaltRequest, ResumeRequest, RiskEventOut, SystemStateOut
from swing_trade_ml.services import system_state

router = APIRouter(prefix="/safety", tags=["safety"])


@router.get("/state", response_model=SystemStateOut)
def get_state(db: DbSession) -> SystemStateOut:
    return SystemStateOut.model_validate(system_state.get_state(db))


@router.post("/halt", response_model=SystemStateOut)
def halt(payload: HaltRequest, db: DbSession) -> SystemStateOut:
    """Stop all new entries immediately. Exits keep running — this can never
    trap capital in a position heading for its stop."""
    return SystemStateOut.model_validate(system_state.halt(db, payload.reason, payload.by))


@router.post("/resume", response_model=SystemStateOut)
def resume(payload: ResumeRequest, db: DbSession) -> SystemStateOut:
    return SystemStateOut.model_validate(system_state.resume(db, payload.by))


@router.get("/risk-events", response_model=list[RiskEventOut])
def risk_events(db: DbSession, limit: int = Query(50, ge=1, le=500)) -> list[RiskEvent]:
    """Newest first — the interesting question is always "what got blocked
    today", not "what got blocked when this started running"."""
    return list(
        db.execute(select(RiskEvent).order_by(RiskEvent.ts.desc(), RiskEvent.id.desc()).limit(limit))
        .scalars()
        .all()
    )
