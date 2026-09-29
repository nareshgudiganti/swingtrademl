"""Shared FastAPI dependencies."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.plans import DEFAULT_PLAN, FEATURES, PLAN_KEYS, ROUTE_RULES
from swing_trade_ml.core.security import decode_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]

bearer_scheme = HTTPBearer(auto_error=False)


def _user_from_bearer(credentials: HTTPAuthorizationCredentials, db: Session) -> User:
    payload = decode_access_token(credentials.credentials)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token")

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    """Resolve the dashboard user from a bearer token. Used where a human user
    identity is actually needed (e.g. showing "logged in as"), not just any
    valid credential — see `require_auth` for that."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return _user_from_bearer(credentials, db)


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class Principal:
    """Who is calling: a signed-in user, or a machine holding the API key."""

    user: User | None
    via_api_key: bool = False

    @property
    def is_owner(self) -> bool:
        return self.via_api_key or bool(self.user and self.user.is_superuser)


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    """Accepts either credential:
    - A bearer JWT from `POST /auth/login` — what the dashboard sends after a
      real username/password login.
    - The shared `X-API-Key` secret — kept for scripts, curl, CI, and other
      machine callers that have no user account and shouldn't need one.

    The bearer token is checked first when present, since a JWT identifies a
    specific person and is preferable for anything the dashboard does.
    """
    if credentials is not None:
        return Principal(user=_user_from_bearer(credentials, db))

    if x_api_key is not None and hmac.compare_digest(x_api_key, settings.API_KEY):
        return Principal(user=None, via_api_key=True)

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Provide a valid Authorization bearer token or X-API-Key header",
    )


@dataclass(frozen=True)
class PlanAccess:
    """What the caller's plan allows. The owner gets everything, unless they
    asked to preview a plan (X-Preview-Plan), in which case they get exactly
    what that plan's users get."""

    is_owner: bool
    plan: str | None
    features: frozenset[str] = frozenset()
    limits: dict = field(default_factory=dict)
    previewing: bool = False

    def has(self, feature: str) -> bool:
        return self.is_owner or feature in self.features

    @property
    def picks_per_day(self) -> int | None:
        return None if self.is_owner else (self.limits.get("picks_per_day") or None)

    @property
    def history_days(self) -> int | None:
        return None if self.is_owner else (self.limits.get("history_days") or None)

    @property
    def cap_tiers(self) -> set[str] | None:
        return None if self.is_owner else set(self.limits.get("allowed_cap_tiers") or [])


def plan_access_for(db: Session, principal: Principal, preview: str | None = None) -> PlanAccess:
    from swing_trade_ml.services.plans import get_plan

    if principal.is_owner and preview not in PLAN_KEYS:
        return PlanAccess(is_owner=True, plan=None)
    if principal.is_owner:
        key, previewing = preview, True
    else:
        user_plan = principal.user.plan if principal.user else None
        key, previewing = (user_plan if user_plan in PLAN_KEYS else DEFAULT_PLAN), False
    plan = get_plan(db, key)
    return PlanAccess(
        is_owner=False,
        plan=key,
        features=frozenset(k for k, on in plan["features"].items() if on),
        limits=plan["limits"],
        previewing=previewing,
    )


async def get_plan_access(
    principal: Annotated[Principal, Depends(get_principal)],
    db: DbSession,
    x_preview_plan: Annotated[str | None, Header(alias="X-Preview-Plan")] = None,
) -> PlanAccess:
    return plan_access_for(db, principal, x_preview_plan)


PlanAccessDep = Annotated[PlanAccess, Depends(get_plan_access)]


async def require_auth(request: Request, access: PlanAccessDep) -> None:
    """Gate for every route that can read positions or move money.

    Authenticates (see `get_principal`), then applies the caller's plan:
    the owner passes; anyone else passes only a route that
    core/plans.py::ROUTE_RULES opens with a feature their plan includes.
    Everything else — every write, the real account, safety, finance — is
    owner-only by default, so a new endpoint is never accidentally public.
    """
    if access.is_owner:
        return

    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    if path.startswith(settings.API_V1_PREFIX):
        path = path[len(settings.API_V1_PREFIX):]

    rule = ROUTE_RULES.get((request.method, path))
    if rule is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This part of the app isn't included in your plan.")
    feature, required_query = rule
    if not access.has(feature):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"“{FEATURES[feature]['label']}” isn't included in the {access.plan} plan.",
        )
    for name, value in required_query.items():
        if request.query_params.get(name) != value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This view isn't included in your plan.")


async def require_owner(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    """Owner-only screens such as the Plans Manager. Checks the real
    account, never a preview, so the owner can always get back out."""
    if not principal.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can do this.")
    return principal
