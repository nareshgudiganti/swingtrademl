# P0 (Release A): Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the login and permission weaknesses found in the security review, before any new member is let in. No change to trading, the house trial or the Zerodha path.

**Architecture:** Add an explicit `role` (`owner` · `tester` · `member`) next to `is_superuser`, kept equal on every write so old code and the frontend stay correct. Sessions carry a `token_version` so they can be revoked. Logins lock after repeated failures. Google sign-in hands over a one-time code instead of a JWT in the URL. Non-owner reads fail closed. Every sign-in and admin action lands in a new append-only `audit_log`. Everything is Postgres-only; Redis stays unused.

**Tech Stack:** FastAPI, SQLAlchemy 2 (Mapped), Alembic, PyJWT, bcrypt, pytest with the shared `client`/`db_session` fixtures, React + TypeScript (checked with `npx tsc --noEmit -p .`).

**Spec:** `docs/superpowers/specs/2026-10-16-multi-user-portfolios-design.md` (revision 2): §6 (threat model, findings S1–S6, S9, authorization model, account audit), §8.1 (rollback rehearsal), §9 (auth acceptance), §10 release A.

## Global Constraints

- Work on a new local branch `feature/p0-security` cut from `develop`. **No push, merge, deploy, or prod permission change** without the owner's separate approval.
- Do not touch: order placement, sizing, stops, limits, `services/risk.py`, `services/execution.py` trading logic, brain modules, `TRADING_MODE`, `ALLOW_LIVE_TRADING`, `REAL_ACCOUNT_USERS` value.
- **No role is changed on prod by this plan's code.** The migration reproduces today's powers exactly (`is_superuser → owner`). The owner's decision (2026-10-16: `sudeeksha` only owner, all others secondary with no owner powers and no My Holdings) is applied after deploy, one command at a time, via the Task 9 CLI (runbook step 12). `REAL_ACCOUNT_USERS` stays `sudeeksha`.
- No new paid infrastructure. No Redis use. Postgres only.
- Run tests with `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE .venv/Scripts/python.exe -m pytest …`. Docker Postgres must be up (port 5433 test DB). DB tests hang silently otherwise.
- `ruff format` only files you touched. Never the whole package. No prettier on existing frontend files.
- Never read, print or commit `.env` values.
- Login failure message (exact, every failure path): `Incorrect username or password. After several wrong tries, sign-in pauses for 15 minutes.`
- Lockout: **5** consecutive failures → locked **15 minutes**.
- Google one-time code lifetime: **60 seconds**, single use.
- Plain English in every user-facing message.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Owner locked out at deploy.** The backfill must make every current superuser an owner, and the API key must still work. Pinned in Task 1 (backfill test) and Task 10 (API key row).
2. **Vijay's 4-week test breaks.** The `tester` role must keep exactly his buy/close/read flow, and nothing more. Pinned in Task 4 (his real routes, plus a refusal on a house position).
3. **A legacy token (no `tv` claim) after a password change.** It must stop working once the version is bumped, and keep working before. Pinned in Task 5.
4. **Username enumeration via lockout.** A locked account, an unknown user and a wrong password must give the identical message and status. Pinned in Task 6.
5. **Old code on the new schema (rollback).** The previous commit must boot and log in against the upgraded DB. Pinned in Task 11 (rehearsal script and checklist).

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `backend/src/swing_trade_ml/db/models/session.py` | `User.role`, `token_version`, `failed_login_count`, `locked_until`, `ROLES`, role↔superuser sync | 1 |
| `backend/src/swing_trade_ml/db/models/audit.py` (new) | `AuditLog`, `LoginCode` tables | 1 |
| `backend/src/swing_trade_ml/db/models/__init__.py` | register new models | 1 |
| `backend/alembic/versions/20261016_1200_p0_security.py` (new) | schema + role backfill + downgrade | 1 |
| `backend/src/swing_trade_ml/services/audit.py` (new) | `record(...)` | 2 |
| `backend/src/swing_trade_ml/api/deps.py` | roles in `Principal`, fail-closed reads, tester write allowlist, token checks | 3, 4, 5 |
| `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py` | tester-book check on close | 4 |
| `backend/src/swing_trade_ml/api/v1/endpoints/auth.py` | `issue_token`, lockout, password change, sign out everywhere, Google code | 5, 6, 7 |
| `backend/src/swing_trade_ml/services/login_codes.py` (new) | issue/redeem one-time codes | 7 |
| `backend/src/swing_trade_ml/schemas/__init__.py` | `PasswordChangeRequest`, `LoginCodeExchange`, `role` on `CurrentUserOut` | 3, 5, 7 |
| `backend/src/swing_trade_ml/core/security.py` | `assert_secrets_safe` | 8 |
| `backend/src/swing_trade_ml/core/config.py`, `.env.example` | `ALLOW_SIGNUP` default false | 8 |
| `backend/src/swing_trade_ml/main.py` | call the guard at startup | 8 |
| `backend/src/swing_trade_ml/cli.py` | `audit-roles`, `set-role`, `disable-user`, `unlock-user`, `revoke-sessions`; `create-user --role` | 9 |
| `backend/src/swing_trade_ml/api/v1/endpoints/plans.py` | audit plan/switch changes | 9 |
| `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/App.tsx`, `frontend/src/components/AuthScreen.tsx`, `frontend/src/pages/Settings.tsx` | code exchange, password change, sign out everywhere | 5, 7 |
| `backend/tests/test_p0_*.py` (new), `test_permissions_review.py`, `test_plans.py`, `test_brain_owner_only_writes.py` | tests | all |
| `backend/scripts/rehearse_p0_migration.py` (new) | migration + rollback rehearsal | 11 |
| `docs/deploy/P0-security-runbook.md` (new), `docs/architecture/CODE-MAP.md` | deploy checks, rollback, map | 11 |

---

### Task 0: Branch and test-DB reset

**Files:** none changed.

- [ ] **Step 1: Create the branch**

```bash
cd "D:/machine learning/swing-trade-bot"
git switch develop && git switch -c feature/p0-security
```

- [ ] **Step 2: Confirm the single alembic head**

Run: `cd backend && .venv/Scripts/python.exe -m alembic heads`
Expected: exactly one head, `d8a1y2c3h4k5`. If another head is printed, use **that** id as `down_revision` in Task 1 and note it in the commit message.

- [ ] **Step 3: Confirm Docker Postgres is up (a liveness check, not a port check)**

Run: `docker exec stml-postgres pg_isready` (container name per `docker-compose.yml`; if different, `docker ps`)
Expected: `accepting connections`.

---

### Task 1: Schema: roles, token version, lockout columns, audit and login-code tables

**Files:**
- Modify: `backend/src/swing_trade_ml/db/models/session.py`
- Create: `backend/src/swing_trade_ml/db/models/audit.py`
- Modify: `backend/src/swing_trade_ml/db/models/__init__.py`
- Create: `backend/alembic/versions/20261016_1200_p0_security.py`
- Test: `backend/tests/test_p0_roles_model.py`

**Interfaces:**
- Produces: `User.role: str` (`"owner" | "tester" | "member"`), `User.token_version: int`, `User.failed_login_count: int`, `User.locked_until: datetime | None`; constant `ROLES = ("owner", "tester", "member")` in `db/models/session.py`; models `AuditLog`, `LoginCode` in `db/models/audit.py`.
- Invariant: after any flush, `user.is_superuser == (user.role == "owner")`. A role change bumps `token_version` by 1.

- [ ] **Step 1: Reset the test database schema** (create_all cannot add columns to an existing `users` table)

```bash
cd backend && .venv/Scripts/python.exe - <<'EOF'
from sqlalchemy import create_engine, text
url = "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_test"
assert url.endswith("_test")  # never the real database
with create_engine(url).begin() as c:
    c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
print("test schema reset")
EOF
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_p0_roles_model.py
"""Roles (P0): role and is_superuser always agree, so old code and the frontend stay right."""

from __future__ import annotations

import pytest

from swing_trade_ml.db.models.audit import AuditLog, LoginCode
from swing_trade_ml.db.models.session import ROLES, User


def _add(db, **kw) -> User:
    user = User(hashed_password="x", is_active=True, plan="free", **kw)
    db.add(user)
    db.flush()
    return user


def test_old_style_superuser_becomes_owner(db_session):
    assert _add(db_session, username="old-owner", is_superuser=True).role == "owner"


def test_old_style_plain_user_becomes_member(db_session):
    user = _add(db_session, username="old-user", is_superuser=False)
    assert user.role == "member" and user.is_superuser is False


def test_role_drives_is_superuser(db_session):
    tester = _add(db_session, username="t1", role="tester")
    assert tester.is_superuser is False
    owner = _add(db_session, username="o1", role="owner")
    assert owner.is_superuser is True


def test_changing_role_updates_superuser_and_revokes_sessions(db_session):
    user = _add(db_session, username="o2", role="owner")
    before = user.token_version
    user.role = "tester"
    db_session.flush()
    assert user.is_superuser is False
    assert user.token_version == before + 1


def test_setting_is_superuser_false_on_an_owner_makes_a_member(db_session):
    user = _add(db_session, username="o3", role="owner")
    user.is_superuser = False
    db_session.flush()
    assert user.role == "member"


def test_unknown_role_is_refused(db_session):
    with pytest.raises(ValueError):
        _add(db_session, username="bad", role="admin")


def test_new_columns_default_safely(db_session):
    user = _add(db_session, username="d1")
    assert (user.token_version, user.failed_login_count, user.locked_until) == (0, 0, None)
    assert ROLES == ("owner", "tester", "member")


def test_audit_and_login_code_tables_exist(db_session):
    db_session.add(AuditLog(actor_label="system", action="test.ping"))
    db_session.flush()
    assert db_session.query(AuditLog).count() >= 1
    assert LoginCode.__tablename__ == "login_codes"
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE .venv/Scripts/python.exe -m pytest tests/test_p0_roles_model.py -v`
Expected: FAIL: `ImportError: cannot import name 'AuditLog'`.

- [ ] **Step 4: Add the columns and sync to `User`** (`db/models/session.py`)

Change the imports at the top to:

```python
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, event, inspect
```

Add right after the imports:

```python
#: What a login may do (api/deps.py Principal). owner: everything, as
#: is_superuser meant before. tester: the manual paper-testing book only.
#: member: what their plan opens, never a write outside their own sign-in.
ROLES = ("owner", "tester", "member")
```

Inside `class User`, after `plan`:

```python
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
```

After the class:

```python
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
```

- [ ] **Step 5: Create `db/models/audit.py`**

