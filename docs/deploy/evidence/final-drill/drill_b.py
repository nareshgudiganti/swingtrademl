"""Drill B: legacy database at wlquantity01 with representative data, upgrade to head, verify, sign in."""

import sys

from drill_common import *

DB = "drill_fin_legacy"
HERE = os.path.dirname(os.path.abspath(__file__))
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    log(f"CHECK {'PASS' if cond else 'FAIL'} {name} {detail}")


def counts():
    return {
        t: psql_db(DB, f"select count(*) from {t}")
        for t in ("users", "strategies", "instruments", "signals", "stock_score_history")
    }


admin_sql(f"DROP DATABASE IF EXISTS {DB}", DB)
admin_sql(f"CREATE DATABASE {DB}", DB)
rc, _ = run_alembic(DB, "upgrade", "wlquantity01")
check("build to old head wlquantity01", rc == 0)
rc, out = run_alembic(DB, "current")
check("current is wlquantity01", "wlquantity01" in out, out)
check(
    "owner_private absent before",
    psql_db(
        DB,
        "select count(*) from information_schema.columns where table_name='strategies' and column_name='owner_private'",
    )
    == "0",
)
rc, out = run_py(DB, HERE + "/seed_legacy.py")
log(out.strip())
check("seed", rc == 0)
before = counts()
log(f"COUNTS before {before}")
rc, _ = run_alembic(DB, "upgrade", "head")
check("upgrade head rc=0", rc == 0)
rc, out = run_alembic(DB, "current")
check("current is acctdelete01", "acctdelete01" in out, out)
rc, out = run_alembic(DB, "heads")
check("exactly one head acctdelete01", out.count("(head)") == 1 and "acctdelete01" in out, out)
after = counts()
log(f"COUNTS after {after}")
check("row counts unchanged", before == after)
rc, out = run_py(DB, HERE + "/verify_upgrade.py")
log(out.strip())
check("verify_upgrade", rc == 0)
rc, out = run_py(DB, HERE + "/signin_int.py")
log(out.strip())
check("sign-in compat, plans off", rc == 0)
psql_db(
    DB,
    "insert into plan_settings(id, enabled) values (1, true) on conflict (id) do update set enabled=true",
)
psql_db(DB, "update users set plan='pro' where username='member1'")
rc, out = run_py(DB, HERE + "/signin_plans_on.py")
log(out.strip())
check("plans ON member visibility", rc == 0)
admin_sql(f"DROP DATABASE IF EXISTS {DB}", DB)
log("DRILL B " + ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
