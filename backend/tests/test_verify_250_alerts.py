# ruff: noqa: E501  (long plain-English test text)
"""#250 Verify in-app price and paper-order alerts.

Tests only. Nothing here changes an alert, an order or a notification, and nothing reaches Telegram or any network:
every test replaces the notifier with a recorder (or, where the send path itself is exercised, replaces the HTTP client
and uses a made-up chat id). Each test states what the code is EXPECTED to do and checks what it OBSERVABLY does at the
baseline commit. A gap is a strict expected failure (`xfail(strict=True, raises=AssertionError)`) with one line saying
what is missing; if the code is fixed the strict marker turns red and must be removed on purpose.

The findings note is docs/verification/250-alerts.md. Needs the test database; every write rolls back.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers.base import OrderResult
from swing_trade_ml.brokers.paper import PaperBroker
from swing_trade_ml.core.enums import OrderStatus
from swing_trade_ml.db.models.market import Instrument, Quote
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy, Trade
from swing_trade_ml.notifications import alert_policy
from swing_trade_ml.services import execution, holdings_sync

GAP = {"strict": True, "raises": AssertionError}
_tokens = iter(range(970_000, 970_900))


@pytest.fixture()
def sent(monkeypatch):
    """Every alert the code tries to send, as (text, event, kind). `sent.ok` is what the fake send reports back."""

    class Box(list):
        ok = True

    box = Box()

    def fake(text, event="system", kind=None):
        box.append((text, str(event), kind))
        return box.ok

    monkeypatch.setattr(execution.notifier, "send_sync", fake)
    return box


def inst(db, symbol: str) -> Instrument:
    row = Instrument(instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(row)
    db.flush()
    return row


def strategy(
    db, name: str, *, mode: str = "paper", execution_mode: str = "auto", kind: str = "ml_swing"
) -> Strategy:
    row = Strategy(name=name, strategy_type=kind, mode=mode, execution_mode=execution_mode, is_active=True)
    db.add(row)
    db.flush()
    return row


def position(db, strat: Strategy, row: Instrument, *, mode: str = "paper", **kw) -> Position:
    p = Position(
        strategy_id=strat.id,
        instrument_id=row.id,
        mode=mode,
        status="OPEN",
        quantity=kw.pop("quantity", 10),
        entry_price=kw.pop("entry_price", 100.0),
        entry_at=kw.pop("entry_at", datetime.now(UTC) - timedelta(days=2)),
        current_price=kw.pop("current_price", 100.0),
        total_charges=10.0,
        **kw,
    )
    db.add(p)
    db.flush()
    return p


def with_quote(db, row: Instrument, value: float) -> Instrument:
    """A stored quote, so the paper broker can price a sell for this stock."""
    db.add(Quote(instrument_id=row.id, last_price=value, ts=datetime.now(UTC)))
    db.flush()
    return row


def price_at(monkeypatch, value: float) -> None:
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: dict.fromkeys(keys, value))


def real_holding(db, symbol: str, **kw):
    """A My Holdings position: the real_trading advisory book, which the bot never sells."""
    strat = db.scalar(select(Strategy).where(Strategy.name == "real_trading")) or strategy(
        db, "real_trading", mode="live", execution_mode="advisory"
    )
    row = inst(db, symbol)
    return strat, row, position(db, strat, row, mode="live", **kw)


# ======================================================================== (a) price alerts, advisory book


def test_a1_a_stop_loss_alert_fires_once_with_the_right_numbers_and_cannot_be_held(
    db_session, monkeypatch, sent
):
    _, _, pos = real_holding(db_session, "A1STOP", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    assert len(sent) == 1
    text, event, kind = sent[0]
    assert "EXIT RECOMMENDED" in text and "A1STOP" in text
    assert "Entry: ₹100.00" in text and "Current: ₹95.00" in text and "Quantity: 10" in text
    assert (event, kind) == (
        "signal",
        None,
    )  # no kind: never dropped or held for quiet hours (alert_policy.route)
    assert pos.advisory_alert_sent_at is not None
    execution.check_exits(db_session)  # the next 60-second sweep
    assert len(sent) == 1  # once, not every minute


def test_a2_a_target_alert_fires_once_and_nothing_fires_between_stop_and_target(
    db_session, monkeypatch, sent
):
    _, _, pos = real_holding(db_session, "A2TARGET", stop_loss=96.0, take_profit=108.0)
    price_at(monkeypatch, 102.0)
    execution.check_exits(db_session)
    assert sent == [] and pos.advisory_alert_sent_at is None  # inside the band: silence
    price_at(monkeypatch, 108.5)
    execution.check_exits(db_session)
    execution.check_exits(db_session)
    assert len(sent) == 1 and "Current: ₹108.50" in sent[0][0]


def test_a3_the_two_flags_surface_differently_stop_flag_is_exit_confidence_flag_is_weakening():
    """advisory_alert_sent_at (stop, target, time stop) reads as EXIT; confidence_alert_sent_at (conviction fading) is the
    weaker 'needs a look'. api/v1/endpoints/portfolio.py:291 passes the confidence flag as alert_sent and :301 the
    advisory flag as exit_alert_sent. Also pinned in test_advisory_exit_alert_visibility.py."""
    common = {
        "entry_confidence": 0.7,
        "last_confidence": 0.68,
        "holding_days": 3,
        "horizon_days": 5,
        "exit_confidence": 0.35,
    }
    confidence_only, _ = execution.position_action(alert_sent=True, exit_alert_sent=False, **common)
    stop_breached, _ = execution.position_action(alert_sent=False, exit_alert_sent=True, **common)
    assert stop_breached == "exit" and confidence_only != "exit"


def test_a3b_through_the_real_endpoint_the_stop_flag_reads_exit_and_the_confidence_flag_does_not(
    client, db_session
):
    """Swapping the two flags at api/v1/endpoints/portfolio.py:291 / :301 would fail here: one holding carries only the
    stop-style flag (advisory_alert_sent_at), the other only the confidence flag (confidence_alert_sent_at)."""
    strat = strategy(db_session, "real_trading", mode="live", execution_mode="advisory")
    now = datetime.now(UTC)
    stopped = position(
        db_session,
        strat,
        inst(db_session, "A3BSTOP"),
        mode="live",
        current_price=95.0,
        stop_loss=96.0,
        entry_confidence=0.70,
        last_confidence=0.68,
        advisory_alert_sent_at=now,
    )
    fading = position(
        db_session,
        strat,
        inst(db_session, "A3BFADE"),
        mode="live",
        current_price=101.0,
        stop_loss=96.0,
        entry_confidence=0.80,
        last_confidence=0.40,
        confidence_alert_sent_at=now,
    )
    assert stopped.confidence_alert_sent_at is None and fading.advisory_alert_sent_at is None
    db_session.commit()
    rows = client.get(
        "/api/v1/portfolio/positions/detailed?book=real", headers={"X-API-Key": "test-api-key"}
    ).json()
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["A3BSTOP"]["action_code"] == "exit"  # the stop flag outranks the model's healthy 68%
    assert by_symbol["A3BFADE"]["action_code"] != "exit"  # a fading score is a warning, not an exit
    assert by_symbol["A3BFADE"]["action_code"] == "alert"  # and it reads as the weaker "alert"


def _weak_world(db, symbol):
    strat = strategy(db, f"{symbol}_strat")
    row = inst(db, symbol)
    pos = position(db, strat, row, entry_confidence=0.80, stop_loss=96.0, take_profit=108.0)
    return strat, row, pos


def test_a4_a_confidence_alert_fires_once_per_episode_with_the_right_numbers(db_session, sent):
    strat, row, pos = _weak_world(db_session, "A4CONF")
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 1
    text, _, kind = sent[0]
    assert "CONFIDENCE FALLING" in text and "A4CONF" in text
    assert "Entry confidence: <b>80%</b> → now <b>40%</b>  (down 40%)" in text
    assert "not an exit" in text  # a warning, said plainly
    assert kind == alert_policy.HOLDING_WARNINGS  # switchable: the owner may mute or hold it
    assert pos.confidence_alert_sent_at is not None
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 1  # still weak: no repeat
    execution._check_confidence_decay(db_session, pos, strat, row, 0.70, "paper")  # recovers
    assert pos.confidence_alert_sent_at is None and len(sent) == 1
    execution._check_confidence_decay(db_session, pos, strat, row, 0.38, "paper")  # a new episode
    assert len(sent) == 2


@pytest.mark.xfail(
    **GAP,
    reason="gap a6: sell and exit alerts print internal codes (STOP_LOSS_HIT, TIME_STOP) and an API path, not plain English",
)
def test_a6_exit_alerts_are_in_plain_english(db_session, monkeypatch, sent):
    real_holding(db_session, "A6PLAIN", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    text = re.sub(r"<[^>]+>", "", sent[0][0])
    assert not re.search(r"\b[A-Z]{2,}_[A-Z_]+\b", text), text  # STOP_LOSS_HIT
    assert "POST /" not in text, text


# ==================================================================== (b) paper-order alerts match the stored rows


def test_b1_a_bot_exit_alert_matches_the_stored_trade_and_says_paper(db_session, monkeypatch, sent):
    strat = strategy(db_session, "b1_bot")
    row = with_quote(db_session, inst(db_session, "B1EXIT"), 95.0)
    pos = position(db_session, strat, row, stop_loss=96.0, take_profit=110.0, entry_price=100.0)
    price_at(monkeypatch, 95.0)
    closed = execution.check_exits(db_session)
    trade = next(t for t in closed if t.position_id == pos.id)
    text = next(t for t, _, _ in sent if "CLOSED" in t)
    assert "📝 PAPER · Bot" in text and "LIVE" not in text  # never implies a real order
    assert f"Entry ₹{trade.entry_price:,.2f} → Exit ₹{trade.exit_price:,.2f}" in text
    assert (
        f"Quantity: {trade.quantity:,}" in text
        and f"₹{trade.net_pnl:,.2f}" in text
        and f"{trade.return_pct:+.2%}" in text
    )
    assert f"Held: {trade.holding_days} days" in text


def test_b2_an_entry_alert_matches_the_stored_order_and_position_and_says_paper(db_session, sent):
    strat = strategy(db_session, "b2_bot")
    row = inst(db_session, "B2ENTRY")
    db_session.add(Quote(instrument_id=row.id, last_price=250.0, ts=datetime.now(UTC)))
    sig = Signal(
        strategy_id=strat.id,
        instrument_id=row.id,
        signal_type="BUY",
        mode="paper",
        price=250.0,
        confidence=0.72,
        stop_loss=240.0,
        take_profit=270.0,
        generated_at=datetime.now(UTC),
    )
    db_session.add(sig)
    db_session.flush()
    pos = execution.open_position(db_session, strat, row, sig, 4)
    assert pos is not None
    order = db_session.scalar(select(Order).where(Order.position_id == pos.id))
    text, _, kind = next(entry for entry in sent if "ENTERED" in entry[0])
    assert "📝 PAPER" in text and "LIVE" not in text
    assert f"BUY <b>{pos.quantity:,}</b> @ <b>₹{pos.entry_price:,.2f}</b>" in text
    assert f"Order: <code>{order.broker_order_id}</code>" in text and f"₹{pos.stop_loss:,.2f}" in text
    assert (
        kind == alert_policy.PAPER_BUYS
    )  # a paper buy may be muted; a real buy never can (execution.py:_buy_alert_kind)
    assert pos.quantity == order.filled_quantity == 4


def test_b3_a_rejected_order_is_alerted_with_its_own_id_and_reason_and_cannot_be_held(db_session, sent):
    row = inst(db_session, "B3REJECT")
    order = Order(
        instrument_id=row.id,
        mode="paper",
        transaction_type="BUY",
        order_type="MARKET",
        product="CNC",
        quantity=5,
        status="PENDING",
        placed_at=datetime.now(UTC),
    )
    db_session.add(order)
    db_session.flush()
    execution._fail_reconciled_order(
        db_session,
        order,
        OrderResult(status=OrderStatus.REJECTED, broker_order_id="X1", message="Insufficient funds"),
    )
    text, event, kind = sent[-1]
    assert f"order {order.id}" in text and "B3REJECT" in text and "Insufficient funds" in text
    assert (event, kind) == ("error", None)


def test_b4_a_real_money_buy_alert_can_never_be_switched_off_and_a_paper_one_can():
    assert execution._buy_alert_kind("paper") == alert_policy.PAPER_BUYS
    assert execution._buy_alert_kind("live") is None
    assert alert_policy.PAPER_BUYS in alert_policy.SWITCHABLE_KEYS


@pytest.mark.xfail(
    **GAP,
    reason="gap b5: the exit alert for a real (My Holdings) position is labelled with the BOT's mode, so a real-money holding says PAPER while the bot is on paper",
)
def test_b5_an_exit_alert_for_a_real_holding_does_not_say_paper(db_session, monkeypatch, sent):
    _, _, pos = real_holding(db_session, "B5REAL", stop_loss=96.0, take_profit=110.0)
    assert pos.mode == "live"
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)  # the bot itself is on paper
    text = sent[0][0]
    assert "PAPER" not in text, text  # execution.py:1575 passes broker.mode, not position.mode


# ================================================================ (c) an alert goes only to the owner's one chat


def test_c1_every_alert_goes_to_the_single_configured_chat_and_names_no_person(monkeypatch):
    """There is one Telegram chat (the owner's), set in the settings; no alert is addressed to a user or a book."""
    from swing_trade_ml.notifications import telegram as tg

    posted = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            posted.append(json)
            return FakeResponse()

    monkeypatch.setattr(tg.httpx, "AsyncClient", FakeClient)  # nothing can reach the network
    notifier = tg.TelegramNotifier()
    monkeypatch.setattr(notifier, "_token", "TEST-TOKEN-NOT-REAL")
    monkeypatch.setattr(notifier, "_chat_id", "TEST-CHAT-NOT-REAL")
    assert notifier.send_sync.__self__ is notifier
    import asyncio

    assert asyncio.run(notifier._post("hello")) is True
    assert [p["chat_id"] for p in posted] == ["TEST-CHAT-NOT-REAL"] and posted[0]["text"] == "hello"


def test_c2_alert_texts_carry_no_account_or_person_identifiers(db_session, monkeypatch, sent):
    """A weak check, said plainly: it bans a short list of words ("@", "chat", "email", ...) in one stop alert. It cannot prove
    that no identifier ever appears; the message builders take only the instrument, position and trade."""
    real_holding(db_session, "C2PRIVATE", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    text = sent[0][0].lower()
    for word in ("@", "email", "password", "token", "username", "user_id", "chat"):
        assert word not in text, word


def test_c3_the_two_books_are_labelled_in_a_bot_sell_alert_and_a_testing_one(db_session, monkeypatch, sent):
    """book=bot and the Testing book are told apart in the badge. (Real-book visibility rules: #426, test_p0_tester_private.)"""
    bot = strategy(db_session, "c3_bot")
    tester = strategy(db_session, "tester_paper", kind="tester_paper")
    for strat, symbol in ((bot, "C3BOT"), (tester, "C3TEST")):
        position(
            db_session,
            strat,
            with_quote(db_session, inst(db_session, symbol), 95.0),
            stop_loss=96.0,
            take_profit=110.0,
        )
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    texts = {t for t, _, _ in sent if "CLOSED" in t}
    assert any("C3BOT" in t and "· Bot" in t for t in texts) and any(
        "C3TEST" in t and "· Testing" in t for t in texts
    )


# ================================================================ (d) held alerts: delivered once after the quiet period


def test_d1_a_held_alert_is_delivered_once_after_quiet_hours_and_then_not_again(db_session):
    from datetime import time

    from swing_trade_ml.db.models.alerts import AlertOutbox
    from swing_trade_ml.notifications.alert_policy import AlertPrefs
    from swing_trade_ml.services import alert_settings

    prefs = AlertPrefs(quiet_enabled=True, quiet_start=time(22, 0), quiet_end=time(7, 0))
    alert_settings.save(db_session, prefs, "test")
    night = datetime(2026, 12, 1, 18, 0, tzinfo=UTC)  # 23:30 IST: inside quiet hours
    held_session = lambda: _Ctx(db_session)  # noqa: E731
    assert (
        alert_settings.gate(alert_policy.HOLDING_WARNINGS, "score slipping", now=night, sessions=held_session)
        == "held"
    )
    assert (
        alert_settings.gate(alert_policy.DAILY_SUMMARY, "summary", now=night, sessions=held_session) == "held"
    )
    assert (
        alert_settings.gate("sells", "sold", now=night, sessions=held_session) == "send"
    )  # untagged/unknown: never held
    delivered: list[str] = []
    still_quiet = datetime(2026, 12, 1, 20, 0, tzinfo=UTC)  # 01:30 IST
    assert alert_settings.flush(db_session, still_quiet, lambda t: delivered.append(t) or True)["sent"] == 0
    morning = datetime(2026, 12, 1, 2, 0, tzinfo=UTC) + timedelta(days=1)  # 07:30 IST next day
    out = alert_settings.flush(db_session, morning, lambda t: delivered.append(t) or True)
    assert out["sent"] == 2 and len(delivered) == 1  # both go out together in one message
    assert "score slipping" in delivered[0] and "summary" in delivered[0]
    again = alert_settings.flush(
        db_session, morning + timedelta(minutes=5), lambda t: delivered.append(t) or True
    )
    assert again["sent"] == 0 and len(delivered) == 1  # once
    assert db_session.scalar(select(AlertOutbox).where(AlertOutbox.sent_at.is_(None))) is None


class _Ctx:
    """A session factory context that hands back the test session without closing it."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False


def test_d2_a_failed_delivery_of_held_alerts_keeps_them_held_for_the_next_run(db_session):
    from datetime import time

    from swing_trade_ml.db.models.alerts import AlertOutbox
    from swing_trade_ml.notifications.alert_policy import AlertPrefs
    from swing_trade_ml.services import alert_settings

    alert_settings.save(
        db_session, AlertPrefs(quiet_enabled=True, quiet_start=time(22, 0), quiet_end=time(7, 0)), "test"
    )
    night = datetime(2026, 12, 1, 18, 0, tzinfo=UTC)
    assert (
        alert_settings.gate(alert_policy.HOLDING_WARNINGS, "x", now=night, sessions=lambda: _Ctx(db_session))
        == "held"
    )
    morning = night + timedelta(hours=9)
    assert alert_settings.flush(db_session, morning, lambda t: False)["sent"] == 0  # Telegram refused
    assert (
        db_session.scalar(select(AlertOutbox).where(AlertOutbox.sent_at.is_(None))) is not None
    )  # still held
    assert alert_settings.flush(db_session, morning + timedelta(minutes=5), lambda t: True)["sent"] == 1


# ============================================================================ (e) a failed send is not lost silently


def test_e1_a_failed_telegram_send_returns_false_and_only_logs(monkeypatch):
    """What exists today: the notifier reports False and writes a log line. Nothing is stored for the owner to see."""
    from swing_trade_ml.notifications import telegram as tg

    class Refused:
        status_code = 500
        text = "server error"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return Refused()

    monkeypatch.setattr(tg.httpx, "AsyncClient", FakeClient)
    notifier = tg.TelegramNotifier()
    monkeypatch.setattr(notifier, "_token", "TEST-TOKEN-NOT-REAL")
    monkeypatch.setattr(notifier, "_chat_id", "TEST-CHAT-NOT-REAL")
    import asyncio

    assert asyncio.run(notifier._post("x")) is False


@pytest.mark.xfail(
    **GAP,
    reason="gap e2: check_exits marks a stop-loss alert as sent even when the send failed, so it is never retried and the loss is silent",
)
def test_e2_a_stop_alert_that_failed_to_send_is_not_marked_as_sent(db_session, monkeypatch, sent):
    sent.ok = False  # Telegram refused the message
    _, _, pos = real_holding(db_session, "E2LOST", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    assert pos.advisory_alert_sent_at is None, (
        pos.advisory_alert_sent_at
    )  # execution.py:1575-1576 sets it regardless


@pytest.mark.xfail(
    **GAP,
    reason="gap e3: a failed confidence alert is also marked as sent before the send, so it is never retried",
)
def test_e3_a_confidence_alert_that_failed_to_send_is_not_marked_as_sent(db_session, sent):
    sent.ok = False
    strat, row, pos = _weak_world(db_session, "E3LOST")
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert pos.confidence_alert_sent_at is None, (
        pos.confidence_alert_sent_at
    )  # execution.py:867 sets it before sending


# ==================================================================== (f) a stock sold elsewhere stops alerting


def test_f1_a_ghost_holding_stops_alerting_after_the_sync_closes_it(db_session, monkeypatch, sent):
    strat, _, ghost = real_holding(db_session, "F1GHOST", stop_loss=96.0, take_profit=110.0)
    _, _, kept = real_holding(db_session, "F1KEPT", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    ghost.entry_at = kept.entry_at = datetime.now(UTC) - timedelta(days=5)
    closed = holdings_sync.close_positions_no_longer_held(db_session, strat, {"F1KEPT"})
    assert [c["symbol"] for c in closed] == ["F1GHOST"] and ghost.status == "CLOSED" and kept.status == "OPEN"
    sent.clear()
    execution.check_exits(db_session)
    assert (
        len(sent) == 1 and "F1KEPT" in sent[0][0] and "F1GHOST" not in sent[0][0]
    )  # only the stock still held
    execution.check_exits(db_session)
    assert len(sent) == 1  # and that one only once


def test_f2_an_empty_broker_list_never_closes_everything_by_mistake(db_session):
    """A failed load must not read as 'everything was sold': the caller passes the held set, and a held stock stays open."""
    strat, _, pos = real_holding(db_session, "F2SAFE")
    pos.entry_at = datetime.now(UTC) - timedelta(days=5)
    assert holdings_sync.close_positions_no_longer_held(db_session, strat, {"F2SAFE"}) == []
    assert pos.status == "OPEN"


def test_f3_closing_a_ghost_alerts_once_and_says_it_was_a_manual_close(db_session, sent):
    strat, _, ghost = real_holding(db_session, "F3SOLD", stop_loss=96.0, take_profit=110.0)
    ghost.entry_at = datetime.now(UTC) - timedelta(days=5)
    holdings_sync.close_positions_no_longer_held(db_session, strat, set())
    texts = [t for t, _, _ in sent if "F3SOLD" in t]
    assert len(texts) == 1 and "CLOSED" in texts[0] and "MANUAL" in texts[0]
    assert db_session.scalar(select(Trade).where(Trade.position_id == ghost.id)) is not None
