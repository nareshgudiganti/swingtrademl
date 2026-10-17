"""Horizon experiments (design rev 3): owner-only. Record picks, correct them before the cutoff, read outcomes
and
the report. Simulated research only; nothing here touches orders, positions or the brain."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession, Principal, actor_name, require_owner
from swing_trade_ml.db.models.experiments import ExperimentOutcome, ExperimentSelection
from swing_trade_ml.services.experiments import ledger, report
from swing_trade_ml.services.experiments.protocol import PROTOCOL_V1, ensure_owner_cohort
from swing_trade_ml.services.experiments.rules import IST

router = APIRouter(prefix="/experiments", tags=["experiments"], dependencies=[Depends(require_owner)])
Owner = Annotated[Principal, Depends(require_owner)]


class PickIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    intended_horizon: int | None = None
    note: str | None = Field(default=None, max_length=500)


def _now() -> datetime:
    return datetime.now(UTC)


def _selection_out(s: ExperimentSelection) -> dict[str, Any]:
    return {
        "id": s.id,
        "symbol": s.symbol_at_entry,
        "intended_horizon": s.intended_horizon,
        "note": s.note,
        "submitted_at": s.submitted_at.astimezone(IST).isoformat(),
        "submitted_by": s.submitted_by,
        "entry_session": s.entry_session.isoformat() if s.entry_session else None,
        "status": s.status,
        "reject_reason": s.reject_reason,
        "supersedes_id": s.supersedes_id,
    }


@router.get("/protocol", response_model=dict)
def protocol(db: DbSession) -> dict[str, Any]:
    row, _ = ensure_owner_cohort(db, PROTOCOL_V1)
    return {"code": row.code, "frozen_at": row.frozen_at.isoformat(), **row.params}


@router.post("/selections", response_model=dict)
def add_pick(body: PickIn, db: DbSession, principal: Owner) -> dict[str, Any]:
    sel = ledger.submit(
        db,
        symbol=body.symbol,
        intended_horizon=body.intended_horizon,
        note=body.note,
        user=actor_name(principal),
        now=_now(),
    )
    db.commit()
    return _selection_out(sel)


@router.post("/selections/{selection_id}/correct", response_model=dict)
def correct_pick(selection_id: int, body: PickIn, db: DbSession, principal: Owner) -> dict[str, Any]:
    try:
        sel = ledger.correct(
            db,
            selection_id,
            symbol=body.symbol,
            intended_horizon=body.intended_horizon,
            note=body.note,
            user=actor_name(principal),
            now=_now(),
        )
    except ledger.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ledger.TooLateError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return _selection_out(sel)


@router.get("/selections", response_model=list[dict])
def list_picks(db: DbSession) -> list[dict[str, Any]]:
    rows = db.scalars(select(ExperimentSelection).order_by(ExperimentSelection.id.desc()).limit(500))
    return [_selection_out(s) for s in rows]


@router.get("/outcomes", response_model=list[dict])
def list_outcomes(db: DbSession, horizon: int | None = Query(None)) -> list[dict[str, Any]]:
    q = (
        select(ExperimentOutcome, ExperimentSelection)
        .join(ExperimentSelection, ExperimentSelection.id == ExperimentOutcome.selection_id)
        .order_by(ExperimentOutcome.selection_id.desc(), ExperimentOutcome.horizon)
    )
    if horizon is not None:
        q = q.where(ExperimentOutcome.horizon == horizon)
    out = []
    for o, s in db.execute(q).all():
        out.append(
            {
                "selection_id": s.id,
                "symbol": s.symbol_at_entry,
                "intended_horizon": s.intended_horizon,
                "horizon": o.horizon,
                "state": o.state,
                "entry_session": s.entry_session.isoformat() if s.entry_session else None,
                "exit_session": o.exit_session.isoformat() if o.exit_session else None,
                "mark_session": o.mark_session.isoformat() if o.mark_session else None,
                "entry_price": o.entry_price,
                "exit_price": o.exit_price,
                "gross_return": o.gross_return,
                "net_return": o.net_return,
                "costs_inr": o.costs_inr,
                "slippage_inr": o.slippage_inr,
                "nifty_return": o.nifty_return,
                "universe_return": o.universe_return,
                "universe_count": o.universe_count,
                "buy_hold_return": o.buy_hold_return,
                "excess_vs_nifty": o.excess_vs_nifty,
                "excess_vs_universe": o.excess_vs_universe,
                "data_flags": o.data_flags or {},
                "scored_at": o.scored_at.isoformat(),
            }
        )
    return out


@router.get("/report", response_model=dict)
def get_report(db: DbSession, intended: int | None = Query(None)) -> dict[str, Any]:
    return report.build(db, today=datetime.now(IST).date(), intended=intended)
