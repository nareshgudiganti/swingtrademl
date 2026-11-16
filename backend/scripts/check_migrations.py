"""Fail CI if the migrations do not build the schema the code expects (Codex audit finding 10).

The test suite builds its schema with `create_all()`, so a broken or missing Alembic migration is
invisible to it — and then breaks the deploy, which runs `alembic upgrade head` on the real database.
This script runs against a database that `alembic upgrade head` has just built from EMPTY and checks:

1. there is exactly one migration head (two heads mean a merge was forgotten);
2. the database is at that head;
3. every table the models define exists, and no table exists that the models do not define;
4. every column the models define exists in its table, and no column exists that the models do not
   define. A new model column without a migration, or a migration column the model forgot, fails.

Column TYPES and server defaults are not compared here: `alembic check` shows pre-existing drift in
those, which CI reports as advisory until that backlog is cleared and baselined.

Usage (from backend/, after `alembic upgrade head` on a throwaway database):

    DATABASE_URL=postgresql+psycopg://.../swing_trade_ml_migrate_test python scripts/check_migrations.py

Refuses to run unless the database passes swing_trade_ml.core.db_guard (local, name ends in `_test`,
no URL query parameters); the refusal never prints the URL.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]
# Tables owned by the extensions or Alembic itself, not by the models.
EXTENSION_TABLES = frozenset({"alembic_version"})


def compare_schema(expected: dict[str, set[str]], actual: dict[str, set[str]]) -> list[str]:
    """Compare {table: column names} from the models with the same from the migrated database."""
    problems: list[str] = []
    for table in sorted(expected.keys() - actual.keys()):
        problems.append(f"model table '{table}' is not created by any migration")
    for table in sorted(actual.keys() - expected.keys()):
        problems.append(f"migrations create table '{table}' that no model defines")
    for table in sorted(expected.keys() & actual.keys()):
        for column in sorted(expected[table] - actual[table]):
            problems.append(f"model column '{table}.{column}' is not created by any migration")
        for column in sorted(actual[table] - expected[table]):
            problems.append(f"migrations create column '{table}.{column}' that no model defines")
    return problems


def check(database_url: str) -> list[str]:
    """Return a list of problems (empty = fine)."""
    from swing_trade_ml.db import models  # noqa: F401 — registers every table on Base
    from swing_trade_ml.db.base import Base

    problems: list[str] = []

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    heads = script.get_heads()
    if len(heads) != 1:
        problems.append(f"expected exactly one migration head, found {len(heads)}: {sorted(heads)}")

    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if sorted(current) != sorted(heads):
                problems.append(f"database is at {sorted(current)}, not at head {sorted(heads)}")
            inspector = inspect(conn)
            actual = {
                table: {column["name"] for column in inspector.get_columns(table)}
                for table in inspector.get_table_names()
                if table not in EXTENSION_TABLES
            }
    finally:
        engine.dispose()

    expected = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }
    return problems + compare_schema(expected, actual)


def main() -> int:
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.core.db_guard import assert_local_test_database, assert_no_connection_overrides

    try:
        assert_no_connection_overrides(os.environ)
        assert_local_test_database(settings.DATABASE_URL)
    except RuntimeError as refusal:  # the message never contains the URL
        print(refusal, file=sys.stderr)
        return 2

    problems = check(settings.DATABASE_URL)
    if problems:
        print("Migration check FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("Migration check passed: one head, database at head, tables and columns match the models.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
