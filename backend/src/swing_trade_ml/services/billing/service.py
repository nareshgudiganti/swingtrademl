"""Billing actions: pick the provider, create/cancel subscriptions, and apply webhooks.

Webhook rule: ordering is not guaranteed, so on every subscription event we FETCH the
subscription's current state from the provider and upsert from that, never from the
event's own order or contents. The event row and the state change share one transaction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.billing import BillingEvent, Subscription
from swing_trade_ml.services.billing.base import (
    BillingConfigError,
    BillingError,
    BillingProvider,
    CheckoutInfo,
    ProviderSubscription,
)
from swing_trade_ml.services.billing.fake import FakeProvider
from swing_trade_ml.services.billing.razorpay import RazorpayProvider

log = get_logger(__name__)

_provider: BillingProvider | None = None
_fake: FakeProvider | None = None


def get_provider() -> BillingProvider:
    """The configured provider (cached). Raises BillingConfigError for unsafe or missing settings."""
    global _provider, _fake
    if _provider is not None:
        return _provider
    name = settings.BILLING_PROVIDER
    if name == "fake":
        _fake = _fake or FakeProvider()
        _provider = _fake
    elif name == "razorpay":
        _provider = RazorpayProvider()
    else:
        raise BillingConfigError(f"Unknown BILLING_PROVIDER {name!r}")
    return _provider


def set_provider(provider: BillingProvider | None) -> None:
    """Tests: force a provider (None = rebuild from settings next time)."""
    global _provider, _fake
    _provider = provider
    if provider is None:
        _fake = None


def apply_provider_state(sub: Subscription, state: ProviderSubscription) -> None:
    sub.status = state.status
    sub.provider_plan_id = state.provider_plan_id or sub.provider_plan_id
    sub.current_start = state.current_start
    sub.current_end = state.current_end
    sub.cancelled_at = state.cancelled_at
    if state.cancel_at_cycle_end is not None:
        sub.cancel_at_cycle_end = state.cancel_at_cycle_end
    # Provider silent about the flag: keep what we recorded when the member asked to cancel.


def sync_subscription(
    db: Session, sub: Subscription, provider: BillingProvider | None = None
) -> Subscription:
    state = (provider or get_provider()).fetch_subscription(sub.provider_subscription_id)
    apply_provider_state(sub, state)
    sub.updated_at = datetime.now(UTC)
    return sub


def latest_subscription(db: Session, user_id: int) -> Subscription | None:
    return (
        db.execute(
            select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id.desc())
        )
        .scalars()
        .first()
    )


def create_checkout(db: Session, user: Any, plan_key: str = "pro") -> CheckoutInfo:
    provider = get_provider()
    info = provider.create_subscription(user, plan_key)
    db.add(
        Subscription(
            user_id=user.id,
            provider=info.provider,
            provider_subscription_id=info.provider_subscription_id,
            provider_plan_id=info.provider_plan_id,
            status="created",
        )
    )
    db.flush()
    return info


def cancel(db: Session, sub: Subscription, at_cycle_end: bool) -> Subscription:
    provider = get_provider()
    provider.cancel_subscription(sub.provider_subscription_id, at_cycle_end)
    if at_cycle_end:
        sub.cancel_at_cycle_end = True  # recorded by us: Razorpay's fetch does not report it
    sync_subscription(db, sub, provider)
    if at_cycle_end:
        sub.cancel_at_cycle_end = True
    db.flush()
    return sub


def _subscription_id_from(payload: dict) -> str | None:
    try:
        return payload["payload"]["subscription"]["entity"]["id"]
    except (KeyError, TypeError):
        return None


def process_event(
    db: Session,
    *,
    provider_name: str,
    event_id: str,
    event_type: str,
    payload_hash: str | None,
    provider_subscription_id: str | None,
    provider: BillingProvider | None = None,
) -> str:
    """Record one event once and apply it. Returns the outcome. Duplicate = 'duplicate', no effect.

    The caller commits. A provider failure propagates after the event row is forgotten, so the
    provider's retry is processed afresh."""
    try:
        with db.begin_nested():
            event = BillingEvent(
                provider=provider_name,
                event_id=event_id[:96],
                event_type=event_type[:48],
                payload_hash=payload_hash,
            )
            db.add(event)
            db.flush()
    except IntegrityError:
        return "duplicate"
    try:
        with db.begin_nested():  # a failed provider call undoes only the state change
            if not event_type.startswith("subscription.") or not provider_subscription_id:
                outcome = "ignored"
            else:
                sub = db.execute(
                    select(Subscription).where(
                        Subscription.provider_subscription_id == provider_subscription_id
                    )
                ).scalar_one_or_none()
                if sub is None:
                    outcome = "unknown_subscription"
                else:
                    sync_subscription(db, sub, provider)
                    outcome = f"synced:{sub.status}"
    except Exception:
        db.delete(event)  # forget the event so the provider's retry is processed afresh
        db.flush()
        raise
    event.processed_at = datetime.now(UTC)
    event.outcome = outcome[:48]
    db.flush()
    return outcome


def handle_webhook(
    db: Session, raw_body: bytes, signature_header: str | None, event_id_header: str | None
) -> str:
    """Verify first (over the raw bytes), then parse. Raises BillingError('bad signature') on failure."""
    provider = get_provider()
    if not provider.verify_webhook(raw_body, signature_header or ""):
        raise BillingError("bad signature")
    digest = hashlib.sha256(raw_body).hexdigest()
    try:
        payload = json.loads(raw_body)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    event_type = str(payload.get("event") or "unknown")
    event_id = event_id_header or digest  # a re-delivery of identical bytes dedupes by hash
    outcome = process_event(
        db,
        provider_name=provider.name,
        event_id=event_id,
        event_type=event_type,
        payload_hash=digest,
        provider_subscription_id=_subscription_id_from(payload),
        provider=provider,
    )
    log.info("billing.webhook", event_type=event_type, outcome=outcome)  # no body, no secrets
    return outcome
