"""Write market episodes to `brain_episodes`.

Episodes are re-derived from the whole NIFTY history each time (a few
hundred milliseconds), so the table always matches the current rules: the
backfill and every live nightly run call the same `sync_from_reader`.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m04_situations.episodes import Episode, episodes_from_labels
from swing_trade_ml.brain.modules.m04_situations.rules import label_days
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainEpisode


def sync_market_episodes(db: Session, episodes: list[Episode]) -> int:
    db.execute(delete(BrainEpisode).where(BrainEpisode.scope == "market"))
    for e in episodes:
        db.add(
            BrainEpisode(
                scope="market",
                label=e.label,
                start_day=e.start,
                end_day=e.end,
                state_key=e.label,
                stats={**e.stats, "days": e.days},
            )
        )
    db.flush()
    return len(episodes)


def sync_from_reader(db: Session, reader) -> int:
    nifty = reader.dated_closes(settings.BENCHMARK_INDEX_SYMBOL)
    if nifty.empty:
        return 0
    labels = label_days(nifty, reader.dated_closes("INDIA VIX"))["label"]
    return sync_market_episodes(db, episodes_from_labels(labels, nifty))


def market_episodes(db: Session, limit: int = 50) -> list[BrainEpisode]:
    return list(
        db.execute(
            select(BrainEpisode)
            .where(BrainEpisode.scope == "market")
            .order_by(BrainEpisode.start_day.desc())
            .limit(limit)
        ).scalars()
    )
