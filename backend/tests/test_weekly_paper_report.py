"""The weekly paper report: three sources kept apart, counts checked against the transaction records.

The case that started this: a week with 21 SELL events of which only 20 were reported with a classified
reason, and a BUY count taken from the positions still open. Here the exit reasons must always add up to the
SELL count, and buys come from the order log, so a position opened and closed inside the week still counts.
"""

from __future__ import annotations

import json
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


def test_weekly_windows_touch_with_no_gap_and_no_overlap_even_across_a_holiday():
    sunday = datetime(2026, 11, 8, 4, 0, tzinfo=UTC)  # Sunday 09:30 IST, after a Tuesday-holiday-free week
    this_start, this_end = w.window(sunday)
    _, prev_end = w.window(sunday - timedelta(days=7))
    assert (this_start, this_end) == (date(2026, 11, 1), date(2026, 11, 7))
    assert prev_end + timedelta(days=1) == this_start
    assert (this_end - this_start).days == 6
    # Diwali Balipratipada, Tuesday 10 Nov 2026, is a market holiday: it is still inside one window.
    _, end = w.window(datetime(2026, 11, 15, 4, 0, tzinfo=UTC))
    assert date(2026, 11, 10) <= end


def test_an_order_just_after_midnight_india_time_belongs_to_the_india_day():
    # 2026-11-02 18:40 UTC is 00:10 IST on 3 Nov: outside a window that ends 2 Nov, inside the next one.
    late = datetime(2026, 11, 2, 18, 40, tzinfo=UTC)
    assert w._ist_date(late) == date(2026, 11, 3)
    first = datetime(2026, 10, 26, 18, 40, tzinfo=UTC)  # 00:10 IST on 27 Oct: the first minute of the window
    assert w._ist_date(first) == START


def _h05_world(db):
    from swing_trade_ml.db.models.lanes import H05GroupDay, H05Run, H05Signal

    run = H05Run(
        run_no=1, protocol_code="t", protocol_hash="x" * 64, status="active", start_day=date(2026, 11, 2),
        end_day=date(2027, 1, 28), models={}, universe={}, universe_hash="u" * 64,
    )
    db.add(run)
    db.flush()
    for group in ("large", "mid", "small"):
        for day in (date(2026, 11, 2), date(2026, 11, 3)):
            db.add(H05GroupDay(run_id=run.id, signal_day=day, group=group, universe_n=10, scored_n=9,
                               not_scored_n=1, selected_n=5, shortfall=0))
        db.add(H05Signal(run_id=run.id, signal_day=date(2026, 11, 2), symbol=f"{group}A", group=group,
                         status="scored", selected=True, label_status="pending"))
    db.flush()
    return run


def test_h05_is_its_own_section_and_says_when_outcomes_are_not_there_yet(db_session):
    _h05_world(db_session)
    out = w.h05_section(db_session, date(2026, 11, 2), date(2026, 11, 3))
    assert out["active"] and set(out["groups"]) == {"large", "mid", "small"}
    for g in out["groups"].values():
        assert g["signal_days_recorded"] == 2 and g["picks_made"] == 10
        assert g["picks_matured"] == 0 and "no outcomes yet" in g["outcomes_status"]
    assert out["sessions_not_recorded"] == []  # both sessions of the window were recorded


def test_a_matured_pick_is_counted_once_and_a_missing_hit_value_is_not_a_zero(db_session):
    from swing_trade_ml.db.models.lanes import H05Signal

    run = _h05_world(db_session)
    db_session.add(H05Signal(run_id=run.id, signal_day=date(2026, 11, 2), symbol="LARGEHIT", group="large",
                             status="scored", selected=True, label_status="matured", label_hit=1,
                             label_day5=date(2026, 11, 9)))
    db_session.add(H05Signal(run_id=run.id, signal_day=date(2026, 11, 2), symbol="LARGENODATA", group="large",
                             status="scored", selected=True, label_status="unavailable", label_hit=None,
                             label_day5=date(2026, 11, 9)))
    db_session.flush()
    large = w.h05_section(db_session, date(2026, 11, 9), date(2026, 11, 15))["groups"]["large"]
    assert large["picks_matured"] == 1 and large["picks_hit_plus_2pct"] == 1
    assert "1 of 3 picks matured" in large["outcomes_status"]


def test_an_empty_week_says_so_instead_of_showing_zeros_as_results():
    out = w.summarise_book([], [], [], START, END)
    assert out["data_status"] == "no buys or sells this week"
    assert out["realized_pnl"]["net"] == 0.0 and out["avg_sell_return_pct"] is None


# --- the brain's reserved paper slot is sealed and never part of the Bot's numbers -----------------