```python
"""Append-only audit trail of sign-ins and administrative actions, and the
one-time codes that hand a Google sign-in to the app (spec §6, release A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow


class AuditLog(Base):
    """One thing someone did. Never updated or deleted by the app."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Who, as text: a username, "api-key", "system", "cli", or the name typed
    # on a failed sign-in (untrusted, truncated).
    actor_label: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(48), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    # Changed fields only; services/audit.py redacts anything secret.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # The proxy's address until uvicorn runs with --proxy-headers; kept for
    # reading the trail, never used to decide anything.
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))


class LoginCode(Base):
    """A 60-second, single-use code the Google callback puts in the URL instead
    of a session token; the app swaps it for a token with one POST."""

    __tablename__ = "login_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 6: Register the models** in `db/models/__init__.py`

Add next to the `session` import line:

```python
from swing_trade_ml.db.models.audit import AuditLog, LoginCode
```

and add `"AuditLog",` and `"LoginCode",` to `__all__` (keep its existing order style).

- [ ] **Step 7: Write the migration** `backend/alembic/versions/20261016_1200_p0_security.py`

```python
"""P0 security: roles, session versions, sign-in lockout, audit log, login codes

The backfill reproduces today's powers exactly: every superuser becomes an
owner, everyone else a member. Changing anyone's role is a separate,
audited, owner-run step (swingtrade set-role) — never part of a migration.

Revision ID: e1p0s2e3c4u5
Revises: d8a1y2c3h4k5
Create Date: 2026-10-16 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1p0s2e3c4u5"
down_revision: str | None = "d8a1y2c3h4k5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(12), nullable=False, server_default="member"))
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "users", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET role = 'owner' WHERE is_superuser")

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_label", sa.String(128), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
    )
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    op.create_table(
        "login_codes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_login_codes_user_id", "login_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_login_codes_user_id", table_name="login_codes")
    op.drop_table("login_codes")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_ts", table_name="audit_log")
    op.drop_table("audit_log")
    # is_superuser was kept equal to role == 'owner', so dropping role loses nothing old code reads.
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "token_version")
    op.drop_column("users", "role")
```

If Task 0 Step 2 printed a different head, use it for `down_revision` and in the docstring.

- [ ] **Step 8: Run the tests**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE .venv/Scripts/python.exe -m pytest tests/test_p0_roles_model.py -v`
Expected: 8 passed.

- [ ] **Step 9: Run the existing auth/permission suites (they create users with `is_superuser=` only)**

Run: `… -m pytest tests/test_permissions_review.py tests/test_plans.py tests/test_brain_owner_only_writes.py tests/test_real_account_private.py tests/test_auth_options.py -q`
Expected: all pass (no behaviour change yet).

- [ ] **Step 10: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/db/models/session.py src/swing_trade_ml/db/models/audit.py src/swing_trade_ml/db/models/__init__.py alembic/versions/20261016_1200_p0_security.py tests/test_p0_roles_model.py
cd .. && git add backend/src/swing_trade_ml/db/models/session.py backend/src/swing_trade_ml/db/models/audit.py backend/src/swing_trade_ml/db/models/__init__.py backend/alembic/versions/20261016_1200_p0_security.py backend/tests/test_p0_roles_model.py
git commit -m "P0: user roles kept in step with is_superuser, session versions, lockout columns, audit log and login-code tables

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Audit service

**Files:**
- Create: `backend/src/swing_trade_ml/services/audit.py`
- Test: `backend/tests/test_p0_audit.py`

**Interfaces:**
- Consumes: `AuditLog` (Task 1).
- Produces: `record(db: Session, action: str, *, actor: User | None = None, actor_label: str | None = None, target_type: str | None = None, target_id: object | None = None, before: dict | None = None, after: dict | None = None, request: Request | None = None) -> AuditLog`. It adds and flushes the row. **It never commits** (the caller commits).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_audit.py
from __future__ import annotations

from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import audit


def test_record_names_the_actor_and_target(db_session):
    user = User(username="aud1", hashed_password="x", role="owner")
    db_session.add(user)
    db_session.flush()
    row = audit.record(db_session, "user.role_change", actor=user, target_type="user", target_id=7,
                       before={"role": "owner"}, after={"role": "tester"})
    assert (row.actor_user_id, row.actor_label, row.target_id) == (user.id, "aud1", "7")
    assert row.after == {"role": "tester"}


def test_record_redacts_secrets(db_session):
    row = audit.record(db_session, "auth.password_change", actor_label="cli",
                       after={"password": "hunter22", "hashed_password": "$2b$..", "token": "eyJ", "ok": True})
    assert row.after == {"password": "[redacted]", "hashed_password": "[redacted]", "token": "[redacted]", "ok": True}


def test_record_without_actor_is_system_and_truncates_labels(db_session):
    row = audit.record(db_session, "auth.login_failed", actor_label="x" * 500)
    assert len(row.actor_label) == 128
    assert audit.record(db_session, "job.ping").actor_label == "system"


def test_record_does_not_commit(db_session):
    audit.record(db_session, "test.nocommit")
    db_session.rollback()
    assert db_session.query(AuditLog).filter_by(action="test.nocommit").count() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `… -m pytest tests/test_p0_audit.py -v`
Expected: FAIL: `ImportError: cannot import name 'audit'`.

- [ ] **Step 3: Implement**

```python
# backend/src/swing_trade_ml/services/audit.py
"""Write one audit_log row. The caller commits: an action and its audit row
succeed or fail together."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

_SECRET_KEYS = frozenset(
    {"password", "new_password", "current_password", "hashed_password", "token", "access_token", "code", "secret"}
)


