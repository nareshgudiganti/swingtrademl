"""With the plans switch ON and the member on Pro, owner-private strategies are hidden from the member."""

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
from fastapi.testclient import TestClient
from swing_trade_ml.main import app

c = TestClient(app)
r0 = c.post(
    "/api/v1/auth/login",
    json={"username": "member1", "password": "MemberPass-Drill-5530"},
)
h = {"Authorization": "Bearer " + r0.json()["access_token"]}
r = c.get("/api/v1/signals/buy-list", headers=h)
got = (
    sorted(x["strategy_name"] for x in r.json())
    if r.status_code == 200
    else r.status_code
)
print("member (pro) buy-list, plans ON", r.status_code, got)
ok = got == sorted(["brain_main", "sma_rule", "auto_ml"])
print(
    "CHECK",
    "PASS" if ok else "FAIL",
    "plans ON: only member-facing strategies visible to the member",
)
sys.exit(0 if ok else 1)