def _seed_week(db, day, with_brain=True):
    inst = Instrument(instrument_token=991_002, tradingsymbol="BRAINSYM", exchange="NSE", is_watchlisted=False)
    db.add(inst)
    db.flush()
    strats = [(_book(db, "wk_bot"), 45.0)]
    if with_brain:
        strats.append((_book(db, "TradeMind brain", "brain"), 777.0))
    when = datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=10)
    for strat, net in strats:
        pos = Position(
            strategy_id=strat.id, instrument_id=inst.id, mode="paper", status="CLOSED", quantity=10,
            entry_price=100.0, entry_at=when - timedelta(days=2),
        )  # fmt: skip
        db.add(pos)
        db.flush()
        for side, at in (("BUY", when - timedelta(days=2)), ("SELL", when)):
            db.add(
                Order(
                    strategy_id=strat.id, position_id=pos.id, instrument_id=inst.id, mode="paper",
                    transaction_type=side, quantity=10, status="COMPLETE", average_price=105.0, placed_at=at,
                )
            )  # fmt: skip
        db.add(
            Trade(
                position_id=pos.id, strategy_id=strat.id, instrument_id=inst.id, mode="paper",
                symbol="BRAINSYM", quantity=10, entry_price=100.0, exit_price=107.77,
                entry_at=when - timedelta(days=2), exit_at=when, holding_days=2, gross_pnl=net + 5,
                charges=5.0, net_pnl=net, return_pct=0.0777 if net == 777.0 else 0.05,
                exit_reason="TARGET_HIT", is_win=True,
            )
        )  # fmt: skip
        db.add(
            Position(
                strategy_id=strat.id, instrument_id=inst.id, mode="paper", status="OPEN", quantity=5,
                entry_price=100.0, current_price=102.33 if net == 777.0 else 101.5, entry_at=when,
            )
        )  # fmt: skip
    db.flush()


def _window():
    return w.window(datetime(2026, 11, 3, 5, 0, tzinfo=UTC))


def test_brain_paper_trade_never_reaches_the_bot_numbers_or_the_message(db_session):
    from test_trial_seal_leaks import _leaks

    _seed_week(db_session, date(2026, 10, 30))
    rep = w.build_report(db_session, datetime(2026, 11, 3, 5, 0, tzinfo=UTC))
    bot = rep["bot"]
    assert bot["realized_pnl"]["net"] == 45.0 and bot["buys"]["orders"] == 1
    assert set(bot["buys"]["by_strategy"]) == {"wk_bot"}
    assert set(bot["sells"]["by_strategy"]) == {"wk_bot"}
    assert bot["positions"]["open"] == 1
    assert all(e["strategy"] == "wk_bot" for e in bot["events"])
    brain = rep["brain_paper"]
    assert brain["sealed"] is True and brain["text"] == "sealed during the trial"
    assert (brain["buys"], brain["sell_orders"], brain["open_positions"]) == (1, 1, 1)
    assert brain["before_trial"] is None
    text = json.dumps(rep, default=str)
    brain_text = json.dumps(brain, default=str)
    for bad in ("BRAINSYM", "TradeMind brain", "777", "102.33", "TARGET_HIT", "0.0777"):
        assert bad not in brain_text
    assert "777" not in text and "TradeMind brain" not in text and "102.33" not in text
    assert _leaks(text) == []
    msg = w.format_message(rep)
    assert "777" not in msg and "brain" not in msg.lower()
    assert _leaks(msg) == []


def test_bot_and_testing_unchanged_without_a_brain_strategy(db_session):
    _seed_week(db_session, date(2026, 10, 30), with_brain=False)
    a = w.build_report(db_session, datetime(2026, 11, 3, 5, 0, tzinfo=UTC))
    assert a["bot"]["realized_pnl"]["net"] == 45.0
    assert a["brain_paper"]["buys"] == a["brain_paper"]["sell_orders"] == a["brain_paper"]["open_positions"] == 0
    assert a["testing"]["buys"]["orders"] == 0


def test_brain_rows_before_the_trial_start_keep_their_full_book_apart_from_the_bot(db_session):
    _seed_week(db_session, date(2026, 10, 9))
    start, end = date(2026, 10, 5), date(2026, 10, 11)
    books = w.collect(db_session, start, end)
    sec = w.brain_paper_section(books["brain_paper"], start, end)
    assert sec["before_trial"]["realized_pnl"]["net"] == 777.0
    assert sec["buys"] == 0 and sec["sell_orders"] == 0
    assert w.summarise_book(**books["bot"], start=start, end=end)["realized_pnl"]["net"] == 45.0


def test_seal_off_shows_the_brain_book_in_full_but_still_apart(db_session, monkeypatch):
    from swing_trade_ml.services import trial_seal

    monkeypatch.setattr(trial_seal, "SEALED", False)
    _seed_week(db_session, date(2026, 10, 30))
    rep = w.build_report(db_session, datetime(2026, 11, 3, 5, 0, tzinfo=UTC))
    assert rep["brain_paper"]["sealed"] is False
    assert rep["brain_paper"]["before_trial"]["realized_pnl"]["net"] == 777.0
    assert rep["bot"]["realized_pnl"]["net"] == 45.0


def test_is_brain_strategy_matches_by_name_and_type():
    assert w.is_brain_strategy("TradeMind brain") and w.is_brain_strategy("x", "brain")
    assert not w.is_brain_strategy("ml_swing_main", "ml_swing")
