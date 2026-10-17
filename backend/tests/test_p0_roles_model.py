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
