import os
from sqlalchemy import create_engine,text
from swing_trade_ml.core.security import hash_password
e=create_engine(os.environ["DATABASE_URL"])
rows=[("owner1","owner@example.test",hash_password("OwnerPass-Drill-7421"),True,"local",None,"member","pro"),
("member1","member1@example.test",hash_password("MemberPass-Drill-5530"),False,"local",None,"member","free"),
("member_noemail",None,hash_password("NoEmailPass-Drill-1188"),False,"local",None,"member","free"),
("g_email","g1@example.test",None,False,"google","gid-111","member","free"),
("g_noemail",None,None,False,"google","gid-222","member","free"),
("tester1","tester@example.test",hash_password("TesterPass-Drill-9902"),False,"local",None,"tester","free")]
with e.begin() as c:
  for u,em,h,su,ap,g,r,pl in rows:
    c.execute(text("insert into users(username,email,hashed_password,is_active,is_superuser,auth_provider,google_id,role,plan) values(:u,:em,:h,true,:su,:ap,:g,:r,:pl)"),dict(u=u,em=em,h=h,su=su,ap=ap,g=g,r=r,pl=pl))
  print(c.execute(text("select count(*) from users")).scalar())
