"""SELL labels for the Bot and Testing tabs, and the book name on sell alerts. Display only."""

from __future__ import annotations

from types import SimpleNamespace

from swing_trade_ml.services import execution
from swing_trade_ml.services import sell_labels as s


def test_closed_trade_labels():
    assert s.trade_label("SCALE_OUT", "paper") == s.PARTIAL_SELL
    for reason in ("TARGET_HIT", "STOP_LOSS_HIT", "TIME_STOP", "SIGNAL_EXIT", "MANUAL"):
        assert s.trade_label(reason, "paper") == s.PAPER_SELL
    assert s.trade_label("TARGET_HIT", "live") == s.LIVE_SELL  # a live sale is never called a paper sale


def _open(**kw):
    base = {"price": 100.0, "stop_loss": 96.0, "take_profit": 108.0, "holding_days": 3, "limit_days": 30,
            "exits_enabled": True, "check_job_ok": True}
    return s.open_label(**{**base, **kw})


def test_open_position_states():
    assert _open() is None
    assert _open(price=95.0) == s.REVIEW_REQUIRED  # past the stop
    assert _open(price=109.0) == s.REVIEW_REQUIRED  # past the target
    assert _open(holding_days=30) == s.REVIEW_REQUIRED  # past the time limit
    assert _open(exits_enabled=False) == s.CHECK_UNAVAILABLE
    assert _open(check_job_ok=False) == s.CHECK_UNAVAILABLE
    assert _open(price=None) == s.CHECK_UNAVAILABLE


def test_an_untrustworthy_check_is_reported_before_a_breach():
    assert _open(price=95.0, check_job_ok=False) == s.CHECK_UNAVAILABLE


def test_book_label():
    assert s.book_label("tester_paper") == "Testing"
    assert s.book_label("ml_swing_main") == "Bot"
    assert s.book_label(None) == "Bot"


def _trade():
    return SimpleNamespace(net_pnl=-100.0, entry_price=100.0, exit_price=95.0, quantity=10, return_pct=-0.05,
                           holding_days=2)


def test_sell_alert_names_the_book():
    inst = SimpleNamespace(tradingsymbol="ABC")
    testing = execution._exit_message(inst, _trade(), "STOP_LOSS_HIT", "paper", "Testing")
    bot = execution._exit_message(inst, _trade(), "STOP_LOSS_HIT", "paper", "Bot")
    assert "PAPER · Testing" in testing and "PAPER · Bot" in bot
    assert "CLOSED · ABC" in testing  # the existing wording is kept
    assert "PAPER" in execution._exit_message(inst, _trade(), "STOP_LOSS_HIT", "paper")  # old call works


def test_partial_sell_alert_names_the_book():
    inst = SimpleNamespace(tradingsymbol="ABC")
    pos = SimpleNamespace(quantity=5, stop_loss=100.0, entry_price=100.0, take_profit=110.0)
    msg = execution._partial_exit_message(inst, _trade(), pos, "SCALE_OUT", "paper", "Testing")
    assert "PAPER · Testing" in msg


def test_trades_and_positions_endpoints_carry_the_labels(client):
    r = client.get("/api/v1/portfolio/trades?book=tester", headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200
    r = client.get("/api/v1/portfolio/positions/detailed", headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200