def _clean(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {k: ("[redacted]" if k in _SECRET_KEYS else v) for k, v in values.items()}


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_label: str | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    label = actor_label or (actor.username if actor is not None else "system")
    row = AuditLog(
        actor_user_id=actor.id if actor is not None else None,
        actor_label=label[:128],
        action=action[:48],
        target_type=target_type,
        target_id=None if target_id is None else str(target_id)[:64],
        before=_clean(before),
        after=_clean(after),
        ip=(request.client.host if request is not None and request.client else None),
        user_agent=((request.headers.get("user-agent") or "")[:256] if request is not None else None),
    )
    db.add(row)
    db.flush()
    return row
```

- [ ] **Step 4: Run the tests**

Run: `… -m pytest tests/test_p0_audit.py -v`
Expected: 4 passed.

- [ ] **Step 5: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/services/audit.py tests/test_p0_audit.py
cd .. && git add backend/src/swing_trade_ml/services/audit.py backend/tests/test_p0_audit.py
git commit -m "P0: audit service (redacts secrets, never commits on its own)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Roles in the permission check; member reads fail closed

**Files:**
- Modify: `backend/src/swing_trade_ml/api/deps.py` (`Principal`, `plan_access_for`)
- Modify: `backend/src/swing_trade_ml/schemas/__init__.py` (`CurrentUserOut.role`)
- Modify: `frontend/src/api/types.ts` (`role` on the current-user type, next to `is_superuser`)
- Modify (deliberate behaviour change, S1): `backend/tests/test_plans.py`, `backend/tests/test_brain_owner_only_writes.py`
- Test: `backend/tests/test_p0_member_reads.py`

**Interfaces:**
- Consumes: `User.role` (Task 1).
- Produces: `Principal.role -> str`, `Principal.is_owner` (API key or `role == "owner"`), `Principal.is_tester`. `plan_access_for` returns unrestricted for: owner, and tester **while plans are off**. Members always get their plan's rules.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_member_reads.py
"""S1: a signed-in non-owner no longer sees the house book just because plans are off."""

from __future__ import annotations

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User

API_KEY = {"X-API-Key": "test-api-key"}


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_member_is_refused_owner_screens_while_plans_are_off(client, db_session):
    member = _as(db_session, "m-read", "member")
    for path in ("/api/v1/strategies", "/api/v1/status", "/api/v1/risk/limits", "/api/v1/portfolio/summary"):
        assert client.get(path, headers=member).status_code == 403, path


def test_member_me_plan_is_restricted(client, db_session):
    me = client.get("/api/v1/me/plan", headers=_as(db_session, "m-me", "member")).json()
    assert me["unrestricted"] is False and me["can_manage_plans"] is False


def test_tester_still_reads_like_today_while_plans_are_off(client, db_session):
    tester = _as(db_session, "t-read", "tester")
    assert client.get("/api/v1/strategies", headers=tester).status_code == 200
    assert client.get("/api/v1/portfolio/summary?book=tester", headers=tester).status_code == 200


def test_tester_is_not_owner_and_cannot_see_real_account(client, db_session):
    tester = _as(db_session, "t-real", "tester")
    me = client.get("/api/v1/me/plan", headers=tester).json()
    assert me["can_manage_plans"] is False and me["can_see_real_account"] is False
    assert client.get("/api/v1/portfolio/summary?book=real", headers=tester).status_code == 403


def test_owner_and_api_key_unchanged(client, db_session):
    owner = _as(db_session, "o-read", "owner")
    for headers in (owner, API_KEY):
        assert client.get("/api/v1/strategies", headers=headers).status_code == 200


def test_me_reports_role(client, db_session):
    assert client.get("/api/v1/auth/me", headers=_as(db_session, "t-me", "tester")).json()["role"] == "tester"
```

- [ ] **Step 2: Run to verify it fails**

Run: `… -m pytest tests/test_p0_member_reads.py -v`
Expected: FAIL: the member gets 200 on `/strategies`, and `role` is missing from `/auth/me`.

- [ ] **Step 3: Implement in `api/deps.py`**

Replace the `Principal` property bodies:

```python
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
```

In `plan_access_for`, replace the `elif` branch:

```python
    if principal.is_owner and preview in PLAN_KEYS:
        key, previewing = preview, True
    elif principal.is_owner or (principal.is_tester and not plans_enabled(db)):
        # Owners see everything. A tester keeps today's view (the whole app
        # while plans are off) until their own member account exists (release C).
        # A member never: "plans off" no longer means "everyone sees the house book" (S1).
        return PlanAccess(unrestricted=True, plan=None)
    else:
```

Update the `PlanAccess` docstring's first sentence to: "`unrestricted` callers see everything: the owner always, and a tester while plans are switched off. Members always get their plan's rules."

- [ ] **Step 4: Add `role` to the schema and frontend type**

In `schemas/__init__.py` `CurrentUserOut`, after `is_superuser: bool`:

```python
    role: str
```

In `frontend/src/api/types.ts`, after `is_superuser: boolean` (line 13):

```ts
  role: 'owner' | 'tester' | 'member'
```

- [ ] **Step 5: Update the two tests that pinned the old behaviour (approved change S1)**

In `backend/tests/test_brain_owner_only_writes.py`, give `_login` a role and rename the read test:

```python
def _login(db_session, username: str, *, owner: bool = False, role: str | None = None) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, is_superuser=owner, plan="free", role=role)
    db_session.add(user)
    db_session.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_a_tester_can_still_read_while_plans_are_off(client, db_session):
    tester = _login(db_session, "guest4", role="tester")
    assert client.get("/api/v1/brain/stage", headers=tester).status_code == 200
    assert client.get("/api/v1/strategies", headers=tester).status_code == 200


def test_a_member_cannot_read_owner_screens_while_plans_are_off(client, db_session):
    member = _login(db_session, "guest5")
    assert client.get("/api/v1/strategies", headers=member).status_code == 403
```

(`role=None` keeps the old `is_superuser`-derived behaviour via the Task 1 listener.)

In `backend/tests/test_plans.py`, give `_user` a `role` keyword (`role: str | None = None`, passed to `User(...)`), then replace the two switch tests:

```python
def test_plans_off_by_default_testers_see_everything_members_do_not(client, db_session, book):
    tester = _user(db_session, "v1tester", role="tester")
    assert client.get("/api/v1/strategies", headers=tester).status_code == 200
    assert client.get("/api/v1/status", headers=tester).status_code == 200
    assert len(client.get("/api/v1/signals/picks", headers=tester).json()) == 10
    me = client.get("/api/v1/me/plan", headers=tester).json()
    assert me["unrestricted"] is True and me["plans_enabled"] is False
    assert me["can_manage_plans"] is False

    member = _user(db_session, "v1member")
    assert client.get("/api/v1/strategies", headers=member).status_code == 403
    assert client.get("/api/v1/me/plan", headers=member).json()["unrestricted"] is False


def test_owner_flips_the_switch(client, db_session, book):
    tester = _user(db_session, "switchee", role="tester")
    assert client.get("/api/v1/admin/switch", headers=API_KEY).json() == {"enabled": False}
    resp = client.put("/api/v1/admin/switch", json={"enabled": True}, headers=API_KEY)
    assert resp.json() == {"enabled": True}
    assert client.get("/api/v1/strategies", headers=tester).status_code == 403
    client.put("/api/v1/admin/switch", json={"enabled": False}, headers=API_KEY)
    assert client.get("/api/v1/strategies", headers=tester).status_code == 200
```

Also update the module docstring line "With plans switched off (the default), everyone sees everything" to "With plans switched off (the default), owners and testers see everything; members get their plan's rules regardless."

- [ ] **Step 6: Run the tests**

Run: `… -m pytest tests/test_p0_member_reads.py tests/test_plans.py tests/test_brain_owner_only_writes.py tests/test_real_account_private.py tests/test_permissions_review.py tests/test_brain_observatory_api.py -q`
Expected: all pass. If any other test fails because a plain non-owner user can no longer read, check whether it meant "tester". Give that test `role="tester"` only if so, and list each changed test in the commit message.

- [ ] **Step 7: Typecheck the frontend**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no errors.

- [ ] **Step 8: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/api/deps.py tests/test_p0_member_reads.py tests/test_plans.py tests/test_brain_owner_only_writes.py
cd .. && git add backend/src/swing_trade_ml/api/deps.py backend/src/swing_trade_ml/schemas/__init__.py frontend/src/api/types.ts backend/tests/test_p0_member_reads.py backend/tests/test_plans.py backend/tests/test_brain_owner_only_writes.py
git commit -m "P0 (S1/S2): permissions read the role; members no longer see the house book while plans are off

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Tester writes limited to the tester book

**Files:**
- Modify: `backend/src/swing_trade_ml/api/deps.py` (`require_auth`)
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py` (`close`, line ~874)
- Test: `backend/tests/test_p0_tester_writes.py`

**Interfaces:**
- Consumes: `Principal.is_tester` (Task 3); `tester_paper.get_or_create_strategy`, `only_tester` (existing).
- Produces: `TESTER_WRITES: frozenset[tuple[str, str]]` in `deps.py` = `{("POST", "/portfolio/tester/buy"), ("POST", "/portfolio/positions/{position_id}/close")}`. The handler-level check `_refuse_tester_outside_tester_book(principal, position, db)` in `portfolio.py`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_tester_writes.py
"""A tester (Vijay) keeps his manual paper-testing flow and nothing else."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import tester_paper


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def _open(db, strategy: Strategy, symbol: str) -> Position:
    inst = Instrument(instrument_token=abs(hash(symbol)) % 10_000_000, tradingsymbol=symbol, exchange="NSE")
    db.add(inst)
    db.flush()
    pos = Position(strategy_id=strategy.id, instrument_id=inst.id, mode="paper", status="OPEN",
                   quantity=1, initial_quantity=1, entry_price=100.0, entry_at=datetime.now(UTC))
    db.add(pos)
    db.flush()
    return pos


def test_tester_cannot_close_a_house_position(client, db_session):
    house = Strategy(name="ml_swing_house_t", strategy_type="ml_swing", mode="paper", is_active=True)
    db_session.add(house)
    db_session.flush()
    pos = _open(db_session, house, "HOUSEPOS")
    r = client.post(f"/api/v1/portfolio/positions/{pos.id}/close", json={"reason": "MANUAL"},
                    headers=_as(db_session, "t-close-house", "tester"))
    assert r.status_code == 403


def test_tester_close_on_a_tester_position_passes_the_guard(client, db_session):
    pos = _open(db_session, tester_paper.get_or_create_strategy(db_session), "TESTPOS")
    r = client.post(f"/api/v1/portfolio/positions/{pos.id}/close", json={"reason": "MANUAL"},
                    headers=_as(db_session, "t-close-own", "tester"))
    assert r.status_code not in (401, 403), r.text  # got past the guards; the close itself may need a price


def test_tester_buy_route_passes_the_guard(client, db_session):
    r = client.post("/api/v1/portfolio/tester/buy", json={"symbol": "NOPE", "quantity": 1, "cap_tier": "large"},
                    headers=_as(db_session, "t-buy", "tester"))
    assert r.status_code not in (401, 403), r.text  # 404 unknown symbol / disabled is fine


def test_tester_is_refused_every_other_write(client, db_session):
    tester = _as(db_session, "t-other", "tester")
    assert client.post("/api/v1/safety/halt", json={"reason": "x"}, headers=tester).status_code == 403
    assert client.put("/api/v1/brain/stage", json={"stage": "shadow", "reason": "x"}, headers=tester).status_code == 403
    assert client.post("/api/v1/portfolio/positions/manual", json={}, headers=tester).status_code == 403


def test_member_cannot_use_tester_routes(client, db_session):
    member = _as(db_session, "m-tester", "member")
    r = client.post("/api/v1/portfolio/tester/buy", json={"symbol": "X", "quantity": 1, "cap_tier": "large"},
                    headers=member)
    assert r.status_code == 403
```

- [ ] **Step 2: Run to verify it fails**

Run: `… -m pytest tests/test_p0_tester_writes.py -v`
Expected: FAIL: the tester's buy/close are refused 403 (every non-owner write is refused today).

- [ ] **Step 3: Allow exactly the tester routes in `require_auth`** (`api/deps.py`)

Add above `require_auth`:

```python
#: The only writes a tester may make: the manual paper-testing book. The close
#: handler also checks the position really is in that book.
TESTER_WRITES: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/portfolio/tester/buy"), ("POST", "/portfolio/positions/{position_id}/close")}
)
```

Replace the first `if` in `require_auth` with:

```python
    if request.method not in READ_METHODS and not principal.is_owner:
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        if route_path.startswith(settings.API_V1_PREFIX):
            route_path = route_path[len(settings.API_V1_PREFIX):]
        if not (principal.is_tester and (request.method, route_path) in TESTER_WRITES):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change this.")
```

- [ ] **Step 4: Check the book in the close handler** (`endpoints/portfolio.py`)

Add below `_refuse_other_peoples_real_position` (find it with `grep -n "_refuse_other_peoples_real_position" portfolio.py`):

```python
def _refuse_tester_outside_tester_book(principal: Principal, position: Position, db: Session) -> None:
    """A tester may only close positions in the manual paper-testing book."""
    if principal.is_owner or not principal.is_tester:
        return
    from swing_trade_ml.services.tester_paper import get_or_create_strategy

    if position.strategy_id != get_or_create_strategy(db).id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only close positions in your testing book.")
```

In `close(...)`, directly after `_refuse_other_peoples_real_position(principal, position)`:

```python
    _refuse_tester_outside_tester_book(principal, position, db)
```

Make sure `Principal` and `Session` are imported in `portfolio.py` (`from swing_trade_ml.api.deps import Principal` and `from sqlalchemy.orm import Session`; add only what is missing).

- [ ] **Step 5: Run the tests**

Run: `… -m pytest tests/test_p0_tester_writes.py tests/test_permissions_review.py tests/test_real_account_private.py -q`
Expected: `test_p0_tester_writes.py` passes. `test_permissions_review.py` still passes (its guest is a member).

- [ ] **Step 6: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/api/deps.py src/swing_trade_ml/api/v1/endpoints/portfolio.py tests/test_p0_tester_writes.py
cd .. && git add backend/src/swing_trade_ml/api/deps.py backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py backend/tests/test_p0_tester_writes.py
git commit -m "P0: tester role may buy and close in the testing book only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Revocable sessions, password change, sign out everywhere

**Files:**
- Modify: `backend/src/swing_trade_ml/api/deps.py` (`_user_from_bearer`)
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/auth.py` (`issue_token`, new routes)
- Modify: `backend/src/swing_trade_ml/schemas/__init__.py` (`PasswordChangeRequest`)
- Modify: `frontend/src/api/client.ts`, `frontend/src/pages/Settings.tsx`
- Modify: `backend/tests/test_permissions_review.py` (`OPEN_WRITES`)
- Test: `backend/tests/test_p0_sessions.py`

**Interfaces:**
- Consumes: `User.token_version` (Task 1), `audit.record` (Task 2).
- Produces: `issue_token(user: User) -> TokenResponse` in `endpoints/auth.py`; the JWT claims `sub` (username), `uid` (int), `tv` (int). Routes `POST /auth/password` (body `{current_password, new_password}`) → `TokenResponse`, and `POST /auth/logout-all` → `MessageResponse`.
- Rule: a token without `tv` counts as `tv=0`. Valid only while `user.token_version == 0`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_sessions.py
from __future__ import annotations

from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User


def _user(db, name="s1", password="correct-horse-1", role="member") -> User:
    user = User(username=name, hashed_password=hash_password(password), is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_token_carries_uid_and_version(client, db_session):
    user = _user(db_session, "s-claims")
    tok = client.post("/api/v1/auth/login", json={"username": "s-claims", "password": "correct-horse-1"}).json()["access_token"]
    from swing_trade_ml.core.security import decode_access_token
    claims = decode_access_token(tok)
    assert (claims["sub"], claims["uid"], claims["tv"]) == ("s-claims", user.id, 0)


def test_legacy_token_works_until_version_bumped(client, db_session):
    user = _user(db_session, "s-legacy")
    legacy = _bearer(create_access_token(user.username, {"uid": user.id}))
    assert client.get("/api/v1/auth/me", headers=legacy).status_code == 200
    user.token_version += 1
    db_session.flush()
    assert client.get("/api/v1/auth/me", headers=legacy).status_code == 401


def test_password_change_ends_old_sessions_and_returns_a_new_one(client, db_session):
    user = _user(db_session, "s-pw")
    old = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    r = client.post("/api/v1/auth/password", headers=old,
                    json={"current_password": "correct-horse-1", "new_password": "battery-staple-2"})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_bearer(r.json()["access_token"])).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": "s-pw", "password": "battery-staple-2"}).status_code == 200
    assert db_session.query(AuditLog).filter_by(action="auth.password_change", actor_user_id=user.id).count() == 1


def test_password_change_needs_the_current_password(client, db_session):
    user = _user(db_session, "s-pw2")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    r = client.post("/api/v1/auth/password", headers=tok,
                    json={"current_password": "wrong", "new_password": "battery-staple-2"})
    assert r.status_code == 400


def test_new_password_must_be_8_or_more(client, db_session):
    user = _user(db_session, "s-pw3")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    r = client.post("/api/v1/auth/password", headers=tok, json={"current_password": "correct-horse-1", "new_password": "short"})
    assert r.status_code == 422


def test_logout_all_ends_every_session(client, db_session):
    user = _user(db_session, "s-out")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    assert client.post("/api/v1/auth/logout-all", headers=tok).status_code == 200
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 401


def test_uid_and_username_must_agree(client, db_session):
    a, b = _user(db_session, "s-a"), _user(db_session, "s-b")
    forged = _bearer(create_access_token(a.username, {"uid": b.id, "tv": 0}))
    assert client.get("/api/v1/auth/me", headers=forged).status_code == 401


def test_disabled_user_is_rejected(client, db_session):
    user = _user(db_session, "s-off")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    user.is_active = False
    db_session.flush()
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `… -m pytest tests/test_p0_sessions.py -v`
Expected: FAIL: `KeyError: 'tv'`, and 404 on `/auth/password`.

- [ ] **Step 3: Check uid and version in `_user_from_bearer`** (`api/deps.py`)

```python
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
```

- [ ] **Step 4: Schema** (`schemas/__init__.py`, after `SignupRequest`)

```python
class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
```

- [ ] **Step 5: `issue_token` and the two routes** (`endpoints/auth.py`)

Add `PasswordChangeRequest` and `MessageResponse` to the schemas import, `from fastapi import Request`, and `from swing_trade_ml.services import audit`. Add below the router definition:

```python
def issue_token(user: User) -> TokenResponse:
    """A session token naming the account by id and by its current session version."""
    return TokenResponse(
        access_token=create_access_token(user.username, {"uid": user.id, "tv": user.token_version or 0}),
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
    )
```

Replace both `return TokenResponse(...)` blocks in `login` and `signup` with `return issue_token(user)`. Add:

```python
@router.post("/password", response_model=TokenResponse)
def change_password(payload: PasswordChangeRequest, user: CurrentUser, db: DbSession, request: Request) -> TokenResponse:
    """Change your own password. Every other session of this account ends; this one gets a fresh token."""
    if not user.hashed_password or not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password is not right.")
    user.hashed_password = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    audit.record(db, "auth.password_change", actor=user, target_type="user", target_id=user.id, request=request)
    db.commit()
    return issue_token(user)


@router.post("/logout-all", response_model=MessageResponse)
def logout_everywhere(user: CurrentUser, db: DbSession, request: Request) -> MessageResponse:
    """End every session of this account, on every device."""
    user.token_version = (user.token_version or 0) + 1
    audit.record(db, "auth.logout_all", actor=user, target_type="user", target_id=user.id, request=request)
    db.commit()
    return MessageResponse(message="Signed out on every device.")
```

Check `MessageResponse`'s field name with `grep -n "class MessageResponse" -A3 backend/src/swing_trade_ml/schemas/__init__.py` and use it.

- [ ] **Step 6: Tell the permission walk these two writes are self-service** (`tests/test_permissions_review.py`, `OPEN_WRITES`)

```python
    ("POST", "/auth/password"): "a signed-in person changes their own password, nobody else's",
    ("POST", "/auth/logout-all"): "a signed-in person ends their own sessions, nobody else's",
```

- [ ] **Step 7: Frontend client + Settings**

In `frontend/src/api/client.ts`, next to `login`:

```ts
  changePassword: (current_password: string, new_password: string) =>
    post<{ access_token: string }>('/auth/password', { current_password, new_password }),
  logoutEverywhere: () => post<{ message: string }>('/auth/logout-all'),
```

In `frontend/src/pages/Settings.tsx`, add a card visible to every signed-in user. Read the file first and match its card/button markup and the `useMutation` import it already uses:

```tsx
function SignInCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: (r) => { setToken(r.access_token); setCurrent(''); setNext(''); setNote('Password changed. Other devices are signed out.') },
    onError: (e) => setNote(e instanceof ApiError ? e.message : 'Could not change the password.'),
  })
  const out = useMutation({
    mutationFn: api.logoutEverywhere,
    onSuccess: () => { clearToken(); window.location.reload() },
  })
  return (
    <div className="card">
      <h2>Sign-in</h2>
      {note && <p className="muted">{note}</p>}
      <label><div className="stat-label">Current password</div>
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
      <label><div className="stat-label">New password (8 or more characters)</div>
        <input type="password" value={next} minLength={8} onChange={(e) => setNext(e.target.value)} /></label>
      <button className="primary" disabled={change.isPending || next.length < 8} onClick={() => change.mutate()}>Change password</button>
      <button disabled={out.isPending} onClick={() => out.mutate()}>Sign out on every device</button>
    </div>
  )
}
```

Render `<SignInCard />` near the top of the Settings page for all users, and import `setToken`, `clearToken`, `ApiError` from `../api/client` if they are not already imported.

- [ ] **Step 8: Run tests and typecheck**

Run: `… -m pytest tests/test_p0_sessions.py tests/test_permissions_review.py tests/test_auth_options.py -q` then `cd frontend && npx tsc --noEmit -p .`
Expected: all pass, no type errors.

- [ ] **Step 9: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/api/deps.py src/swing_trade_ml/api/v1/endpoints/auth.py tests/test_p0_sessions.py tests/test_permissions_review.py
cd .. && git add backend/src/swing_trade_ml/api/deps.py backend/src/swing_trade_ml/api/v1/endpoints/auth.py backend/src/swing_trade_ml/schemas/__init__.py backend/tests/test_p0_sessions.py backend/tests/test_permissions_review.py frontend/src/api/client.ts frontend/src/pages/Settings.tsx
git commit -m "P0 (S4): sessions can be ended — token version, password change, sign out everywhere

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Sign-in lockout

**Files:**
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/auth.py` (`login`)
- Test: `backend/tests/test_p0_lockout.py`

