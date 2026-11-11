"""An in-memory stand-in for the payment provider: no network, deterministic.

Tests and the local private journey use it to walk a subscription through
activated / charged / pending / halted / cancelled / completed. `simulate`
changes the fake's state exactly as the real provider would before it sends
the webhook; the app then fetches that state like it does for Razorpay.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from swing_trade_ml.services.billing import signature
from swing_trade_ml.services.billing.base import (
    BillingError,
    CheckoutInfo,
    ProviderSubscription,
)

FAKE_WEBHOOK_SECRET = "fake-webhook-secret"  # not a real secret: the fake has no network
CYCLE = timedelta(days=30)
SIMULATED_EVENTS = ("activated", "charged", "pending", "halted", "cancelled", "completed")


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self._subs: dict[str, ProviderSubscription] = {}
        self._counter = itertools.count(1)

    def create_subscription(self, user, plan_key: str) -> CheckoutInfo:
        sub_id = f"sub_fake_{next(self._counter):06d}"
        self._subs[sub_id] = ProviderSubscription(
            provider_subscription_id=sub_id,
            status="created",
            provider_plan_id=f"plan_fake_{plan_key}",
            cancel_at_cycle_end=False,
        )
        return CheckoutInfo(
            provider="fake",
            provider_subscription_id=sub_id,
            provider_plan_id=f"plan_fake_{plan_key}",
            completion_url="/billing/fake/simulate",
            completion_token=sub_id,
        )

    def fetch_subscription(self, provider_subscription_id: str) -> ProviderSubscription:
        try:
            return self._subs[provider_subscription_id]
        except KeyError:
            raise BillingError("Unknown subscription") from None

    def cancel_subscription(self, provider_subscription_id: str, at_cycle_end: bool) -> None:
        sub = self.fetch_subscription(provider_subscription_id)
        if at_cycle_end:
            if sub.status in ("created", "authenticated"):
                raise BillingError("Cannot cancel at cycle end before the first payment")
            self._subs[provider_subscription_id] = replace(sub, cancel_at_cycle_end=True)
        else:
            self._subs[provider_subscription_id] = replace(
                sub, status="cancelled", cancelled_at=datetime.now(UTC), cancel_at_cycle_end=False
            )

    def verify_webhook(self, raw_body: bytes, signature_header: str) -> bool:
        return signature.verify(raw_body, signature_header, FAKE_WEBHOOK_SECRET)

    # -- test / private-journey driver ------------------------------------------------

    def simulate(
        self, provider_subscription_id: str, event: str, now: datetime | None = None
    ) -> ProviderSubscription:
        if event not in SIMULATED_EVENTS:
            raise BillingError(f"Unknown event: {event}")
        now = now or datetime.now(UTC)
        sub = self.fetch_subscription(provider_subscription_id)
        if event in ("activated", "charged"):
            new = replace(sub, status="active", current_start=now, current_end=now + CYCLE)
        elif event == "pending":
            new = replace(sub, status="pending")
        elif event == "halted":
            new = replace(sub, status="halted")
        elif event == "cancelled":
            new = replace(sub, status="cancelled", cancelled_at=now)
        else:  # completed
            new = replace(sub, status="completed")
        self._subs[provider_subscription_id] = new
        return new

    def set_state(self, provider_subscription_id: str, **changes) -> None:
        """Tests only: overwrite fields of the fake's stored subscription."""
        current = self.fetch_subscription(provider_subscription_id)
        self._subs[provider_subscription_id] = replace(current, **changes)
