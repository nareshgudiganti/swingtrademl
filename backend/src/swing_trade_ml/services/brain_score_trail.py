"""The brain's own score for one stock, one point per Indian calendar day (read-only, display only).

The stock page's headline number is the brain's score. The brain loads ONE model for every stock
(`swing_classifier`), while the cap-tier daily check scores a mid- or small-size stock with that tier's own
model. Those are different models, so their numbers differ for the same stock on the same day (DEEPAKNTR on
16 Nov 2026: brain 82, mid-size model 45). The line next to the headline is therefore built from the brain's
stored decisions, never from the daily check. Nothing here changes a decision.
"""

from __future__ import annotations

import re
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

IST = ZoneInfo("Asia/Kolkata")
_MODEL_RE = re.compile(r"active model \(([^)]+)\)", re.IGNORECASE)


def model_from_reasons(reasons: list[Any] | None) -> str | None:
    """The model the brain's stored line names ("The active model (swing_classifier v2) ..."), or None."""
    for r in reasons or []:
        m = _MODEL_RE.search(str(r))
        if m:
            return m.group(1)
    return None


def _run_models(db: Session, run_ids: set[str]) -> dict[str, str]:
    """The model each run loaded, read from any of its rows that names it (one run = one model)."""
    found: dict[str, str] = {}
    for run_id in run_ids:  # few: only days whose own row names no model
        reasons = db.execute(
            select(BrainDecision.reasons)
            .where(
                BrainDecision.run_id == run_id,
                cast(BrainDecision.reasons, String).like("%active model (%"),
            )
            .limit(1)
        ).scalar_one_or_none()
        model = model_from_reasons(reasons)
        if model:
            found[run_id] = model
    return found


def brain_trail(db: Session, symbol: str, limit: int = 30) -> list[dict[str, Any]]:
    """Oldest-first {date, score, model_version}: the newest finished live run of each IST day."""
    rows = db.execute(
        select(BrainDecision.run_id, BrainDecision.confidence, BrainDecision.reasons, BrainRun.started_at)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(
            BrainDecision.symbol == symbol,
            BrainDecision.kind == "idea",
            BrainDecision.confidence.is_not(None),
            BrainRun.status == "done",
            BrainRun.live.is_(True),
        )
        .order_by(BrainRun.started_at.desc())
        .limit(limit * 6)  # headroom: several runs can share one day
    ).all()
    by_day: dict[str, tuple[str, float, str | None]] = {}
    for run_id, confidence, reasons, started_at in rows:
        day = started_at.astimezone(IST).date().isoformat()
        if day not in by_day:  # newest first, so the first row of a day is its latest run
            by_day[day] = (run_id, confidence, model_from_reasons(reasons))
        if len(by_day) >= limit:
            break
    missing = {run_id for run_id, _, model in by_day.values() if model is None}
    run_models = _run_models(db, missing)
    return [
        {"date": day, "score": confidence, "model_version": model or run_models.get(run_id)}
        for day, (run_id, confidence, model) in sorted(by_day.items())
    ]
