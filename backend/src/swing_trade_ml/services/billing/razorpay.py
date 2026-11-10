"""Razorpay over plain HTTPS (httpx), HTTP Basic auth, https://api.razorpay.com/v1/.

We do not use the `razorpay` PyPI package (it documents Python 3.12+; this repo is 3.11).
Nothing here runs unless BILLING_PROVIDER=razorpay. The key guard: with ALLOW_LIVE_BILLING
false, a key id that does not start with `rzp_test_` is refused. Secrets are never logged
or put in an error message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.billing import signature
from swing_trade_ml.services.billing.base import (
    BillingConfigError,
    BillingError,
    CheckoutInfo,
    ProviderSubscription,
)

BASE_URL = "https://api.razorpay.com/v1/"
TEST_KEY_PREFIX = "rzp_test_"
TIMEOUT = 15.0
#: Billing cycles to charge; large = "until cancelled". The upper bound Razorpay accepts is UNVERIFIED.
TOTAL_COUNT = 120


def check_key_id(key_id: str) -> None:
    """Refuse a live key unless live billing was explicitly allowed. Names no secret."""
    if not key_id:
        raise BillingConfigError("RAZORPAY_KEY_ID is not set")
    if not settings.ALLOW_LIVE_BILLING and not key_id.startswith(TEST_KEY_PREFIX):
        raise BillingConfigError(
            "Live Razorpay keys are refused while ALLOW_LIVE_BILLING is false "
            f"(a test key id starts with {TEST_KEY_PREFIX})."
        )


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), tz=UTC) if value else None


class RazorpayProvider:
    name = "razorpay"

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        webhook_secret: str | None = None,
        plan_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._key_id = settings.RAZORPAY_KEY_ID if key_id is None else key_id
        self._key_secret = settings.RAZORPAY_KEY_SECRET if key_secret is None else key_secret
        self._webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET if webhook_secret is None else webhook_secret
        self._plan_id = settings.RAZORPAY_PLAN_ID_PRO_MONTHLY if plan_id is None else plan_id
        self._transport = transport
        check_key_id(self._key_id)
        if not self._key_secret:
            raise BillingConfigError("RAZORPAY_KEY_SECRET is not set")

    def _request(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        check_key_id(self._key_id)  # guards use, not only construction
        try:
            with httpx.Client(
                base_url=BASE_URL,
                auth=(self._key_id, self._key_secret),
                timeout=TIMEOUT,
                transport=self._transport,
            ) as client:
                resp = client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise BillingError(f"Razorpay request failed ({type(exc).__name__})") from None
        if resp.status_code >= 400:
            raise BillingError(f"Razorpay answered HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise BillingError("Razorpay sent a reply that is not JSON") from None

    def create_subscription(self, user, plan_key: str) -> CheckoutInfo:
        if plan_key != "pro":
            raise BillingError("Only the pro plan can be bought")
        if not self._plan_id:
            raise BillingConfigError("RAZORPAY_PLAN_ID_PRO_MONTHLY is not set")
        data = self._request(
            "POST",
            "subscriptions",
            {
                "plan_id": self._plan_id,
                "total_count": TOTAL_COUNT,
                "quantity": 1,
                "customer_notify": 1,
                "notes": {"user_id": str(user.id)},
            },
        )
        return CheckoutInfo(
            provider="razorpay",
            provider_subscription_id=data["id"],
            provider_plan_id=data.get("plan_id") or self._plan_id,
            key_id=self._key_id,  # the public id only; the secret never leaves the server
        )

    def fetch_subscription(self, provider_subscription_id: str) -> ProviderSubscription:
        data = self._request("GET", f"subscriptions/{provider_subscription_id}")
        # A reply we cannot read is a FAILED lookup (BillingError), never a state: the caller then
        # leaves the stored row untouched and the webhook answers 5xx so the provider retries.
        try:
            if not isinstance(data, dict) or not isinstance(data["status"], str) or not data["status"]:
                raise ValueError("no status")
            status = data["status"]
            return ProviderSubscription(
                provider_subscription_id=str(data["id"]),
                status=status,
                provider_plan_id=data.get("plan_id"),
                current_start=_ts(data.get("current_start")),
                current_end=_ts(data.get("current_end")),
                cancel_at_cycle_end=None,  # fetch does not report it (UNVERIFIED)
                # ended_at is UNVERIFIED as the cancellation time; it confirms a cycle-end cancel
                cancelled_at=_ts(data.get("ended_at")) if status == "cancelled" else None,
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            raise BillingError("Razorpay sent a subscription reply we cannot read") from None

    def cancel_subscription(self, provider_subscription_id: str, at_cycle_end: bool) -> None:
        self._request(
            "POST",
            f"subscriptions/{provider_subscription_id}/cancel",
            {"cancel_at_cycle_end": 1 if at_cycle_end else 0},
        )

    def verify_webhook(self, raw_body: bytes, signature_header: str) -> bool:
        return signature.verify(raw_body, signature_header, self._webhook_secret)
