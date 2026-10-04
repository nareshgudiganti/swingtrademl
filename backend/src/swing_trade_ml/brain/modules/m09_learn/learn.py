"""M09 learning loop, task 5: the report the owner actually reads, and the
weekly job that scores, reports and proposes in one call.

score_pending (task 1) only flushes; store.create commits only when it
actually creates a proposal — so a caller that wants `run_learning`'s scoring
durable (the CLI, the weekly job) must `db.commit()` itself afterwards.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m09_learn import store
from swing_trade_ml.brain.modules.m09_learn.drift import MIN_RECENT_DAYS, drift_report, recent_bar_date_count
from swing_trade_ml.brain.modules.m09_learn.drift import drift_lines as drift_lines_for
from swing_trade_ml.brain.modules.m09_learn.failures import failure_patterns
from swing_trade_ml.brain.modules.m09_learn.proposals import buy_level_proposal
from swing_trade_ml.brain.modules.m09_learn.report import by_band, by_week, by_word, one_per_day
from swing_trade_ml.brain.modules.m09_learn.scoring import (
    SCORED_OUTCOMES,
    last_closed_trading_day,
    score_pending,
)
from swing_trade_ml.brain.reader import IST
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.ml.sector_map import get_sector_bucket

MIN_SCORED = 30
DRIFT_NEVER_CHECKED_NOTE = "Drift has not been checked yet — it is checked every Saturday."

_ROW_COLUMNS = (
    "run_id",
    "run_started",
    "decision_day",
    "symbol",
    "word",
    "confidence",
    "score_source",
    "outcome",
    "ret",
    "market",
    "sector",
)


def _market_label(context: dict | None) -> str | None:
    for s in (context or {}).get("situations", []):
        if s.get("scope") == "market":
            return s.get("label")
    return None


def _scored_rows(db: Session, since: date | None) -> pd.DataFrame:
    """One row per scored idea decision (`scoring.score_pending` already
    restricted these to live nightly runs — see its docstring), with the
    extra `market`/`sector` columns `failures.failure_patterns` needs."""
    stmt = (
        select(BrainDecision, BrainRun.started_at, BrainRun.as_of, BrainRun.context)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        # Superseded runs are hidden from Performance (owner decision
        # 2026-10-04); they stay stored for history.
        .where(BrainDecision.outcome.in_(SCORED_OUTCOMES), BrainRun.status == "done")
    )
    records = []
    if since is not None:
        # decision day = the run's as_of read in IST, so its first instant is
        # IST midnight of `since`.
        stmt = stmt.where(BrainRun.as_of >= datetime.combine(since, time(0, 0), tzinfo=IST))
    for decision, started_at, as_of, context in db.execute(stmt).all():
        decision_day = as_of.astimezone(IST).date()
        records.append(
            {
                "run_id": decision.run_id,
                "run_started": started_at,
                "decision_day": decision_day,
                "symbol": decision.symbol,
                "word": decision.word,
                "confidence": decision.confidence,
                "score_source": decision.score_source,
                "outcome": decision.outcome,
                "ret": decision.outcome_return,
                "market": _market_label(context),
                "sector": get_sector_bucket(decision.symbol),
            }
        )
    return pd.DataFrame(records, columns=list(_ROW_COLUMNS))


def learning_report(db: Session, since: date | None = None) -> dict:
    """Expected vs actual, grouped every way the owner might ask "is it
    working?" — plus any failure patterns and feature drift worth a look.
    `note` warns when there simply isn't enough graded history yet to trust
    any of it. Drift is never recomputed here (walking every watch-listed
    stock's history is far too slow for a page load, F3) — it reads back
    whatever the latest weekly `run_learning` stored."""
    rows = _scored_rows(db, since)
    n_scored = len(one_per_day(rows))
    # A confidence band only means something when every row in it is the
    # same kind of number; "model" is a raw ranking score, while a
    # calibrated chance (or no probability at all) reads on a different
    # scale, so mixing them into one band would be comparing apples to
    # oranges (F4).
    model_rows = rows[rows["score_source"] == "model"]
    stored = store.latest_learning_run(db)
    if stored is None:
        drift, drift_lines, drift_note = [], [], DRIFT_NEVER_CHECKED_NOTE
    else:
        drift, drift_lines, drift_note = stored.drift, stored.drift_lines, stored.drift_note
    note = (
        f"Only {n_scored} ideas have finished so far — too few to judge; keep collecting."
        if n_scored < MIN_SCORED
        else None
    )
    return {
        "since": since,
        "n_scored": n_scored,
        "by_band": by_band(model_rows),
        "by_word": by_word(rows),
        "by_week": by_week(rows),
        "failures": failure_patterns(rows),
        "drift": drift,
        "drift_lines": drift_lines,
        "drift_note": drift_note,
        "note": note,
    }


def _check_drift(db: Session) -> tuple[list[dict], list[str], str | None]:
    """Compute this week's drift and a plain note for why it is empty, when
    that is for a reason the owner should know about (not enough recent
    history yet) rather than just nothing having drifted."""
    drift = drift_report(db)
    lines = drift_lines_for(drift)
    note = None
    if not drift:
        n = recent_bar_date_count(db)
        if n < MIN_RECENT_DAYS:
            note = (
                "Not enough recent days yet to check whether the market has changed "
                f"({n} so far; needs {MIN_RECENT_DAYS})."
            )
    return drift, lines, note


def run_learning(db: Session, since: date | None = None, now: datetime | None = None) -> dict:
    """The weekly job (and `swingtrade brain learn`): score every idea whose
    outcome is now known, check feature drift and store it (F3), build the
    report, and propose a different buy level when the evidence plainly
    supports one (never applied by itself — the owner must accept it,
    constitution C9)."""
    # Never a partial day's bar: score up to the last fully closed trading day.
    upto = last_closed_trading_day(now or datetime.now(UTC))
    newly_scored = score_pending(db, upto)
    drift, drift_lines, drift_note = _check_drift(db)
    store.record_learning_run(db, drift, drift_lines, drift_note)
    report = learning_report(db, since)
    report["newly_scored"] = newly_scored
    rows = one_per_day(_scored_rows(db, since))
    model_rows = rows[rows["score_source"] == "model"]
    current = store.accepted_buy_level(db) or settings.ML_MIN_CONFIDENCE
    draft = buy_level_proposal(model_rows, current)
    new_proposals = []
    if draft is not None:
        created = store.create(db, draft)
        if created is not None:
            new_proposals.append(
                {"id": created.id, "kind": created.kind, "title": created.title, "evidence": created.evidence}
            )
    report["new_proposals"] = new_proposals
    return report
