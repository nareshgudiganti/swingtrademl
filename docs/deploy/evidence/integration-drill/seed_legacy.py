"""Seed synthetic pre-change data into the legacy drill DB (schema at wlquantity01). Synthetic only."""

import os

from sqlalchemy import create_engine, text
from swing_trade_ml.core.security import hash_password

e = create_engine(os.environ["DATABASE_URL"])
users = [
    (
        "owner1",
        "owner@example.test",
        hash_password("OwnerPass-Drill-7421"),
        True,
        "local",
        None,
        "owner",
        "pro",
    ),
    (
        "member1",
        "member1@example.test",
        hash_password("MemberPass-Drill-5530"),
        False,
        "local",
        None,
        "member",
        "free",
    ),
    (
        "member_noemail",
        None,
        hash_password("NoEmailPass-Drill-1188"),
        False,
        "local",
        None,
        "member",
        "free",
    ),
    ("g_email", "g1@example.test", None, False, "google", "gid-111", "member", "free"),
    ("g_noemail", None, None, False, "google", "gid-222", "member", "free"),
    (
        "tester1",
        "tester@example.test",
        hash_password("TesterPass-Drill-9902"),
        False,
        "local",
        None,
        "tester",
        "free",
    ),
]
# name, type, mode, execution_mode
strategies = [
    ("real_trading", "ml_swing", "live", "advisory"),
    (
        "my_real_book_copy",
        "ml_swing",
        "live",
        "advisory",
    ),  # renamed copy of real_trading
    ("tester_paper", "tester_paper", "paper", "auto"),
    ("brain_main", "brain", "paper", "auto"),
    ("sma_rule", "sma_crossover", "paper", "auto"),
    ("auto_ml", "ml_swing", "paper", "auto"),
    ("unknown_kind", "mystery_type", "paper", "auto"),
    ("advisory_live", "sma_crossover", "live", "advisory"),
]
with e.begin() as c:
    for u, em, h, su, ap, g, r, pl in users:
        c.execute(
            text(
                "insert into users(username,email,hashed_password,is_active,is_superuser,auth_provider,google_id,role,plan) "
                "values(:u,:em,:h,true,:su,:ap,:g,:r,:pl)"
            ),
            dict(u=u, em=em, h=h, su=su, ap=ap, g=g, r=r, pl=pl),
        )
    for i, (n, t, m, x) in enumerate(strategies, start=1):
        c.execute(
            text(
                "insert into strategies(name,strategy_type,params,is_active,mode,execution_mode,allow_pyramiding,symbols) "
                "values(:n,:t,'{}',true,:m,:x,false,'[]')"
            ),
            dict(n=n, t=t, m=m, x=x),
        )
        c.execute(
            text(
                "insert into instruments(instrument_token,tradingsymbol,name,exchange,lot_size,tick_size,is_watchlisted,is_active) "
                "values(:tok,:sym,:sym,'NSE',1,0.05,true,true)"
            ),
            dict(tok=900000 + i, sym=f"DRL{i}"),
        )
    # one fresh BUY signal per strategy on its own instrument
    c.execute(
        text(
            "insert into signals(strategy_id,instrument_id,signal_type,mode,price,confidence,reason,features,was_executed,generated_at) "
            "select s.id, i.id, 'BUY', 'paper', 100.0, 0.7, 'drill', '{}', false, now() "
            "from strategies s join instruments i on i.instrument_token = 900000 + s.id"
        )
    )
    c.execute(
        text(
            "insert into stock_score_history(instrument_id,as_of,score,band,model_version) "
            "select id, date '2026-11-05', 55.0, 'mid', 'swing_v7:abc123' from instruments where instrument_token in (900001, 900002)"
        )
    )
    c.execute(
        text(
            "insert into stock_score_history(instrument_id,as_of,score,band,model_version) "
            "select id, date '2026-11-06', 61.0, 'high', null from instruments where instrument_token = 900001"
        )
    )
    for t in ("users", "strategies", "instruments", "signals", "stock_score_history"):
        print(t, c.execute(text(f"select count(*) from {t}")).scalar())
