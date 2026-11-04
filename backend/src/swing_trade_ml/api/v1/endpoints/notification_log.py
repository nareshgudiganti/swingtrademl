"""Owner-only, read-only: how the app's important Telegram messages went. See services/notification_log.py.

SENT = accepted by Telegram's API. It is not a delivery or read receipt."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from swing_trade_ml.api.deps import DbSession, require_owner
from swing_trade_ml.db.models.notification_log import NotificationLog

router = APIRouter(
    prefix="/admin/notification-log", tags=["notification-log"], dependencies=[Depends(require_owner)]
)

_FIELDS = (
    "id",
    "message_type",
    "book",
    "symbol",
    "trade_id",
    "position_id",
    "status",
    "attempts",
    "created_at",
    "last_attempt_at",
    "sent_at",
    "http_status",
    "error_kind",
    "error_detail",
)


@router.get("")
def notification_log(
    db: DbSession,
    status: str | None = Query(default=None, pattern="^(PENDING|SENT|FAILED|SKIPPED)$"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    since = datetime.now(UTC) - timedelta(days=7)
    counts = dict(
        db.execute(
            select(NotificationLog.status, func.count())
            .where(NotificationLog.created_at >= since)
            .group_by(NotificationLog.status)
        ).all()
    )
    stmt = select(NotificationLog).order_by(NotificationLog.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(NotificationLog.status == status)
    rows = [{f: getattr(r, f) for f in _FIELDS} for r in db.execute(stmt).scalars()]
    return {
        "meaning": "SENT = accepted by Telegram's API. It does not mean delivered to or read on a phone.",
        "last_7_days": {s: counts.get(s, 0) for s in ("PENDING", "SENT", "FAILED", "SKIPPED")},
        "rows": rows,
    }
