"""Horizon picks: one owner-only, read-only table of every recorded test pick, tagged by horizon and cap size.

GET only. It reads the lanes' own tables (today: the 5-day h05 lane) and nothing else, so it cannot reach the
brain, the bot, an order or the sealed trial. A pick shown here is a test record, never a trade or advice.
A later lane (10-day, 15-day) adds one more source to `_rows`; the shape of a row does not change."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession, require_owner
from swing_trade_ml.db.models.lanes import H05Run, H05Signal

router = APIRouter(prefix="/research/lane-picks", tags=["lane-picks"], dependencies=[Depends(require_owner)])

CAP_LABEL = {"large": "Large cap", "mid": "Mid cap", "small": "Small cap"}
# The one lane there is today (h05). A horizon with no lane has nothing to read.
LANE_HORIZON = 5
NOTE = (
    "Test picks only. Not trades and not advice. "
    "Each horizon is judged on its own; scores are not comparable across horizons."
)


# The lane review's first reading. Kept as a number here, not imported: this route file must not import lane
# records (tests/test_horizon_research_gate.py). A test pins it equal to lane_review.CHECKPOINTS[0].
REVIEW_FLOOR = 60
RATES_WITHHELD = "Not enough finished picks yet: an average from this few would mislead."


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts always; the average only from the lane review's first reading (60 finished picks, #474)."""
    finished = [r for r in rows if r["status"] != "open" and r["net_return"] is not None]
    wins = [r for r in finished if r["net_return"] > 0]
    enough = len(finished) >= REVIEW_FLOOR
    return {
        "picks": len(rows),
        "finished": len(finished),
        "open": len(rows) - len(finished),
        "wins": len(wins),
        "mean_net_return": (sum(r["net_return"] for r in finished) / len(finished)) if enough else None,
        "rates_note": None if enough or not finished else RATES_WITHHELD,
    }


def _status(s: H05Signal) -> str:
    if s.trade_status in (None, "pending"):
        return "open"
    return s.trade_status


def _rows(
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
    cap: str | None = None,
    horizon: int | None = None,
) -> list[dict[str, Any]]:
    """Selected picks, filtered in SQL: `signal_day` (an Indian session date) from `start` to `end` inclusive,
    and the cap size. A horizon other than the lane's own reads nothing."""
    if horizon is not None and horizon != LANE_HORIZON:
        return []
    q = (
        select(H05Signal, H05Run.run_no)
        .join(H05Run, H05Run.id == H05Signal.run_id)
        .where(H05Signal.selected.is_(True))
        .order_by(H05Signal.signal_day.desc(), H05Signal.group, H05Signal.group_rank)
    )
    if start is not None:
        q = q.where(H05Signal.signal_day >= start)
    if end is not None:
        q = q.where(H05Signal.signal_day <= end)
    if cap is not None:
        q = q.where(H05Signal.group == cap)
    out: list[dict[str, Any]] = []
    for s, run_no in db.execute(q).all():
        out.append(
            {
                "horizon_days": LANE_HORIZON,
                "lane": "h05",
                "run_no": run_no,
                "signal_day": s.signal_day.isoformat(),
                "symbol": s.symbol,
                "cap": s.group,
                "cap_label": CAP_LABEL.get(s.group, s.group),
                "rank": s.group_rank,
                "score": s.score,
                "model_id": s.model_id,
                "model_version": s.model_version,
                "status": _status(s),
                "entry_day": s.entry_day.isoformat() if s.entry_day else None,
                "entry_price": s.entry_fill,
                "exit_day": s.exit_day.isoformat() if s.exit_day else None,
                "exit_price": s.exit_fill,
                "exit_reason": s.exit_reason,
                "net_return": s.net_return,
            }
        )
    return out


@router.get("")
def lane_picks(
    db: DbSession,
    horizon: int | None = Query(default=None, ge=1, le=30),
    cap: str | None = Query(default=None, pattern="^(large|mid|small)$"),
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=300, ge=1, le=2000),
) -> dict[str, Any]:
    if start is not None and end is not None and end < start:
        raise HTTPException(422, "'to' must be on or after 'from'.")
    rows = _rows(db, start, end, cap, horizon)
    return {
        "note": NOTE,
        "lanes": [{"horizon_days": 5, "lane": "h05", "label": "5-day (existing models)", "live": True}],
        "summary": summarise(rows),
        "rows": rows[:limit],
    }