**Interfaces:**
- Consumes: `User.failed_login_count`, `User.locked_until` (Task 1), `audit.record` (Task 2), `issue_token` (Task 5).
- Produces: constants `LOCKOUT_THRESHOLD = 5`, `LOCKOUT_MINUTES = 15`, `LOGIN_FAILED` (the exact message from Global Constraints) in `endpoints/auth.py`. Audit actions: `auth.login`, `auth.login_failed`, `auth.locked`, `auth.login_while_locked`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_lockout.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.api.v1.endpoints.auth import LOGIN_FAILED
from swing_trade_ml.core.security import hash_password
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

PW = "correct-horse-1"


def _user(db, name) -> User:
    user = User(username=name, hashed_password=hash_password(PW), is_active=True, role="member", plan="free")
    db.add(user)
    db.flush()
    return user


def _login(client, name, pw):
    return client.post("/api/v1/auth/login", json={"username": name, "password": pw})


def test_five_wrong_passwords_lock_the_account(client, db_session):
    user = _user(db_session, "lk1")
    for _ in range(5):
        assert _login(client, "lk1", "nope").status_code == 401
    db_session.refresh(user)
    assert user.locked_until is not None and user.locked_until > datetime.now(UTC)
    assert _login(client, "lk1", PW).status_code == 401  # right password refused while locked


def test_lock_lifts_after_15_minutes(client, db_session):
    user = _user(db_session, "lk2")
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert _login(client, "lk2", PW).status_code == 200
    db_session.refresh(user)
    assert user.failed_login_count == 0 and user.locked_until is None


def test_success_resets_the_count(client, db_session):
    user = _user(db_session, "lk3")
    for _ in range(4):
        _login(client, "lk3", "nope")
    assert _login(client, "lk3", PW).status_code == 200
    db_session.refresh(user)
    assert user.failed_login_count == 0


def test_unknown_locked_and_wrong_look_identical(client, db_session):
    _user(db_session, "lk4")
    locked = _user(db_session, "lk5")
    locked.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    db_session.flush()
    answers = [_login(client, "nobody-here", "x"), _login(client, "lk4", "nope"), _login(client, "lk5", PW)]
    assert {(r.status_code, r.json()["detail"]) for r in answers} == {(401, LOGIN_FAILED)}


def test_every_attempt_is_audited(client, db_session):
    _user(db_session, "lk6")
    _login(client, "lk6", "nope")
    _login(client, "lk6", PW)
    actions = [a.action for a in db_session.query(AuditLog).filter(AuditLog.actor_label == "lk6").order_by(AuditLog.id)]
    assert actions[-2:] == ["auth.login_failed", "auth.login"]


def test_google_only_account_cannot_password_login(client, db_session):
    db_session.add(User(username="g-only", hashed_password=None, auth_provider="google", is_active=True, plan="free"))
    db_session.flush()
    r = _login(client, "g-only", "anything")
    assert (r.status_code, r.json()["detail"]) == (401, LOGIN_FAILED)
