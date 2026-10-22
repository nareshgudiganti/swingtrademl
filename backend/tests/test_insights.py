"""oa11 Insights (/beginner/insights): day / week / month figures for practice and real, side by side.

The acceptance rules, each a test here:
- every figure equals a direct SQL query on the same rows (`test_figures_equal_a_direct_sql_query`);
- every benchmark names its definition (`test_every_benchmark_names_its_definition`);
- practice and real are never added together, and real is only for the real-account owner;
- the brain's sealed trial and the testing / hand books never reach the practice figures.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest
from sqlalchemy import text

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Strategy, Trade
from swing_trade_ml.services import insights
from swing_trade_ml.services.brain_observatory import baselines

API_KEY = {"X-API-Key": "test-api-key"}
URL = "/api/v1/beginner/insights"


@pytest.fixture(autouse=True)
def _read_only_db_is_the_test_session(db_session):
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides[get_readonly_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_readonly_db, None)


def _today() -> date:
    return datetime.now(IST).date()


def _weekdays_back(n: int) -> list[date]:
    """The n most recent weekdays up to today that are not before the paper trial start."""
    out, d = [], _today()
    while len(out) < n and d >= settings.PAPER_TRIAL_START_DATE:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def _strategy(db, name: str, stype: str = "ml_swing", mode: str = "paper") -> Strategy:
    s = Strategy(name=name, strategy_type=stype, mode=mode, is_active=True)
    db.add(s)
    db.flush()
    return s


def _inst(db, token: int, sym: str) -> Instrument:
    i = Instrument(instrument_token=token, tradingsymbol=sym, exchange="NSE")
    db.add(i)
    db.flush()
    return i


def _trade(db, strat, inst, mode: str, net: float, charges: float, day: date, win: bool, qty: int = 2):
    when = datetime.combine(day, time(14, 0), tzinfo=IST)
    db.add(
        Trade(
            strategy_id=strat.id if strat else None,
            instrument_id=inst.id,
            symbol=inst.tradingsymbol,
            mode=mode,
            quantity=qty,
            entry_price=100.0,
            exit_price=100.0 + net / qty,
            entry_at=when - timedelta(days=3),
            exit_at=when,
            gross_pnl=net + charges,
            charges=charges,
            net_pnl=net,
            return_pct=net / (100.0 * qty),
            is_win=win,
        )
    )


@pytest.fixture()
def books(db_session):
    """Trades in every book on several recent days, including a late-evening IST exit (UTC next day
    boundary) to prove periods are IST days."""
    days = _weekdays_back(4)
    bot = _strategy(db_session, "oa11_bot")
    brain = _strategy(db_session, "oa11_brain", stype="brain")
    tester = _strategy(db_session, "oa11_tester", stype="tester_paper")
    real = _strategy(db_session, "real_trading", mode="live")
    inst = _inst(db_session, 911_001, "OA11A")
    for i, d in enumerate(days):
        _trade(db_session, bot, inst, "paper", 120.0 + i, 6.5, d, True)
        _trade(db_session, None, inst, "paper", -45.0 - i, 4.25, d, False)
        _trade(db_session, brain, inst, "paper", 9_111.0, 11.0, d, True)  # sealed brain: never shown
        _trade(db_session, tester, inst, "paper", 8_222.0, 12.0, d, True)  # testing book: never shown
        _trade(db_session, real, inst, "live", 3_330.0 + i, 33.0, d, True, qty=5)
        _trade(db_session, real, inst, "paper", 7_444.0, 44.0, d, True)  # not the live real book
    late = datetime.combine(days[0], time(23, 50), tzinfo=IST)
    db_session.add(
        Trade(
            strategy_id=bot.id, instrument_id=inst.id, symbol="OA11A", mode="paper", quantity=1,
            entry_price=200.0, exit_price=210.0, entry_at=late - timedelta(days=2), exit_at=late,
            gross_pnl=12.0, charges=2.0, net_pnl=10.0, return_pct=0.05, is_win=True,
        )
    )  # fmt: skip
    db_session.flush()
    return days


PAPER_SQL = """
SELECT count(*), coalesce(sum(t.net_pnl), 0), coalesce(sum(t.charges), 0),
       count(*) FILTER (WHERE t.is_win), coalesce(sum(t.entry_price * t.quantity), 0)
