"""Keep each open trade's daily track (M15). One row per trade per day — a
later run that day updates it. The stored stop never drops below the last
one stored for the same trade (constitution C6: stops only move up)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.db.models.brain import BrainTrack


def _same_trade(book: str, symbol: str, opened_on: date):
    return (BrainTrack.book == book, BrainTrack.symbol == symbol, BrainTrack.opened_on == opened_on)


def save_points(
    db: Session, book: str, opened: dict[str, date], points: list[c.TrackPoint], day: date
) -> None:
    for p in points:
        opened_on = opened.get(p.symbol)
        if opened_on is None:
            continue
        trade = _same_trade(book, p.symbol, opened_on)
        earlier = db.execute(
            select(BrainTrack.stop)
            .where(*trade, BrainTrack.day < day, BrainTrack.stop.is_not(None))
            .order_by(BrainTrack.day.desc())
            .limit(1)
        ).scalar_one_or_none()
        stop = p.stop if earlier is None or p.stop is None else max(p.stop, earlier)
        values = {
            "day_n": p.day_n,
            "ret": p.ret,
            "status": p.status,
            "reason": p.reason,
            "stop": stop,
            "band": [list(b) for b in p.band],
        }
        row = db.execute(select(BrainTrack).where(*trade, BrainTrack.day == day)).scalar_one_or_none()
        if row is None:
            db.add(BrainTrack(book=book, symbol=p.symbol, opened_on=opened_on, day=day, **values))
        else:
            for k, v in values.items():
                setattr(row, k, v)
    db.flush()


def track_rows(db: Session, book: str, symbol: str) -> list[BrainTrack]:
    """Every stored day of the most recent trade in this stock."""
    latest = db.execute(
        select(BrainTrack.opened_on)
        .where(BrainTrack.book == book, BrainTrack.symbol == symbol)
        .order_by(BrainTrack.opened_on.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return []
    return list(
        db.execute(
            select(BrainTrack).where(*_same_trade(book, symbol, latest)).order_by(BrainTrack.day)
        ).scalars()
    )
