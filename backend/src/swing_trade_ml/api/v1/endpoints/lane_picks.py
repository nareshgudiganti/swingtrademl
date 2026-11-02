"""Horizon picks: one owner-only, read-only table of every recorded test pick, tagged by horizon and cap size.

GET only. It reads the lanes' own tables (today: the 5-day h05 lane) and nothing else, so it cannot reach the
brain, the bot, an order or the sealed trial. A pick shown here is a test record, never a trade or advice.
A later lane (10-day, 15-day) adds one more source to `_rows`; the shape of a row does not change."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession, require_owner
from swing_trade_ml.db.models.lanes import H05Run, H05Signal

router = APIRouter(prefix="/research/lane-picks", tags=["lane-picks"], dependencies=[Depends(require_owner)])

CAP_LABEL = {"large": "Large cap", "mid": "Mid cap", "small": "Small cap"}
NOTE = (
    "Test picks only. Not trades and not advice. "
    "Each horizon is judged on its own; scores are not comparable across horizons."
)


def _status(s: H05Signal) -> str:
    if s.trade_status in (None, "pending"):
        return "open"
    return s.trade_status


def _rows(db: DbSession) -> list[dict[str, Any]]:
    q = (
        select(H05Signal, H05Run.run_no)
        .join(H05Run, H05Run.id == H05Signal.run_id)
        .where(H05Signal.selected.is_(True))
        .order_by(H05Signal.signal_day.desc(), H05Signal.group, H05Signal.group_rank)
    )
    out: list[dict[str, Any]] = []
    for s, run_no in db.execute(q).all():
        out.append(
            {
                "horizon_days": 5,
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
    limit: int = Query(default=300, ge=1, le=2000),
) -> dict[str, Any]:
    rows = _rows(db)
    if horizon is not None:
        rows = [r for r in rows if r["horizon_days"] == horizon]
    if cap is not None:
        rows = [r for r in rows if r["cap"] == cap]
    finished = [r for r in rows if r["status"] != "open" and r["net_return"] is not None]
    wins = [r for r in finished if r["net_return"] > 0]
    return {
        "note": NOTE,
        "lanes": [{"horizon_days": 5, "lane": "h05", "label": "5-day (existing models)", "live": True}],
        "summary": {
            "picks": len(rows),
            "finished": len(finished),
            "open": len(rows) - len(finished),
            "wins": len(wins),
            "mean_net_return": (sum(r["net_return"] for r in finished) / len(finished)) if finished else None,
        },
        "rows": rows[:limit],
    }