```

- [ ] **Step 2: Run to verify it fails**

Run: `… -m pytest tests/test_p0_lockout.py -v`
Expected: FAIL: `ImportError: cannot import name 'LOGIN_FAILED'`.

- [ ] **Step 3: Implement** (`endpoints/auth.py`). Add `from datetime import timedelta` to the datetime import, then:

```python
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15
LOGIN_FAILED = "Incorrect username or password. After several wrong tries, sign-in pauses for 15 minutes."
# Compared against when there is no real hash, so an unknown username takes as
# long to refuse as a wrong password (no timing hint that the account exists).
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession, request: Request) -> TokenResponse:
    """One message for every failure (unknown user, wrong password, locked,
    Google-only account) so the answer never tells whether an account exists."""
    user = db.execute(
        select(User).where(User.username == payload.username).with_for_update()
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    who = payload.username[:128]

    def refuse(action: str, **after: object) -> HTTPException:
        audit.record(db, action, actor=user, actor_label=who, target_type="user", target_id=who,
                     after=after or None, request=request)
        db.commit()
        return HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)

    if user is None or not user.hashed_password:
        verify_password(payload.password, _DUMMY_HASH)
        raise refuse("auth.login_failed", why="unknown_or_no_password")
    if user.locked_until is not None and user.locked_until > now:
        verify_password(payload.password, _DUMMY_HASH)
        raise refuse("auth.login_while_locked")
    if not verify_password(payload.password, user.hashed_password):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= LOCKOUT_THRESHOLD:
            user.failed_login_count = 0
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            raise refuse("auth.locked", minutes=LOCKOUT_MINUTES)
        raise refuse("auth.login_failed", failed_count=user.failed_login_count)
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    audit.record(db, "auth.login", actor=user, actor_label=who, target_type="user", target_id=user.id, request=request)
    db.commit()
    return issue_token(user)
```

(In the `refuse` audit rows, `actor_label=who` makes failed tries for a real user searchable by the name typed. `actor=user` links them when the account exists.)

- [ ] **Step 4: Run the tests**

Run: `… -m pytest tests/test_p0_lockout.py tests/test_p0_sessions.py -q`
Expected: all pass.

- [ ] **Step 5: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/api/v1/endpoints/auth.py tests/test_p0_lockout.py
cd .. && git add backend/src/swing_trade_ml/api/v1/endpoints/auth.py backend/tests/test_p0_lockout.py
git commit -m "P0 (S3): sign-in pauses for 15 minutes after 5 wrong passwords; every attempt audited

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Google sign-in via a one-time code

**Files:**
- Create: `backend/src/swing_trade_ml/services/login_codes.py`
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/auth.py` (`google_callback` end; new `POST /auth/google/exchange`)
- Modify: `backend/src/swing_trade_ml/schemas/__init__.py` (`LoginCodeExchange`)
- Modify: `backend/tests/test_permissions_review.py` (`PUBLIC`, `OPEN_WRITES`)
- Modify: `frontend/src/api/client.ts`, `frontend/src/App.tsx`, `frontend/src/components/AuthScreen.tsx`
- Test: `backend/tests/test_p0_google_code.py`

**Interfaces:**
- Consumes: `LoginCode` (Task 1), `issue_token` (Task 5), `audit.record` (Task 2).
- Produces: `login_codes.issue(db, user) -> str` (raw code; only its SHA-256 is stored) and `login_codes.redeem(db, code) -> User | None` (single use, 60 s, active users only). The route `POST /auth/google/exchange` with body `{code}` returns `TokenResponse`, or 401 with `"This sign-in link has expired. Please sign in again."`. The callback redirects to `{post_login_url}/?login_code=<code>`. Frontend: `takeLoginCodeFromRedirect(): string | null` and `api.exchangeLoginCode(code)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_google_code.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.audit import LoginCode
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import login_codes


def _user(db, name="g1", active=True) -> User:
    user = User(username=name, hashed_password=None, auth_provider="google", is_active=active, plan="free")
    db.add(user)
    db.flush()
    return user


def test_code_is_stored_hashed_and_redeems_once(db_session):
    user = _user(db_session)
    code = login_codes.issue(db_session, user)
    assert db_session.query(LoginCode).filter_by(code_hash=code).count() == 0  # raw code never stored
    assert login_codes.redeem(db_session, code).id == user.id
    assert login_codes.redeem(db_session, code) is None


def test_expired_code_is_refused(db_session):
    user = _user(db_session, "g2")
    code = login_codes.issue(db_session, user)
    row = db_session.query(LoginCode).filter_by(user_id=user.id).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert login_codes.redeem(db_session, code) is None


def test_disabled_user_code_is_refused(db_session):
    user = _user(db_session, "g3")
    code = login_codes.issue(db_session, user)
    user.is_active = False
    db_session.flush()
    assert login_codes.redeem(db_session, code) is None


def test_exchange_route(client, db_session):
    user = _user(db_session, "g4")
    code = login_codes.issue(db_session, user)
    r = client.post("/api/v1/auth/google/exchange", json={"code": code})
    assert r.status_code == 200 and r.json()["access_token"]
    again = client.post("/api/v1/auth/google/exchange", json={"code": code})
    assert again.status_code == 401


def test_callback_puts_a_code_not_a_token_in_the_url(client, db_session, monkeypatch):
    from swing_trade_ml.api.v1.endpoints import auth as auth_ep

    monkeypatch.setattr(settings, "GOOGLE_ALLOWED_EMAILS", "g5@example.com")
    state = auth_ep._issue_state()

    class _Resp:
        def __init__(self, data): self._d = data
        def raise_for_status(self): pass
        def json(self): return self._d

    monkeypatch.setattr(auth_ep.httpx, "post", lambda *a, **k: _Resp({"access_token": "google-at"}))
    monkeypatch.setattr(auth_ep.httpx, "get", lambda *a, **k: _Resp(
        {"sub": "google-sub-g5", "email": "g5@example.com", "email_verified": True}))
    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert "login_code=" in location and "token=" not in location.replace("login_code=", "")
```

- [ ] **Step 2: Run to verify it fails**

Run: `… -m pytest tests/test_p0_google_code.py -v`
Expected: FAIL: `ImportError: cannot import name 'login_codes'`.

- [ ] **Step 3: Implement `services/login_codes.py`**

```python
"""One-time codes that hand a finished Google sign-in to the app. The code,
not a session token, is what travels in the browser's address bar."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.audit import LoginCode
from swing_trade_ml.db.models.session import User

CODE_TTL_SECONDS = 60


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def issue(db: Session, user: User) -> str:
    code = secrets.token_urlsafe(32)
    db.add(
        LoginCode(
            code_hash=_hash(code),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(seconds=CODE_TTL_SECONDS),
        )
    )
    db.flush()
    return code


def redeem(db: Session, code: str) -> User | None:
    """The account the code was issued for, once; None if unknown, used, expired or disabled."""
    row = db.execute(
        select(LoginCode).where(LoginCode.code_hash == _hash(code)).with_for_update()
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    row.used_at = now
    db.flush()
    user = db.get(User, row.user_id)
    return user if user is not None and user.is_active else None
```

- [ ] **Step 4: Schema** (`schemas/__init__.py`)

```python
class LoginCodeExchange(BaseModel):
    code: str = Field(..., min_length=10, max_length=128)
```

- [ ] **Step 5: Callback and exchange route** (`endpoints/auth.py`; import `LoginCodeExchange` and `from swing_trade_ml.services import login_codes`)

Replace the last two lines of `google_callback`:

```python
    code = login_codes.issue(db, user)
    db.commit()
    # A one-time code, not the session token: the address bar ends up in
    # browser history, server logs and Referer headers (spec finding S5).
    return RedirectResponse(f"{settings.post_login_url()}/?login_code={code}")
```

Add:

```python
@router.post("/google/exchange", response_model=TokenResponse)
def google_exchange(payload: LoginCodeExchange, db: DbSession, request: Request) -> TokenResponse:
    """Swap the one-time code from the Google redirect for a session. Works once, within 60 seconds."""
    user = login_codes.redeem(db, payload.code)
    if user is None:
        db.commit()  # keep the code marked used even when the account is disabled
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This sign-in link has expired. Please sign in again.")
    user.last_login_at = datetime.now(UTC)
    audit.record(db, "auth.login", actor=user, target_type="user", target_id=user.id, after={"via": "google"}, request=request)
    db.commit()
    return issue_token(user)
```

- [ ] **Step 6: Permission walk** (`tests/test_permissions_review.py`): add to both `PUBLIC` and `OPEN_WRITES`:

```python
    ("POST", "/auth/google/exchange"): "finishes Google sign-in; the one-time code is the credential",
```

- [ ] **Step 7: Frontend**

In `frontend/src/api/client.ts`, replace `captureTokenFromRedirect` (lines ~143–158) with:

```ts
/**
 * Google sign-in comes back with `?login_code=...` (one use, 60 seconds).
 * Read it and strip it from the address bar before anything renders. An old
 * `?token=` link is stripped and never honoured.
 */
export function takeLoginCodeFromRedirect(): string | null {
  const url = new URL(window.location.href)
  if (!url.searchParams.has('login_code') && !url.searchParams.has('token')) return null
  const code = url.searchParams.get('login_code')
  url.searchParams.delete('login_code')
  url.searchParams.delete('token')
  window.history.replaceState({}, '', url.toString())
  return code
}
```

and add to `api` next to `login`:

```ts
  exchangeLoginCode: (code: string) => post<{ access_token: string }>('/auth/google/exchange', { code }),
```

Run `grep -rn "captureTokenFromRedirect" frontend/src` and replace every use.

In `frontend/src/App.tsx`, replace the module-level `captureTokenFromRedirect()` (line ~141) with `const pendingLoginCode = takeLoginCodeFromRedirect()` and update the import. At the **top of `App()`, before any early return**, add:

```tsx
  const [loginError, setLoginError] = useState<string | null>(null)
  const [exchanging, setExchanging] = useState(!!pendingLoginCode)
  useEffect(() => {
    if (!pendingLoginCode) return
    api
      .exchangeLoginCode(pendingLoginCode)
      .then((r) => {
        setToken(r.access_token)
        window.location.reload()
      })
      .catch((e) => {
        setExchanging(false)
        setLoginError(e instanceof ApiError ? e.message : 'Google sign-in did not finish. Please try again.')
      })
  }, [])
  if (exchanging) return <div style={{ padding: '2rem' }}>Signing you in…</div>
```

Pass `loginError` to wherever `<AuthScreen />` is rendered: `<AuthScreen initialError={loginError} />`. In `AuthScreen.tsx` change the signature to `export default function AuthScreen({ initialError = null }: { initialError?: string | null } = {})` and initialise `useState<string | null>(initialError)` for `error`.

