"""Prod-shaped: the 7 accounts seen on 2026-10-16 (spec §6.5), by role and provider."""

from __future__ import annotations

import pytest

from swing_trade_ml.cli import apply_disable, apply_revoke, apply_role, apply_unlock, role_audit_rows
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

PROD_SHAPE = [
    ("naresh", "local", True),
    ("claude_verify_tmp", "local", False),
    ("claudecheck1787413845531", "local", False),
    ("admin", "local", False),
    ("sudeeksha", "local", True),
    ("naresh.gudiganti23", "google", False),
    ("vijay", "local", True),
]


@pytest.fixture()
def prod_users(db_session):
    for name, provider, owner in PROD_SHAPE:
        db_session.add(
            User(
                username=f"p0-{name}",
                hashed_password="x",
                auth_provider=provider,
                is_active=True,
                is_superuser=owner,
                plan="free",
            )
        )
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
    assert row.before == {"role": "owner"} and row.after == {
        "role": "tester",
        "reason": "spec 6.5 approved by owner",
    }
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
