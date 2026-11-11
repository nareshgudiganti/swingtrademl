import os
for k,v in dict(TRADING_MODE="paper",ALLOW_LIVE_TRADING="false",ENABLE_SCHEDULER="false",TELEGRAM_ENABLED="false",ERROR_WATCH_ENABLED="false",API_KEY="test-api-key",JWT_SECRET_KEY="test-jwt-secret",DB_AUTO_MIGRATE="false",RATE_LIMIT_ENABLED="false").items(): os.environ[k]=v
import swing_trade_ml; print(swing_trade_ml.__file__)
from fastapi.testclient import TestClient
from swing_trade_ml.main import app
c=TestClient(app)
def login(u,p): return c.post("/api/v1/auth/login",json={"username":u,"password":p})
for u,p in [("owner1","OwnerPass-Drill-7421"),("member1","MemberPass-Drill-5530"),("member_noemail","NoEmailPass-Drill-1188"),("tester1","TesterPass-Drill-9902"),("member1@example.test","MemberPass-Drill-5530")]:
    r=login(u,p); print("login",u,r.status_code)
    if r.status_code==200:
        m=c.get("/api/v1/auth/me",headers={"Authorization":"Bearer "+r.json()["access_token"]})
        print("  me",m.status_code,{k:v for k,v in m.json().items() if k in("username","email","is_superuser","role","plan","full_name","mobile","email_verified_at")})
print("wrong pw owner1",login("owner1","bad").status_code)
print("google user pw login",login("g_email","x").status_code)
for i in range(6): print("tester wrong",i+1,login("tester1","bad").status_code)
print("tester right pw while locked",login("tester1","TesterPass-Drill-9902").status_code)