- [ ] **Step 8: Run tests and typecheck**

Run: `… -m pytest tests/test_p0_google_code.py tests/test_permissions_review.py -q` then `cd frontend && npx tsc --noEmit -p .`
Expected: all pass; no type errors.

- [ ] **Step 9: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/services/login_codes.py src/swing_trade_ml/api/v1/endpoints/auth.py tests/test_p0_google_code.py tests/test_permissions_review.py
cd .. && git add backend/src/swing_trade_ml/services/login_codes.py backend/src/swing_trade_ml/api/v1/endpoints/auth.py backend/src/swing_trade_ml/schemas/__init__.py backend/tests/test_p0_google_code.py backend/tests/test_permissions_review.py frontend/src/api/client.ts frontend/src/App.tsx frontend/src/components/AuthScreen.tsx
git commit -m "P0 (S5): Google sign-in hands over a 60-second one-time code, never the session token in the URL

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Startup secret guard; sign-up closed by default

**Files:**
- Modify: `backend/src/swing_trade_ml/core/security.py`
- Modify: `backend/src/swing_trade_ml/main.py` (first line of `lifespan`)
- Modify: `backend/src/swing_trade_ml/core/config.py` (`ALLOW_SIGNUP` default), `.env.example`
- Test: `backend/tests/test_p0_startup_guard.py`

**Interfaces:**
- Produces: `assert_secrets_safe(cfg: Settings) -> None`. Raises `RuntimeError` naming the setting (never its value) when `ENVIRONMENT != "local"` and `JWT_SECRET_KEY` or `API_KEY` is empty or a known default. It logs `security.short_secret` (setting name only) when one is shorter than 32 characters. It **does not refuse** a short secret, so prod cannot be taken down by an unknown length.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_startup_guard.py
from __future__ import annotations

import pytest

from swing_trade_ml.core.config import Settings, settings
from swing_trade_ml.core.security import assert_secrets_safe

LONG = "x" * 40


def _cfg(monkeypatch, env, jwt, key):
    monkeypatch.setattr(settings, "ENVIRONMENT", env)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", jwt)
    monkeypatch.setattr(settings, "API_KEY", key)
    return settings


@pytest.mark.parametrize("bad", ["", "change-me", " change-me "])
def test_refuses_default_secrets_outside_local(monkeypatch, bad):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        assert_secrets_safe(_cfg(monkeypatch, "production", bad, LONG))


def test_error_never_contains_the_secret_value(monkeypatch):
    with pytest.raises(RuntimeError) as exc:
        assert_secrets_safe(_cfg(monkeypatch, "production", LONG, "change-me"))
    assert LONG not in str(exc.value)


def test_names_api_key_too(monkeypatch):
    with pytest.raises(RuntimeError, match="API_KEY"):
        assert_secrets_safe(_cfg(monkeypatch, "staging", LONG, "change-me"))


def test_local_is_allowed_defaults(monkeypatch):
    assert_secrets_safe(_cfg(monkeypatch, "local", "change-me", "change-me"))


def test_real_secrets_pass_and_short_ones_only_warn(monkeypatch):
    assert_secrets_safe(_cfg(monkeypatch, "production", LONG, LONG))
    assert_secrets_safe(_cfg(monkeypatch, "production", "short-but-real", LONG))


def test_signup_is_closed_by_default():
    assert Settings.model_fields["ALLOW_SIGNUP"].default is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `… -m pytest tests/test_p0_startup_guard.py -v`
Expected: FAIL: `ImportError: cannot import name 'assert_secrets_safe'`.

- [ ] **Step 3: Implement** (`core/security.py`)

```python
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

_DEFAULT_SECRETS = frozenset({"", "change-me", "changeme", "secret"})


def assert_secrets_safe(cfg) -> None:
    """Refuse to serve outside local development while a signing secret is
    still a placeholder: anyone could mint an owner session (spec finding S6).
    Names the setting, never its value."""
    if cfg.ENVIRONMENT == "local":
        return
    names = ("JWT_SECRET_KEY", "API_KEY")
    bad = [n for n in names if getattr(cfg, n).strip() in _DEFAULT_SECRETS]
    if bad:
        raise RuntimeError(
            f"Refusing to start: {', '.join(bad)} still has a placeholder value. Set a real value in .env."
        )
    for n in names:
        if len(getattr(cfg, n)) < 32:
            log.warning("security.short_secret", setting=n)
```

- [ ] **Step 4: Call it at startup** (`main.py`, first line inside `lifespan`, before the `log.info("app.starting", …)`):

```python
    assert_secrets_safe(settings)
```

with `from swing_trade_ml.core.security import assert_secrets_safe` among the imports.

- [ ] **Step 5: Close sign-up by default**

`core/config.py`: `ALLOW_SIGNUP: bool = False` and update its comment to: "Self-registration. Off by default; invitations replace it (release C). Turn on in .env only for local development."
`.env.example` line 49: `ALLOW_SIGNUP=false` (update the comment above it the same way).

- [ ] **Step 6: Run tests**

Run: `… -m pytest tests/test_p0_startup_guard.py tests/test_auth_options.py -q`
Expected: all pass (`test_auth_options` sets the value explicitly).

- [ ] **Step 7: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/core/security.py src/swing_trade_ml/main.py tests/test_p0_startup_guard.py
cd .. && git add backend/src/swing_trade_ml/core/security.py backend/src/swing_trade_ml/main.py backend/src/swing_trade_ml/core/config.py .env.example backend/tests/test_p0_startup_guard.py
git commit -m "P0 (S6/S9): refuse to start with placeholder secrets outside local; sign-up closed by default

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Owner CLI for audited role changes; audit the plan admin routes

**Files:**
- Modify: `backend/src/swing_trade_ml/cli.py` (new commands; `create-user` gets `--role`)
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/plans.py` (`set_user_plan`, `set_switch`, `update_plan` record audit rows)
- Test: `backend/tests/test_p0_cli_roles.py`, `backend/tests/test_p0_plan_audit.py`

**Interfaces:**
- Consumes: `ROLES`, role sync (Task 1), `audit.record` (Task 2).
- Produces:
  - Pure helpers in `cli.py`, testable without argparse:
    - `role_audit_rows(db) -> list[dict]`: one row per user with `id, username, auth_provider, active, role, is_superuser, last_login_at, mismatch: bool` (`mismatch` = `is_superuser != (role == "owner")`).
    - `apply_role(db, username, role, reason) -> str`: sets the role (listener bumps `token_version`), audits `user.role_change` with before/after and the reason, and returns a plain sentence. It refuses to remove the **last** owner.
    - `apply_disable(db, username, reason) -> str`: `is_active=False`, `token_version+1`, audit `user.disable`.
    - `apply_unlock(db, username) -> str`: clears the lock, audit `user.unlock`.
    - `apply_revoke(db, username) -> str`: `token_version+1`, audit `user.revoke_sessions`.
  - Commands `swingtrade audit-roles`, `set-role --username U --role R --reason "…"`, `disable-user --username U --reason "…"`, `unlock-user --username U`, `revoke-sessions --username U`.
  - `create-user` requires `--role` (choices `ROLES`); `make-owner` = `apply_role(..., "owner", "make-owner command")`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_p0_cli_roles.py
"""Prod-shaped: the 7 accounts seen on 2026-10-16 (spec §6.5), by role and provider."""

from __future__ import annotations

import pytest

from swing_trade_ml.cli import apply_disable, apply_revoke, apply_role, apply_unlock, role_audit_rows
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

PROD_SHAPE = [
    ("naresh", "local", True), ("claude_verify_tmp", "local", False), ("claudecheck1787413845531", "local", False),
    ("admin", "local", False), ("sudeeksha", "local", True), ("naresh.gudiganti23", "google", False), ("vijay", "local", True),
]


@pytest.fixture()
def prod_users(db_session):
    for name, provider, owner in PROD_SHAPE:
        db_session.add(User(username=f"p0-{name}", hashed_password="x", auth_provider=provider,
                            is_active=True, is_superuser=owner, plan="free"))
    db_session.flush()


def _rows(db):
    return {r["username"]: r for r in role_audit_rows(db) if r["username"].startswith("p0-")}


def test_backfill_shape_matches_today(db_session, prod_users):
    rows = _rows(db_session)
    assert {u for u, r in rows.items() if r["role"] == "owner"} == {"p0-naresh", "p0-sudeeksha", "p0-vijay"}
    assert not any(r["mismatch"] for r in rows.values())


def test_set_role_audits_and_revokes(db_session, prod_users):
    msg = apply_role(db_session, "p0-vijay", "tester", "spec 6.5 approved by owner")
    user = db_session.query(User).filter_by(username="p0-vijay").one()
    assert (user.role, user.is_superuser, user.token_version) == ("tester", False, 1)
    row = db_session.query(AuditLog).filter_by(action="user.role_change", target_id=str(user.id)).one()
    assert row.before == {"role": "owner"} and row.after == {"role": "tester", "reason": "spec 6.5 approved by owner"}
    assert "vijay" in msg


def test_cannot_remove_the_last_owner(db_session):
    for u in db_session.query(User).filter(User.role == "owner"):
        u.role = "member"
    db_session.add(User(username="p0-only-owner", hashed_password="x", role="owner", plan="free"))
    db_session.flush()
    with pytest.raises(ValueError, match="last owner"):
        apply_role(db_session, "p0-only-owner", "member", "x")


def test_unknown_role_and_user_are_refused(db_session, prod_users):
    with pytest.raises(ValueError):
        apply_role(db_session, "p0-admin", "superadmin", "x")
    with pytest.raises(LookupError):
        apply_role(db_session, "p0-nobody", "member", "x")


def test_disable_unlock_revoke(db_session, prod_users):
    apply_disable(db_session, "p0-admin", "unknown holder")
    admin = db_session.query(User).filter_by(username="p0-admin").one()
    assert admin.is_active is False and admin.token_version == 1
    apply_revoke(db_session, "p0-sudeeksha")
    assert db_session.query(User).filter_by(username="p0-sudeeksha").one().token_version == 1
    apply_unlock(db_session, "p0-sudeeksha")
    actions = {a.action for a in db_session.query(AuditLog)}
    assert {"user.disable", "user.revoke_sessions", "user.unlock"} <= actions
```

