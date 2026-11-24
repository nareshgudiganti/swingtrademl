"""Which plans may use which optional module (#335, first slice).

A module names the plan features (core/plans.py FEATURES) a plan must include to reach it. A module that
names none is owner-only for plan callers, which is how every optional module outside TradeMind is treated
today (core/plans.py: anything not opened by ROUTE_RULES or brain_route_access is owner-only). This is a
second, independent check beside the plan gate in api/deps.py: both must agree, so a mistake in one cannot
open a module.

Pure: no database, no request. The owner, the shared key and a tester while plans are off are never limited
here (the caller decides that; see api/module_capability.py).
"""

from __future__ import annotations

from collections.abc import Iterable

from swing_trade_ml.core.modules import Module


def plan_may_use_module(module: Module, plan_features: Iterable[str]) -> bool:
    """True when the plan includes every feature the module needs. No needed feature = owner-only = False."""
    if not module.capabilities:
        return False
    have = set(plan_features)
    return all(capability in have for capability in module.capabilities)
