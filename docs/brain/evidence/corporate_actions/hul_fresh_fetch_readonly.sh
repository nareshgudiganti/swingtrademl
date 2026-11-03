#!/usr/bin/env bash
# READ-ONLY check: does Zerodha Kite's CURRENT history for HINDUNILVR show the Dec-2025 Kwality Wall's demerger adjustment?
# NOT run by anyone yet. For the owner to run on the prod droplet (or to authorise Claude to run). Prints only; writes nothing.
#
# What it does: reads the newest active Kite session from the worker container, calls the RAW Kite client once for
# 2025-11-25..2025-12-12 daily bars (bypassing reauth_and_retry so it can never trigger an auto-login), prints them, and rolls back.
# If there is no active session or the token is rejected: STOP. Do not log in from anywhere else.
#
# How to read the output (our stored values, local and prod: 2025-12-04 close 2462.2; 2025-12-05 open 2422.0, low 2286.7, close 2338.6):
#   Kite 2025-12-04 close ~2462.2  -> Kite history is UNADJUSTED for the demerger (matches ours).
#   Kite 2025-12-04 close ~2415    -> Kite history IS adjusted (2462.2 x 0.9809 COA = 2415.2); our stored pre-ex bars are stale.
#   Also check 2025-11-25..2025-12-03: if adjusted, every close is ~0.9809 x ours. Bars from 2025-12-05 onward should match either way.
#   Factor = Kite 2025-12-04 close / 2462.2; compare with 0.9809 (COA 98.09% HUL, reported by news; the filing is not yet read).
#
# Container name is from docker-compose.yml (stml-worker); confirm with `docker ps`.
docker exec -i stml-worker python - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.brokers.kite import kite_broker

IST = ZoneInfo("Asia/Kolkata")
with session_scope() as db:
    inst = db.execute(
        select(Instrument).where(Instrument.tradingsymbol == "HINDUNILVR", Instrument.exchange == "NSE")
    ).scalar_one()
    if not kite_broker.load_session(db):  # reads the newest active BrokerSession
        raise SystemExit("no active Kite session - do NOT log in; stop")
    bars = kite_broker._kite.historical_data(  # raw client: no auto-login side effect
        instrument_token=inst.instrument_token,
        from_date=datetime(2025, 11, 25, tzinfo=IST),
        to_date=datetime(2025, 12, 12, 23, 59, tzinfo=IST),
        interval="day",
        continuous=False,
        oi=False,
    )
    for b in bars:
        print(b["date"], b["open"], b["high"], b["low"], b["close"], b["volume"])
    db.rollback()  # nothing is committed
PY
