"""Report numbers on one fixed fixture, frozen as a snapshot (#322 slice 1).

The same four round trips are told to every report path:
  * real_report      from broker fills (first-bought-first-sold matching, charges from the cost model),
  * weekly report    from the paper Trade rows (summarise_book over collect()),
  * /portfolio       performance_stats, strategy_performance_stats, /portfolio/summary, /portfolio/trades,
  * Observatory      evidence.paper, which is performance_stats for the trial window.

`test_every_path_matches_the_snapshot` fails if any displayed number of any path changes; it was written and
green BEFORE the metrics were moved into services/report_metrics.py. Regenerate only on purpose, with
REPORT_METRICS_SNAPSHOT_UPDATE=1, and read the diff: a changed number is an owner decision.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import TradingMode
from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy, Trade
from swing_trade_ml.services import real_report, weekly_paper_report
from swing_trade_ml.services.brain_observatory import evidence
from swing_trade_ml.services.portfolio import performance_stats, strategy_performance_stats

IST = ZoneInfo("Asia/Kolkata")
API_KEY = {"X-API-Key": "test-api-key"}
SNAPSHOT = Path(__file__).parent / "snapshots" / "report_metrics.json"
WINDOW = (date(2026, 11, 2), date(2026, 11, 9))

# symbol, side, quantity, price, IST day (all at 10:30)
FILLS = [
    ("WINA", "BUY", 10, 100.0, date(2026, 11, 2)),
    ("WINA", "SELL", 10, 110.0, date(2026, 11, 5)),
    ("LOSEB", "BUY", 20, 50.0, date(2026, 11, 2)),
    ("LOSEB", "SELL", 20, 45.0, date(2026, 11, 6)),
    ("PARTD", "BUY", 30, 100.0, date(2026, 11, 3)),
    ("PARTD", "SELL", 10, 104.0, date(2026, 11, 4)),
    ("PARTD", "SELL", 20, 98.0, date(2026, 11, 9)),
]


def at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 10, 30, tzinfo=IST)


@pytest.fixture()
def book(db_session, monkeypatch):
    """Fills for real_report and the same round trips as paper Trade rows (numbers taken from real_report)."""
    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", date(2026, 1, 1))
    monkeypatch.setattr(settings, "PAPER_STARTING_CAPITAL", 1_000_000.0)
    db_session.execute(delete(Trade))
    db_session.execute(delete(BrokerFill))
    strategy = Strategy(
        name="ml_swing_main", strategy_type="ml_swing", params={}, mode="paper", is_active=True
    )
    db_session.add(strategy)
    db_session.flush()
    instruments = {}
    for n, symbol in enumerate(sorted({f[0] for f in FILLS})):
        inst = Instrument(instrument_token=993_300 + n, tradingsymbol=symbol, exchange="NSE")
        db_session.add(inst)
        instruments[symbol] = inst
    db_session.flush()
    for n, (symbol, side, qty, price, day) in enumerate(FILLS):
        db_session.add(
            BrokerFill(
                trade_id=f"snap-{n}", symbol=symbol, side=side, quantity=qty, price=price, executed_at=at(day)
            )
        )
    db_session.flush()
    report = real_report.build_report(db_session, None, None, None)
    for c in report["closed"]:
        db_session.add(
            Trade(
                strategy_id=strategy.id,
                instrument_id=instruments[c["symbol"]].id,
                mode=TradingMode.PAPER,
                symbol=c["symbol"],
                quantity=c["quantity"],
                entry_price=c["buy_price"],
                exit_price=c["sell_price"],
                entry_at=c["buy_date"],
                exit_at=c["sell_date"],
                holding_days=c["holding_days"],
                gross_pnl=c["gross_pnl"],
                charges=c["charges"],
                net_pnl=c["net_pnl"],
                return_pct=c["pnl_pct"] / 100,
                exit_reason="TARGET",
                is_win=c["net_pnl"] > 0,
            )
        )
    db_session.flush()
    return {"strategy": strategy, "report": report}


def _weekly(db_session) -> dict:
    books = weekly_paper_report.collect(db_session, *WINDOW)
    return weekly_paper_report.summarise_book(**books["bot"], start=WINDOW[0], end=WINDOW[1])


def _trades_endpoint(client) -> list[dict]:
    rows = client.get("/api/v1/portfolio/trades?mode=paper&all_time=true", headers=API_KEY).json()
    keep = ("symbol", "quantity", "gross_pnl", "charges", "net_pnl", "return_pct", "holding_days", "is_win")
    return sorted(({k: r[k] for k in keep} for r in rows), key=lambda r: (r["symbol"], r["quantity"]))


def _summary_endpoint(client) -> dict:
    return client.get("/api/v1/portfolio/summary?mode=paper&all_time=true", headers=API_KEY).json()


def _without_row_ids(report: dict) -> dict:
    """Database row ids change from run to run; every number and date in the report is kept."""
    return {**report, "fills": [{k: v for k, v in f.items() if k != "id"} for f in report["fills"]]}


def collect_everything(db_session, client, book) -> dict:
    sid = book["strategy"].id
    return {
        "real_report": _without_row_ids(real_report.build_report(db_session, None, None, None)),
        "weekly_bot_book": _weekly(db_session),
        "portfolio_performance_stats": performance_stats(db_session, TradingMode.PAPER, all_time=True),
        "portfolio_strategy_stats": strategy_performance_stats(db_session, sid),
        "portfolio_summary_endpoint": _summary_endpoint(client),
        "portfolio_trades_endpoint": _trades_endpoint(client),
        "observatory_paper": evidence.paper(db_session).data,
    }


def _jsonable(value: dict) -> dict:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def test_every_path_matches_the_snapshot(db_session, client, book):
    now = _jsonable(collect_everything(db_session, client, book))
    if os.environ.get("REPORT_METRICS_SNAPSHOT_UPDATE") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert SNAPSHOT.exists(), (
        "snapshot missing: generate it with REPORT_METRICS_SNAPSHOT_UPDATE=1 before refactoring"
    )
    frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert set(now) == set(frozen)
    for path in sorted(frozen):
        assert now[path] == frozen[path], f"the {path} numbers changed"


def test_the_fixture_has_wins_and_losses_and_a_split_sale(book):
    closed = book["report"]["closed"]
    assert len(closed) == 4  # WINA, LOSEB and PARTD sold in two slices
    assert any(c["net_pnl"] > 0 for c in closed) and any(c["net_pnl"] < 0 for c in closed)
