# ruff: noqa: E501 (long explanatory lines)
"""The score ledger writer and reader (#389 S2, IDENTITY-CONTRACTS.md section 4).

Rules: write-once. The same key and the same value is a no-op; the same key with a DIFFERENT value is a new,
numbered revision that points at the one it replaces (`supersedes_id`); nothing is ever updated or deleted (the
database refuses it). A score that could not be produced is written as a `missing` row, never as 0 and never left
out for a stock that was meant to be scored. None of these functions commits; the caller does.

The key is (security, session date, horizon, source, model name, model version, revision). `session_date` is the
market session of the candle that was scored, never the clock day of the call.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.identity import (
    LEDGER_MISSING,
    LEDGER_SCORED,
    LEDGER_STATUSES,
    SOURCES,
    ScoreLedger,
)

_SAME = 1e-12
_ATTEMPTS = 4


@dataclass(frozen=True)
class LedgerResult:
    row_id: int
    revision: int
    created: bool  # False = the same value was already recorded (a retry): nothing was written


def _latest(
    db: Session,
    security_id: int,
    session_date: date,
    horizon_days: int | None,
    source: str,
    model_name: str,
    model_version: str,
) -> ScoreLedger | None:
    horizon = ScoreLedger.horizon_days.is_(None) if horizon_days is None else ScoreLedger.horizon_days == horizon_days
    return db.scalar(
        select(ScoreLedger)
        .where(
            ScoreLedger.security_id == security_id,
            ScoreLedger.session_date == session_date,
            horizon,
            ScoreLedger.source == source,
            ScoreLedger.model_name == model_name,
            ScoreLedger.model_version == model_version,
        )
        .order_by(ScoreLedger.revision.desc())
        .limit(1)
    )


def _same_value(row: ScoreLedger, score: float | None, status: str) -> bool:
    if row.status != status:
        return False
    if row.score is None or score is None:
        return row.score is None and score is None
    return abs(row.score - score) < _SAME


def append_score(
    db: Session,
    *,
    security_id: int,
    session_date: date,
    source: str,
    score: float | None,
    horizon_days: int | None = None,
    model_name: str = "",
    model_version: str = "",
    status: str = LEDGER_SCORED,
    model_id: int | None = None,
    scan_key: str | None = None,
    input_cutoff: datetime | None = None,
    run_ref: str | None = None,
    note: str | None = None,
) -> LedgerResult:
    """Record one score once. A retry is a no-op; a changed value is the next revision."""
    if status not in LEDGER_STATUSES:
        raise ValueError(f"unknown ledger status {status!r}")
    if source not in SOURCES:
        raise ValueError(f"unknown ledger source {source!r}")
    if status == LEDGER_SCORED and score is None:
        raise ValueError("a scored row needs a score; use append_missing for a gap")
    for _ in range(_ATTEMPTS):
        latest = _latest(db, security_id, session_date, horizon_days, source, model_name, model_version)
        if latest is not None and _same_value(latest, score, status):
            return LedgerResult(latest.id, latest.revision, False)
        values: dict[str, Any] = {
            "security_id": security_id,
            "session_date": session_date,
            "horizon_days": horizon_days,
            "source": source,
            "model_id": model_id,
            "model_name": model_name,
            "model_version": model_version,
            "score": score,
            "status": status,
            "scan_key": scan_key,
            "revision": 1 if latest is None else latest.revision + 1,
            "supersedes_id": None if latest is None else latest.id,
            "input_cutoff": input_cutoff,
            "run_ref": run_ref,
            "note": note,
        }
        row_id = db.execute(
            pg_insert(ScoreLedger).values(**values).on_conflict_do_nothing().returning(ScoreLedger.id)
        ).scalar_one_or_none()
        if row_id is not None:
            return LedgerResult(row_id, values["revision"], True)
        # Another writer took this revision a moment ago: look again (it may be the very same value).
    raise RuntimeError("the score ledger could not record this row after several attempts")


def append_missing(
    db: Session,
    *,
    security_id: int,
    session_date: date,
    source: str,
    reason: str,
    horizon_days: int | None = None,
    model_name: str = "",
    model_version: str = "",
    scan_key: str | None = None,
    status: str = LEDGER_MISSING,
) -> LedgerResult:
    """A gap is a row: the stock was meant to be scored that session and was not. Never a 0."""
    return append_score(
        db,
        security_id=security_id,
        session_date=session_date,
        source=source,
        score=None,
        horizon_days=horizon_days,
        model_name=model_name,
        model_version=model_version,
        status=status,
        scan_key=scan_key,
        note=reason,
    )


def append_missing_for_universe(
    db: Session,
    *,
    session_date: date,
    universe_security_ids: Iterable[int],
    scored_security_ids: Iterable[int],
    source: str,
    reason: str = "no score was produced for this stock in this scan",
    horizon_days: int | None = None,
    model_name: str = "",
    model_version: str = "",
    scan_key: str | None = None,
) -> int:
    """Write a `missing` row for every stock the scan was meant to cover and did not score. Returns rows written."""
    scored = set(scored_security_ids)
    written = 0
    for security_id in sorted(set(universe_security_ids) - scored):
        result = append_missing(
            db,
            security_id=security_id,
            session_date=session_date,
            source=source,
            reason=reason,
            horizon_days=horizon_days,
            model_name=model_name,
            model_version=model_version,
            scan_key=scan_key,
        )
        written += 1 if result.created else 0
    return written


def history(
    db: Session,
    security_id: int,
    *,
    view: str = "latest",
    horizon_days: int | None = None,
    source: str | None = None,
    since: date | None = None,
    until: date | None = None,
) -> list[ScoreLedger]:
    """One stock's rows, oldest session first. `view`: "latest" (the newest revision of each key; what a screen
    shows), "first" (revision 1 of each key; the evidence) or "all" (every revision). Gaps come back as rows
    with status 'missing'; a session with no row at all is simply absent."""
    if view not in ("latest", "first", "all"):
        raise ValueError("view must be latest, first or all")
    query = select(ScoreLedger).where(ScoreLedger.security_id == security_id)
    if horizon_days is not None:
        query = query.where(ScoreLedger.horizon_days == horizon_days)
    if source is not None:
        query = query.where(ScoreLedger.source == source)
    if since is not None:
        query = query.where(ScoreLedger.session_date >= since)
    if until is not None:
        query = query.where(ScoreLedger.session_date <= until)
    rows = list(db.scalars(query.order_by(ScoreLedger.session_date, ScoreLedger.id)))
    if view == "all":
        return rows
    best: dict[tuple, ScoreLedger] = {}
    for row in rows:
        key = (row.session_date, row.horizon_days, row.source, row.model_name, row.model_version)
        kept = best.get(key)
        if kept is None or (row.revision < kept.revision if view == "first" else row.revision > kept.revision):
            best[key] = row
    return sorted(best.values(), key=lambda r: (r.session_date, r.id))


def session_state(
    db: Session,
    security_ids: Iterable[int],
    session_date: date,
    *,
    horizon_days: int | None,
    source: str | None = None,
    model_name: str | None = None,
) -> dict[int, ScoreLedger | None]:
    """For each security, the newest revision recorded for one session, or None when nothing was recorded.

    A row with status `missing` or `stale` is an explicit gap (the stock was in the scan and no fresh score came
    out); None means the stock was not in any scan that session. Never read either as a score of 0."""
    ids = sorted(set(security_ids))
    query = select(ScoreLedger).where(
        ScoreLedger.security_id.in_(ids), ScoreLedger.session_date == session_date
    )
    # The horizon is required: one row per stock would let a 15-day score hide a 5-day gap. `None` asks for the rows
    # whose horizon is not known; pass a model name to tell two models of one horizon apart.
    query = query.where(
        ScoreLedger.horizon_days.is_(None) if horizon_days is None else ScoreLedger.horizon_days == horizon_days
    )
    if source is not None:
        query = query.where(ScoreLedger.source == source)
    if model_name is not None:
        query = query.where(ScoreLedger.model_name == model_name)
    best: dict[int, ScoreLedger] = {}
    for row in db.scalars(query.order_by(ScoreLedger.id)):
        kept = best.get(row.security_id)
        # a scored row outranks a gap row for the same stock and session; within a kind, the newest revision wins
        rank = (row.status == LEDGER_SCORED, row.revision, row.id)
        if kept is None or rank > (kept.status == LEDGER_SCORED, kept.revision, kept.id):
            best[row.security_id] = row
    return {i: best.get(i) for i in ids}


def append_from_brain_run(db: Session, run_id: str) -> int:
    """Record one finished brain run's decisions in the ledger (source `brain`), with the run id as provenance.

    The brain stores no model identity on a decision, so `model_name`/`model_version` stay empty (null, never
    guessed) and the decision's `score_source` goes in the note. A decision with no confidence is a `missing` row.
    A re-run of the same run is a no-op. On-demand `why` runs are not scans and are skipped. Returns rows written."""
    from swing_trade_ml.core.market_session import IST
    from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.services.identity import writer

    run = db.get(BrainRun, run_id)
    if run is None or run.kind == "why":
        return 0
    session_date = run.as_of.astimezone(IST).date()
    written = 0
    for decision in db.scalars(select(BrainDecision).where(BrainDecision.run_id == run_id)):
        instrument = db.scalar(
            select(Instrument).where(Instrument.exchange == "NSE", Instrument.tradingsymbol == decision.symbol)
        )
        if instrument is None:
            continue
        try:
            with db.begin_nested():
                security_id = writer.ensure_for_instrument(db, instrument)
        except writer.IdentityConflictError:
            continue
        note = f"brain {decision.kind}; score_source={decision.score_source or 'unknown'}"
        common = {
            "security_id": security_id,
            "session_date": session_date,
            "source": "brain",
            # None, not decision.horizon_days: the brain stamps a frozen default of 15 on a score that may come from a
            # 5-session model (#385). Until that is fixed the evidence ledger must not carry the label.
            "horizon_days": None,
            "scan_key": f"brain:{run.kind}:{session_date.isoformat()}:{run.book}",
            "run_ref": run_id,
        }
        if decision.confidence is None:
            result = append_score(db, score=None, status=LEDGER_MISSING, note="brain gave no score; " + note, **common)
        else:
            result = append_score(db, score=decision.confidence, note=note, **common)
        written += 1 if result.created else 0
    return written


def backfill_from_stock_scores(db: Session, *, since: date | None = None) -> int:
    """Copy the old one-row-a-day `stock_score_history` into the ledger as source `backfill` (#389 S5).

    The old table is never changed. Model name and version are copied exactly as stored (empty when the old row
    had none: never guessed); the horizon is unknown (None). Idempotent. Returns rows written."""
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import StockScore
    from swing_trade_ml.services.identity import writer

    query = select(StockScore, Instrument).join(Instrument, Instrument.id == StockScore.instrument_id)
    if since is not None:
        query = query.where(StockScore.as_of >= since)
    written = 0
    for score_row, instrument in db.execute(query.order_by(StockScore.as_of, StockScore.id)):
        try:
            with db.begin_nested():
                security_id = writer.ensure_for_instrument(db, instrument)
        except writer.IdentityConflictError:
            continue
        stored = score_row.model_version or ""
        result = append_score(
            db,
            security_id=security_id,
            session_date=score_row.as_of,
            source="backfill",
            score=score_row.score,
            model_name=score_row.model_name or "",
            model_version=stored.split(":", 1)[1][:64] if ":" in stored else "",
            note="backfilled from stock_score_history",
        )
        written += 1 if result.created else 0
    return written
