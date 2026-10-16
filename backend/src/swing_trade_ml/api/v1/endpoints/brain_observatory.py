"""Brain Observatory, Phase 1A (spec docs/superpowers/specs/2026-10-15-brain-observatory-design.md).

Owner only, GET only. Every request reads through its own READ ONLY, time-limited transaction
(services/brain_observatory/db.py) and every response passes through the free-text redaction.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from swing_trade_ml.api.deps import require_owner
from swing_trade_ml.core.config import settings
from swing_trade_ml.services.brain_observatory import counts, health, outcomes, queries, schedule, verdicts
from swing_trade_ml.services.brain_observatory.db import get_readonly_db
from swing_trade_ml.services.brain_observatory.redact import redact_response

IST = schedule.IST
MAX_DAYS = 92
RECORDING_CARD = "Existing records only — partial visibility."
NOT_RECORDED_1A = "Not recorded in Phase 1A"
DEFERRED = "Not recorded — decision-path recording deferred during trial"
NOT_RECORDED_LIST = [
    "Each module's opinion on each stock, including shadow modules",
    "The risk verdict per stock",
    "The sector and rank used for each stock",
    "The decision path: which rule or module changed a decision (deferred during the trial)",
    "Code, model and settings versions of each run",
]


def _brain_on() -> None:
    if not settings.BRAIN_ENABLED:
        raise HTTPException(404, "Not Found")


def get_now() -> datetime:
    return datetime.now(IST)


ReadOnlyDb = Annotated[Session, Depends(get_readonly_db)]
Now = Annotated[datetime, Depends(get_now)]
router = APIRouter(
    prefix="/brain/observatory",
    tags=["brain-observatory"],
    dependencies=[Depends(_brain_on), Depends(require_owner)],
)


def _range(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(422, "'to' must be on or after 'from'.")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"Ask for at most {MAX_DAYS} days at a time.")


def _run_summary(r) -> dict:
    return {
        "id": r.id,
        "kind": r.kind,
        "live": r.live,
        "status": r.status,
        "book": r.book,
        "as_of": r.as_of.isoformat(),
        "day": schedule.run_day(r.as_of).isoformat(),
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "ms": r.ms,
        "error": r.error,
    }


def _brief(r) -> dict:
    return {"id": r.id, "kind": r.kind, "live": r.live, "status": r.status}


@router.get("/days")
def days(
    db: ReadOnlyDb,
    now: Now,
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
) -> dict:
    _range(start, end)
    by_day: dict[date, list] = {}
    for r in queries.runs_between(db, start, end):
        by_day.setdefault(schedule.run_day(r.as_of), []).append(r)
    nightly = {d: schedule.nightly_state(d, now, [_brief(r) for r in rs]) for d, rs in by_day.items()}
    nightly_ids = {d: s["run_id"] for d, s in nightly.items() if s["state"] == "observed"}
    words: dict[str, list] = {}
    for run_id, kind, word, n in queries.word_rows(db, list(nightly_ids.values())):
        words.setdefault(run_id, []).append((kind, word, n))
    universe = queries.universe_by_run(db, list(nightly_ids.values()))
    tracked = queries.tracked_by_day(db, start, end)
    signals = queries.brain_signals_by_day(db, start, end)
    orders = queries.brain_orders_by_day(db, start, end)
    out = []
    d = start
    while d <= end:
        rs = by_day.get(d, [])
        state = nightly.get(d) or schedule.nightly_state(d, now, [])
        run_id = nightly_ids.get(d)
        out.append(
            {
                "day": d.isoformat(),
                "nightly": state,
                "counts": counts.word_counts(words.get(run_id, [])) if run_id else None,
                "universe": universe.get(run_id) if run_id else None,
                "intraday": {
                    **schedule.intraday_expectation(d, now),
                    "recorded": sum(1 for r in rs if r.kind == "intraday"),
                },
                "tracked": {"by_book": tracked.get(d, {}), "label": "day-level context, not linked to a run"},
                "signals": {"by_mode": signals.get(d, {}), "label": "not linked to a specific run"},
                "paper_orders": {"by_mode": orders.get(d, {}), "label": "not linked to a specific run"},
                "other_runs": [_brief(r) for r in rs if r.id != run_id],
            }
        )
        d += timedelta(days=1)
    return redact_response({"days": out})


@router.get("/runs")
def runs(
    db: ReadOnlyDb,
    now: Now,
    day: date = Query(..., alias="date"),
    after_started_at: datetime | None = None,
    after_id: str | None = None,
    limit: int = Query(200, ge=1, le=queries.PAGE_MAX),
) -> dict:
    after = (after_started_at, after_id) if after_started_at and after_id else None
    rows = queries.runs_on(db, day, after, limit)
    page, more = rows[:limit], len(rows) > limit
    last = page[-1] if page else None
    return redact_response(
        {
            "date": day.isoformat(),
            "nightly": schedule.nightly_state(day, now, queries.nightly_runs_on(db, day)),
            "intraday": schedule.intraday_expectation(day, now),
            "items": [_run_summary(r) for r in page],
            "next_cursor": {"after_started_at": last.started_at.isoformat(), "after_id": last.id}
            if more and last
            else None,
        }
    )


@router.get("/runs/{run_id}")
def run_detail(run_id: str, db: ReadOnlyDb) -> dict:
    r = queries.run(db, run_id)
    if r is None:
        raise HTTPException(404, "No such run.")
    rows = health.module_rows(r.kind, r.modules, r.trace, health.current_step_map())
    fallbacks = health.step_fallbacks(r.trace)
    wc = counts.word_counts([(k, w, n) for _, k, w, n in queries.word_rows(db, [r.id])])
    ctx = r.context or {}
    manifest = ctx.get("data_manifest") or {}
    return redact_response(
        {
            "run": _run_summary(r),
            "headline": health.headline(r.status, rows, fallbacks),
            "banner": {"mode": r.banner_mode, "headline": r.banner_headline},
            "modules": rows,
            "counts": health.flag_counts(rows),
            "step_fallbacks": fallbacks,
            "outside_steps": health.outside_rows(
                r.kind, r.live, r.status, r.alerts_checked_at, queries.alerts_sent(db, r.id)
            ),
            "stage_that_day": {
                "stage": queries.stage_on(db, schedule.run_day(r.as_of)),
                "label": "day context, not part of this run",
            },
            "words": wc,
            "universe_relation": counts.idea_relation(
                manifest.get("universe_count"), wc["ideas_total"], wc["holdings_total"]
            ),
            "quality": r.quality or {"state": "not_observed"},
            "sectors": {"state": "observed", "items": ctx["sectors"]}
            if "sectors" in ctx
            else {"state": "not_observed"},
            "situations": ctx.get("situations", {"state": "not_observed"}),
            "data_manifest": manifest or {"state": "not_observed"},
            "recording": {
                "card": RECORDING_CARD,
                "phase": "1A",
                "not_recorded": NOT_RECORDED_LIST,
                "versions": NOT_RECORDED_1A,
            },
        }
    )


def _decision_brief(d) -> dict:
    return {
        "id": d.id,
        "symbol": d.symbol,
        "kind": d.kind,
        "word": d.word,
        "confidence": d.confidence,
        "score_source": d.score_source,
    }


@router.get("/runs/{run_id}/stocks")
def stocks(
    run_id: str,
    db: ReadOnlyDb,
    after_id: int | None = None,
    limit: int = Query(200, ge=1, le=queries.PAGE_MAX),
    symbol: str | None = None,
) -> dict:
    if queries.run(db, run_id) is None:
        raise HTTPException(404, "No such run.")
    rows = queries.decisions(db, run_id, after_id, limit, symbol)
    page, more = rows[:limit], len(rows) > limit
    return redact_response(
        {
            "items": [_decision_brief(d) for d in page],
            "next_cursor": {"after_id": page[-1].id} if more and page else None,
        }
    )


@router.get("/runs/{run_id}/stocks/{decision_id}")
def stock_detail(run_id: str, decision_id: int, db: ReadOnlyDb) -> dict:
    d = queries.decision(db, decision_id)
    r = queries.run(db, run_id)
    if d is None or r is None or d.run_id != run_id:
        raise HTTPException(404, "No such decision in this run.")
    snap = queries.snapshot_for_run(db, run_id, d.symbol)
    quality = r.quality or {}
    day = schedule.run_day(r.as_of)
    overrule = None
    if d.overruled_word is not None:
        overrule = {
            "word": d.overruled_word,
            "overrule_reason": d.overrule_reason,
            "at": d.overruled_at.isoformat() if d.overruled_at else None,
            "by": "owner",
        }
    outcome = None
    if d.outcome is not None:
        outcome = {
            "outcome": d.outcome,
            "gross_return": d.outcome_return,
            "days": d.outcome_days,
            "max_up": d.max_up,
            "max_down": d.max_down,
            "resolved_on": d.resolved_on.isoformat() if d.resolved_on else None,
            "source": outcomes.SOURCES["stored_grade"],
        }
    features = (
        {
            "state": "observed",
            "bar_date": snap.bar_date.isoformat(),
            "close": snap.close,
            "atr_14": snap.atr_14,
            "adv_inr_20": snap.adv_inr_20,
            "features": snap.features,
        }
        if snap
        else {"state": "not_observed", "why": "No feature snapshot stored by this run for this stock."}
    )
    return redact_response(
        {
            "decision": {
                **_decision_brief(d),
                "entry_low": d.entry_low,
                "entry_high": d.entry_high,
                "target": d.target,
                "stop": d.stop,
                "qty": d.qty,
                "horizon_days": d.horizon_days,
                "reasons": list(d.reasons or []),
                "evidence_text": d.evidence_text,
                "downgraded_from": d.downgraded_from,
                "downgrade_reason": d.downgrade_reason,
                "downgrade_label": "as stored: the word before any downgrade, and the last downgrade reason; "
                "not a path",
                "overrule": overrule,
                "outcome": outcome,
            },
            "features": features,
            "stale": {
                "listed_stale": d.symbol in quality.get("stale", []),
                "note": "Not listed means fresh or not assessed.",
            }
            if "stale" in quality
            else {"state": "not_observed"},
            "tracker": {
                "book": r.book,
                "label": "tracker records for this stock on this day: day-level context, "
                "not linked to this run",
                "rows": [
                    {
                        "day": t.day.isoformat(),
                        "day_n": t.day_n,
                        "ret": t.ret,
                        "status": t.status,
                        "reason": t.reason,
                    }
                    for t in queries.track_rows(db, d.symbol, day, r.book)
                ],
            },
            "instrument": {
                "label": "current instrument master, not recorded by the run",
                "current": [
                    {"exchange": i.exchange, "instrument_token": i.instrument_token}
                    for i in queries.instruments(db, d.symbol)
                ],
            },
            "influence": {
                "state": "not_recorded_1a",
                "text": "Influence on this stock: Not recorded in Phase 1A.",
            },
            "not_recorded": {
                "opinions": NOT_RECORDED_1A,
                "risk_verdict": NOT_RECORDED_1A,
                "stock_state": NOT_RECORDED_1A,
                "sector_used": NOT_RECORDED_1A,
                "decision_path": DEFERRED,
                "why_no_trade": DEFERRED,
            },
        }
    )


@router.get("/learning")
def learning(
    db: ReadOnlyDb,
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
) -> dict:
    _range(start, end)
    claims = {c["claim"]: c for c in verdicts.evaluate(verdicts.load_registry())}
    return redact_response(
        {
            **queries.learning_summary(db, start, end, settings.TRADING_MODE),
            "proven_improvement": claims["learning_changes"],
            "note": "Only M09 activity counts as learning: results collected, changes proposed, "
            "changes accepted.",
        }
    )


@router.get("/outcomes")
def outcomes_route(
    db: ReadOnlyDb,
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
    category: str = Query(..., pattern="^(practice|backtest|paper)$"),
) -> dict:
    _range(start, end)
    return redact_response(outcomes.build(db, start, end, category))


@router.get("/forward-gate")
def forward_gate(db: ReadOnlyDb, now: Now) -> dict:
    """The official forward gate over the established trial cohort; never depends on a page's date range."""
    return redact_response(outcomes.official_forward_gate(db, now.date()))


@router.get("/effectiveness")
def effectiveness() -> dict:
    registry = verdicts.load_registry()
    return redact_response(
        {"claims": verdicts.evaluate(registry), "rejected_entries": verdicts.rejected_entries(registry)}
    )
