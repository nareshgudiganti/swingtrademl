"""Daily operations digest: GET only, owner or a read_ops / read_all service key.

See services/ops_digest.py for what it contains and, deliberately, what it leaves out.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from swing_trade_ml.api.deps import DbSession, Principal, get_principal
from swing_trade_ml.services import ops_digest

OPS_SCOPES = frozenset({"read_ops", "read_all"})


async def _owner_or_ops_key(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    """Owner (login or the shared key) or an ops-capable service key. NOT a tester or member, even
    while plans are off, so the digest never reaches anyone else."""
    if principal.is_owner or principal.service_scope in OPS_SCOPES:
        return principal
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner or an ops service key can read this.")


router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(_owner_or_ops_key)])


@router.get("/digest")
def digest(db: DbSession) -> dict[str, Any]:
    return ops_digest.build_digest(db)
