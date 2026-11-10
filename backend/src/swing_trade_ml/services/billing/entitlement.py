"""Who is on Pro right now. Computed at read time, so a cancelled-at-cycle-end
subscription falls back to Free by itself when the paid-through date passes.

`effective_plan_for` is pure. `effective_plan_for_user` is the glue the plan
system calls; it changes nothing for a person with no subscription and no grant.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings

DEFAULT_GRACE = timedelta(days=4)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def grant_in_force(grant: Any, now: datetime) -> bool:
    if grant.revoked_at is not None or grant.plan_key != "pro":
        return False
    starts = _aware(grant.starts_at)
    expires = _aware(grant.expires_at)
    return starts <= now and (expires is None or now < expires)


def subscription_entitled(sub: Any, now: datetime, grace: timedelta = DEFAULT_GRACE) -> bool:
    """Pro by payment: `active`, or `pending` (renewal retries), each only up to the paid-through
    date plus a short grace; or cancelled/scheduled-to-cancel until the paid-through date exactly.
    halted, paused, completed, created, authenticated, and cancelled past the paid-through date are Free."""
    status = sub.status
    end = _aware(sub.current_end)
    if status == "active":
        if sub.cancel_at_cycle_end:
            return end is not None and now < end  # ending: exactly what was paid for, no grace
        return end is None or now < end + grace
    if status == "pending":
        return end is not None and now < end + grace
    if status == "cancelled":
        return bool(sub.cancel_at_cycle_end) and end is not None and now < end
    return False


def effective_plan_for(
    stored_plan: str | None,
    subscription: Any,
    grants: Iterable[Any] | None,
    now: datetime,
    grace: timedelta = DEFAULT_GRACE,
) -> str:
    """ "pro" or "free". Pro when the stored plan is pro (admin-set, as before), or an
    unrevoked grant is in force, or a subscription is entitled. `subscription` may be one
    subscription, several, or None. The owner is never limited: callers handle that before this."""
    now = _aware(now)
    if stored_plan == "pro":
        return "pro"
    if any(grant_in_force(g, now) for g in (grants or ())):
        return "pro"
    if subscription is None:
        subs: list[Any] = []
    elif isinstance(subscription, Iterable):
        subs = list(subscription)
    else:
        subs = [subscription]
    if any(subscription_entitled(s, now, grace) for s in subs):
        return "pro"
    return "free"


def effective_plan_for_user(db: Session, user: Any, now: datetime | None = None) -> str | None:
    """The plan key plan resolution should use for this person.

    Returns the stored plan untouched unless billing is on AND a subscription or grant lifts
    them to Pro, so a person with neither resolves exactly as before. Billing off = always
    the stored plan."""
    stored = getattr(user, "plan", None)
    if user is None or stored == "pro" or not settings.BILLING_ENABLED:
        return stored
    from swing_trade_ml.db.models.billing import PlanGrant, Subscription

    now = now or datetime.now(UTC)
    subs = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalars().all()
    grants = db.execute(select(PlanGrant).where(PlanGrant.user_id == user.id)).scalars().all()
    if effective_plan_for(stored, subs, grants, now, timedelta(days=settings.BILLING_GRACE_DAYS)) == "pro":
        return "pro"
    return stored
