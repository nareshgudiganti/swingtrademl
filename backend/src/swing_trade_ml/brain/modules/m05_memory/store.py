"""The experience table: every watch-list stock-day with its key and outcome.

Rebuilt whole from candles (about 50,000 rows, a few seconds) by
`swingtrade brain memory-build` and after live nightly runs, so it always
matches the current rules. Reads keep only outcomes known by a given day.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m04_situations.rules import label_days
from swing_trade_ml.brain.modules.m05_memory.cases import build_cases
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainExperience

log = get_logger(__name__)
COLUMNS = (
    "symbol",
    "day",
    "market",
    "stock",
    "trend",
    "vol",
    "outcome",
    "exit_return",
    "days",
    "outcome_day",
    "path_day",
    "path",
)


def sync_experience(db: Session, cases: pd.DataFrame) -> int:
    db.execute(delete(BrainExperience))
    rows = [
        {c: (row[c] if c != "path" else [float(x) for x in row[c]]) for c in COLUMNS}
        for row in cases[list(COLUMNS)].to_dict("records")
    ]
    for start in range(0, len(rows), 5000):
        db.execute(insert(BrainExperience), rows[start : start + 5000])
    db.flush()
    return len(rows)


def load_experience(db: Session, upto: date) -> pd.DataFrame:
    rows = db.execute(
        select(*(getattr(BrainExperience, c) for c in COLUMNS)).where(BrainExperience.outcome_day <= upto)
    ).all()
    return pd.DataFrame(rows, columns=list(COLUMNS))


def rebuild_from_reader(db: Session, reader) -> int:
    nifty = reader.dated_closes(settings.BENCHMARK_INDEX_SYMBOL)
    if nifty.empty:
        return 0
    labels = label_days(nifty, reader.dated_closes("INDIA VIX"))["label"]
    parts = []
    for symbol in reader.universe():
        bars = reader.dated_bars(symbol)
        if len(bars) >= 220:
            parts.append(build_cases(symbol, bars, labels))
    if not parts:
        return 0
    count = sync_experience(db, pd.concat(parts, ignore_index=True))
    log.info("brain.memory.rebuilt", cases=count, stocks=len(parts))
    return count