```python
# backend/tests/test_p0_plan_audit.py
from __future__ import annotations

from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

API_KEY = {"X-API-Key": "test-api-key"}


def test_plan_change_and_switch_are_audited(client, db_session):
    user = User(username="pa1", hashed_password="x", plan="free")
    db_session.add(user)
    db_session.flush()
    client.put(f"/api/v1/admin/users/{user.id}/plan", json={"plan": "pro"}, headers=API_KEY)
    client.put("/api/v1/admin/switch", json={"enabled": False}, headers=API_KEY)
    rows = {a.action: a for a in db_session.query(AuditLog).filter(AuditLog.action.in_(["user.plan_change", "plans.switch"]))}
    assert rows["user.plan_change"].before == {"plan": "free"} and rows["user.plan_change"].after == {"plan": "pro"}
    assert rows["user.plan_change"].actor_label == "api-key"
    assert rows["plans.switch"].after == {"enabled": False}
```

- [ ] **Step 2: Run to verify they fail**

Run: `… -m pytest tests/test_p0_cli_roles.py tests/test_p0_plan_audit.py -v`
Expected: FAIL: `ImportError: cannot import name 'apply_role'`.

- [ ] **Step 3: Implement the helpers in `cli.py`** (top-level functions, above `cmd_create_user`)

```python
def _find_user(db, username: str):
    from sqlalchemy import select

    from swing_trade_ml.db.models.session import User

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise LookupError(f"No user '{username}'")
    return user


def role_audit_rows(db) -> list[dict]:
    from sqlalchemy import select

    from swing_trade_ml.db.models.session import User

    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return [
        {
            "id": u.id, "username": u.username, "auth_provider": u.auth_provider, "active": u.is_active,
            "role": u.role, "is_superuser": u.is_superuser, "last_login_at": u.last_login_at,
            "mismatch": u.is_superuser != (u.role == "owner"),
        }
        for u in users
    ]


def apply_role(db, username: str, role: str, reason: str) -> str:
    from sqlalchemy import func, select

    from swing_trade_ml.db.models.session import ROLES, User
    from swing_trade_ml.services import audit

    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}")
    user = _find_user(db, username)
    before = user.role
    if before == "owner" and role != "owner":
        owners = db.execute(select(func.count()).select_from(User).where(User.role == "owner", User.is_active)).scalar_one()
        if owners <= 1:
            raise ValueError("Refusing: this is the last owner account")
    user.role = role
    db.flush()
    audit.record(db, "user.role_change", actor_label="cli", target_type="user", target_id=user.id,
                 before={"role": before}, after={"role": role, "reason": reason})
    return f"{username}: {before} → {role}. Their open sessions have ended."


def apply_disable(db, username: str, reason: str) -> str:
    from swing_trade_ml.services import audit

    user = _find_user(db, username)
    user.is_active = False
    user.token_version = (user.token_version or 0) + 1
    audit.record(db, "user.disable", actor_label="cli", target_type="user", target_id=user.id,
                 before={"active": True}, after={"active": False, "reason": reason})
    return f"{username} can no longer sign in."


def apply_unlock(db, username: str) -> str:
    from swing_trade_ml.services import audit

    user = _find_user(db, username)
    user.locked_until, user.failed_login_count = None, 0
    audit.record(db, "user.unlock", actor_label="cli", target_type="user", target_id=user.id)
    return f"{username} can sign in again."


def apply_revoke(db, username: str) -> str:
    from swing_trade_ml.services import audit

    user = _find_user(db, username)
    user.token_version = (user.token_version or 0) + 1
    audit.record(db, "user.revoke_sessions", actor_label="cli", target_type="user", target_id=user.id)
    return f"Every session of {username} has ended."
```

Thin `cmd_*` wrappers (each opens `session_scope()`, calls the helper, prints the message, and returns 0, or prints `❌ …` and returns 1 on `ValueError`/`LookupError`):

```python
def cmd_audit_roles(args: argparse.Namespace) -> int:
    from swing_trade_ml.db.session import session_scope

    with session_scope() as db:
        for r in role_audit_rows(db):
            flag = "  ⚠ role/superuser disagree" if r["mismatch"] else ""
            print(f"{r['id']:>4}  {r['username']:<28} {r['auth_provider']:<7} "
                  f"{'active' if r['active'] else 'DISABLED':<8} role={r['role']:<7} last={r['last_login_at']}{flag}")
    print("Nothing was changed. Use set-role / disable-user after the owner approves.")
    return 0


def _run(fn, *a) -> int:
    from swing_trade_ml.db.session import session_scope

    try:
        with session_scope() as db:
            print(f"✅ {fn(db, *a)}")
        return 0
    except (ValueError, LookupError) as exc:
        print(f"❌ {exc}")
        return 1


def cmd_set_role(args: argparse.Namespace) -> int:
    return _run(apply_role, args.username, args.role, args.reason)


def cmd_disable_user(args: argparse.Namespace) -> int:
    return _run(apply_disable, args.username, args.reason)


def cmd_unlock_user(args: argparse.Namespace) -> int:
    return _run(apply_unlock, args.username)


def cmd_revoke_sessions(args: argparse.Namespace) -> int:
    return _run(apply_revoke, args.username)
```

Change `cmd_create_user` to `role=args.role` instead of `is_superuser=True`. Change `cmd_make_owner` body to `return _run(apply_role, args.username, "owner", "make-owner command")`. `cmd_local_dev` stays (local only; it sets `is_superuser`, which the listener turns into `owner`).

Parser additions (next to `create-user`, around line 756):

```python
    p.add_argument("--role", required=True, choices=["owner", "tester", "member"])  # on create-user

    sub.add_parser("audit-roles", help="List every login and its role (changes nothing)").set_defaults(func=cmd_audit_roles)
    p = sub.add_parser("set-role", help="Change a login's role (audited; ends their sessions)")
    p.add_argument("--username", required=True)
    p.add_argument("--role", required=True, choices=["owner", "tester", "member"])
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_set_role)
    p = sub.add_parser("disable-user", help="Stop a login from signing in (audited)")
    p.add_argument("--username", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_disable_user)
    p = sub.add_parser("unlock-user", help="Lift a sign-in pause early (audited)")
    p.add_argument("--username", required=True)
    p.set_defaults(func=cmd_unlock_user)
    p = sub.add_parser("revoke-sessions", help="End every session of a login (audited)")
    p.add_argument("--username", required=True)
    p.set_defaults(func=cmd_revoke_sessions)
```

Update the module docstring example `swingtrade create-user --username admin --password secret` to add `--role owner`.

- [ ] **Step 4: Audit plan admin writes** (`endpoints/plans.py`)

Import `PrincipalDep, actor_name` from `swing_trade_ml.api.deps` and `from swing_trade_ml.services import audit`. In `set_user_plan` add `principal: PrincipalDep` and replace `user.plan = body.plan; db.commit()` with:

```python
    before = user.plan
    user.plan = body.plan
    audit.record(db, "user.plan_change", actor=principal.user, actor_label=actor_name(principal),
                 target_type="user", target_id=user.id, before={"plan": before}, after={"plan": body.plan})
    db.commit()
```

In `set_switch` add `principal: PrincipalDep`:

```python
    enabled = plan_service.set_plans_enabled(db, body.enabled)
    audit.record(db, "plans.switch", actor=principal.user, actor_label=actor_name(principal), after={"enabled": enabled})
    db.commit()
    return {"enabled": enabled}
```

In `update_plan` add `principal: PrincipalDep` and, after a successful `save_plan`, `audit.record(db, "plans.edit", actor=principal.user, actor_label=actor_name(principal), target_type="plan", target_id=key, after={"features": body.features, "limits": body.limits}); db.commit()`. Check first with `grep -n "def set_plans_enabled\|def save_plan" -A12 src/swing_trade_ml/services/plans.py` whether those already commit. If they do, the extra commit is harmless. Keep the audit row inside the same transaction by recording before their commit where possible.

- [ ] **Step 5: Run the tests**

Run: `… -m pytest tests/test_p0_cli_roles.py tests/test_p0_plan_audit.py tests/test_plans.py -q`
Expected: all pass.

- [ ] **Step 6: Format and commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/cli.py src/swing_trade_ml/api/v1/endpoints/plans.py tests/test_p0_cli_roles.py tests/test_p0_plan_audit.py
cd .. && git add backend/src/swing_trade_ml/cli.py backend/src/swing_trade_ml/api/v1/endpoints/plans.py backend/tests/test_p0_cli_roles.py backend/tests/test_p0_plan_audit.py
git commit -m "P0: owner CLI for audited role changes, disable, unlock, revoke; plan changes audited

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Role × route matrix (every route)

**Files:**
- Create: `backend/tests/test_p0_role_matrix.py`

**Interfaces:**
- Consumes: `_routes()`, `_url()`, `OPEN_WRITES`, `PUBLIC` from `tests/test_permissions_review.py`; `TESTER_WRITES` from `api.deps` (Task 4).

- [ ] **Step 1: Write the tests**

```python
# backend/tests/test_p0_role_matrix.py
"""Every route × every role. A new route that forgets its guard fails here."""

from __future__ import annotations

import pytest

from swing_trade_ml.api.deps import TESTER_WRITES
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from test_permissions_review import OPEN_WRITES, WRITE_METHODS, _routes, _url  # sibling import, like brain_fakes

REAL_ACCOUNT_PREFIXES = ("/portfolio/real/", "/real-report")


def _as(db, username, role, active=True) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=active, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


WRITES = [r for r in _routes() if r[0] in WRITE_METHODS]


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_tester_writes_only_the_testing_book(client, db_session, method, path):
    if (method, path) in OPEN_WRITES or (method, path) in TESTER_WRITES:
        pytest.skip("self-service or tester route")
    r = client.request(method, _url(path), json={}, headers=_as(db_session, "mx-tester", "tester"))
    assert r.status_code in (401, 403), f"{method} {path} let a tester through: {r.status_code}"


@pytest.mark.parametrize(("method", "path"), [r for r in _routes() if r[1].startswith(REAL_ACCOUNT_PREFIXES)])
def test_real_account_is_never_open_to_testers_or_members(client, db_session, method, path):
    for role in ("tester", "member"):
        r = client.request(method, _url(path), json={} if method in WRITE_METHODS else None,
                           headers=_as(db_session, f"mx-real-{role}", role))
        assert r.status_code in (401, 403), f"{role} reached {method} {path}"


def test_disabled_account_is_refused(client, db_session):
    r = client.get("/api/v1/auth/me", headers=_as(db_session, "mx-off", "owner", active=False))
    assert r.status_code == 401


def test_api_key_still_owner(client):
    assert client.get("/api/v1/strategies", headers={"X-API-Key": "test-api-key"}).status_code == 200
```

