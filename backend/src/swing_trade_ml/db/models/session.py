"""Dashboard users and the daily Zerodha access token."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin

#: What a login may do (api/deps.py Principal). owner: everything, as
#: is_superuser meant before. tester: the manual paper-testing book only.
#: member: what their plan opens, never a write outside their own sign-in.
ROLES = ("owner", "tester", "member")


class User(Base, TimestampMixin):
    """Login for the React dashboard.

    Deliberately separate from the Zerodha broker session: the dashboard should
    stay reachable to check positions even on a day nobody has logged in to
    Kite yet.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    # Null for accounts created via Google — there is no local password to
    # check for those, sign-in happens entirely through Google's identity.
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    # "local" | "google" — which flow created/authenticates this account.
    auth_provider: Mapped[str] = mapped_column(String(16), default="local")
    # Google's stable per-account identifier, used to find the local row on
    # repeat logins. Email alone isn't a safe join key long-term (Google lets
    # the same email be reused across accounts in edge cases); this is.
    google_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "free" | "pro" — see core/plans.py. Ignored for superusers,
    # who always see everything.
    plan: Mapped[str] = mapped_column(String(16), default="free", server_default="free")
    # See ROLES. is_superuser is kept equal to (role == "owner") on every
    # write (listeners below), so the frontend and an older build at rollback
    # still read the same answer.
    role: Mapped[str] = mapped_column(String(12), default=None, server_default="member")
    # Part of every session token ("tv"). Bumping it ends every session this
    # account has open: password change, "sign out everywhere", disable, role change.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Consecutive wrong passwords; reset on success. See endpoints/auth.py login.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<User {self.username}>"


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; expected one of {', '.join(ROLES)}")
    return role


@event.listens_for(User, "before_insert")
def _role_on_insert(_mapper, _conn, user: User) -> None:
    if user.role is None:
        user.role = "owner" if user.is_superuser else "member"
    _check_role(user.role)
    user.is_superuser = user.role == "owner"
    user.token_version = user.token_version or 0
    user.failed_login_count = user.failed_login_count or 0


@event.listens_for(User, "before_update")
def _role_on_update(_mapper, _conn, user: User) -> None:
    state = inspect(user)
    if state.attrs.role.history.has_changes():
        _check_role(user.role)
        user.is_superuser = user.role == "owner"
        user.token_version = (user.token_version or 0) + 1
    elif state.attrs.is_superuser.history.has_changes():
        user.role = "owner" if user.is_superuser else ("member" if user.role == "owner" else user.role)
        user.token_version = (user.token_version or 0) + 1


class PlanSettings(Base, TimestampMixin):
    """One row, id=1: the owner's master switch for plans. No row, or
    enabled=false, means plans are off and every signed-in account sees the
    whole app, as before plans existed."""

    __tablename__ = "plan_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class SubscriptionPlan(Base, TimestampMixin):
    """The owner's edits to one plan. A plan with no row here uses its
    defaults from core/plans.py, so a fresh database needs no seeding."""

    __tablename__ = "subscription_plans"

    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def __repr__(self) -> str:
        return f"<SubscriptionPlan {self.key}>"


class BrokerSession(Base, TimestampMixin):
    """A Kite access token.

    Kite invalidates tokens daily around 06:00 IST, so this table is an
    append-only log: the newest active row is loaded at startup, and a fresh
    login each trading morning adds a new one. Keeping history makes it
    possible to correlate an API failure with which token was in use.
    """

    __tablename__ = "broker_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broker: Mapped[str] = mapped_column(String(32), default="zerodha", index=True)
    kite_user_id: Mapped[str | None] = mapped_column(String(64))
    user_name: Mapped[str | None] = mapped_column(String(128))

    access_token: Mapped[str] = mapped_column(String(512))
    public_token: Mapped[str | None] = mapped_column(String(512))
    refresh_token: Mapped[str | None] = mapped_column(String(512))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<BrokerSession {self.broker} user={self.kite_user_id} active={self.is_active}>"
