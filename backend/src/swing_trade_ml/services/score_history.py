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

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.trading import PositionScore, StockScore
from swing_trade_ml.ml import real_question

log = get_logger(__name__)

BANDS = ("strong", "easing", "weak")
BAND_LABELS = {"strong": "Strong", "easing": "Easing", "weak": "Weak"}
_RANK = {band: i for i, band in enumerate(BANDS)}


def score_band(score: float, exit_confidence: float, min_confidence: float | None = None) -> str:
    """Pure: which band a score falls in."""
    min_confidence = real_question.min_confidence() if min_confidence is None else min_confidence
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


# The one-year value model answers a different question from the swing models; its score is never
# drawn on the stock trail.
EXCLUDED_TRAIL_MODELS = frozenset({"long_term_value"})


def model_name_of(model_version: str | None) -> str:
    """"swing_classifier:v2" -> "swing_classifier"; no model recorded -> "" (its own line)."""
    return (model_version or "").split(":", 1)[0][:64]


def record_stock_scores(
    db: Session,
    scores: list[tuple[int, float, str | None]],
    exit_confidence: float,
    today: date | None = None,
    universe: Iterable[int] | None = None,
) -> int:
    """Store today's score for each (instrument_id, score, model_version).

    One row per stock, day and model: a second scan by the SAME model replaces that day's row,
    a different model gets its own row instead of overwriting. Never raises: this is a display
    feature and must not be able to break scanning or trading, so any failure is logged and
    rolled back inside a savepoint. Returns rows written.
    """
    scores = [t for t in scores if model_name_of(t[2]) not in EXCLUDED_TRAIL_MODELS]
    universe = None if universe is None else list(universe)
    if not scores:
        if universe:  # nothing was scored, but the stocks it was meant to cover are gaps, not absences
            append_to_ledger(db, stock_sessions(db, set(universe), today), {}, universe)
        return 0
    # Each stock is filed under the market session of ITS OWN newest candle, never the clock day of the call
    # (#389): a scan run after midnight for Friday's candle is Friday's, and a stock whose newest candle is
    # Thursday's stays Thursday's. A caller that knows the session passes it for every stock.
    sessions = stock_sessions(db, {i for i, _, _ in scores}, today)
    try:
        with db.begin_nested():
            latest: dict[tuple[int, str], tuple[float, str | None]] = {
                (i, model_name_of(m)): (s, m) for i, s, m in scores
            }
            existing = {
                (r.instrument_id, r.model_name, r.as_of): r
                for r in db.execute(
                    select(StockScore).where(
                        StockScore.as_of.in_(set(sessions.values())),
                        StockScore.instrument_id.in_({i for i, _ in latest}),
                    )
                ).scalars()
            }
            for (instrument_id, name), (score, model_version) in latest.items():
                version = model_version[:64] if model_version else None
                band = score_band(score, exit_confidence)
                row = existing.get((instrument_id, name, sessions[instrument_id]))
                if row is None:
                    db.add(
                        StockScore(
                            instrument_id=instrument_id,
                            as_of=sessions[instrument_id],
                            score=score,
                            band=band,
                            model_version=version,
                            model_name=name,
                        )
                    )
                else:
                    row.score, row.band, row.model_version = score, band, version
    except Exception as exc:  # noqa: BLE001 - never break a scan over a display feature
        log.warning("score_history.stock_record_failed", error=str(exc))
        return 0
    append_to_ledger(db, sessions, latest, universe)
    return len(latest)


def stock_sessions(db: Session, instrument_ids: set[int], today: date | None = None) -> dict[int, date]:
    """instrument id -> the market session it is scored for: the IST date of that stock's own newest daily
    candle, never later than today. A caller-supplied `today` is used for every stock. A stock with no
    candle (or a failed lookup) is filed under today's IST date, as it always was."""
    clock = datetime.now(IST).date()
    if today is not None:
        return dict.fromkeys(instrument_ids, today)
    found: dict[int, date] = {}
    try:
        for instrument_id, newest in db.execute(
            select(Candle.instrument_id, func.max(Candle.ts))
            .where(Candle.interval == "day", Candle.instrument_id.in_(instrument_ids))
            .group_by(Candle.instrument_id)
        ):
            found[instrument_id] = min(newest.astimezone(IST).date(), clock)
    except Exception as exc:  # noqa: BLE001 - a display feature must not break a scan
        log.warning("score_history.session_lookup_failed", error=str(exc))
    return {i: found.get(i, clock) for i in instrument_ids}


