"""Day-by-day strength score for positions the TradeMind brain owns.

Version 1 records its score inside the scan (services/execution.py). The brain
strategy is staged, and its decisions carry a number that is not always a
probability, so that path is skipped for it. This is the brain's own path: once
per finished live brain run, for each open position owned by the brain
strategy, store the model score the brain put on that holding.

Honesty rules:
  * Only a score whose BrainDecision.score_source is "model" or "combined" is
    stored. Anything else (no score, an opinion's own confidence) leaves a
    gap for that day, never a made-up number.
  * `model_version` is "brain:<score_source>", so a change of source shows as
    a break in the trail. A band change across a break is not an alert, and
    the baseline for "fell a long way" is the first day on the same source.
  * A run that is not live, not "done" (failed, or superseded by a newer run
    of the same day) writes nothing.
  * Nothing here touches orders, sizing, stops or limits, and nothing here can
    fail a brain run: the caller wraps it, and each position is isolated.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, PositionScore, Strategy
from swing_trade_ml.services import score_history
from swing_trade_ml.services.execution import _score_band_message
from swing_trade_ml.services.exit_policy import exit_confidence_for

log = get_logger(__name__)

COMPARABLE_SOURCES = ("model", "combined")
RECORDED_RUN_KINDS = ("nightly", "intraday")
VERSION_PREFIX = "brain:"


def version_for(score_source: str | None) -> str | None:
    """The `model_version` label for a comparable source, else None (= gap)."""
    return f"{VERSION_PREFIX}{score_source}" if score_source in COMPARABLE_SOURCES else None


def _comparable_scores(db: Session, run_id: str) -> dict[str, tuple[float, str]]:
    """symbol -> (score, version) for the run's decisions that carry a score
    that is comparable day to day. Holding rows win over idea rows."""
    out: dict[str, tuple[float, str]] = {}
    rows = db.execute(
        select(BrainDecision).where(BrainDecision.run_id == run_id).order_by(BrainDecision.kind.desc())
    ).scalars()
    for d in rows:
        version = version_for(d.score_source)
        if version is None or d.confidence is None or not 0.0 <= d.confidence <= 1.0:
            continue
        out.setdefault(d.symbol, (float(d.confidence), version))
    return out


def _baseline(db: Session, position_id: int, version: str, today: date) -> float | None:
    """First score on file for this source before today: the honest 'where it
    started' for a brain position (its entry number may be a different kind)."""
    return db.execute(
        select(PositionScore.score)
        .where(
            PositionScore.position_id == position_id,
            PositionScore.as_of < today,
            PositionScore.model_version == version,
        )
        .order_by(PositionScore.as_of)
        .limit(1)
    ).scalar_one_or_none()


def _previous_version(db: Session, position_id: int, today: date) -> str | None:
    return db.execute(
        select(PositionScore.model_version)
        .where(PositionScore.position_id == position_id, PositionScore.as_of < today)
        .order_by(PositionScore.as_of.desc())
        .limit(1)
    ).scalar_one_or_none()


def record_run_scores(db: Session, run_id: str, send: Callable[[str], None] | None = None) -> int:
    """Store today's score for each open brain-owned position and send at most
    one 'score slipping' message per position per day. Returns rows written."""
    run = db.get(BrainRun, run_id)
    if run is None or not run.live or run.status != "done" or run.kind not in RECORDED_RUN_KINDS:
        return 0
    scores = _comparable_scores(db, run_id)
    if not scores:
        return 0
    today = run.as_of.astimezone(IST).date()
    if send is None:
        from swing_trade_ml.notifications import notifier

        def send(text: str) -> None:
            notifier.send_sync(text, "signal")

    rows = db.execute(
        select(Position, Instrument, Strategy)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .join(Strategy, Strategy.id == Position.strategy_id)
        .where(
            Strategy.strategy_type == "brain",
            Position.mode == run.book,
            Position.status == PositionStatus.OPEN,
        )
    ).all()

    written = 0
    for position, instrument, strategy in rows:
        scored = scores.get(instrument.tradingsymbol)
        if scored is None:
            continue  # a gap for today, on purpose
        score, version = scored
        message: str | None = None
        try:
            with db.begin_nested():
                exit_confidence = exit_confidence_for(strategy)
                baseline = _baseline(db, position.id, version, today)
                previous_version = _previous_version(db, position.id, today)
                recorded = score_history.record_score(
                    db,
                    position.id,
                    score,
                    exit_confidence,
                    model_version=version,
                    today=today,
                    entry_score=baseline,
                )
                # A different source than the last day on file is a break, not a slide.
                comparable_before = previous_version in (None, version)
                if recorded.worsened and comparable_before and not recorded.already_alerted:
                    score_history.mark_alerted(db, position.id, today)
                    message = _score_band_message(
                        instrument,
                        position,
                        score,
                        recorded.band,
                        position.mode,
                        baseline=baseline,
                        baseline_label="first tracked",
                    )
            written += 1
        except Exception:
            log.exception("brain.position_score.failed", position_id=position.id)
            continue
        db.commit()
        if message:
            try:
                send(message)
            except Exception:
                log.exception("brain.position_score.alert_failed", position_id=position.id)
    return written


def after_run(db: Session, run_id: str) -> None:
    """The brain's after-run hook: never raises."""
    try:
        record_run_scores(db, run_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.warning("brain.position_score.job_failed", run_id=run_id, error=str(exc))


def latest_for(trail: list[dict[str, Any]], exit_confidence: float) -> tuple[float | None, str | None]:
    """(score, band) from the newest trail row, for the API; (None, None) when empty."""
    if not trail:
        return None, None
    score = float(trail[-1]["score"])
    return score, score_history.score_band(score, exit_confidence)