Before writing `REAL_ACCOUNT_PREFIXES`, run `grep -n "require_real_account\|_OWNER" backend/src/swing_trade_ml/api/v1/endpoints/*.py` and list every real-account route prefix it shows. The parametrised list must not be empty, so add `assert` on its length in a separate test if needed.

- [ ] **Step 2: Run**

Run: `… -m pytest tests/test_p0_role_matrix.py tests/test_permissions_review.py -q`
Expected: all pass. A failure here is a real permission gap. Fix it in the guard, never by adding to a skip list without the owner's say.

- [ ] **Step 3: Full suite**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE .venv/Scripts/python.exe -m pytest -q`
Expected: everything green. Record the pass count in the commit message.

- [ ] **Step 4: Commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format tests/test_p0_role_matrix.py
cd .. && git add backend/tests/test_p0_role_matrix.py
git commit -m "P0: role × route matrix over every route; real account closed to testers and members

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Migration and rollback rehearsal; deploy runbook

**Files:**
- Create: `backend/scripts/rehearse_p0_migration.py`
- Create: `docs/deploy/P0-security-runbook.md`
- Modify: `docs/architecture/CODE-MAP.md` (auth rows: `services/audit.py`, `services/login_codes.py`, `db/models/audit.py`, roles)

**Interfaces:** none (operational).

- [ ] **Step 1: Write the rehearsal script**

```python
# backend/scripts/rehearse_p0_migration.py
"""Rehearse the P0 migration on a scratch database shaped like prod (7 users).

Usage (Docker Postgres up):  .venv/Scripts/python.exe scripts/rehearse_p0_migration.py
Creates and drops database swing_trade_ml_p0_rehearsal. Never touches the real or test DB.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

SERVER = "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433"
NAME = "swing_trade_ml_p0_rehearsal"
URL = f"{SERVER}/{NAME}"
BEFORE, AFTER = "d8a1y2c3h4k5", "e1p0s2e3c4u5"
USERS = [("naresh", True), ("claude_verify_tmp", False), ("claudecheck1787413845531", False),
         ("admin", False), ("sudeeksha", True), ("naresh.gudiganti23", False), ("vijay", True)]


def _cfg() -> Config:
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", URL)
    return cfg


def main() -> None:
    admin = create_engine(f"{SERVER}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {NAME}"))
        c.execute(text(f"CREATE DATABASE {NAME}"))
    eng = create_engine(URL)
    try:
        command.upgrade(_cfg(), BEFORE)
        with eng.begin() as c:
            for name, su in USERS:
                c.execute(text("INSERT INTO users (username, hashed_password, auth_provider, is_active, is_superuser, plan, created_at, updated_at) "
                               "VALUES (:u, 'x', 'local', true, :su, 'free', now(), now())"), {"u": name, "su": su})
        command.upgrade(_cfg(), AFTER)
        with eng.connect() as c:
            rows = dict(c.execute(text("SELECT username, role FROM users")).all())
            assert {u for u, r in rows.items() if r == "owner"} == {"naresh", "sudeeksha", "vijay"}, rows
            assert c.execute(text("SELECT count(*) FROM users WHERE is_superuser <> (role = 'owner')")).scalar_one() == 0
            assert c.execute(text("SELECT count(*) FROM users")).scalar_one() == len(USERS)
        command.downgrade(_cfg(), BEFORE)
        with eng.connect() as c:
            cols = {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))}
            assert "role" not in cols and "token_version" not in cols
            assert c.execute(text("SELECT count(*) FROM users WHERE is_superuser")).scalar_one() == 3
        command.upgrade(_cfg(), AFTER)  # and forward again
        print("✅ P0 migration: upgrade, backfill, downgrade, re-upgrade all as expected")
        print(f"Scratch DB {NAME} left at {AFTER} for the old-code rehearsal (Step 3). Drop it afterwards.")
    finally:
        eng.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `cd backend && .venv/Scripts/python.exe scripts/rehearse_p0_migration.py`
Expected: the ✅ line.

- [ ] **Step 3: Old code against the new schema** (the rollback that matters)

```bash
cd "D:/machine learning/swing-trade-bot"
git worktree add ../stb-p0-oldcode develop          # the pre-P0 code
cd ../stb-p0-oldcode/backend
# point the OLD code at the upgraded scratch DB, in a throwaway shell only:
DATABASE_URL=postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_p0_rehearsal \
ENVIRONMENT=local ENABLE_SCHEDULER=false TRADING_MODE=paper DB_AUTO_MIGRATE=true \
"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m uvicorn swing_trade_ml.main:app --port 8077
```

In a second shell:
- `curl -s localhost:8077/api/v1/health` → `{"status":"ok"…}`
- the old code logged `db.migrate.failed` (it does not know revision `e1p0s2e3c4u5`) and then `db.create_all.fallback`, **without crashing**. Copy those two log lines into the runbook as observed evidence.
- create a login on the scratch DB with the old CLI (`swingtrade create-user --username rb --password rollback-check-1`, with the same `DATABASE_URL`), then `POST /api/v1/auth/login` → 200. This shows old code can still sign people in on the new schema.
- `SELECT username, role, is_superuser FROM users WHERE username='rb'` shows `role=member, is_superuser=true`, the mismatch the runbook warns about. After roll-forward, `swingtrade audit-roles` flags it.

Stop the server, then `git worktree remove ../stb-p0-oldcode`, and drop the scratch DB.

- [ ] **Step 4: Write `docs/deploy/P0-security-runbook.md`**

```markdown
# P0 security release: deploy and rollback runbook

Owner approval needed for every step marked 🔒. Nothing here changes trading.

## Before deploy
1. Role table approved (spec §6.5): `sudeeksha` only owner (owner decision 2026-10-16).
2. All tests green on `feature/p0-security` (pass count: ___).
3. Migration rehearsal printed ✅ (Task 11 Step 2); old-code rehearsal evidence pasted below.
4. Placeholder-secret check: the API refuses to start in production if `JWT_SECRET_KEY` or `API_KEY`
   is a placeholder. 🔒 Owner confirms both are real values on the droplet (names only, never values).
   If unsure, run the startup guard on the droplet: `docker compose exec api python -c "from swing_trade_ml.core.config import settings; from swing_trade_ml.core.security import assert_secrets_safe; assert_secrets_safe(settings); print('ok')"`.
5. Database backup taken on the droplet (`pg_dump`), file name noted: ___.
6. Tell Vijay and other users: everyone signs in again once after deploy.

## Deploy
7. 🔒 Owner merges to `main` (push to main = deploy).
8. Watch: `GET /health` ok; `GET /api/v1/status` (API key) shows `environment: production`, `trading_mode: paper`.
9. Owner signs in (password and Google). Google lands on the app with no `token=` in the address bar.
10. Vijay buys and closes one practice position in his testing book. Works.

## Apply roles (after deploy, one at a time, each audited)
11. `swingtrade audit-roles`: matches spec §6.5, no ⚠ lines.
12. 🔒 Owner decision 2026-10-16: **`sudeeksha` is the only owner**; everyone else is secondary
    (no owner powers, no My Holdings). `REAL_ACCOUNT_USERS` stays `sudeeksha`. Run, in this order:
    `swingtrade set-role --username naresh --role member --reason "owner decision 2026-10-16: sudeeksha only owner"`
    `swingtrade set-role --username vijay --role tester --reason "owner decision 2026-10-16: secondary; testing book only"`
    `swingtrade disable-user --username admin --reason "unknown holder"`
    `swingtrade disable-user --username claude_verify_tmp --reason "leftover test account"`
    `swingtrade disable-user --username claudecheck1787413845531 --reason "leftover test account"`
    (`naresh.gudiganti23` is already a member — no command needed.)
    Then sign in as `sudeeksha` and confirm My Holdings still opens; sign in as `naresh` and confirm
    My Holdings and owner screens are refused.
13. `swingtrade audit-roles` again; `GET /admin/users` shows the same.

## Rollback
- **Code:** revert the merge on `main` (deploys the previous build). Rehearsed: the old code boots
  on the new schema (logs `db.migrate.failed` then `db.create_all.fallback`) and logins work.
- **Roles after rollback:** old code reads only `is_superuser`, which mirrors `role`. A tester stays
  non-owner, so Vijay's testing writes are refused on old code. If needed, temporarily
  `swingtrade make-owner --username vijay` (audited on the next roll-forward via `audit-roles`).
- **Schema (only if required):** `alembic downgrade d8a1y2c3h4k5` drops the new columns and
  tables. The audit trail is lost, so export `audit_log` first.
- **Roll-forward after a rollback:** run `swingtrade audit-roles`. Any ⚠ (accounts created by old
  code get `role=member` with `is_superuser=true`) is fixed with `set-role`.

## Acceptance (release A done when all true)
- [ ] Only `sudeeksha` has `role=owner`; `audit-roles` shows no ⚠; only `sudeeksha` opens My Holdings.
- [ ] 5 wrong passwords pause sign-in for 15 minutes; message identical for every failure.
- [ ] Password change / sign out everywhere end old sessions.
- [ ] Google sign-in URL never contains a session token.
- [ ] A member account gets 403 on house screens; tester keeps their testing book only.
- [ ] API refuses to start with placeholder secrets outside local.
- [ ] Every sign-in, role, plan and switch change is in `audit_log`.
- [ ] Real-account routes refuse testers and members; `TRADING_MODE`/`ALLOW_LIVE_TRADING` unchanged.

## Observed rehearsal evidence
(paste the Task 11 Step 3 log lines here)
```

- [ ] **Step 5: Update `docs/architecture/CODE-MAP.md`**

In §5 (API), after the `Auth/plan gate:` sentence, add: `Roles (owner/tester/member), session versions and lockout: db/models/session.py, api/deps.py, endpoints/auth.py; audit trail: db/models/audit.py, services/audit.py; Google one-time codes: services/login_codes.py; owner CLI: swingtrade audit-roles / set-role / disable-user / unlock-user / revoke-sessions.`

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/rehearse_p0_migration.py docs/deploy/P0-security-runbook.md docs/architecture/CODE-MAP.md
git commit -m "P0: migration + old-code rollback rehearsal, deploy runbook with owner approval gates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Stop.** Report the branch, the commits, the test pass count and the rehearsal evidence to the owner. **Do not push or merge.**

---

## Acceptance criteria (release A)

Copied into the runbook. Release A is done only when every box there is ticked on prod, after the
owner's merge and role approvals.

## Threat model, impacted files, database changes

See spec §6.1 (threat model), the File map above (impacted files), and Task 1 (database changes:
`users.role`, `token_version`, `failed_login_count`, `locked_until`; tables `audit_log`, `login_codes`).
