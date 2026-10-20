"""The owner's alert settings, stored, and the held-message outbox (tracker ux3).

Three entry points:
- `gate(kind, text)`: called by the Telegram notifier for a message tagged with a
  switchable kind. Answers "send", "drop" or "held". Any failure (database down,
  a bad stored value) answers "send": a broken setting never silences a message.
- `flush(db, now, deliver)`: called every few minutes by the scheduler. Sends
  what was held, as one message (or a few, if long), once it is due.
- `load` / `save` / `as_dict`: for the settings page.

Writes only alert_settings and alert_outbox. Read by nothing that trades.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.alerts import AlertOutbox, AlertSettings
from swing_trade_ml.notifications import alert_policy as policy
from swing_trade_ml.notifications.alert_policy import AlertPrefs

log = get_logger(__name__)

OWNER = "owner"
#: Sent rows are kept a while for checking what went out, then removed.
KEEP_SENT = timedelta(days=30)


def _row(db: Session, scope: str) -> AlertSettings | None:
    return db.execute(select(AlertSettings).where(AlertSettings.scope == scope)).scalar_one_or_none()


def _prefs(row: AlertSettings | None) -> AlertPrefs:
    """Stored row -> AlertPrefs. A bad stored value raises (callers fail open)."""
    if row is None:
        return AlertPrefs()
    disabled = row.disabled_kinds or []
    if not isinstance(disabled, list) or not all(isinstance(k, str) for k in disabled):
        raise ValueError("disabled_kinds is not a list of names")
    return AlertPrefs(
        disabled=frozenset(disabled),
        quiet_enabled=bool(row.quiet_enabled),
        quiet_start=policy.parse_hhmm(row.quiet_start),
        quiet_end=policy.parse_hhmm(row.quiet_end),
        digest_enabled=bool(row.digest_enabled),
        digest_time=policy.parse_hhmm(row.digest_time),
        last_digest_on=row.last_digest_on,
    )


def load(db: Session, scope: str = OWNER) -> AlertPrefs:
    return _prefs(_row(db, scope))


def from_payload(payload: dict[str, Any]) -> AlertPrefs:
    """The settings page's body -> AlertPrefs. Raises ValueError with a plain reason."""
    disabled = payload.get("disabled", [])
    if not isinstance(disabled, list) or not all(isinstance(k, str) for k in disabled):
        raise ValueError("disabled must be a list of alert names")
    prefs = AlertPrefs(
        disabled=frozenset(disabled),
        quiet_enabled=bool(payload.get("quiet_enabled", False)),
        quiet_start=policy.parse_hhmm(payload.get("quiet_start", "22:00")),
        quiet_end=policy.parse_hhmm(payload.get("quiet_end", "07:00")),
        digest_enabled=bool(payload.get("digest_enabled", False)),
        digest_time=policy.parse_hhmm(payload.get("digest_time", "18:00")),
    )
    policy.validate(prefs)
    return prefs


def save(db: Session, prefs: AlertPrefs, by: str, scope: str = OWNER) -> AlertPrefs:
    policy.validate(prefs)
    row = _row(db, scope)
    if row is None:
        row = AlertSettings(scope=scope)
        db.add(row)
    row.disabled_kinds = sorted(prefs.disabled)
    row.quiet_enabled = prefs.quiet_enabled
    row.quiet_start = policy.hhmm(prefs.quiet_start)
    row.quiet_end = policy.hhmm(prefs.quiet_end)
    row.digest_enabled = prefs.digest_enabled
    row.digest_time = policy.hhmm(prefs.digest_time)
    row.updated_by = by
    db.commit()
    return _prefs(row)


def held_count(db: Session, scope: str = OWNER) -> int:
    return db.execute(
        select(func.count())
        .select_from(AlertOutbox)
        .where(AlertOutbox.scope == scope, AlertOutbox.sent_at.is_(None))
    ).scalar_one()


