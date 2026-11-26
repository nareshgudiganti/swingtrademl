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


class Clock:
    """The alert retry clock the code reads, moved by hand."""

    def __init__(self):
        self.now = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)

    def advance(self, minutes: float) -> None:
        self.now += timedelta(minutes=minutes)


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(execution, "_alert_now", lambda: c.now, raising=False)
    monkeypatch.setattr(execution, "_ALERT_ATTEMPTS", {}, raising=False)
    return c


@pytest.fixture()
def sent(monkeypatch, clock):
    """Every alert the code tries to send as (text, event, kind). `sent.ok` is what the fake send answers."""

    class Box(list):
        ok = True

    box = Box()

    def fake(text, event="system", kind=None):
        box.append((text, str(event), kind))
        return box.ok

    monkeypatch.setattr(execution.notifier, "send_sync", fake)
    # Delivery is possible in these tests (a real, configured notifier); the "cannot deliver by design" case sets it off.
    monkeypatch.setattr(execution.notifier, "can_deliver", lambda event, kind=None: True, raising=False)
    return box


def inst(db, symbol: str) -> Instrument:
    row = Instrument(instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(row)
    db.flush()
    return row


def strategy(db, name: str, *, mode: str = "paper", execution_mode: str = "auto") -> Strategy:
    row = Strategy(
        name=name, strategy_type="ml_swing", mode=mode, execution_mode=execution_mode, is_active=True
    )
    db.add(row)
    db.flush()
    return row


def position(db, strat: Strategy, row: Instrument, *, mode: str = "paper", **kw) -> Position:
    p = Position(
        strategy_id=strat.id,
        instrument_id=row.id,
        mode=mode,
        status="OPEN",
        quantity=10,
        entry_price=100.0,
        entry_at=kw.pop("entry_at", datetime.now(UTC) - timedelta(days=2)),
        current_price=100.0,
        total_charges=10.0,
        **kw,
    )
    db.add(p)
    db.flush()
    return p


def real_holding(db, symbol: str, **kw) -> Position:
    strat = db.scalar(select(Strategy).where(Strategy.name == "real_trading")) or strategy(
        db, "real_trading", mode="live", execution_mode="advisory"
    )
    return position(db, strat, inst(db, symbol), mode="live", **kw)


def price_at(monkeypatch, value: float) -> None:
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: dict.fromkeys(keys, value))


def weak_world(db, symbol):
    strat = strategy(db, f"{symbol}_strat")
    row = inst(db, symbol)
    return strat, row, position(db, strat, row, entry_confidence=0.80, stop_loss=96.0, take_profit=108.0)


# ---------------------------------------------------------------- (1) the flag follows a confirmed delivery


