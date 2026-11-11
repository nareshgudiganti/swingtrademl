"""Second step (two-step code) for the older privileged admin routes.

Off by default (`ADMIN_MFA_ENFORCED=false`): nothing changes for the owner today. When the owner turns it
on, every route that carries `Depends(require_admin_step_up)` needs a signed-in owner-role person who has
set up two-step sign-in AND holds a live token from POST /admin/mfa/verify, sent as `X-Admin-Mfa`.
The shared API key is refused there: no person is behind it to type a code.
Read-only views are not gated (see docs/design/ADMIN-ROUTE-AUDIT.md).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from swing_trade_ml.api.deps import DbSession, Principal, get_principal
from swing_trade_ml.core.config import settings
from swing_trade_ml.services import admin_mfa as mfa


async def require_admin_step_up(
    principal: Annotated[Principal, Depends(get_principal)],
    db: DbSession,
    x_admin_mfa: Annotated[str | None, Header(alias="X-Admin-Mfa")] = None,
) -> None:
    if not settings.ADMIN_MFA_ENFORCED:
        return
    user = principal.user
    if principal.via_api_key or user is None or user.role != "owner" or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the admin can do this.")
    if not mfa.is_enrolled(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "mfa_setup_required", "message": "Set up two-step sign-in first."},
        )
    if not mfa.step_up_valid(x_admin_mfa, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, {"code": "mfa_required", "message": "Enter your two-step code."}
        )


StepUp = Depends(require_admin_step_up)
