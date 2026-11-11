"""Shared helpers for the integration drill. Never prints the connection address.

Every command that touches a database goes through run_alembic / psql_db / admin_sql and is
logged with the exact database name it targets (LOG file). Only drill_int_* databases are touched,
plus the Postgres maintenance database 'postgres' for CREATE/DROP DATABASE of those names.
"""

import datetime
import os
import re
import subprocess

WT = r"D:/machine learning/int-wt"
BACKEND = WT + "/backend"
PY = r"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe"
LOG = os.environ.get("DRILL_LOG", "drill.log")
ALLOWED = {"drill_int_clean", "drill_int_legacy"}
CONTAINER = "stml-postgres"
PGUSER = "swingtrade"


def log(msg):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def url(dbname):
    assert dbname in ALLOWED, dbname
    t = open(BACKEND + "/tests/conftest.py", encoding="utf-8").read()
    m = re.search(r'"(postgresql\+psycopg://[^"]+)/swing_trade_ml_test"', t)
    return m.group(1) + "/" + dbname


def admin_sql(sql, dbname):
    """CREATE/DROP DATABASE via the maintenance DB. dbname is the database being created/dropped."""
    assert dbname in ALLOWED
    log(f"TARGET maintenance-db=postgres affecting={dbname} sql={sql}")
    r = subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "psql",
            "-U",
            PGUSER,
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )
    log(f"  rc={r.returncode} {r.stdout.strip()[:200]} {r.stderr.strip()[:200]}")
    return r


def psql_db(dbname, sql):
    assert dbname in ALLOWED
    log(f"TARGET db={dbname} psql sql={sql[:150]}")
    r = subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "psql",
            "-U",
            PGUSER,
            "-d",
            dbname,
            "-At",
            "-F",
            "|",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode:
        log(f"  ERROR {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def env_for(dbname, extra=None):
    e = dict(os.environ)
    for k in ("API_KEY", "JWT_SECRET_KEY", "TRADING_MODE", "DATABASE_URL"):
        e.pop(k, None)
    e.update(DATABASE_URL=url(dbname), PYTHONPATH=BACKEND + "/src")
    if extra:
        e.update(extra)
    return e


def run_alembic(dbname, *args):
    log(f"TARGET db={dbname} alembic {' '.join(args)}")
    r = subprocess.run(
        [PY, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env_for(dbname),
        capture_output=True,
        text=True,
    )
    out = (r.stdout + r.stderr).strip()
    log(f"  rc={r.returncode} {out[-400:]!r}")
    return r.returncode, out


def run_py(dbname, script, *args, extra=None):
    log(f"TARGET db={dbname} python {os.path.basename(script)}")
    r = subprocess.run(
        [PY, script, *args],
        cwd=BACKEND,
        env=env_for(dbname, extra),
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout + r.stderr
