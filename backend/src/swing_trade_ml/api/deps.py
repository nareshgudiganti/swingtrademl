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
from swing_trade_ml.core.plans import DEFAULT_PLAN, FEATURES, PLAN_KEYS, ROUTE_RULES, brain_route_access
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

    uid = payload.get("uid")
    if isinstance(uid, int):
        user = db.get(User, uid)
        if user is not None and user.username != username:
            user = None
    else:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    # Tokens issued before P0 carry no "tv"; they count as version 0 and stop
    # working the first time this account's sessions are ended.
    if int(payload.get("tv", 0)) != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Please sign in again.")
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
    def role(self) -> str:
        if self.via_api_key:
            return "owner"
        return self.user.role if self.user is not None else "member"

    @property
    def is_owner(self) -> bool:
        return self.via_api_key or bool(self.user and self.user.role == "owner")

    @property
    def is_tester(self) -> bool:
        return bool(self.user and self.user.role == "tester")

    @property
    def can_see_real_account(self) -> bool:
        """The real Zerodha account (My Holdings, real orders): signed-in owner
        accounts named in REAL_ACCOUNT_USERS, and the shared API key (the owner's
        own scripts). Testers and members never."""
        if self.via_api_key:
            return True
        if self.user is None or self.user.role != "owner":
            return False
        allowed = {n.strip().lower() for n in settings.REAL_ACCOUNT_USERS.split(",") if n.strip()}
        return self.user.username.lower() in allowed


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
    """What the caller may see. `unrestricted` callers see everything: the
    owner always, and a tester while plans are switched off. Members always get
    their plan's rules. The owner can still preview a plan
    (X-Preview-Plan) and then gets exactly what that plan's users get."""

    unrestricted: bool
    plan: str | None
    features: frozenset[str] = frozenset()
    limits: dict = field(default_factory=dict)
    previewing: bool = False

    def has(self, feature: str) -> bool:
        return self.unrestricted or feature in self.features

    @property
    def picks_per_day(self) -> int | None:
        return None if self.unrestricted else (self.limits.get("picks_per_day") or None)

    @property
    def history_days(self) -> int | None:
        return None if self.unrestricted else (self.limits.get("history_days") or None)

    @property
    def cap_tiers(self) -> set[str] | None:
        return None if self.unrestricted else set(self.limits.get("allowed_cap_tiers") or [])


def plan_access_for(db: Session, principal: Principal, preview: str | None = None) -> PlanAccess:
    from swing_trade_ml.services.plans import get_plan, plans_enabled

    if principal.is_owner and preview in PLAN_KEYS:
        key, previewing = preview, True
    elif principal.is_owner or (principal.is_tester and not plans_enabled(db)):
        # Owners see everything. A tester keeps today's view (the whole app
        # while plans are off) until their own member account exists (release C).
        # A member never: "plans off" no longer means "everyone sees the house book" (S1).
        return PlanAccess(unrestricted=True, plan=None)
    else:
        user_plan = principal.user.plan if principal.user else None
        key, previewing = (user_plan if user_plan in PLAN_KEYS else DEFAULT_PLAN), False
    plan = get_plan(db, key)
    return PlanAccess(
        unrestricted=False,
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


READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The only writes a tester may make: the manual paper-testing book. The close
#: handler also checks the position really is in that book.
TESTER_WRITES: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/portfolio/tester/buy"), ("POST", "/portfolio/positions/{position_id}/close")}
)

#: Self-service routes any signed-in PERSON may call, whatever their role or
#: plan: their own watchlist (endpoints/my_watchlist.py), and nothing else.
#: These are the only writes open to a member. They are safe to open because the
#: handlers only ever read or change the caller's own rows, keyed by the user id
#: from the credential itself (never from the body or the path), and they touch
#: no money, order, position, limit or the bot's global watchlist. An API-key
#: caller has no person behind it, so it is refused here (and again in the handler).
SELF_SERVICE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/me/watchlist"),
        ("GET", "/me/watchlist/search"),
        ("POST", "/me/watchlist"),
        ("DELETE", "/me/watchlist/{symbol}"),
    }
)
SELF_SERVICE_NEEDS_PERSON = "Sign in with your own account to use your watchlist."

