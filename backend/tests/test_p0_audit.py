# backend/tests/test_p0_audit.py
from __future__ import annotations

from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import audit


def test_record_names_the_actor_and_target(db_session):
    user = User(username="aud1", hashed_password="x", role="owner")
    db_session.add(user)
    db_session.flush()
    row = audit.record(
        db_session,
        "user.role_change",
        actor=user,
        target_type="user",
        target_id=7,
        before={"role": "owner"},
        after={"role": "tester"},
    )
    assert (row.actor_user_id, row.actor_label, row.target_id) == (user.id, "aud1", "7")
    assert row.after == {"role": "tester"}


def test_record_redacts_secrets(db_session):
    row = audit.record(
        db_session,
        "auth.password_change",
        actor_label="cli",
        after={"password": "hunter22", "hashed_password": "$2b$..", "token": "eyJ", "ok": True},
    )
    assert row.after == {
        "password": "[redacted]",
        "hashed_password": "[redacted]",
        "token": "[redacted]",
        "ok": True,
    }


def test_record_without_actor_is_system_and_truncates_labels(db_session):
    row = audit.record(db_session, "auth.login_failed", actor_label="x" * 500)
    assert len(row.actor_label) == 128
    assert audit.record(db_session, "job.ping").actor_label == "system"


def test_record_does_not_commit(db_session):
    audit.record(db_session, "test.nocommit")
    db_session.rollback()
    assert db_session.query(AuditLog).filter_by(action="test.nocommit").count() == 0
