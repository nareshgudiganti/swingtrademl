"""M09 learning loop, task 5: the report the owner actually reads, and the
weekly job that scores, reports and proposes in one call.

score_pending (task 1) only flushes; store.create commits only when it
actually creates a proposal — so a caller that wants `run_learning`'s scoring
durable (the CLI, the weekly job) must `db.commit()` itself afterwards.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m09_learn import store
from swing_trade_ml.brain.modules.m09_learn.drift import drift_lines as drift_lines_for
from swing_trade_ml.brain.modules.m09_learn.drift import drift_report
from swing_trade_ml.brain.modules.m09_learn.failures import failure_patterns
from swing_trade_ml.brain.modules.m09_learn.proposals import buy_level_proposal
from swing_trade_ml.brain.modules.m09_learn.report import by_band, by_week, by_word, one_per_day
from swing_trade_ml.brain.modules.m09_learn.scoring import score_pending
from swing_trade_ml.brain.reader import IST
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.ml.sector_map import get_sector_bucket

MIN_SCORED = 30

_ROW_COLUMNS = (
    "run_started",
    "decision_day",
    "symbol",
    "word",
    "confidence",
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
        .where(BrainDecision.outcome.is_not(None))
    )
    records = []
    for decision, started_at, as_of, context in db.execute(stmt).all():
        decision_day = as_of.astimezone(IST).date()
        if since is not None and decision_day < since:
            continue
        records.append(
            {
                "run_started": started_at,
                "decision_day": decision_day,
                "symbol": decision.symbol,
                "word": decision.word,
                "confidence": decision.confidence,
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
    any of it."""
    rows = _scored_rows(db, since)
    n_scored = len(one_per_day(rows))
    drift = drift_report(db)
    note = (
        f"Only {n_scored} ideas have finished so far — too few to judge; keep collecting."
        if n_scored < MIN_SCORED
        else None
    )
    return {
        "since": since,
        "n_scored": n_scored,
        "by_band": by_band(rows),
        "by_word": by_word(rows),
        "by_week": by_week(rows),
        "failures": failure_patterns(rows),
        "drift": drift,
        "drift_lines": drift_lines_for(drift),
        "note": note,
    }


def run_learning(db: Session, since: date | None = None) -> dict:
    """The weekly job (and `swingtrade brain learn`): score every idea whose
    outcome is now known, build the report, and propose a different buy
    level when the evidence plainly supports one (never applied by itself —
    the owner must accept it, constitution C9)."""
    today = datetime.now(UTC).astimezone(IST).date()
    score_pending(db, today)
    report = learning_report(db, since)
    rows = one_per_day(_scored_rows(db, since))
    current = store.accepted_buy_level(db) or settings.ML_MIN_CONFIDENCE
    draft = buy_level_proposal(rows, current)
    new_proposals = []
    if draft is not None:
        created = store.create(db, draft)
        if created is not None:
            new_proposals.append(
                {"id": created.id, "kind": created.kind, "title": created.title, "evidence": created.evidence}
            )
    report["new_proposals"] = new_proposals
    return report
