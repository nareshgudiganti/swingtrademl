# ruff: noqa: N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""h05 lane: owner-only, read-only. The 5-trading-day evaluation of the existing models.

GET only. Nothing here starts a run, scores a day, places an order or touches the brain; the lane's
switches live in the lane itself (LANE_H05_*)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from swing_trade_ml.api.deps import DbSession, require_owner
from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_report

router = APIRouter(prefix="/research/h05", tags=["h05"], dependencies=[Depends(require_owner)])


@router.get("/protocol")
def protocol() -> dict:
    s = P.H05Settings()
    return {
        "title": P.PAGE_LABEL,
        "protocol_code": P.PROTOCOL_CODE,
        "protocol_hash": P.protocol_hash(),
        "enabled": s.ENABLED,
        "accepted": P.protocol_hash() == s.ACCEPTED_PROTOCOL_HASH,
        "missing_values": P.missing_values(),
        "unresolved": [list(u) for u in P.UNRESOLVED],
        "scoring_label": P.SCORING_LABEL,
        "slippage_status": P.SLIPPAGE_STATUS,
        "cost_units": P.COST_UNITS,
        "rules": P.RULES,
        "models": P.EXPECTED_MODELS,
        "earlier_evidence": P.EARLIER_EVIDENCE,
    }


@router.get("/report")
def report(db: DbSession, run_no: int | None = Query(default=None, ge=1, le=3)) -> dict:
    return h05_report.build_report(db, run_no)
