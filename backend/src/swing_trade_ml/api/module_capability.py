"""Router guard: a plan caller must hold the capabilities of the optional module they call (#335 slice).

Runs after sign-in and the registry's on/off guard. The owner, the shared key and a tester while plans are
off are `unrestricted` (api/deps.py::PlanAccess), so for them it does nothing: defaults are unchanged. A
member is held to their plan always. Answers the same 403 text as the plan gate.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, status

from swing_trade_ml.api.deps import PlanAccessDep, PrincipalDep
from swing_trade_ml.core import capabilities, modules

NOT_IN_PLAN = "This part of the app isn't included in your plan."


def require_module_capability(module_id: str) -> Callable[..., None]:
    module = modules.switches.module(module_id)  # an unknown id fails at start-up

    def _guard(access: PlanAccessDep, principal: PrincipalDep) -> None:
        # A scoped service key has no plan: require_auth already checked its scope for this exact route.
        if principal.service_scope is not None or access.unrestricted:
            return
        if not capabilities.plan_may_use_module(module, access.features):
            raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_IN_PLAN)

    _guard.module_id = module_id  # type: ignore[attr-defined]  # the marker the route sweep reads
    return _guard
