"""Drill A: clean database, full chain, one head, column checks, step down and back up."""

import sys

from drill_common import *

DB = "drill_int_clean"
# Explicit revisions: "-1" is ambiguous at the merge point (mergeheads01 has two parents).
DOWN = ["authtokens01", "usernamemob01", "mergeheads01"]
UP = ["mergeheads01", "usernamemob01", "authtokens01", "billing01"]
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    log(f"CHECK {'PASS' if cond else 'FAIL'} {name} {detail}")


def cols(table):
    return set(
        psql_db(
            DB,
            f"select column_name from information_schema.columns where table_name='{table}'",
        ).split("\n")
    )


def tables():
    return set(
        psql_db(
            DB,
            "select table_name from information_schema.tables where table_schema='public'",
        ).split("\n")
    )


admin_sql(f"DROP DATABASE IF EXISTS {DB}", DB)
admin_sql(f"CREATE DATABASE {DB}", DB)
rc, _ = run_alembic(DB, "upgrade", "head")
check("upgrade head rc=0", rc == 0)
rc, out = run_alembic(DB, "heads")
check(
    "exactly one head billing01", out.count("(head)") == 1 and "billing01" in out, out
)
rc, out = run_alembic(DB, "current")
check("current is billing01", "billing01" in out, out)
check("users columns", {"full_name", "mobile", "email_verified_at"} <= cols("users"))
check("strategies.owner_private", "owner_private" in cols("strategies"))
check("auth_tokens table", "auth_tokens" in tables(), str(sorted(cols("auth_tokens"))))
for t in ("subscriptions", "billing_events", "plan_grants"):
    check(f"{t} table", t in tables(), str(sorted(cols(t))))
check(
    "no unique/other index on users.mobile",
    psql_db(
        DB,
        "select count(*) from pg_indexes where tablename='users' and indexdef ilike '%mobile%'",
    )
    == "0",
)

# step down the last four, one at a time, then back up one at a time
for rev in DOWN:
    rc, _ = run_alembic(DB, "downgrade", rev)
    check(f"downgrade to {rev} rc=0", rc == 0)
    rc, out = run_alembic(DB, "current")
    check(f"current is {rev}", rev in out, out)
for rev in ("ownerprivate01", "wlquantity01"):
    rc, _ = run_alembic(DB, "downgrade", rev)
    check(f"downgrade to {rev} rc=0", rc == 0)
check("after 4 downs: owner_private gone", "owner_private" not in cols("strategies"))
check(
    "after 4 downs: users columns gone",
    not ({"full_name", "mobile", "email_verified_at"} & cols("users")),
)
check(
    "after 4 downs: billing/auth tables gone",
    not ({"auth_tokens", "subscriptions", "billing_events", "plan_grants"} & tables()),
)
rc, out = run_alembic(DB, "current")
check("after 4 downs: current is wlquantity01", "wlquantity01" in out, out)
for rev in UP:
    rc, _ = run_alembic(DB, "upgrade", rev)
    check(f"upgrade to {rev} rc=0", rc == 0)
rc, out = run_alembic(DB, "current")
check("after 4 ups: current is billing01 and one head", "billing01" in out)
check(
    "after 4 ups: all objects back",
    {"full_name", "mobile", "email_verified_at"} <= cols("users")
    and "owner_private" in cols("strategies")
    and {"auth_tokens", "subscriptions", "billing_events", "plan_grants"} <= tables(),
)
admin_sql(f"DROP DATABASE IF EXISTS {DB}", DB)
log("DRILL A " + ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
