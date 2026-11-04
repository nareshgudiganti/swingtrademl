"""Send an important Telegram message once, and keep a small record of how it went.

States:
  PENDING  the send was started and has not finished (or the process stopped in the middle)
  SENT     Telegram's API accepted the message. This does NOT mean it reached or was read on a phone
  FAILED   the API refused it or could not be reached; a later call with the same key may retry
  SKIPPED  nothing was attempted because Telegram is off for this environment

Rules:
  * One message per `dedupe_key`: once a row is SENT or SKIPPED, a second call sends nothing.
  * A FAILED row is retried, up to MAX_ATTEMPTS in total. A recent PENDING row is left alone (another sender
    probably in flight); an old one is treated as failed.
  * The message must still go out if the log cannot be written: a logging problem never replaces an alert,
    and never raises into a trade.
  * No token and no message text is stored: only a trade reference, the book, timestamps and a scrubbed error.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.notification_log import FAILED, PENDING, SENT, SKIPPED, NotificationLog
from swing_trade_ml.notifications.telegram import SendResult, scrub

log = get_logger(__name__)

MAX_ATTEMPTS = 3
# A PENDING row younger than this is assumed to be in flight; older means the sender died.
PENDING_STALE_AFTER = timedelta(minutes=5)

SessionFactory = Callable[[], AbstractContextManager[Session]]


def _sessions() -> SessionFactory:
    from swing_trade_ml.db.session import session_scope

    return session_scope


def _claim(db: Session, key: str, fields: dict[str, Any], now: datetime) -> tuple[int | None, str]:
    """Take the right to send. Returns (row id, "send") or (None, why not): "duplicate" or "in_flight"."""
    inserted = db.execute(
        insert(NotificationLog)
        .values(dedupe_key=key, status=PENDING, attempts=1, created_at=now, last_attempt_at=now, **fields)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(NotificationLog.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted, "send"

    row = db.execute(
        select(NotificationLog).where(NotificationLog.dedupe_key == key).with_for_update()
    ).scalar_one()
    if row.status in (SENT, SKIPPED):
        return None, "duplicate"
    if row.status == PENDING and row.last_attempt_at and now - row.last_attempt_at < PENDING_STALE_AFTER:
        return None, "in_flight"
    if row.attempts >= MAX_ATTEMPTS:
        return None, "gave_up"
    row.status, row.attempts, row.last_attempt_at = PENDING, row.attempts + 1, now
    return row.id, "send"


def _finish(db: Session, row_id: int, result: SendResult, now: datetime) -> None:
    row = db.get(NotificationLog, row_id)
    if row is None:
        return
    row.http_status = result.http_status
    if result.skipped:
        row.status = SKIPPED
    elif result.ok:
        row.status, row.sent_at, row.error_kind, row.error_detail = SENT, now, None, None
    else:
        row.status, row.error_kind, row.error_detail = FAILED, result.error_kind, scrub(result.error_detail)


def _attempt(notifier: Any, text: str, event: str) -> SendResult:
    """One send through the notifier's ordinary send_sync (so it behaves as before), then ask how it ended.
    No post at all means Telegram is off here: SKIPPED, not FAILED."""
    ok = notifier.send_sync(text, event)
    took = getattr(notifier, "take_last_result", None)
    result = took() if callable(took) else None
    if result is not None:
        return result
    return SendResult(True) if ok else SendResult(False, skipped=True)


def send_logged(
    text: str,
    *,
    dedupe_key: str,
    message_type: str,
    book: str,
    symbol: str | None = None,
    trade_id: int | None = None,
    position_id: int | None = None,
    event: str = "fill",
    notifier: Any = None,
    sessions: SessionFactory | None = None,
) -> str:
    """Send `text` through Telegram once for this key and record the outcome.

    Returns "sent", "failed", "skipped", or why nothing was sent: "duplicate", "in_flight", "gave_up".
    "logged_off" means the log could not be used and the message was sent without one. Never raises."""
    if notifier is None:
        from swing_trade_ml.notifications import notifier as default_notifier

        notifier = default_notifier
    now = datetime.now(UTC)
    fields = {
        "message_type": message_type,
        "book": book,
        "symbol": symbol,
        "trade_id": trade_id,
        "position_id": position_id,
    }
    row_id: int | None = None
    try:
        with (sessions or _sessions())() as db:
            row_id, decision = _claim(db, dedupe_key, fields, now)
        if row_id is None:
            log.info("notification_log.not_sent", reason=decision, key=dedupe_key)
            return decision
    except Exception as exc:  # noqa: BLE001 - the alert matters more than its record
        log.warning("notification_log.unavailable_sending_anyway", error_kind=type(exc).__name__)
        try:
            notifier.send_sync(text, event)
        except Exception:  # noqa: BLE001
            log.warning("notification_log.plain_send_failed")
        return "logged_off"

    try:
        result = _attempt(notifier, text, event)
    except Exception as exc:  # noqa: BLE001
        result = SendResult(False, error_kind=type(exc).__name__)
    try:
        with (sessions or _sessions())() as db:
            _finish(db, row_id, result, datetime.now(UTC))
    except Exception as exc:  # noqa: BLE001 - the message already went; the row stays PENDING and ages out
        log.warning("notification_log.finish_failed", error_kind=type(exc).__name__)
    return "skipped" if result.skipped else ("sent" if result.ok else "failed")
