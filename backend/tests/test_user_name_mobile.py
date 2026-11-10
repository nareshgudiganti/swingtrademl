"""Task 1.2: name and mobile on the user record (data layer + validation only)."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.core.mobile import normalise_full_name, normalise_mobile
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User

BACKEND = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "raw",
    [
        "9876543210",
        "98765 43210",
        " 9876543210 ",
        "+91 98765 43210",
        "+919876543210",
        "91-9876543210",
        "91 9876543210",
        "919876543210",
        "09876543210",
        "0 98765-43210",
        "0091 9876543210",
        "(98765) 43210",
    ],
)
def test_valid_mobile_forms_become_ten_digits(raw):
    assert normalise_mobile(raw) == "9876543210"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "5876543210",  # must start 6-9
        "0123456789",
        "987654321",  # 9 digits
        "98765432101",  # 11 digits, no valid prefix
        "+1 9876543210",  # other country
        "+44 9876543210",
        "98765abc10",
        "98765-43210x",
        "+91",
        "0000000000",
        None,
        9876543210,
    ],
)
def test_invalid_mobile_is_refused(raw):
    with pytest.raises(ValueError):
        normalise_mobile(raw)


def test_mobile_starting_six_to_nine_all_accepted():
    for first in "6789":
        assert normalise_mobile(f"{first}123456789") == f"{first}123456789"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Asha Rao", "Asha Rao"),
        ("  Asha   Rao  ", "Asha Rao"),
        ("Asha\tRao", "Asha Rao"),
        ("A.B. Kumar-Singh", "A.B. Kumar-Singh"),
        ("Ravi", "Ravi"),
        ("అనిల్ కుమార్", "అనిల్ కుమార్"),
        ("A1 Kumar", "A1 Kumar"),
        ("x" * 80, "x" * 80),
    ],
)
def test_valid_names_are_tidied(raw, expected):
    assert normalise_full_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "A", " A ", "x" * 81, "12345", "12 34", "Asha\x00Rao", "Asha\x07", "Asha\u202eRao", None, 5],
)
def test_invalid_names_are_refused(raw):
    with pytest.raises(ValueError):
        normalise_full_name(raw)


def test_single_migration_head_and_parent():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    heads = script.get_heads()
    assert heads == ["usernamemob01"]
    assert script.get_revision("usernamemob01").down_revision == "wlquantity01"


def test_model_columns_are_nullable_and_mobile_unique():
    cols = User.__table__.c
    assert cols.full_name.nullable and cols.mobile.nullable
    assert cols.mobile.type.length == 10
    assert cols.full_name.type.length == 80
    assert any(i.unique and [c.name for c in i.columns] == ["mobile"] for i in User.__table__.indexes)


def _user(name, **kw):
    return User(username=name, email=f"{name}@example.com", hashed_password="x", **kw)


def test_two_users_without_mobile_are_allowed(db_session):
    db_session.add_all([_user("nm_a"), _user("nm_b")])
    db_session.flush()


def test_duplicate_mobile_is_rejected(db_session):
    db_session.add(_user("nm_c", mobile="9876543210"))
    db_session.flush()
    db_session.add(_user("nm_d", mobile="9876543210"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_migration_downgrade_then_upgrade(db_session):
    path = BACKEND / "alembic/versions/20261110_1000_user_name_mobile.py"
    spec = spec_from_file_location("user_name_mobile_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "wlquantity01"

    conn = db_session.connection()  # inside the test's transaction: rolled back afterwards
    migration.op = Operations(MigrationContext.configure(conn))
    migration.downgrade()
    cols = {c["name"] for c in inspect(conn).get_columns("users")}
    assert not {"full_name", "mobile"} & cols
    migration.upgrade()
    migration.upgrade()  # safe to run twice
    cols = {c["name"] for c in inspect(conn).get_columns("users")}
    assert {"full_name", "mobile"} <= cols
    idx = {i["name"]: i for i in inspect(conn).get_indexes("users")}
    assert idx["ix_users_mobile"]["unique"]
    migration.downgrade()
    migration.upgrade()


def test_me_returns_own_name_and_mobile(client, db_session):
    u = _user("nm_me", full_name="Asha Rao", mobile="9876543210")
    db_session.add(u)
    db_session.flush()
    token = create_access_token(u.username, {"uid": u.id, "tv": 0})
    body = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["full_name"] == "Asha Rao"
    assert body["mobile"] == "9876543210"
