#!/usr/bin/env bash
# READ-ONLY check (hardened 2026-11-05): compare FRESH Kite daily bars with our STORED candles for
#   HINDUNILVR 2025-11-25..2025-12-12   (Dec-2025 Kwality Wall's demerger)
#   BAJAJELEC  2023-09-08..2023-09-20
# NOT run by anyone yet. For the owner to run on the production worker. See FETCH-INSTRUCTIONS.md.
#
# Why this cannot write anything:
#   - It does not use the app's Kite wrapper, so nothing can log in, renew or deactivate a session.
#   - The database transaction is opened READ ONLY (the database itself refuses any write), only SELECT is used,
#     and the transaction is rolled back and closed at the end.
#   - The one Kite call is a plain historical-bars request using the newest stored session; nothing is retried.
#   - No access token, key, secret, host name or personal path is ever printed. Errors print only the
#     exception class and a short sanitised message, and the script exits non-zero.
# If anything about the session is wrong: STOP. Do not log in from anywhere else.
#
# Container name is from docker-compose.yml (stml-worker); confirm with `docker ps`.
docker exec -i stml-worker python - <<'PY'
import sys
from datetime import datetime, UTC
from statistics import median
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
JOBS = [
    ("HINDUNILVR", (2025, 11, 25), (2025, 12, 12)),
    ("BAJAJELEC", (2023, 9, 8), (2023, 9, 20)),
]
_secrets = []


def clean(msg):
    msg = str(msg)
    for s in _secrets:
        if s:
            msg = msg.replace(s, "***")
    if "://" in msg or "host" in msg.lower() or "\\" in msg or "/" in msg:
        return "(message withheld: may contain an address)"
    return msg[:120]


def verdict(ratios):
    if not ratios:
        return "no overlapping dates - cannot tell"
    m = median(ratios)
    spread = max(ratios) - min(ratios)
    if abs(m - 1.0) <= 0.001 and spread <= 0.002:
        return "ratio ~1.000 on every date = SAME SCALE as stored (not adjusted)"
    if spread <= 0.003:
        return "ratio is a constant %.4f on every date = history looks ADJUSTED by that factor" % m
    return "ratios differ by date (%.4f to %.4f) = mixed; send this output back, do not guess" % (min(ratios), max(ratios))


conn = None
engine = None
code = 1
try:
    from sqlalchemy import create_engine, text
    from kiteconnect import KiteConnect
    from swing_trade_ml.core.config import settings

    _secrets.extend([settings.DATABASE_URL, settings.KITE_API_KEY])
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=False)
    conn = engine.connect().execution_options(postgresql_readonly=True)
    conn.execute(text("SET TRANSACTION READ ONLY"))
    ro = conn.execute(text("SHOW transaction_read_only")).scalar()
    if str(ro).lower() != "on":
        raise RuntimeError("database transaction is not read only - aborting")

    row = conn.execute(
        text(
            "SELECT access_token, expires_at FROM broker_sessions "
            "WHERE is_active IS TRUE ORDER BY created_at DESC LIMIT 1"
        )
    ).first()
    if row is None:
        print("STOP: no active Kite session is stored. Do NOT log in from anywhere else.")
        raise SystemExit(2)
    _secrets.append(row[0])
    if row[1] is not None and row[1] < datetime.now(UTC):
        print("STOP: the stored Kite session has expired. Do NOT log in from anywhere else.")
        raise SystemExit(2)

    kite = KiteConnect(api_key=settings.KITE_API_KEY)
    kite.set_access_token(row[0])

    for sym, d0, d1 in JOBS:
        inst = conn.execute(
            text("SELECT id, instrument_token FROM instruments WHERE tradingsymbol = :s AND exchange = 'NSE'"),
            {"s": sym},
        ).all()
        if len(inst) != 1:
            raise RuntimeError("expected exactly one instrument row for %s, found %d" % (sym, len(inst)))
        inst_id, inst_tok = inst[0][0], inst[0][1]

        lo = datetime(*d0, tzinfo=IST)
        hi = datetime(*d1, 23, 59, tzinfo=IST)
        bars = kite.historical_data(
            instrument_token=inst_tok, from_date=lo, to_date=hi, interval="day", continuous=False, oi=False
        )
        stored = {
            r[0]: r[1:]
            for r in conn.execute(
                text(
                    "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date AS d, open, high, low, close, volume "
                    "FROM candles WHERE instrument_id = :i AND interval = 'day' "
                    "AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN :a AND :b ORDER BY ts"
                ),
                {"i": inst_id, "a": lo.date(), "b": hi.date()},
            ).all()
        }

        print("== %s fresh Kite daily bars %s .. %s ==" % (sym, lo.date(), hi.date()))
        print("date,open,high,low,close,volume")
        fetched = {}
        for b in bars:
            dt = b["date"]
            day = dt.astimezone(IST).date() if getattr(dt, "tzinfo", None) else dt.date()
            fetched[day] = b["close"]
            print(day, b["open"], b["high"], b["low"], b["close"], b["volume"], sep=",")

        print("-- %s comparison with stored candles (same read-only transaction) --" % sym)
        print("date,stored_close,fetched_close,ratio_fetched_over_stored")
        ratios = []
        for day in sorted(set(fetched) | set(stored)):
            sc = stored[day][3] if day in stored else None
            fc = fetched.get(day)
            ratio = (fc / sc) if (sc and fc) else None
            if ratio is not None:
                ratios.append(ratio)
            print(day, sc, fc, "%.4f" % ratio if ratio is not None else "n/a", sep=",")
        print("VERDICT HINT %s: %s" % (sym, verdict(ratios)))
        print()
    code = 0
except SystemExit as stop:
    code = stop.code if isinstance(stop.code, int) and stop.code else 1
except BaseException as exc:
    print("ERROR: %s: %s" % (type(exc).__name__, clean(exc)))
    print("STOP. Do NOT log in to Kite from anywhere else. Send this message back.")
    code = 1
finally:
    try:
        if conn is not None:
            conn.rollback()
            conn.close()
    except Exception:
        pass
    try:
        if engine is not None:
            engine.dispose()
    except Exception:
        pass
sys.exit(code)
PY
