"""After upgrade: check backfills and that nothing was lost. Prints PASS/FAIL lines."""

import os
import sys

from sqlalchemy import create_engine, text

e = create_engine(os.environ["DATABASE_URL"])
ok = True


def chk(name, cond):
    global ok
    ok &= bool(cond)
    print("CHECK", "PASS" if cond else "FAIL", name)


with e.connect() as c:
    chk("users=6", c.execute(text("select count(*) from users")).scalar() == 6)
    chk(
        "strategies=8", c.execute(text("select count(*) from strategies")).scalar() == 8
    )
    chk(
        "instruments=8",
        c.execute(text("select count(*) from instruments")).scalar() == 8,
    )
    chk("signals=8", c.execute(text("select count(*) from signals")).scalar() == 8)
    rows = c.execute(text("select instrument_id, as_of::text, model_name from stock_score_history order by 1,2")).all()
    print("score history:", rows)
    chk("score history 3 rows kept", len(rows) == 3)
    chk("model_name backfilled before the colon, empty when no version", sorted(r[2] for r in rows) == ["", "swing_v7", "swing_v7"])
    got = dict(c.execute(text("select name, owner_private from strategies")).all())
    print("owner_private:", got)
    private = {
        "real_trading",
        "my_real_book_copy",
        "tester_paper",
        "unknown_kind",
        "advisory_live",
    }
    visible = {"brain_main", "sma_rule", "auto_ml"}
    chk("private set correct", {n for n, v in got.items() if v} == private)
    chk("visible set correct", {n for n, v in got.items() if not v} == visible)
    ver = dict(
        c.execute(
            text("select username, email_verified_at is not null from users")
        ).all()
    )
    print("email_verified:", ver)
    chk(
        "only google-with-email verified",
        {u for u, v in ver.items() if v} == {"g_email"},
    )
    chk(
        "full_name/mobile null for all",
        c.execute(
            text(
                "select count(*) from users where full_name is not null or mobile is not null"
            )
        ).scalar()
        == 0,
    )
    old = c.execute(
        text(
            "select username,email,is_superuser,auth_provider,google_id,role,plan,hashed_password is not null "
            "from users order by username"
        )
    ).all()
    exp = sorted(
        [
            ("owner1", "owner@example.test", True, "local", None, "owner", "pro", True),
            (
                "member1",
                "member1@example.test",
                False,
                "local",
                None,
                "member",
                "free",
                True,
            ),
            ("member_noemail", None, False, "local", None, "member", "free", True),
            (
                "g_email",
                "g1@example.test",
                False,
                "google",
                "gid-111",
                "member",
                "free",
                False,
            ),
            ("g_noemail", None, False, "google", "gid-222", "member", "free", False),
            (
                "tester1",
                "tester@example.test",
                False,
                "local",
                None,
                "tester",
                "free",
                True,
            ),
        ]
    )
    chk("old user columns unchanged", [tuple(r) for r in old] == exp)
print("VERIFY", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
