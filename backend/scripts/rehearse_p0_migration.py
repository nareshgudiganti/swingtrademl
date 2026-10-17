"""Rehearse the P0 migration on a scratch database shaped like prod (7 users).

Usage (Docker Postgres up):  .venv/Scripts/python.exe scripts/rehearse_p0_migration.py
Creates and drops database swing_trade_ml_p0_rehearsal. Never touches the real or test DB.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

SERVER = "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433"
NAME = "swing_trade_ml_p0_rehearsal"
URL = f"{SERVER}/{NAME}"
BEFORE, AFTER = "d8a1y2c3h4k5", "e1p0s2e3c4u5"
# alembic/env.py takes the URL from application settings, so point settings at the scratch DB
# before anything imports them.
os.environ["DATABASE_URL"] = URL
os.environ.setdefault("ENVIRONMENT", "local")
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
            # Every pre-P0 session ends at deploy: old tokens carry no tv (= 0).
            assert c.execute(text("SELECT count(*) FROM users WHERE token_version <> 1")).scalar_one() == 0
        command.downgrade(_cfg(), BEFORE)
        with eng.connect() as c:
            cols = {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))}
            assert "role" not in cols and "token_version" not in cols
            assert c.execute(text("SELECT count(*) FROM users WHERE is_superuser")).scalar_one() == 3
        command.upgrade(_cfg(), AFTER)  # and forward again
        print("OK P0 migration: upgrade, backfill, sessions ended (token_version=1), downgrade, re-upgrade all as expected")
        print(f"Scratch DB {NAME} left at {AFTER} for the old-code rehearsal (Step 3). Drop it afterwards.")
    finally:
        eng.dispose()


if __name__ == "__main__":
    main()
