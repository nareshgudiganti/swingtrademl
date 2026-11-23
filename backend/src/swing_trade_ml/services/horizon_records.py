# ruff: noqa: E501 (long explanatory lines)
"""Write and read horizon recommendation records, keyed by the permanent stock identity (#387, #389).

Rules (the identity contract, section 2, in plain words): a record is written once. The same key and the same result
is a no-op (a retry adds nothing); the same key with a DIFFERENT result is the next numbered revision that points at
the one it replaces; nothing is ever updated or deleted (the database refuses it). `research_only` is stamped from the
versioned research config at write time, never taken from the caller, and `product_records` leaves research-only rows
out: that is the one reader a customer screen or a Brain decision may use. None of these functions commits.

The record is read by its attributes only (the dataclass of brain/horizons/workflow.py), so this module does not
import the Brain, and the Brain imports nothing from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from swing_trade_ml.core import research_config
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.services.identity import resolve

_SAME = 1e-12
_ATTEMPTS = 4


class UnknownSecurityError(ValueError):
    """The stock is not recognised. Nothing is created from a typo."""


class RecordLike(Protocol):
    decision_horizon: int
    symbol: str
    input_session: date
    evaluation_due_session: date | None
    decision: str
    reason: str
    model_name: str | None
    model_version: str | None
    score: float | None
    input_close: float | None
    policy_code: str | None
    target_pct: float | None
    stop_pct: float | None
    half_out_pct: float | None


@dataclass(frozen=True)
class SaveResult:
    row_id: int
    revision: int
    created: bool  # False = the same result was already recorded (a retry): nothing was written


def _num_same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < _SAME


def _same_result(row: HorizonRecordRow, values: dict[str, Any]) -> bool:
    return (
        row.decision == values["decision"]
        and row.evaluation_due_session == values["evaluation_due_session"]
        and row.policy_code == values["policy_code"]
        and row.research_config_version == values["research_config_version"]
        and row.research_config_sha256 == values["research_config_sha256"]
        and all(
            _num_same(getattr(row, k), values[k])
            for k in ("score", "input_close", "target_pct", "stop_pct", "half_out_pct")
        )
    )


def _latest(
    db: Session, security_id: int, session_date: date, horizon: int, model_id: int | None, model_version: str
) -> HorizonRecordRow | None:
    model = HorizonRecordRow.model_id.is_(None) if model_id is None else HorizonRecordRow.model_id == model_id
    return db.scalar(
        select(HorizonRecordRow)
        .where(
            HorizonRecordRow.security_id == security_id,
            HorizonRecordRow.session_date == session_date,
            HorizonRecordRow.horizon_days == horizon,
            model,
            HorizonRecordRow.model_version == model_version,
        )
        .order_by(HorizonRecordRow.revision.desc())
        .limit(1)
    )


def save_record(
    db: Session,
    record: RecordLike,
    *,
    security_id: int,
    model_id: int | None = None,
    scan_key: str | None = None,
    run_ref: str | None = None,
    input_cutoff: datetime | None = None,
    config_version: str | None = None,
) -> SaveResult:
    """Record one workflow result once. A retry is a no-op; a changed result is the next revision."""
    config = research_config.get_version(config_version) if config_version else research_config.active()
    rule = config.rule(record.decision_horizon)  # an unknown horizon is an error, never a guess
    model_version = record.model_version or ""
    for _ in range(_ATTEMPTS):
        latest = _latest(db, security_id, record.input_session, record.decision_horizon, model_id, model_version)
        values: dict[str, Any] = {
            "security_id": security_id,
            "session_date": record.input_session,
            "horizon_days": record.decision_horizon,
            "model_id": model_id,
            "model_name": record.model_name or "",
            "model_version": model_version,
            "decision": record.decision,
            "reason": record.reason,
            "score": record.score,
            "input_close": record.input_close,
            "evaluation_due_session": record.evaluation_due_session,
            "policy_code": record.policy_code,
            "target_pct": record.target_pct,
            "stop_pct": record.stop_pct,
            "half_out_pct": record.half_out_pct,
            "research_config_version": config.version,
            "research_config_sha256": config.sha256,
            "research_only": rule.research_only,
            "scan_key": scan_key,
            "run_ref": run_ref,
            "input_cutoff": input_cutoff,
        }
        if latest is not None and _same_result(latest, values):
            return SaveResult(latest.id, latest.revision, False)
        values["revision"] = 1 if latest is None else latest.revision + 1
        values["supersedes_id"] = None if latest is None else latest.id
        row_id = db.execute(
            pg_insert(HorizonRecordRow).values(**values).on_conflict_do_nothing().returning(HorizonRecordRow.id)
        ).scalar_one_or_none()
        if row_id is not None:
            return SaveResult(row_id, values["revision"], True)
        # Another writer took this revision a moment ago: look again (it may be the very same result).
    raise RuntimeError("the horizon record could not be written after several attempts")


def save_for_symbol(db: Session, record: RecordLike, **kwargs: Any) -> SaveResult:
    """Resolve the stock through the identity service first. An unknown stock is refused and nothing is written."""
    security_id = resolve(db, symbol=record.symbol)
    if security_id is None:
        raise UnknownSecurityError(f"stock {record.symbol!r} is not recognised")
    return save_record(db, record, security_id=security_id, **kwargs)


def records_for(
    db: Session,
    security_id: int,
    *,
    view: str = "latest",
    horizon_days: int | None = None,
    since: date | None = None,
    until: date | None = None,
    product_only: bool = False,
) -> list[HorizonRecordRow]:
    """One stock's records, oldest session first. `view`: "latest" (newest revision of each key; what a screen
    shows), "first" (revision 1; the evidence) or "all". Each horizon is its own line: nothing joins 5, 10 and 15.
    `product_only` leaves out every research-only row."""
    if view not in ("latest", "first", "all"):
        raise ValueError("view must be latest, first or all")
    query = select(HorizonRecordRow).where(HorizonRecordRow.security_id == security_id)
    if horizon_days is not None:
        query = query.where(HorizonRecordRow.horizon_days == horizon_days)
    if since is not None:
        query = query.where(HorizonRecordRow.session_date >= since)
    if until is not None:
        query = query.where(HorizonRecordRow.session_date <= until)
    if product_only:
        query = query.where(HorizonRecordRow.research_only.is_(False))
    rows = list(db.scalars(query.order_by(HorizonRecordRow.session_date, HorizonRecordRow.id)))
    if view == "all":
        return rows
    best: dict[tuple, HorizonRecordRow] = {}
    for row in rows:
        key = (row.session_date, row.horizon_days, row.model_id, row.model_version)
        kept = best.get(key)
        if kept is None or (row.revision < kept.revision if view == "first" else row.revision > kept.revision):
            best[key] = row
    return sorted(best.values(), key=lambda r: (r.session_date, r.id))


def product_records(db: Session, security_id: int, **kwargs: Any) -> list[HorizonRecordRow]:
    """The only reader for a customer screen or a Brain decision: research-only rows (10D, 15D) never appear."""
    return records_for(db, security_id, product_only=True, **kwargs)
