"""The weekly paper report: three sources kept apart, counts checked against the transaction records.

The case that started this: a week with 21 SELL events of which only 20 were reported with a classified
reason, and a BUY count taken from the positions still open. Here the exit reasons must always add up to the
SELL count, and buys come from the order log, so a position opened and closed inside the week still counts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import weekly_paper_report as w

START, END = date(2026, 10, 27), date(2026, 11, 2)
HEADERS = {"X-API-Key": "test-api-key"}


def _order(i, side, day, symbol="AAA", strategy="ml_swing_main"):
    return {
        "id": i,
        "side": side,
        "status": "COMPLETE",
        "on": day,
        "symbol": symbol,
        "strategy": strategy,
        "cap_tier": "large",
        "position_id": i,
        "at": f"{day}T10:00:00+00:00",
    }


def _trade(i, day, reason, net=100.0, strategy="ml_swing_main"):
    return {
        "id": i,
        "position_id": i,
        "at": f"{day}T10:00:00+00:00",
        "symbol": "AAA",
        "strategy": strategy,
        "cap_tier": "large",
        "exit_on": day,
        "exit_reason": reason,
        "gross_pnl": net + 10,
        "charges": 10.0,
        "net_pnl": net,
        "return_pct": 0.02,
        "holding_days": 2,
    }


def test_exit_reasons_add_up_even_when_one_is_missing():
    d = date(2026, 10, 30)
    reasons = ["SCALE_OUT"] * 11 + ["TARGET_HIT"] * 5 + ["STOP_LOSS_HIT"] * 4 + ["SIGNAL_EXIT", None]
    orders = [_order(i, "SELL", d) for i in range(len(reasons))]
    trades = [_trade(i, d, r) for i, r in enumerate(reasons)]
    out = w.summarise_book(orders, trades, [], START, END)
    assert out["sells"]["orders"] == 22 == out["sells"]["trade_rows"]
    assert sum(out["sells"]["exit_reasons"].values()) == 22
    assert out["sells"]["exit_reasons"][w.UNCLASSIFIED] == 1
    assert out["reconciliation"]["exit_reasons_add_up"] and out["reconciliation"]["unclassified_exits"] == 1
    assert out["sells"]["partial"] == 11 and out["sells"]["full"] == 11


def test_a_mismatch_between_sell_orders_and_trade_rows_is_shown_not_hidden():
    d = date(2026, 10, 30)
    out = w.summarise_book(
        [_order(1, "SELL", d), _order(2, "SELL", d)], [_trade(1, d, "TARGET_HIT")], [], START, END
    )
    assert out["reconciliation"]["sell_orders_equal_trade_rows"] is False
    assert [e for e in out["events"] if e["exit_reason"] == "NO_TRADE_ROW"]


def test_buys_come_from_orders_so_a_position_opened_and_closed_in_the_week_counts():
    d = date(2026, 10, 28)
    orders = [_order(1, "BUY", d, "AAA"), _order(2, "BUY", d, "BBB"), _order(3, "SELL", d, "AAA")]
    still_open = {
        "symbol": "BBB",
        "strategy": "s",
        "cap_tier": "large",
        "invested": 1000.0,
        "unrealized_pnl": 20.0,
        "current_price": 1.0,
        "stop_loss": None,
        "take_profit": None,
    }
    out = w.summarise_book(orders, [_trade(3, d, "TARGET_HIT")], [still_open], START, END)
    assert out["buys"]["orders"] == 2 and out["positions"]["open"] == 1  # both were bought, one is still open


def test_orders_outside_the_window_or_not_complete_are_not_counted():
    old = _order(1, "BUY", START - timedelta(days=1))
    rejected = {**_order(2, "BUY", START), "status": "REJECTED"}
    assert w.summarise_book([old, rejected], [], [], START, END)["buys"]["orders"] == 0


def test_realized_and_unrealized_are_never_summed():
    d = date(2026, 10, 29)
    pos = {
        "symbol": "X",
        "strategy": "s",
        "cap_tier": "large",
        "invested": 1000.0,
        "unrealized_pnl": -50.0,
        "current_price": 1.0,
        "stop_loss": None,
        "take_profit": None,
    }
    out = w.summarise_book([], [_trade(1, d, "TARGET_HIT", net=300.0)], [pos], START, END)
    assert out["realized_pnl"]["net"] == 300.0 and out["realized_pnl"]["gross"] == 310.0
    assert out["realized_pnl"]["charges"] == 10.0
    assert out["unrealized_pnl"]["amount"] == -50.0 and out["unrealized_pnl"]["pct_of_invested"] == -5.0
    assert "total" not in out["realized_pnl"] and "total" not in out["unrealized_pnl"]


def test_hand_books_are_not_in_the_report_and_testing_is_its_own_source():
    assert w.source_of("tester_paper") == "testing"
    assert w.source_of("real_trading") is None
    assert w.source_of("ml_swing_main") == "bot"


def _book(db, name, stype="ml_swing"):
    s = Strategy(
        name=name, strategy_type=stype, mode="paper", execution_mode="auto", is_active=False, params={}
    )
    db.add(s)
    db.flush()
    return s


def test_database_report_keeps_bot_and_testing_apart(db_session):
    inst = Instrument(instrument_token=991_001, tradingsymbol="WKRPT", exchange="NSE", is_watchlisted=False)
    db_session.add(inst)
    db_session.flush()
    bot = _book(db_session, "wk_bot")
    testing = _book(db_session, "tester_paper", "tester_paper")
    hand = _book(db_session, "real_trading")
    when = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
    for strat in (bot, testing, hand):
        pos = Position(
            strategy_id=strat.id,
            instrument_id=inst.id,
            mode="paper",
            status="CLOSED",
            quantity=10,
            entry_price=100.0,
            entry_at=when - timedelta(days=2),
        )
        db_session.add(pos)
        db_session.flush()
        for side, price, at in (("BUY", 100.0, when - timedelta(days=2)), ("SELL", 105.0, when)):
            db_session.add(
                Order(
                    strategy_id=strat.id,
                    position_id=pos.id,
                    instrument_id=inst.id,
                    mode="paper",
                    transaction_type=side,
                    quantity=10,
                    status="COMPLETE",
                    average_price=price,
                    placed_at=at,
                )
            )
        db_session.add(
            Trade(
                position_id=pos.id,
                strategy_id=strat.id,
                instrument_id=inst.id,
                mode="paper",
                symbol="WKRPT",
                quantity=10,
                entry_price=100.0,
                exit_price=105.0,
                entry_at=when - timedelta(days=2),
                exit_at=when,
                holding_days=2,
                gross_pnl=50.0,
                charges=5.0,
                net_pnl=45.0,
                return_pct=0.05,
                exit_reason="TARGET_HIT",
                is_win=True,
            )
        )
    db_session.flush()
    start, end = w.window(datetime(2026, 11, 3, 5, 0, tzinfo=UTC))  # Tuesday morning
    assert (start, end) == (date(2026, 10, 27), date(2026, 11, 2))
    books = w.collect(db_session, start, end)
    bot_out = w.summarise_book(**books["bot"], start=start, end=end)
    test_out = w.summarise_book(**books["testing"], start=start, end=end)
    assert bot_out["buys"]["by_strategy"].get("wk_bot") == 1
    assert "tester_paper" not in bot_out["buys"]["by_strategy"]
    assert test_out["buys"]["by_strategy"] == {"tester_paper": 1}
    assert test_out["realized_pnl"]["net"] == 45.0
    assert "real_trading" not in str(bot_out) and "real_trading" not in str(test_out)  # the hand book is out
    assert bot_out["reconciliation"]["sell_orders_equal_trade_rows"]


def test_endpoint_returns_the_three_sources(client):
    r = client.get("/api/v1/research/weekly-report", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert {"h05", "bot", "testing", "benchmark", "jobs_and_data", "window"} <= set(r.json())


def test_message_warns_when_records_do_not_match():
    base = w.summarise_book([], [], [], START, END)
    bad = {**base, "reconciliation": {**base["reconciliation"], "sell_orders_equal_trade_rows": False}}
    report = {
        "window": {"from": "a", "to": "b"},
        "h05": {"active": False},
        "bot": bad,
        "testing": base,
        "jobs_and_data": {"problems": [], "stale_data": []},
    }
    assert "do not match" in w.format_message(report)


def test_weekly_job_has_its_own_id_and_leaves_the_brain_saturday_report_alone():
    import importlib

    from apscheduler.schedulers.background import BackgroundScheduler

    sch = importlib.import_module("swing_trade_ml.workers.scheduler")

    s = BackgroundScheduler(timezone="Asia/Kolkata")
    sch.add_weekly_paper_report_job(s)
    sch.add_brain_jobs(s)
    ids = [j.id for j in s.get_jobs()]
    assert "weekly_paper_report" in ids and "brain_weekly_health" in ids
    weekly = s.get_job("weekly_paper_report").trigger
    assert "day_of_week='sun'" in str(weekly)
    assert "day_of_week='sat'" in str(s.get_job("brain_weekly_health").trigger)
