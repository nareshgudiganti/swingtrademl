"""Customer account deletion: request -> email confirmation -> grace period -> anonymise.

What "deleted" means here (proposal, see docs/RETENTION.md): the person's personal data is removed or
blanked and the account row stays as an anonymous stub (username "deleted-<id>", no email, name,
mobile, password or Google id, inactive), so billing records and the audit trail keep their links.

Safety rules:
- Owner accounts (role owner / superuser) can never be deleted this way.
- A live Pro subscription is cancelled at the provider FIRST. If that fails, nothing is scheduled and the
  email link keeps working; the job retries a failed cancel later and never deletes with a live subscription.
- Only this person's own rows are touched. Shared market and model data are never read or written here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.security import verify_password
from swing_trade_ml.db.models.account_deletion import AccountDeletion
from swing_trade_ml.db.models.audit import AuditLog, LoginCode
from swing_trade_ml.db.models.auth_tokens import AuthToken
from swing_trade_ml.db.models.billing import Subscription
from swing_trade_ml.db.models.invites import InviteRequest
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import audit, auth_tokens
from swing_trade_ml.services.billing import service as billing
from swing_trade_ml.services.billing.base import BillingError

log = get_logger(__name__)

OPEN = ("pending", "scheduled")
ENDED_SUBSCRIPTION = ("cancelled", "completed")


class DeletionRefusedError(Exception):
    """A rule stopped the request. The message is plain English and safe to show."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def is_protected(user: User) -> bool:
    return user.role == "owner" or bool(user.is_superuser)


def open_request(db: Session, user_id: int) -> AccountDeletion | None:
    return db.execute(
        select(AccountDeletion).where(AccountDeletion.user_id == user_id, AccountDeletion.status.in_(OPEN))
    ).scalar_one_or_none()


def latest_request(db: Session, user_id: int) -> AccountDeletion | None:
    return (
        db.execute(
            select(AccountDeletion)
            .where(AccountDeletion.user_id == user_id)
            .order_by(AccountDeletion.id.desc())
        )
        .scalars()
        .first()
    )


def blocks_sign_in(db: Session, user: User) -> bool:
    """True once deletion is confirmed (grace period) or done. A mere request does not block sign-in."""
    row = latest_request(db, user.id)
    return row is not None and row.status in ("scheduled", "completed")


def request_deletion(db: Session, user: User, password: str | None, ip: str | None = None) -> str:
    """Start (or restart) a request. Returns the one-time email token. Caller commits and sends the email."""
    if is_protected(user):
        raise DeletionRefusedError("The owner account cannot be deleted here.")
    # Local account: prove it is really them. Google accounts (no password) confirm by email only.
    if user.hashed_password and not (password and verify_password(password, user.hashed_password)):
        raise DeletionRefusedError("That password is not right.")
    row = open_request(db, user.id)
    if row is not None and row.status == "scheduled":
        raise DeletionRefusedError("Deletion is already scheduled for this account.")
    if row is None:
        db.add(AccountDeletion(user_id=user.id, status="pending"))
        db.flush()
    return auth_tokens.issue(db, user, "delete_account", ip)


def _live_subscriptions(db: Session, user_id: int) -> list[Subscription]:
    return list(
        db.execute(
            select(Subscription).where(
                Subscription.user_id == user_id, Subscription.status.notin_(ENDED_SUBSCRIPTION)
            )
        )
        .scalars()
        .all()
    )


def cancel_live_subscriptions(db: Session, user_id: int) -> int:
    """Cancel every live subscription right now (no wait for the paid-through date). Raises BillingError
    if the provider cannot be reached or refuses, so the caller can stop before changing anything."""
    subs = _live_subscriptions(db, user_id)
    for sub in subs:
        billing.cancel(db, sub, at_cycle_end=False)
        if sub.status not in ENDED_SUBSCRIPTION:
            raise BillingError("The subscription is still active after cancelling.")
    return len(subs)


@dataclass
class Scheduled:
    user: User
    scheduled_for: datetime
    cancel_token: str
    cancelled_subscriptions: int


def confirm_deletion(db: Session, raw_token: str) -> Scheduled | None:
    """Use the emailed token: cancel Pro, end every session, start the grace period.
    None = bad/used/expired token or nothing pending. BillingError propagates (the caller rolls back, so
    the token is not used up and the person can try again). Caller commits."""
    user = auth_tokens.redeem(db, raw_token, "delete_account")
    if user is None:
        return None
    row = open_request(db, user.id)
    if row is None or row.status != "pending" or is_protected(user):
        return None
    cancelled = cancel_live_subscriptions(db, user.id)
    now = _now()
    row.status = "scheduled"
    row.confirmed_at = now
    row.scheduled_for = now + timedelta(days=settings.ACCOUNT_DELETION_GRACE_DAYS)
    user.token_version = (user.token_version or 0) + 1  # every open session ends now
    cancel_token = auth_tokens.issue(db, user, "cancel_delete")
    return Scheduled(user, row.scheduled_for, cancel_token, cancelled)


