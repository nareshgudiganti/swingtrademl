"""Day-by-day strength score for held positions.

The score is the model's current read on the stock (0-100%), re-asked every
scan. This module keeps one number per position per day so the app can show
"entered 91 -> 89 -> 80 -> 70 -> 50", and says when the score slips into a
worse band. It reads and writes nothing about orders, sizing or stops — the
score is shown next to those, never in place of them.

Bands reuse the thresholds position_action() already uses, so the trail, the
badge and the alert can never disagree:
  strong  - at or above the buy bar (ML_MIN_CONFIDENCE)
  easing  - below the buy bar, above the midpoint to the exit level
  weak    - below that midpoint (approaching the exit level)

Two things raise a "score slipping" message, at most once a day: moving into
a worse band, or the first time the score is 15 points or more below where it
was at entry (a 91 -> 70 slide never leaves "strong" but is still worth a
heads-up). Ordinary one-day jitter does neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.trading import PositionScore, StockScore

log = get_logger(__name__)

BANDS = ("strong", "easing", "weak")
BAND_LABELS = {"strong": "Strong", "easing": "Easing", "weak": "Weak"}
_RANK = {band: i for i, band in enumerate(BANDS)}


def score_band(score: float, exit_confidence: float, min_confidence: float | None = None) -> str:
    """Pure: which band a score falls in."""
    min_confidence = settings.ML_MIN_CONFIDENCE if min_confidence is None else min_confidence
    if score >= min_confidence:
        return "strong"
    if score >= (min_confidence + exit_confidence) / 2:
        return "easing"
    return "weak"


def band_worsened(previous: str | None, current: str) -> bool:
    """Pure: moved toward caution. No previous day -> nothing to compare, so no."""
    if previous not in _RANK:
        return False
    return _RANK[current] > _RANK[previous]


@dataclass(frozen=True)
class ScoreRecord:
    band: str
    worsened: bool  # worse band than the last day on file, or a first big fall from entry
    already_alerted: bool


def record_score(
    db: Session,
    position_id: int,
    score: float,
    exit_confidence: float,
    model_version: str | None = None,
    today: date | None = None,
    entry_score: float | None = None,
) -> ScoreRecord:
    """Store today's score (replacing an earlier scan the same day).

    `worsened` compares against the most recent EARLIER day on file, so a gap
    of a few days doesn't hide a drop. `already_alerted` is whether a message
    already went out today — the caller sends at most one per day.
    """
    today = today or datetime.now(IST).date()
    band = score_band(score, exit_confidence)

    previous = db.execute(
        select(PositionScore.band)
        .where(PositionScore.position_id == position_id, PositionScore.as_of < today)
        .order_by(PositionScore.as_of.desc())
        .limit(1)
    ).scalar_one_or_none()
    todays = db.execute(
        select(PositionScore).where(PositionScore.position_id == position_id, PositionScore.as_of == today)
    ).scalar_one_or_none()
    already_alerted = bool(todays and todays.alerted)

    big_fall_first_time = False
    fall_line = None if entry_score is None else entry_score - settings.CONFIDENCE_DECAY_ALERT_PCT
    if fall_line is not None and score <= fall_line:
        earlier_big_fall = db.execute(
            select(PositionScore.id)
            .where(
                PositionScore.position_id == position_id,
                PositionScore.as_of < today,
                PositionScore.score <= fall_line,
            )
            .limit(1)
        ).first()
        big_fall_first_time = earlier_big_fall is None

    if todays is None:
        db.add(
            PositionScore(
                position_id=position_id, as_of=today, score=score, band=band, model_version=model_version
            )
        )
    else:
        todays.score, todays.band, todays.model_version = score, band, model_version
    db.flush()
    return ScoreRecord(
        band=band,
        worsened=band_worsened(previous, band) or big_fall_first_time,
        already_alerted=already_alerted,
    )


def mark_alerted(db: Session, position_id: int, today: date | None = None) -> None:
    today = today or datetime.now(IST).date()
    row = db.execute(
        select(PositionScore).where(PositionScore.position_id == position_id, PositionScore.as_of == today)
    ).scalar_one_or_none()
    if row is not None:
        row.alerted = True
        db.flush()


def trails_for(db: Session, position_ids: list[int], limit: int = 30) -> dict[int, list[dict[str, Any]]]:
    """Oldest-first list per position of {date, score, band, model_version}.

    Only days that really had a score; a missing day is a gap, not a copy.
    """
    if not position_ids:
        return {}
    rows = db.execute(
        select(PositionScore)
        .where(PositionScore.position_id.in_(position_ids))
        .order_by(PositionScore.position_id, PositionScore.as_of)
    ).scalars()
    out: dict[int, list[dict[str, Any]]] = {pid: [] for pid in position_ids}
    for r in rows:
        out[r.position_id].append(
            {"date": r.as_of.isoformat(), "score": r.score, "band": r.band, "model_version": r.model_version}
        )
    return {pid: trail[-limit:] for pid, trail in out.items()}


# --------------------------------------------------------------------------
# Per stock (held or not), for the stock page.
# --------------------------------------------------------------------------


def record_stock_scores(
    db: Session,
    scores: list[tuple[int, float, str | None]],
    exit_confidence: float,
    today: date | None = None,
) -> int:
    """Store today's score for each (instrument_id, score, model_version).

    A second scan the same day replaces that day's row. Never raises: this is
    a display feature and must not be able to break scanning or trading, so any
    failure is logged and rolled back inside a savepoint. Returns rows written.
    """
    if not scores:
        return 0
    today = today or datetime.now(IST).date()
    try:
        with db.begin_nested():
            latest: dict[int, tuple[float, str | None]] = {i: (s, m) for i, s, m in scores}
            existing = {
                r.instrument_id: r
                for r in db.execute(
                    select(StockScore).where(
                        StockScore.as_of == today, StockScore.instrument_id.in_(list(latest))
                    )
                ).scalars()
            }
            for instrument_id, (score, model_version) in latest.items():
                version = model_version[:64] if model_version else None
                band = score_band(score, exit_confidence)
                row = existing.get(instrument_id)
                if row is None:
                    db.add(
                        StockScore(
                            instrument_id=instrument_id,
                            as_of=today,
                            score=score,
                            band=band,
                            model_version=version,
                        )
                    )
                else:
                    row.score, row.band, row.model_version = score, band, version
        return len(latest)
    except Exception as exc:  # noqa: BLE001 - never break a scan over a display feature
        log.warning("score_history.stock_record_failed", error=str(exc))
        return 0


def stock_trail(db: Session, instrument_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """Oldest-first {date, score, band, model_version} for one stock; gaps stay gaps."""
    rows = list(
        db.execute(
            select(StockScore)
            .where(StockScore.instrument_id == instrument_id)
            .order_by(StockScore.as_of.desc())
            .limit(limit)
        ).scalars()
    )
    return [
        {"date": r.as_of.isoformat(), "score": r.score, "band": r.band, "model_version": r.model_version}
        for r in reversed(rows)
    ]
