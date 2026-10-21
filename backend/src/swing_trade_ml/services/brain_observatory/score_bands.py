"""Does a higher score really mean better results? (ps5, 2026-10-21). Read-only, stored outcomes only.

Ideas are grouped by the model score they had, and each group shows how often +8% came before -4%.
If the line is flat, the score is not telling good ideas from bad ones.

Two sources, never mixed:

- **development**: the walk-forward reliability table (docs/brain/evidence/score_reliability.json): models
  that had not seen the days they scored. Already looked at, so it is a diagnostic, not proof.
- **live**: the brain's own stored ideas on prod, graded by M09 (entry at the decision day's close, gross).
  Days before the forward trial started (TRIAL_START) were already looked at, so their results are shown.
  From TRIAL_START on, the trial is a blind test (evidence plan amendment A4): **counts only**, results
  sealed until its evaluation.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST

# (label, low, high) on the 0..1 score; the same bands as the development table so the two line up.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("0%-30%", 0.0, 0.3),
    ("30%-40%", 0.3, 0.4),
    ("40%-50%", 0.4, 0.5),
    ("50%-60%", 0.5, 0.6),
    ("60%-70%", 0.6, 0.7),
    ("70%-80%", 0.7, 0.8),
    ("80%-100%", 0.8, 1.000001),
)
FINISHED = ("target", "stop", "timeout")

# Copied from docs/brain/evidence/score_reliability.json "raw_table_all_folds" (a test keeps them equal).
DEVELOPMENT = {
    "source": "docs/brain/evidence/score_reliability.json (raw_table_all_folds)",
    "period": "walk-forward 2025-10-01 to 2026-08-15, a fresh model per 28-day window",
    "note": (
        "Development data, already looked at: a diagnostic, not proof. Scores from 0% to 70% all reached "
        "+8% first about 14-15% of the time (flat). Only the 80%+ band stood out, and that was found by "
        "looking at this same data, so it is a lead to test (evidence plan Phase B, candidate B1), "
        "not a result."
    ),
    "bands": [
        {"band": "0%-30%", "ideas": 4074, "hit_rate": 0.14285714285714285},
        {"band": "30%-40%", "ideas": 1940, "hit_rate": 0.138659793814433},
        {"band": "40%-50%", "ideas": 1626, "hit_rate": 0.13776137761377613},
        {"band": "50%-60%", "ideas": 1133, "hit_rate": 0.13503971756398941},
        {"band": "60%-70%", "ideas": 807, "hit_rate": 0.1524163568773234},
        {"band": "70%-80%", "ideas": 522, "hit_rate": 0.210727969348659},
        {"band": "80%-100%", "ideas": 429, "hit_rate": 0.40792540792540793},
    ],
}
SEALED = "Sealed until the trial's evaluation (blind test): counts only."


def band_of(score: float) -> str | None:
    for label, lo, hi in BANDS:
        if lo <= score < hi:
            return label
    return None


def summarise(rows: list[tuple[float, str | None]], sealed: bool) -> list[dict[str, Any]]:
    """rows = (score, stored outcome or None) -> one entry per band, in band order."""
    out = []
    for label, _lo, _hi in BANDS:
        mine = [o for s, o in rows if band_of(s) == label]
        finished = [o for o in mine if o in FINISHED]
        row: dict[str, Any] = {"band": label, "ideas": len(mine), "finished": len(finished)}
        if sealed:
            row["hit_rate"] = None
        else:
            row["hit_rate"] = sum(o == "target" for o in finished) / len(finished) if finished else None
        out.append(row)
    return out


def _live_rows(db: Session, start: date, end: date, book: str) -> list[tuple[float, str | None]]:
    from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

    lo = datetime.combine(start, datetime.min.time(), tzinfo=IST)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=IST)
    rows = db.execute(
        select(BrainDecision.confidence, BrainDecision.outcome)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.book == book,
            BrainRun.as_of >= lo,
            BrainRun.as_of < hi,
            BrainDecision.kind == "idea",
            BrainDecision.score_source == "model",  # a raw model score; other kinds are not comparable
            BrainDecision.confidence.isnot(None),
        )
    ).all()
    return [(float(c), o) for c, o in rows]


def build(db: Session, start: date, end: date, book: str) -> dict[str, Any]:
    from swing_trade_ml.brain.trial_journal import TRIAL_START

    parts = []
    before_end = min(end, TRIAL_START - timedelta(days=1))
    if start <= before_end:
        parts.append(
            {
                "period": "before_trial",
                "from": start.isoformat(),
                "to": before_end.isoformat(),
                "label": "Before the trial started: already looked at, shown with results (not proof).",
                "sealed": False,
                "bands": summarise(_live_rows(db, start, before_end, book), sealed=False),
            }
        )
    trial_start = max(start, TRIAL_START)
    if trial_start <= end:
        parts.append(
            {
                "period": "trial",
                "from": trial_start.isoformat(),
                "to": end.isoformat(),
                "label": SEALED,
                "sealed": True,
                "bands": summarise(_live_rows(db, trial_start, end, book), sealed=True),
            }
        )
    return {
        "question": "Does a higher score really mean better results?",
        "rule": "+8% before -4% within 15 trading days "
        "(stored M09 grade: entry at the decision close, gross)",
        "development": DEVELOPMENT,
        "live": parts,
        "trial_start": TRIAL_START.isoformat(),
    }