FROM trades t
WHERE t.mode = 'paper'
  AND (t.exit_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN :lo AND :hi
  AND (t.strategy_id IS NULL OR t.strategy_id NOT IN (
        SELECT id FROM strategies
        WHERE strategy_type IN ('tester_paper', 'brain')
           OR name IN ('real_trading', 'tester_paper', 'TradeMind brain')))
"""
REAL_SQL = """
SELECT count(*), coalesce(sum(t.net_pnl), 0), coalesce(sum(t.charges), 0),
       count(*) FILTER (WHERE t.is_win), coalesce(sum(t.entry_price * t.quantity), 0)
FROM trades t
WHERE t.mode = 'live'
  AND (t.exit_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN :lo AND :hi
  AND t.strategy_id IN (SELECT id FROM strategies WHERE name = 'real_trading')
"""


def _sql(db, query: str, lo: str, hi: str) -> dict:
    n, net, charges, wins, used = db.execute(text(query), {"lo": lo, "hi": hi}).one()
    return {
        "finished": n,
        "net_pnl": float(net),
        "charges": float(charges),
        "wins": n and wins,
        "used": float(used),
    }


@pytest.mark.parametrize("period", ["day", "week", "month"])
def test_figures_equal_a_direct_sql_query(client, db_session, books, period):
    r = client.get(f"{URL}?period={period}", headers=API_KEY)
    assert r.status_code == 200
    body = r.json()
    assert body["rows"], "expected at least one period"
    seen = 0
    for row in body["rows"]:
        for side, query in (("paper", PAPER_SQL), ("real", REAL_SQL)):
            want = _sql(db_session, query, row["from"], row["to"])
            got = row[side]
            assert got["finished"] == want["finished"], (period, row["key"], side)
            assert got["wins"] == want["wins"], (period, row["key"], side)
            assert got["net_pnl"] == pytest.approx(want["net_pnl"], abs=0.01), (period, row["key"], side)
            assert got["charges"] == pytest.approx(want["charges"], abs=0.01), (period, row["key"], side)
            assert got["money_used"] == pytest.approx(want["used"], abs=0.01), (period, row["key"], side)
            if want["used"]:
                assert got["return_pct"] == pytest.approx(round(want["net_pnl"] / want["used"] * 100, 2))
            else:
                assert got["return_pct"] is None
            seen += want["finished"]
    assert seen >= 4 * 3  # the fixture's rows really were counted (2 paper + 1 real per day, 4 days)


def test_sealed_brain_testing_and_hand_books_never_reach_practice(client, db_session, books):
    body = client.get(f"{URL}?period=month", headers=API_KEY).json()
    for marker in ("9111", "8222", "7444"):
        assert marker not in r_text(body), marker


def r_text(body) -> str:
    import json

    return json.dumps(body).replace(".0,", ",")


def test_paper_and_real_are_never_summed(client, db_session, books):
    body = client.get(f"{URL}?period=week", headers=API_KEY).json()
    keys = {"finished", "wins", "net_pnl", "charges", "money_used", "return_pct"}
    for row in body["rows"]:
        assert set(row) == {"key", "label", "from", "to", "paper", "real", "nifty_50", "every_stock"}
        assert set(row["paper"]) == keys and set(row["real"]) == keys
    assert not any(k in body for k in ("total", "combined", "all"))


def test_real_is_only_for_the_real_account_owner(client, db_session, books, monkeypatch):
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "oa11-realowner")
    plain = client.get(f"{URL}?period=month", headers=_as(db_session, "oa11-plainowner", "owner")).json()
    assert plain["real_shown"] is False and plain["real_label"] is None
    assert "real" not in plain["definitions"]
    assert all(row["real"] is None for row in plain["rows"])
    assert "3330" not in r_text(plain) and "3333" not in r_text(plain)
    mine = client.get(f"{URL}?period=month", headers=_as(db_session, "oa11-realowner", "owner")).json()
    assert mine["real_shown"] is True
    assert sum(row["real"]["finished"] for row in mine["rows"]) >= 4


def test_who_may_read(client, db_session):
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=_as(db_session, "oa11-tester", "tester")).status_code == 403
    assert client.get(URL, headers=_as(db_session, "oa11-member", "member")).status_code == 403
    assert client.get(URL, headers=_as(db_session, "oa11-owner", "owner")).status_code == 200
    assert client.get(f"{URL}?period=year", headers=API_KEY).status_code == 422


def test_every_benchmark_names_its_definition(client, db_session):
    body = client.get(URL, headers=API_KEY).json()
    for k in ("nifty_50", "every_stock", "paper", "real"):
        assert body["definitions"][k].strip(), k
    assert "NIFTY 50" in body["definitions"]["nifty_50"]
    assert "every stock the brain looked at" in body["definitions"]["every_stock"].lower()
    assert body["defs"] == "evidence-defs-v1"
    assert "never added together" in body["note"]


def _candles(db, inst, day: date, o: float, c: float):
    db.add(
        Candle(
            instrument_id=inst.id, interval="day", ts=datetime.combine(day, time.min, tzinfo=IST),
            open=o, high=max(o, c) + 1, low=min(o, c) - 1, close=c, volume=1_000,
        )
    )  # fmt: skip


def _bars_sql(db, symbol: str, lo: date, hi: date) -> pd.DataFrame:
    rows = db.execute(
        text(
            """SELECT (c.ts AT TIME ZONE 'Asia/Kolkata')::date AS day, c.open, c.high, c.low, c.close
               FROM candles c JOIN instruments i ON i.id = c.instrument_id
               WHERE i.tradingsymbol = :s AND c.interval = 'day'
                 AND (c.ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN :lo AND :hi ORDER BY c.ts"""
        ),
        {"s": symbol, "lo": lo, "hi": hi},
    ).all()
    return pd.DataFrame([dict(r._mapping) for r in rows], columns=["day", "open", "high", "low", "close"])


def test_benchmarks_equal_the_evidence_defs_buy_and_hold_on_sql_rows(client, db_session):
    days = sorted(_weekdays_back(3))
    nifty = Instrument(
        instrument_token=911_050, tradingsymbol=settings.BENCHMARK_INDEX_SYMBOL, exchange="NSE"
    )
    a, b = _inst(db_session, 911_051, "OA11P"), _inst(db_session, 911_052, "OA11Q")
    db_session.add(nifty)
    db_session.flush()
    for k, d in enumerate(days):
        _candles(db_session, nifty, d, 20_000 + 50 * k, 20_030 + 50 * k)
        _candles(db_session, a, d, 100 + k, 103 + k)
        _candles(db_session, b, d, 50 - k, 49 - k)
    run_id = "oa11-run"
    as_of = datetime.combine(days[0], time(16, 30), tzinfo=IST)
    db_session.add(
        BrainRun(id=run_id, kind="nightly", live=True, status="done", book="paper", as_of=as_of,
                 started_at=as_of, banner_mode="NORMAL")
    )  # fmt: skip
    db_session.flush()
    for sym in ("OA11P", "OA11Q"):
        db_session.add(BrainDecision(run_id=run_id, symbol=sym, kind="idea", word="WAIT", reasons=[]))
    db_session.flush()

    body = client.get(f"{URL}?period=month", headers=API_KEY).json()
    row = next(r for r in body["rows"] if r["from"] <= days[0].isoformat() <= r["to"])
    lo, hi = date.fromisoformat(row["from"]), date.fromisoformat(row["to"])

    idx = _bars_sql(db_session, settings.BENCHMARK_INDEX_SYMBOL, lo, hi)
    want_nifty = baselines.nifty_hold(idx, [idx["day"].iloc[0], idx["day"].iloc[-1]], 40_000.0)
    assert row["nifty_50"]["pct"] == pytest.approx(round(want_nifty["final_net_return"] * 100, 2))

    pcts = []
    for sym in ("OA11P", "OA11Q"):
        df = _bars_sql(db_session, sym, lo, hi)
        pcts.append(
            baselines.nifty_hold(df, [df["day"].iloc[0], df["day"].iloc[-1]], 40_000.0)["final_net_return"]
        )
    assert row["every_stock"]["stocks"] == 2
    assert row["every_stock"]["pct"] == pytest.approx(round(sum(pcts) / 2 * 100, 2))


def test_missing_prices_say_why_never_zero(client, db_session):
    body = client.get(f"{URL}?period=day", headers=API_KEY).json()
    for row in body["rows"]:
        for k in ("nifty_50", "every_stock"):
            if row[k]["pct"] is None:
                assert row[k]["why"], (row["key"], k)


def test_periods_are_cut_at_the_trial_start_and_newest_first():
    start = date(2026, 9, 28)
    months = insights.periods("month", date(2026, 10, 22), start)
    assert [(m["from"], m["to"]) for m in months] == [
        (date(2026, 10, 1), date(2026, 10, 22)),
        (date(2026, 9, 28), date(2026, 9, 30)),
    ]
    weeks = insights.periods("week", date(2026, 10, 22), start)
    assert weeks[0]["from"] == date(2026, 10, 19) and weeks[0]["to"] == date(2026, 10, 22)
    assert weeks[-1]["from"] == date(2026, 9, 28)
    days = insights.periods("day", date(2026, 10, 25), start)  # a Sunday
    assert days[0]["from"] == date(2026, 10, 23) and all(d["from"].weekday() < 5 for d in days)
    assert len(days) == insights.HOW_MANY["day"]