#: Owner-private areas nobody but the owner may even read, whatever the plans
#: switch says: a tester (who otherwise sees the shared app while plans are off)
#: and a plain member alike. No plan feature opens any of them. The owner's
#: money, the Zerodha session, the safety switches, alerts and the brain's
#: go-live controls. `/admin` already answers only the owner itself.
#: `/brain/compare` and `/brain/trial-journal` are the rest of the go-live
#: router (endpoints/brain_golive.py), which has no `/brain/golive` prefix.
TESTER_PRIVATE_PREFIXES: tuple[str, ...] = (
    "/finance",
    "/mutual-funds",
    "/auth/kite",
    "/safety",
    "/notifications",
    "/brain/alerts",
    "/brain/approvals",
    "/brain/stage",
    "/brain/compare",
    "/brain/trial-journal",
    "/admin",
)
PRIVATE_AREA = "This is a private part of the app. You don't have access."


def _route_path(request: Request) -> str:
    """The matched route's template (e.g. /portfolio/positions/{position_id}/close), minus the API prefix."""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    if path.startswith(settings.API_V1_PREFIX):
        path = path[len(settings.API_V1_PREFIX) :]
    return path


def _is_private_area(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in TESTER_PRIVATE_PREFIXES)


async def require_auth(
    request: Request,
    access: PlanAccessDep,
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    """Gate for every route that can read positions or move money.

    Authenticates (see `get_principal`), then applies the caller's plan:
    the owner passes, as does a tester while plans are switched off (never
    a member: "plans off" no longer opens the house book, S1); anyone else
    passes only a route that
    core/plans.py::ROUTE_RULES opens with a feature their plan includes.
    Everything else — every write, the real account, safety, finance — is
    owner-only by default, so a new endpoint is never accidentally public.

    Every write needs the owner (or the API key) whatever the plans switch
    says. "Plans off" means nobody's *view* is limited; it never meant any
    signed-in account may change the trading stage, approve a buy or pull a
    safety switch, which it silently allowed before (audit F-17).
    """
    path = _route_path(request)
    # A person's own watchlist: open to every signed-in person (no plan needed), never to the API key.
    if (request.method, path) in SELF_SERVICE_ROUTES:
        if principal.user is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, SELF_SERVICE_NEEDS_PERSON)
        return
    if (
        request.method not in READ_METHODS
        and not principal.is_owner
        and not (principal.is_tester and (request.method, path) in TESTER_WRITES)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change this.")
    # Nobody but the owner reads the owner's private areas: not a tester (who sees the
    # shared app while plans are off), not a member on any plan, plans on or off.
    if not principal.is_owner and _is_private_area(path):
        raise HTTPException(status.HTTP_403_FORBIDDEN, PRIVATE_AREA)
    if access.unrestricted:
        return

    brain_gate = brain_route_access(request.method, path)
    if brain_gate == "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This part of the app isn't included in your plan.")
    if brain_gate == "trademind":
        if not access.has("trademind"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"“{FEATURES['trademind']['label']}” isn't included in the {access.plan} plan.",
            )
        return

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


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def actor_name(principal: Principal) -> str:
    """Who made a change, from the credential itself: never a name sent in the request body."""
    if principal.user is not None:
        return principal.user.username
    return "api-key"


async def require_real_account(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    """Guards everything that reads or moves the real Zerodha account."""
    if not principal.can_see_real_account:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This is a private account. You don't have access.")
    return principal


def book_for(principal: Principal, book: str) -> str:
    """The book a caller may ask for. The real (My Holdings) book is hidden from
    everyone else: asking for it is refused, and "all" quietly becomes the bot's
    own book, so hand-bought shares never leak into a total. A tester may only
    read the tester book: the house (bot) book is the owner's."""
    if principal.can_see_real_account:
        return book
    if principal.is_tester and book != "tester":
        raise HTTPException(status.HTTP_403_FORBIDDEN, PRIVATE_AREA)
    if book == "real":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This is a private account. You don't have access.")
    return "bot" if book == "all" else book


async def require_owner_or_tester(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    """The manual paper-testing book: the owner (or the API key) and testers only.
    Uses the two existing roles; a plain member is refused whatever their plan."""
    if not (principal.is_owner or principal.is_tester):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the owner or a tester can make practice test buys."
        )
    return principal


async def require_owner(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    """Owner-only screens such as the Plans Manager. Checks the real
    account, never a preview, so the owner can always get back out."""
    if not principal.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can do this.")
    return principal