def append_to_ledger(
    db: Session,
    sessions: dict[int, date],
    latest: dict[tuple[int, str], tuple[float, str | None]],
    universe: Iterable[int] | None = None,
) -> int:
    """Also record each score in the append-only ledger (#389 S2): one row per stock, session, horizon, model
    and version, a changed re-run kept as a numbered revision. Never raises and never changes the old table:
    any failure is logged and rolled back inside its own savepoint. Returns rows written."""
    from swing_trade_ml.services.identity import ledger, writer

    written = 0
    try:
        with db.begin_nested():
            models: dict[tuple[str, str], MLModel | None] = {}
            scored_securities: set[int] = set()
            for (instrument_id, name), (score, model_version) in latest.items():
                instrument = db.get(Instrument, instrument_id)
                if instrument is None:
                    continue
                version = (model_version or "").split(":", 1)[1][:64] if ":" in (model_version or "") else ""
                if (name, version) not in models:
                    models[(name, version)] = db.scalar(
                        select(MLModel).where(MLModel.name == name, MLModel.version == version)
                    )
                model = models[(name, version)]
                try:
                    with db.begin_nested():
                        security_id = writer.ensure_for_instrument(db, instrument)
                except writer.IdentityConflictError as exc:
                    log.warning("score_history.ledger_identity_conflict", error=str(exc))
                    continue  # left for review; the rest of the scan is recorded
                scored_securities.add(security_id)
                result = ledger.append_score(
                    db,
                    security_id=security_id,
                    session_date=sessions[instrument_id],
                    source="v1_scan",
                    score=score,
                    horizon_days=None if model is None else model.prediction_horizon_days,
                    model_name=name,
                    model_version=version,
                    model_id=None if model is None else model.id,
                    scan_key=f"v1:{sessions[instrument_id].isoformat()}",
                )
                written += 1 if result.created else 0
            written += _append_missing(db, sessions, latest, universe, models, scored_securities)
    except Exception as exc:  # noqa: BLE001 - never break a scan over a history feature
        log.warning("score_history.ledger_append_failed", error=str(exc))
        return 0
    return written


def _append_missing(
    db: Session,
    sessions: dict[int, date],
    latest: dict[tuple[int, str], tuple[float, str | None]],
    universe: Iterable[int] | None,
    models: dict[tuple[str, str], MLModel | None],
    scored_securities: set[int],
) -> int:
    """A `missing` ledger row for every stock the scan was meant to cover and did not score (never a 0).

    Filed under the scan's own session (the newest among the stocks it did score, else among the universe),
    for the model the scan used when it used exactly one. Stocks whose identity cannot be settled are left
    for review."""
    from swing_trade_ml.services.identity import ledger, writer

    if not universe:
        return 0
    ids = sorted(set(universe))
    scan_sessions = list(sessions.values()) or list(stock_sessions(db, set(ids)).values())
    session_date = max(scan_sessions)
    identities = set()
    for (_, model_name), (_, model_version) in latest.items():
        text = model_version or ""
        identities.add((model_name, text.split(":", 1)[1][:64] if ":" in text else ""))
    name, version = next(iter(identities)) if len(identities) == 1 else ("", "")
    model = models.get((name, version))
    in_universe: set[int] = set()
    for instrument in db.scalars(select(Instrument).where(Instrument.id.in_(ids))):
        try:
            with db.begin_nested():
                in_universe.add(writer.ensure_for_instrument(db, instrument))
        except writer.IdentityConflictError as exc:
            log.warning("score_history.ledger_identity_conflict", error=str(exc))
    return ledger.append_missing_for_universe(
        db,
        session_date=session_date,
        universe_security_ids=in_universe,
        scored_security_ids=scored_securities,
        source="v1_scan",
        horizon_days=None if model is None else model.prediction_horizon_days,
        model_name=name,
        model_version=version,
        scan_key=f"v1:{session_date.isoformat()}",
    )


def one_model_rows(rows: list[StockScore]) -> list[StockScore]:
    """Keep only the rows of the model that scored this stock most recently.

    A stock's trail is one line from one model. If several models wrote rows, the newest day wins
    (ties go to the model name that sorts first, so the choice never flips between calls).
    """
    rows = [r for r in rows if r.model_name not in EXCLUDED_TRAIL_MODELS]
    if not rows:
        return []
    newest = max(r.as_of for r in rows)
    name = min(r.model_name for r in rows if r.as_of == newest)
    return [r for r in rows if r.model_name == name]


def stock_trail(db: Session, instrument_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """Oldest-first {date, score, band, model_version} for one stock, from ONE model; gaps stay gaps."""
    rows = list(
        db.execute(
            select(StockScore)
            .where(StockScore.instrument_id == instrument_id)
            .order_by(StockScore.as_of.desc())
            .limit(limit * 4)  # headroom: other models' rows share the same days
        ).scalars()
    )
    kept = one_model_rows(rows)[:limit]
    return [
        {"date": r.as_of.isoformat(), "score": r.score, "band": r.band, "model_version": r.model_version}
        for r in reversed(kept)
    ]
