"""The brain: module switches, runs and their decisions, and "why" for one stock.

Protected like /safety. The brain only ever records decisions here; nothing on
this router can place an order.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brain import service
from swing_trade_ml.brain.module import Mode
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

router = APIRouter(prefix="/brain", tags=["brain"])


class ModeUpdate(BaseModel):
    mode: Mode
    note: str | None = None
    by: str = "owner"


class RunCreate(BaseModel):
    kind: str = Field("nightly", pattern="^(nightly|intraday|why)$")
    symbols: list[str] | None = None
    as_of: datetime | None = None  # a past time makes it a replay
    book: str = Field("paper", pattern="^(paper|live)$")


class OverruleCreate(BaseModel):
    word: str
    reason: str
    by: str = "owner"

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say why you are overruling the brain.")
        return value


def _decision_out(d: BrainDecision) -> dict:
    return {
        "id": d.id,
        "run_id": d.run_id,
        "overruled_word": d.overruled_word,
        "overrule_reason": d.overrule_reason,
        "overruled_by": d.overruled_by,
        "overruled_at": d.overruled_at,
        "symbol": d.symbol,
        "kind": d.kind,
        "word": d.word,
        "reasons": d.reasons,
        "entry_low": d.entry_low,
        "entry_high": d.entry_high,
        "target": d.target,
        "stop": d.stop,
        "qty": d.qty,
        "horizon_days": d.horizon_days,
        "confidence": d.confidence,
        "evidence_text": d.evidence_text,
        "downgraded_from": d.downgraded_from,
        "downgrade_reason": d.downgrade_reason,
    }


def _run_summary(db, run: BrainRun) -> dict:
    decisions = service.decisions_for(db, run.id)
    return {
        "run_id": run.id,
        "kind": run.kind,
        "as_of": run.as_of,
        "live": run.live,
        "started_at": run.started_at,
        "ms": run.ms,
        "status": run.status,
        "error": run.error,
        "banner": {"mode": run.banner_mode, "headline": run.banner_headline},
        "counts": dict(Counter(d.word for d in decisions)),
    }


def _run_out(db, run: BrainRun) -> dict:
    decisions = service.decisions_for(db, run.id)
    return {
        "quality": run.quality,
        "error": run.error,
        "run_id": run.id,
        "kind": run.kind,
        "as_of": run.as_of,
        "book": run.book,
        "live": run.live,
        "started_at": run.started_at,
        "ms": run.ms,
        "status": run.status,
        "banner": {"mode": run.banner_mode, "headline": run.banner_headline},
        "modules": run.modules,
        "counts": dict(Counter(d.word for d in decisions)),
        "decisions": [_decision_out(d) for d in decisions],
    }


@router.get("/modules")
def list_modules(db: DbSession) -> dict:
    return {"steps": service.step_overview(), "modules": service.module_overview(db)}


@router.put("/modules/{module_id}")
def switch_module(module_id: str, payload: ModeUpdate, db: DbSession) -> dict:
    try:
        row = service.set_mode(db, module_id, payload.mode, by=payload.by, note=payload.note)
    except service.UnknownModuleError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.ModeRefusedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"module_id": row.module_id, "mode": row.mode}


@router.post("/runs")
def start_run(payload: RunCreate, db: DbSession) -> dict:
    _, run_id = service.run_brain(
        db, kind=payload.kind, as_of=payload.as_of, symbols=payload.symbols, book=payload.book
    )
    return _run_out(db, db.get(BrainRun, run_id))


@router.get("/runs/latest")
def latest(db: DbSession, kind: str | None = Query(None), include_replays: bool = Query(False)) -> dict:
    run = service.latest_run(db, kind, include_replays)
    if run is None:
        raise HTTPException(404, "The brain has not run yet.")
    return _run_out(db, run)


@router.get("/runs")
def list_runs(
    db: DbSession, kind: str | None = Query(None), limit: int = Query(20, ge=1, le=100)
) -> list[dict]:
    return [_run_summary(db, r) for r in service.list_runs(db, kind, limit)]


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: DbSession) -> dict:
    run = db.get(BrainRun, run_id)
    if run is None:
        raise HTTPException(404, "No such run.")
    return _run_out(db, run)


@router.post("/decisions/{decision_id}/overrule")
def overrule(decision_id: int, payload: OverruleCreate, db: DbSession) -> dict:
    try:
        d = service.overrule(db, decision_id, payload.word, payload.reason, payload.by)
    except service.UnknownDecisionError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.OverruleRefusedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _decision_out(d)


@router.get("/health")
def health(db: DbSession) -> dict:
    return service.health(db)


@router.get("/runs/{run_id}/trace")
def run_trace(run_id: str, db: DbSession) -> dict:
    run = db.get(BrainRun, run_id)
    if run is None:
        raise HTTPException(404, "No such run.")
    return {"run_id": run.id, "trace": run.trace}


@router.get("/why/{symbol}")
def why(symbol: str, db: DbSession, book: str = Query("paper", pattern="^(paper|live)$")) -> dict:
    _ctx, run_id = service.run_brain(db, kind="why", symbols=[symbol], book=book)
    run = db.get(BrainRun, run_id)
    decision = next((d for d in service.decisions_for(db, run_id) if d.symbol == symbol.upper()), None)
    return {
        "run_id": run_id,
        "banner": {"mode": run.banner_mode, "headline": run.banner_headline},
        "decision": _decision_out(decision) if decision else None,
        "trace": run.trace,
    }