def cancel_deletion(db: Session, raw_token: str) -> User | None:
    """The "I changed my mind" link. Works only while the grace period runs. A Pro subscription cancelled
    for the deletion stays cancelled (the person can subscribe again). Caller commits."""
    user = auth_tokens.redeem(db, raw_token, "cancel_delete")
    if user is None:
        return None
    row = open_request(db, user.id)
    now = _now()
    if row is None or row.status != "scheduled" or (row.scheduled_for and row.scheduled_for <= now):
        return None
    row.status = "cancelled"
    row.cancelled_at = now
    user.token_version = (user.token_version or 0) + 1
    return user


def anonymise(db: Session, user: User) -> None:
    """Remove personal data. Does not commit. Deletes only rows belonging to this user."""
    label = f"deleted-{user.id}"
    db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    db.execute(delete(LoginCode).where(LoginCode.user_id == user.id))
    db.execute(delete(UserWatchlistItem).where(UserWatchlistItem.user_id == user.id))
    db.execute(
        update(InviteRequest)
        .where(InviteRequest.user_id == user.id)
        .values(name="Deleted", email=f"{label}@deleted.invalid", phone=None, note=None, code_hash=None)
    )
    # The audit trail keeps what happened, but not the person's username.
    db.execute(update(AuditLog).where(AuditLog.actor_user_id == user.id).values(actor_label=label))
    user.username = label
    user.email = None
    user.full_name = None
    user.mobile = None
    user.hashed_password = None
    user.google_id = None
    user.email_verified_at = None
    user.is_active = False
    user.plan = "free"
    user.role = "member"
    user.locked_until = None
    user.token_version = (user.token_version or 0) + 1


def process_due(db: Session, now: datetime | None = None, limit: int = 50) -> dict[str, int]:
    """The daily job: finish every confirmed deletion whose grace period has ended. Each person is its own
    transaction, so one failure never blocks the rest. Does nothing while the feature is switched off."""
    result = {"completed": 0, "skipped": 0, "protected": 0}
    if not settings.ACCOUNT_DELETION_ENABLED:
        return result
    now = now or _now()
    ids = (
        db.execute(
            select(AccountDeletion.id)
            .where(AccountDeletion.status == "scheduled", AccountDeletion.scheduled_for <= now)
            .order_by(AccountDeletion.id)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    for row_id in ids:
        row = db.get(AccountDeletion, row_id, with_for_update=True)
        user = db.get(User, row.user_id) if row else None
        if row is None or user is None or row.status != "scheduled":
            db.commit()
            continue
        if is_protected(user):  # promoted since the request: never delete
            row.status, row.cancelled_at, row.note = "cancelled", now, "protected_account"
            db.commit()
            result["protected"] += 1
            continue
        try:
            with db.begin_nested():
                cancel_live_subscriptions(db, user.id)
        except BillingError as exc:
            db.commit()  # release the row lock; nothing else changed
            log.warning("account_deletion.billing_cancel_failed", user_id=row.user_id, error=str(exc))
            result["skipped"] += 1
            continue
        anonymise(db, user)
        row.status, row.completed_at = "completed", now
        audit.record(
            db, "account.deletion_completed", actor_label="system", target_type="user", target_id=user.id
        )
        db.commit()
        result["completed"] += 1
    return result


def export_data(db: Session, user: User) -> dict:
    """The person's own data as plain JSON (profile, watchlist, subscriptions, deletion status)."""
    items = (
        db.execute(
            select(UserWatchlistItem)
            .where(UserWatchlistItem.user_id == user.id)
            .order_by(UserWatchlistItem.id)
        )
        .scalars()
        .all()
    )
    subs = (
        db.execute(select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.id))
        .scalars()
        .all()
    )
    dele = latest_request(db, user.id)
    return {
        "exported_at": _iso(_now()),
        "profile": {
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "mobile": user.mobile,
            "plan": user.plan,
            "email_verified_at": _iso(user.email_verified_at),
            "created_at": _iso(getattr(user, "created_at", None)),
        },
        "watchlist": [
            {
                "symbol": i.symbol,
                "added_at": _iso(i.added_at),
                "removed_at": _iso(i.removed_at),
                "note": i.note,
                "buy_price": i.buy_price,
            }
            for i in items
        ],
        "subscriptions": [
            {
                "status": s.status,
                "current_start": _iso(s.current_start),
                "current_end": _iso(s.current_end),
                "cancelled_at": _iso(s.cancelled_at),
            }
            for s in subs
        ],
        "account_deletion": (
            {"status": dele.status, "scheduled_for": _iso(dele.scheduled_for)} if dele else None
        ),
    }