def test_a_failed_stop_loss_send_leaves_the_flag_unset_and_is_retried_without_a_duplicate(
    db_session, monkeypatch, sent, clock
):
    pos = real_holding(db_session, "D480STOP", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    sent.ok = False  # Telegram refused
    execution.check_exits(db_session)
    assert len(sent) == 1 and pos.advisory_alert_sent_at is None
    sent.ok = True  # Telegram is back; the next try is due after the retry gap
    clock.advance(execution.ALERT_RETRY_MINUTES + 1)
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


def test_a_failed_confidence_send_leaves_the_flag_unset_and_is_retried_without_a_duplicate(
    db_session, sent, clock
):
    strat, row, pos = weak_world(db_session, "D480CONF")
    sent.ok = False
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 1 and pos.confidence_alert_sent_at is None
    sent.ok = True
    clock.advance(execution.ALERT_RETRY_MINUTES + 1)
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 2 and pos.confidence_alert_sent_at is not None
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 2


def test_a_failed_confidence_send_does_not_mark_the_days_score_as_alerted(db_session, sent):
    from swing_trade_ml.db.models.trading import PositionScore

    strat, row, pos = weak_world(db_session, "D480BAND")
    sent.ok = False
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert all(
        not r.alerted
        for r in db_session.scalars(select(PositionScore).where(PositionScore.position_id == pos.id))
    )


def test_when_nothing_can_be_delivered_by_design_the_stop_flag_is_still_set_so_the_app_shows_the_exit(
    db_session, monkeypatch, sent
):
    """Telegram switched off or not configured: there is nothing to retry, and the app must still read 'exit'."""
    monkeypatch.setattr(execution.notifier, "can_deliver", lambda event, kind=None: False, raising=False)
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


def test_a_real_holding_exit_alert_says_live_not_paper_while_the_bot_is_on_paper(
    db_session, monkeypatch, sent
):
    real_holding(db_session, "D480REAL", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    execution.check_exits(db_session)
    text = sent[0][0]
    assert "PAPER" not in text and "LIVE" in text


def test_a_real_holding_confidence_warning_is_labelled_by_the_holding_too(db_session, sent):
    strat = strategy(db_session, "real_trading", mode="live", execution_mode="advisory")
    pos = position(
        db_session,
        strat,
        inst(db_session, "D480RCONF"),
        mode="live",
        entry_confidence=0.80,
        stop_loss=96.0,
        take_profit=108.0,
    )
    execution._check_confidence_decay(
        db_session, pos, strat, db_session.get(Instrument, pos.instrument_id), 0.40, "paper"
    )
    assert "PAPER" not in sent[0][0] and "LIVE" in sent[0][0]


def test_a_paper_positions_alert_still_says_paper(db_session):
    inst_row = Instrument(instrument_token=next(_tokens), tradingsymbol="D480PAPER", exchange="NSE")
    pos = Position(
        strategy_id=1,
        instrument_id=1,
        mode="paper",
        status="OPEN",
        quantity=10,
        entry_price=100.0,
        current_price=95.0,
    )
    text = execution._advisory_exit_message(inst_row, pos, "STOP_LOSS_HIT", "paper")
    assert "PAPER" in text and "LIVE" not in text


# ---------------------------------------------------------------- (3) plain English, short


@pytest.mark.parametrize(
    ("reason", "words"),
    [
        ("STOP_LOSS_HIT", "Stop-loss hit"),
        ("TARGET_HIT", "Target reached"),
        ("TIME_STOP", "Time limit reached"),
    ],
)
def test_the_exit_alert_says_the_reason_in_plain_english_with_no_codes_or_route_text(
    db_session, reason, words
):
    row = Instrument(instrument_token=next(_tokens), tradingsymbol="D480TEXT", exchange="NSE")
    pos = Position(
        id=77,
        strategy_id=1,
        instrument_id=1,
        mode="live",
        status="OPEN",
        quantity=10,
        entry_price=100.0,
        current_price=95.0,
    )
    text = re.sub(r"<[^>]+>", "", execution._advisory_exit_message(row, pos, reason, "live"))
    assert words in text
    assert not re.search(r"\b[A-Z]{2,}_[A-Z_]+\b", text), text
    assert "POST" not in text and "/portfolio" not in text and "manual-close" not in text
    assert "Entry: ₹100.00" in text and "Current: ₹95.00" in text and "Quantity: 10" in text
    assert len(text) < 400


def test_an_unknown_reason_is_shown_as_words_not_as_a_code(db_session):
    row = Instrument(instrument_token=next(_tokens), tradingsymbol="D480ODD", exchange="NSE")
    pos = Position(
        strategy_id=1,
        instrument_id=1,
        mode="paper",
        status="OPEN",
        quantity=1,
        entry_price=1.0,
        current_price=1.0,
    )
    text = execution._advisory_exit_message(row, pos, "SOME_NEW_REASON", "paper")
    assert "SOME_NEW_REASON" not in text and "Some new reason" in text


# ---------------------------------------------------------------- review follow-ups: a failed send never hides "exit"


def _policy(position):
    from swing_trade_ml.services.exit_policy import exit_policy_for_strategy

    return exit_policy_for_strategy(position.strategy)


def test_exit_reason_for_names_the_stop_target_and_time_limit_and_nothing_in_between(db_session):
    pos = real_holding(db_session, "D480PURE", stop_loss=96.0, take_profit=108.0)
    policy, now = _policy(pos), datetime.now(UTC)
    assert (
        execution.exit_reason_for(pos, 96.0, policy, now) == execution.ExitReason.STOP_LOSS_HIT
    )  # at the level
    assert execution.exit_reason_for(pos, 95.0, policy, now) == execution.ExitReason.STOP_LOSS_HIT
    assert execution.exit_reason_for(pos, 108.0, policy, now) == execution.ExitReason.TARGET_HIT
    assert execution.exit_reason_for(pos, 100.0, policy, now) is None
    assert execution.exit_reason_for(pos, 96.01, policy, now) is None
    late = now + timedelta(days=policy.time_stop_days + 1)
    assert execution.exit_reason_for(pos, 100.0, policy, late) == execution.ExitReason.TIME_STOP


def _action_of(client, position_id: int) -> str:
    rows = client.get(
        "/api/v1/portfolio/positions/detailed?book=real", headers={"X-API-Key": "test-api-key"}
    ).json()
    return next(r["action_code"] for r in rows if r["id"] == position_id)


def test_a_position_past_its_stop_reads_exit_in_the_app_even_when_the_alert_could_not_be_delivered(
    client, db_session, monkeypatch, sent
):
    pos = real_holding(db_session, "D480APP", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    sent.ok = False
    execution.check_exits(db_session)  # the sweep records the price; the send failed
    db_session.refresh(pos)
    assert pos.advisory_alert_sent_at is None  # the flag still means "delivered"
    assert pos.current_price == 95.0
    assert _action_of(client, pos.id) == "exit"


def test_the_same_position_does_not_read_exit_when_it_is_not_past_a_level(
    client, db_session, monkeypatch, sent
):
    pos = real_holding(db_session, "D480CALM", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 100.0)
    execution.check_exits(db_session)
    assert _action_of(client, pos.id) != "exit"


def test_a_weakening_confidence_reads_as_the_alert_state_in_the_app_even_when_the_warning_was_not_delivered(
    client, db_session, sent
):
    strat = strategy(db_session, "real_trading", mode="live", execution_mode="advisory")
    base = {"entry_confidence": 0.80, "stop_loss": 90.0, "take_profit": 120.0}
    flagged = position(
        db_session,
        strat,
        inst(db_session, "D480FLAG"),
        mode="live",
        last_confidence=0.40,
        confidence_alert_sent_at=datetime.now(UTC),
        **base,
    )
    unflagged = position(
        db_session, strat, inst(db_session, "D480NOFLAG"), mode="live", last_confidence=0.40, **base
    )
    assert _action_of(client, unflagged.id) == _action_of(client, flagged.id)


# ---------------------------------------------------------------- retries are capped


def test_a_failed_stop_send_is_tried_once_per_retry_gap_not_every_sweep(db_session, monkeypatch, sent, clock):
    pos = real_holding(db_session, "D480CAP", stop_loss=96.0, take_profit=110.0)
    price_at(monkeypatch, 95.0)
    sent.ok = False
    for _ in range(5):  # five 60-second sweeps
        execution.check_exits(db_session)
        clock.advance(1)
    assert len(sent) == 1 and pos.advisory_alert_sent_at is None
    clock.advance(execution.ALERT_RETRY_MINUTES)
    execution.check_exits(db_session)
    assert len(sent) == 2


def test_a_failed_confidence_send_is_tried_once_per_retry_gap(db_session, sent, clock):
    strat, row, pos = weak_world(db_session, "D480CAPC")
    sent.ok = False
    for _ in range(4):
        execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
        clock.advance(1)
    assert len(sent) == 1
    clock.advance(execution.ALERT_RETRY_MINUTES)
    execution._check_confidence_decay(db_session, pos, strat, row, 0.40, "paper")
    assert len(sent) == 2


# ---------------------------------------------------------------- can_deliver: a safety alert ignores the event list


def test_can_deliver_ignores_the_event_list_for_a_kind_less_safety_alert_but_not_for_a_switchable_kind(
    monkeypatch,
):
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.notifications.telegram import TelegramNotifier

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFY_ON", "error")  # "signal" is left out
    n = TelegramNotifier()
    monkeypatch.setattr(n, "_token", "TEST-TOKEN-NOT-REAL")
    monkeypatch.setattr(n, "_chat_id", "TEST-CHAT-NOT-REAL")
    assert n.can_deliver("signal") is True  # kind-less: only "is Telegram on at all" counts
    assert (
        n.can_deliver("signal", kind=alert_policy.HOLDING_WARNINGS) is False
    )  # a switchable kind honours the list
    monkeypatch.setattr(settings, "TELEGRAM_ENABLED", False)
    assert n.can_deliver("signal") is False and n.can_deliver("error") is False


def test_a_brain_position_is_never_given_the_derived_warning_already_sent_state(client, db_session):
    from swing_trade_ml.core.strategy_policy import STAGED_TYPES

    brain = Strategy(
        name="d480_brain",
        strategy_type=sorted(STAGED_TYPES)[0],
        mode="paper",
        execution_mode="advisory",
        is_active=True,
    )
    db_session.add(brain)
    db_session.flush()
    pos = position(
        db_session,
        brain,
        inst(db_session, "D480BRAIN"),
        mode="paper",
        entry_confidence=0.80,
        last_confidence=0.40,
        stop_loss=90.0,
        take_profit=120.0,
    )
    rows = client.get("/api/v1/portfolio/positions/detailed", headers={"X-API-Key": "test-api-key"}).json()
    row = next(r for r in rows if r["id"] == pos.id)
    # The derived "warning already sent" state is not given to a brain position; its own fresh read is unchanged.
    assert row["action_code"] != "alert" and "alert already sent" not in row["action_label"]
