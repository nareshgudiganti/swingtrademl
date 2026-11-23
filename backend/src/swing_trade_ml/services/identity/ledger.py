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
