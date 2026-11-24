# ruff: noqa: E501 (long plain-English test text)
"""#480: an alert is marked sent only after Telegram took it, a real holding is labelled by its own book, and the exit
alert speaks plain English.

Fakes only: the notifier's `send_sync` is replaced by a recorder whose answer the test chooses, so nothing reaches Telegram
or any network. No order, size, stop or limit is touched; only alert flags and wording.

Written to fail first against 5de3b9c: the flags were set whatever the send answered, the badge used the bot's mode,
and the message printed STOP_LOSS_HIT and an API path.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers.paper import PaperBroker
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.notifications import alert_policy
from swing_trade_ml.notifications.alert_policy import AlertPrefs
from swing_trade_ml.services import alert_settings, execution

_tokens = iter(range(975_000, 975_900))


@pytest.fixture()
def sent(monkeypatch):
    """Every alert the code tries to send as (text, event, kind). `sent.ok` is what the fake send answers."""

    class Box(list):
        ok = True

    box = Box()

    def fake(text, event="system", kind=None):
        box.append((text, str(event), kind))
        return box.ok

    monkeypatch.setattr(execution.notifier, "send_sync", fake)
    # Delivery is possible in these tests (a real, configured notifier); the "cannot deliver by design" case sets it off.
    monkeypatch.setattr(execution.notifier, "can_deliver", lambda event: True, raising=False)
    return box


def inst(db, symbol: str) -> Instrument:
    row = Instrument(instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(row)
    db.flush()
    return row


def strategy(db, name: str, *, mode: str = "paper", execution_mode: str = "auto") -> Strategy:
    row = Strategy(name=name, strategy_type="ml_swing", mode=mode, execution_mode=execution_mode, is_active=True)
    db.add(row)
    db.flush()
    return row


def position(db, strat: Strategy, row: Instrument, *, mode: str = "paper", **kw) -> Position:
    p = Position(
        strategy_id=strat.id, instrument_id=row.id, mode=mode, status="OPEN", quantity=10, entry_price=100.0,
        entry_at=kw.pop("entry_at", datetime.now(UTC) - timedelta(days=2)), current_price=100.0, total_charges=10.0, **kw,
    )
    db.add(p)
    db.flush()
    return p


def real_holding(db, symbol: str, **kw) -> Position:
    strat = db.scalar(select(Strategy).where(Strategy.name == "real_trading")) or strategy(db, "real_trading", mode="live", execution_mode="advisory")
    return position(db, strat, inst(db, symbol), mode="live", **kw)


def price_at(monkeypatch, value: float) -> None:
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: dict.fromkeys(keys, value))


def weak_world(db, symbol):
    strat = strategy(db, f"{symbol}_strat")
    row = inst(db, symbol)
    return strat, row, position(db, strat, row, entry_confidence=0.80, stop_loss=96.0, take_profit=108.0)


# ---------------------------------------------------------------- (1) the flag follows a confirmed delivery


def test_a_failed_stop_loss_send_leaves_the_flag_unset_and_is_retried_without_a_duplicate(db_session, monkeypatch, sent):
    pos = real_holding(db_session, "D480STOP", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    sent.ok = False  # Telegram refused
    execution.check_exits(db_session)
    assert len(sent) == 1 and pos.advisory_alert_sent_at is None
    sent.ok = True  # the next 60-second sweep, Telegram is back
    execution.check_exits(db_session)
    assert len(sent) == 2 and pos.advisory_alert_sent_at is not None
    execution.check_exits(db_session)
    assert len(sent) == 2  # delivered once: no third message


def test_a_stop_loss_send_that_works_sets_the_flag_at_once_and_sends_once(db_session, monkeypatch, sent):
    pos = real_holding(db_session, "D480OK", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    execution.check_exits(db_session)
    assert len(sent) == 1 and pos.advisory_alert_sent_at is not None


def test_a_failed_confidence_send_leaves_the_flag_unset_and_is_retried_without_a_duplicate(db_session, sent):
    strat, row, pos = weak_world(db_session, "D480CONF")
    sent.ok = False
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 1 and pos.confidence_alert_sent_at is None
    sent.ok = True
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 2 and pos.confidence_alert_sent_at is not None
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 2


def test_a_failed_confidence_send_does_not_mark_the_days_score_as_alerted(db_session, sent):
    from swing_trade_ml.db.models.trading import PositionScore

    strat, row, pos = weak_world(db_session, "D480BAND")
    sent.ok = False
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert all(not r.alerted for r in db_session.scalars(select(PositionScore).where(PositionScore.position_id == pos.id)))


def test_when_nothing_can_be_delivered_by_design_the_stop_flag_is_still_set_so_the_app_shows_the_exit(db_session, monkeypatch, sent):
    """Telegram switched off or not configured: there is nothing to retry, and the app must still read 'exit'."""
    monkeypatch.setattr(execution.notifier, "can_deliver", lambda event: False, raising=False)
    pos = real_holding(db_session, "D480OFF", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    sent.ok = False
    execution.check_exits(db_session)
    assert pos.advisory_alert_sent_at is not None


def test_a_confidence_warning_the_owner_switched_off_is_settled_not_retried_forever(db_session, sent):
    alert_settings.save(db_session, AlertPrefs(disabled=frozenset({alert_policy.HOLDING_WARNINGS})), "test")
    strat, row, pos = weak_world(db_session, "D480MUTE")
    sent.ok = False  # a switched-off kind is answered False by the notifier
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert pos.confidence_alert_sent_at is not None
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 1


# ---------------------------------------------------------------- (2) labelled by the position's own book


def test_a_real_holding_exit_alert_says_live_not_paper_while_the_bot_is_on_paper(db_session, monkeypatch, sent):
    real_holding(db_session, "D480REAL", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    text = sent[0][0]
    assert "PAPER" not in text and "LIVE" in text


def test_a_real_holding_confidence_warning_is_labelled_by_the_holding_too(db_session, sent):
    strat = strategy(db_session, "real_trading", mode="live", execution_mode="advisory")
    pos = position(db_session, strat, inst(db_session, "D480RCONF"), mode="live", entry_confidence=0.80, stop_loss=96.0, take_profit=108.0)
    execution._check_confidence_decay(db_session, pos, strat, db_session.get(Instrument, pos.instrument_id), 0.40, "paper")
    assert "PAPER" not in sent[0][0] and "LIVE" in sent[0][0]


def test_a_paper_positions_alert_still_says_paper(db_session):
    inst_row = Instrument(instrument_token=next(_tokens), tradingsymbol="D480PAPER", exchange="NSE")
    pos = Position(strategy_id=1, instrument_id=1, mode="paper", status="OPEN", quantity=10, entry_price=100.0, current_price=95.0)
    text = execution._advisory_exit_message(inst_row, pos, "STOP_LOSS_HIT", "paper")
    assert "PAPER" in text and "LIVE" not in text


# ---------------------------------------------------------------- (3) plain English, short


@pytest.mark.parametrize(
    ("reason", "words"),
    [("STOP_LOSS_HIT", "Stop-loss hit"), ("TARGET_HIT", "Target reached"), ("TIME_STOP", "Time limit reached")],
)
def test_the_exit_alert_says_the_reason_in_plain_english_with_no_codes_or_route_text(db_session, reason, words):
    row = Instrument(instrument_token=next(_tokens), tradingsymbol="D480TEXT", exchange="NSE")
    pos = Position(id=77, strategy_id=1, instrument_id=1, mode="live", status="OPEN", quantity=10, entry_price=100.0, current_price=95.0)
    text = re.sub(r"<[^>]+>", "", execution._advisory_exit_message(row, pos, reason, "live"))
    assert words in text
    assert not re.search(r"\b[A-Z]{2,}_[A-Z_]+\b", text), text
    assert "POST" not in text and "/portfolio" not in text and "manual-close" not in text
    assert "Entry: ₹100.00" in text and "Current: ₹95.00" in text and "Quantity: 10" in text
    assert len(text) < 400


def test_an_unknown_reason_is_shown_as_words_not_as_a_code(db_session):
    row = Instrument(instrument_token=next(_tokens), tradingsymbol="D480ODD", exchange="NSE")
    pos = Position(strategy_id=1, instrument_id=1, mode="paper", status="OPEN", quantity=1, entry_price=1.0, current_price=1.0)
    text = execution._advisory_exit_message(row, pos, "SOME_NEW_REASON", "paper")
    assert "SOME_NEW_REASON" not in text and "Some new reason" in text
