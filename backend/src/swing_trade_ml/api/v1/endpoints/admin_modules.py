"""Owner-only switches for the optional modules (#291). Core modules are refused; every change is audited.

Switching a module off changes one row (`module_switches`) and nothing else: its data stays, its routes
answer "switched off", its scheduled jobs skip their runs. Switching it back on resumes it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from swing_trade_ml.api.admin_step_up import StepUpAlways
from swing_trade_ml.api.deps import Principal, actor_name, get_principal, require_owner
from swing_trade_ml.core import modules

admin = APIRouter(prefix="/admin/modules", tags=["modules"], dependencies=[Depends(require_owner)])


class SwitchIn(BaseModel):
    enabled: bool
    reason: str = Field(min_length=3, max_length=200)


def _row(m: modules.Module) -> dict:
    return {
        "id": m.id,
        "label": m.label,
        "core": m.core,
        "state": str(m.state),
        "enabled": modules.switches.enabled(m.id),
        "jobs": list(m.jobs),
        # the interface inventory (#258): what the module owns and needs
        "route_prefixes": list(m.route_prefixes),
        "capabilities": list(m.capabilities),
        "depends_on": list(m.depends_on),
        "packages": list(m.packages),
    }


@admin.get("")
def list_modules() -> dict:
    rows = [
        _row(m) for m in modules.switches.modules()
    ]  # reading the state first, so the flag below is current
    return {
        "modules": rows,
        "scope": modules.ENFORCEMENT["scope"],
        # True when the database could not be read: the list shows the declared defaults, not the real state
        "state_unknown": modules.switches.state_unknown,
    }


def _named_owner_person(principal: Principal = Depends(get_principal)) -> Principal:
    """The signed-in, named real-account owner only: not the shared key, not another owner."""
    if principal.via_api_key or principal.user is None or not principal.can_see_real_account:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the named owner, signed in, can do this.")
    return principal


@admin.put("/{module_id}", dependencies=[StepUpAlways])
def switch_module(
    module_id: str, body: SwitchIn, principal: Principal = Depends(_named_owner_person)
) -> dict:
    try:
        by = actor_name(principal)
        changed = modules.switches.set_enabled(module_id, body.enabled, by=by, reason=body.reason)
    except modules.UnknownModuleError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module.") from None
    except modules.CoreModuleError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A core module cannot be switched off.") from None
    except modules.ModuleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {"changed": changed, **_row(modules.switches.module(module_id))}