def as_dict(prefs: AlertPrefs, held: int = 0) -> dict[str, Any]:
    def described(t: policy.AlertType, on: bool) -> dict[str, Any]:
        return {"key": t.key, "label": t.label, "explain": t.explain, "on": on}

    return {
        "switchable": [described(t, t.key not in prefs.disabled) for t in policy.SWITCHABLE],
        "always_on": [described(t, True) for t in policy.ALWAYS_ON],
        "disabled": sorted(prefs.disabled),
        "quiet_enabled": prefs.quiet_enabled,
        "quiet_start": policy.hhmm(prefs.quiet_start),
        "quiet_end": policy.hhmm(prefs.quiet_end),
        "digest_enabled": prefs.digest_enabled,
        "digest_time": policy.hhmm(prefs.digest_time),
        "last_digest_on": prefs.last_digest_on.isoformat() if prefs.last_digest_on else None,
        "held": held,
        "timezone": "IST",
    }


# ------------------------------------------------------------------ gate --

SessionFactory = Callable[[], AbstractContextManager[Session]]


def _default_sessions() -> SessionFactory:
    from swing_trade_ml.db.session import session_scope

    return session_scope


def gate(
    kind: str | None,
    text: str,
    *,
    now: datetime | None = None,
    sessions: SessionFactory | None = None,
    scope: str = OWNER,
) -> str:
    """ "send", "drop" or "held" for one message. Never raises; any failure is "send"."""
    if kind not in policy.SWITCHABLE_KEYS:
        return "send"  # safety-critical or untagged: no database read at all
    now = now or datetime.now(UTC)
    try:
        with (sessions or _default_sessions())() as db:
            decision = policy.route(kind, load(db, scope), now)
            if decision == "hold":
                db.add(AlertOutbox(scope=scope, kind=kind, text=text, created_at=now))
                db.commit()
                return "held"
            return decision
    except Exception as exc:  # noqa: BLE001 - fail open: tell the owner rather than lose the message
        log.warning("alerts.settings_unreadable_sending", kind=kind, error=str(exc))
        return "send"


# ----------------------------------------------------------------- flush --


def flush(db: Session, now: datetime, deliver: Callable[[str], bool], scope: str = OWNER) -> dict[str, Any]:
    """Send held messages once they are due. A message is marked sent only after Telegram took it;
    anything not delivered stays held and is tried again on the next run."""
    try:
        prefs = load(db, scope)
    except Exception as exc:  # noqa: BLE001 - unreadable settings: release what is held now
        log.warning("alerts.flush_settings_unreadable", error=str(exc))
        prefs = AlertPrefs()

    pending = (
        db.execute(
            select(AlertOutbox)
            .where(AlertOutbox.scope == scope, AlertOutbox.sent_at.is_(None))
            .order_by(AlertOutbox.created_at, AlertOutbox.id)
        )
        .scalars()
        .all()
    )
    # A type switched off after it was held is not sent.
    muted = [r for r in pending if r.kind in prefs.disabled]
    for r in muted:
        db.delete(r)
    pending = [r for r in pending if r.kind not in prefs.disabled]
    db.execute(
        delete(AlertOutbox).where(AlertOutbox.sent_at.is_not(None), AlertOutbox.sent_at < now - KEEP_SENT)
    )
    db.commit()

    oldest = pending[0].created_at if pending else None
    if not policy.due(prefs, now, oldest):
        return {"sent": 0, "held": len(pending), "dropped": len(muted)}

    by_id = {r.id: r for r in pending}
    sent = 0
    for text, ids in policy.compose_digest(
        [(r.id, r.created_at, r.text) for r in pending], digest=prefs.digest_enabled
    ):
        if not deliver(text):
            break
        for i in ids:
            by_id[i].sent_at = now
        sent += len(ids)
        db.commit()
    if sent and prefs.digest_enabled:
        row = _row(db, scope)
        if row is not None:
            row.last_digest_on = now.astimezone(policy.IST).date()
            db.commit()
    log.info("alerts.flushed", sent=sent, held=len(pending) - sent)
    return {"sent": sent, "held": len(pending) - sent, "dropped": len(muted)}
