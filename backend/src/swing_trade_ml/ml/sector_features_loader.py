"""Thin READ-ONLY loader for the sector-feature builder (ml/sector_features.py). SELECT only; no writes.

The connection string comes from the environment variable SECTOR_FEATURES_DSN if set, otherwise the local
development database on port 5433 (the same host/credentials the test suite already uses).
"""

from __future__ import annotations

import os

import pandas as pd

from swing_trade_ml.ml.sector_features import DEFAULT_RANK_UNIVERSE, close_series_from_candles

_LOCAL_DSN = "postgresql://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml"

_SQL = """
select c.ts, c.close from candles c join instruments i on i.id = c.instrument_id
where i.tradingsymbol = %s and i.segment = %s and c.interval = 'day' order by c.ts
"""


def connect_readonly(timeout: int = 15):
    import psycopg

    conn = psycopg.connect(os.environ.get("SECTOR_FEATURES_DSN", _LOCAL_DSN), connect_timeout=timeout)
    conn.execute("SET statement_timeout = 60000")
    conn.execute("SET default_transaction_read_only = on")
    conn.execute("select 1").fetchone()
    return conn


def _load(conn, symbol: str, segment: str) -> pd.Series:
    rows = conn.execute(_SQL, (symbol, segment)).fetchall()
    if not rows:
        return pd.Series(dtype="float64")
    df = pd.DataFrame(rows, columns=["ts", "close"])
    df["close"] = df["close"].astype(float)
    return close_series_from_candles(df)


def load_stock_close(conn, symbol: str) -> pd.Series:
    return _load(conn, symbol, "NSE")


def load_index_closes(conn, universe=DEFAULT_RANK_UNIVERSE) -> tuple[pd.Series, dict[str, pd.Series]]:
    """(NIFTY 50 close, {sector index name: close}) indexed by IST date."""
    nifty = _load(conn, "NIFTY 50", "INDICES")
    return nifty, {u: _load(conn, u, "INDICES") for u in universe}
