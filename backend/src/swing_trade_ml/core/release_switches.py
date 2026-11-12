"""Release switches: the four on/off controls that gate what reaches customers.

All default OFF. This module only reads them; it never changes order, sizing,
stop or limit behaviour. `require_release(key)` is a FastAPI dependency for NEW
surfaces added later - it is deliberately not attached to any existing route.

Where each switch applies today:
  open_signup       -> settings.ALLOW_SIGNUP (existing, enforced in auth.py)
  customer_screens  -> NEW; apply with Depends(require_release("customer_screens"))
  model_promotion   -> enforced at POST /ml/models/{id}/activate, POST /ml/train with
                       auto_activate, and `swingtrade train --activate` (see
                       `promotion_refusal`). Training itself is never blocked.
  real_orders       -> settings.ALLOW_REAL_HOLDINGS_ORDERS (existing, My Holdings
                       orders); live trading is separately latched by ALLOW_LIVE_TRADING
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, status

from swing_trade_ml.core.config import settings


@dataclass(frozen=True)
class ReleaseSwitch:
    key: str
    label: str  # plain English
    env_var: str
    setting: str  # attribute name on settings
    how_read: str
    existing: bool  # True when the flag predates this registry


SWITCHES: tuple[ReleaseSwitch, ...] = (
    ReleaseSwitch(
        "open_signup",
        "Anyone can sign up without an invitation",
        "ALLOW_SIGNUP",
        "ALLOW_SIGNUP",
        "settings.ALLOW_SIGNUP, read on each sign-up request",
        True,
    ),
    ReleaseSwitch(
        "customer_screens",
        "Customer screens are visible to non-owner customers",
        "ALLOW_CUSTOMER_SCREENS",
        "ALLOW_CUSTOMER_SCREENS",
        "settings.ALLOW_CUSTOMER_SCREENS, read by require_release('customer_screens')",
        False,
    ),
    ReleaseSwitch(
        "model_promotion",
        "A trained model may be promoted to live use",
        "ALLOW_MODEL_PROMOTION",
        "ALLOW_MODEL_PROMOTION",
        "settings.ALLOW_MODEL_PROMOTION, read by require_release('model_promotion')",
        False,
    ),
    ReleaseSwitch(
        "real_orders",
        "Real-money orders from My Holdings are allowed",
        "ALLOW_REAL_HOLDINGS_ORDERS",
        "ALLOW_REAL_HOLDINGS_ORDERS",
        "settings.ALLOW_REAL_HOLDINGS_ORDERS, read by the broker order guard",
        True,
    ),
)

_BY_KEY = {s.key: s for s in SWITCHES}


def is_enabled(key: str) -> bool:
    return bool(getattr(settings, _BY_KEY[key].setting))


def switch_states() -> list[dict]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "env_var": s.env_var,
            "how_read": s.how_read,
            "enabled": is_enabled(s.key),
            "default": False,
            "existing": s.existing,
        }
        for s in SWITCHES
    ]


PROMOTION_OFF_MESSAGE = (
    "Promoting a model to live use is switched off. Training still works and the model is saved, "
    "but it cannot become the active model until the owner turns on ALLOW_MODEL_PROMOTION."
)


def promotion_refusal() -> str | None:
    """Plain-English refusal while model promotion is off, else None."""
    return None if is_enabled("model_promotion") else PROMOTION_OFF_MESSAGE


def require_release(key: str) -> Callable[[], None]:
    """Dependency for a NEW route: answers 404 (the surface does not exist yet)
    while the switch is off."""
    if key not in _BY_KEY:
        raise KeyError(f"Unknown release switch: {key}")

    def _guard() -> None:
        if not is_enabled(key):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    return _guard
