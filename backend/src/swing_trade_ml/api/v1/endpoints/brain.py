"""The brain: module switches, runs and their decisions, and "why" for one stock.

Protected like /safety. The brain only ever records decisions here; nothing on
this router can place an order.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brain import service
from swing_trade_ml.brain.alerts import service as alerts
from swing_trade_ml.brain.module import Mode
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainDecision, BrainProposal, BrainRun


def _brain_switched_on() -> None:
    """While the brain is off (BRAIN_ENABLED=false, the production default),
    its API does not exist — production looks exactly like it did before."""
    if not settings.BRAIN_ENABLED:
        raise HTTPException(404, "Not Found")


router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])


class ModeUpdate(BaseModel):
    mode: Mode
    note: str | None = None
    by: str = "owner"


class RunCreate(BaseModel):
    kind: str = Field("nightly", pattern="^(nightly|intraday|why)$")
    symbols: list[str] | None = None
    as_of: datetime | None = None  # a past time makes it a replay
    book: str = Field("paper", pattern="^(paper|live)$")

    @field_validator("as_of")
    @classmethod
    def _india_time_by_default(cls, value: datetime | None) -> datetime | None:
        """A time without a timezone is the owner's clock (India), not the server's."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        return value


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


class ProposalDecision(BaseModel):
    note: str = ""
    by: str = "owner"


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
        "sectors": (run.context or {}).get("sectors", []),
        "situations": (run.context or {}).get("situations", []),
        "portfolio": (run.context or {}).get("portfolio", {}),
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


class WhatIfIn(BaseModel):
    symbol: str
    qty: int = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    book: str = "paper"


@router.post("/whatif")
def what_if_trade(body: WhatIfIn, db: DbSession) -> dict:
    """What a planned trade would do to the portfolio (M14). Answers only; approves nothing."""
    from datetime import UTC, datetime

    from swing_trade_ml.brain.modules.m14_portfolio.whatif import what_if
    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.services import risk
    from swing_trade_ml.services.limits import limits_for
    from swing_trade_ml.services.portfolio import portfolio_value_and_cash

    symbol = body.symbol.strip().upper()
    price = body.price
    if price is None:
        last = DatedReader(db, datetime.now(UTC), live=True).last_close(symbol)
        if last is None:
            raise HTTPException(status_code=404, detail=f"No price for {symbol}; give one.")
        price = last[1]
    value, cash = portfolio_value_and_cash(db, body.book)
    limits = limits_for(value)
    holdings: dict[str, float] = {}
    for h in risk.open_holdings(db, body.book):
        holdings[h.tradingsymbol] = holdings.get(h.tradingsymbol, 0.0) + h.value
    return what_if(
        symbol,
        body.qty,
        price,
        value,
        cash,
        holdings,
        limits.max_position_pct,
        limits.sector_cap_pct if limits.sector_rule == "pct_cap" else None,
    )


@router.get("/track/{symbol}")
def holding_track(symbol: str, db: DbSession, book: str = Query("paper")) -> dict:
    """An open trade day by day against the band of similar trades (M15)."""
    from swing_trade_ml.brain.modules.m15_tracker.store import track_rows

    symbol = symbol.strip().upper()
    rows = track_rows(db, book, symbol)
    return {
        "symbol": symbol,
        "opened_on": rows[0].opened_on if rows else None,
        "points": [
            {
                "day": r.day,
                "day_n": r.day_n,
                "ret": r.ret,
                "status": r.status,
                "reason": r.reason,
                "stop": r.stop,
            }
            for r in rows
        ],
        "band": rows[-1].band if rows else [],
    }


@router.get("/episodes")
def market_episodes(db: DbSession) -> list[dict]:
    """Past market situations (M04), newest first."""
    from swing_trade_ml.brain.modules.m04_situations.store import market_episodes as load

    return [
        {
            "label": e.label,
            "start_day": e.start_day,
            "end_day": e.end_day,
            "days": (e.stats or {}).get("days"),
            "nifty_change": (e.stats or {}).get("nifty_change"),
        }
        for e in load(db)
    ]


@router.get("/runs/{run_id}/alerts")
def alert_preview(run_id: str, db: DbSession) -> dict:
    """What this run would tell the owner on Telegram (nothing is sent)."""
    if db.get(BrainRun, run_id) is None:
        raise HTTPException(404, "No such run.")
    return alerts.preview(db, run_id)


@router.post("/runs/{run_id}/alerts/send")
def alert_send(run_id: str, db: DbSession) -> dict:
    if db.get(BrainRun, run_id) is None:
        raise HTTPException(404, "No such run.")
    return alerts.send(db, run_id)


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


@router.get("/learning")
def learning(db: DbSession, since: date | None = Query(None)) -> dict:
    """The learning loop's report (M09): expected vs actual by confidence
    band, word and week, failure patterns and feature drift. Never changes
    anything by itself."""
    from swing_trade_ml.brain.modules.m09_learn.learn import learning_report

    return learning_report(db, since)


def _proposal_out(p: BrainProposal) -> dict:
    return {
        "id": p.id,
        "kind": p.kind,
        "title": p.title,
        "evidence": p.evidence,
        "change": p.change,
        "status": p.status,
        "created_at": p.created_at,
        "decided_by": p.decided_by,
        "decided_at": p.decided_at,
        "decided_note": p.decided_note,
    }


@router.get("/proposals")
def proposals(db: DbSession, status: str | None = Query(None)) -> list[dict]:
    from swing_trade_ml.brain.modules.m09_learn import store

    return [_proposal_out(p) for p in store.list_proposals(db, status)]


@router.post("/proposals/{proposal_id}/accept")
def accept_proposal(proposal_id: int, payload: ProposalDecision, db: DbSession) -> dict:
    """Constitution C9: nothing a proposal suggests takes effect until now."""
    from swing_trade_ml.brain.modules.m09_learn import store

    try:
        p = store.accept(db, proposal_id, payload.by, payload.note)
    except store.UnknownProposalError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _proposal_out(p)


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int, payload: ProposalDecision, db: DbSession) -> dict:
    from swing_trade_ml.brain.modules.m09_learn import store

    try:
        p = store.reject(db, proposal_id, payload.by, payload.note)
    except store.UnknownProposalError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _proposal_out(p)
