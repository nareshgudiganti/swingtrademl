"""Sign-in compatibility through the app's TestClient against the upgraded legacy DB (plans switch OFF)."""

import os
import sys

for k, v in dict(
    TRADING_MODE="paper",
    ALLOW_LIVE_TRADING="false",
    ENABLE_SCHEDULER="false",
    TELEGRAM_ENABLED="false",
    ERROR_WATCH_ENABLED="false",
    API_KEY="test-api-key",
    JWT_SECRET_KEY="test-jwt-secret",
    DB_AUTO_MIGRATE="false",
    RATE_LIMIT_ENABLED="false",
).items():
    os.environ[k] = v
os.environ.pop("REQUIRE_EMAIL_VERIFICATION", None)

import swing_trade_ml

print(swing_trade_ml.__file__)
from fastapi.testclient import TestClient
from swing_trade_ml.main import app

c = TestClient(app)
ok = True


def chk(name, cond):
    global ok
    ok &= bool(cond)
    print("CHECK", "PASS" if cond else "FAIL", name)


def login(u, p):
    return c.post("/api/v1/auth/login", json={"username": u, "password": p})


tok = {}
for u, p, role, su in [
    ("owner1", "OwnerPass-Drill-7421", "owner", True),
    ("member1", "MemberPass-Drill-5530", "member", False),
    ("member_noemail", "NoEmailPass-Drill-1188", "member", False),
    ("tester1", "TesterPass-Drill-9902", "tester", False),
    ("member1@example.test", "MemberPass-Drill-5530", "member", False),
]:
    r = login(u, p)
    chk(f"login {u} 200", r.status_code == 200)
    if r.status_code == 200:
        tok[u] = {"Authorization": "Bearer " + r.json()["access_token"]}
        m = c.get("/api/v1/auth/me", headers=tok[u])
        j = m.json()
        print(
            "  me",
            {
                k: v
                for k, v in j.items()
                if k
                in (
                    "username",
                    "email",
                    "is_superuser",
                    "role",
                    "plan",
                    "full_name",
                    "mobile",
                    "email_verified_at",
                )
            },
        )
        chk(
            f"/auth/me {u}",
            m.status_code == 200
            and j.get("role") == role
            and bool(j.get("is_superuser")) == su,
        )
chk("wrong password 401", login("owner1", "bad").status_code == 401)
chk(
    "google users cannot password-login",
    login("g_email", "x").status_code == 401
    and login("g_noemail", "x").status_code == 401,
)
# Behaviour that already exists on main (not changed by this integration): the owner and, while plans are off,
# a tester see the whole app; a plain member is never unrestricted and, on the Free plan, is refused the Pro-only
# buy-list (403). The integration must not change any of that.
names = {}
for u in ("owner1", "tester1", "member1", "member_noemail"):
    r = c.get("/api/v1/signals/buy-list", headers=tok[u])
    names[u] = (
        sorted(x["strategy_name"] for x in r.json())
        if r.status_code == 200
        else r.status_code
    )
    print("buy-list", u, r.status_code, names[u])
all8 = sorted(
    [
        "real_trading",
        "my_real_book_copy",
        "tester_paper",
        "brain_main",
        "sma_rule",
        "auto_ml",
        "unknown_kind",
        "advisory_live",
    ]
)
chk(
    "plans OFF: owner sees every strategy's BUY (unrestricted, unchanged)",
    names["owner1"] == all8,
)
chk("plans OFF: tester sees the whole app (unchanged)", names["tester1"] == all8)
chk(
    "plans OFF: Free member is refused the Pro-only buy-list, 403 (as on main)",
    names["member1"] == 403 and names["member_noemail"] == 403,
)
sys.exit(0 if ok else 1)
