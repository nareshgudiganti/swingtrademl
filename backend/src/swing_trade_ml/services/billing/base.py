"""What every payment provider must offer, and the plain data it hands back."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class BillingError(Exception):
    """A provider call failed or billing is misconfigured. The message never carries a secret."""


class BillingConfigError(BillingError):
    """Settings are missing or unsafe (for example a live key while live billing is off)."""


@dataclass(frozen=True)
class CheckoutInfo:
    """What the browser needs to start paying. Razorpay: key_id + subscription_id for
    Standard Checkout. Fake: a local completion token/url instead of a key."""

    provider: str
    provider_subscription_id: str
    provider_plan_id: str | None = None
    key_id: str | None = None
    completion_url: str | None = None
    completion_token: str | None = None


@dataclass(frozen=True)
class ProviderSubscription:
    """The provider's current word on one subscription (times are timezone-aware UTC)."""

    provider_subscription_id: str
    status: str
    provider_plan_id: str | None = None
    current_start: datetime | None = None
    current_end: datetime | None = None
    # None = the provider does not say (Razorpay's fetch does not, as far as verified).
    cancel_at_cycle_end: bool | None = None
    cancelled_at: datetime | None = None


class BillingProvider(Protocol):
    name: str

    def create_subscription(self, user, plan_key: str) -> CheckoutInfo: ...

    def fetch_subscription(self, provider_subscription_id: str) -> ProviderSubscription: ...

    def cancel_subscription(self, provider_subscription_id: str, at_cycle_end: bool) -> None: ...

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool: ...
