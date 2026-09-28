"""The stop-loss alert the app sends to Telegram must also be visible on screen.

Two alert flags live on a Position and they are not the same thing:

* `confidence_alert_sent_at` — the model is losing conviction. Already drives
  `action_code`, so "Needs attention" counts it.
* `advisory_alert_sent_at` — the position's **stop-loss, target or time stop**
  was breached and the owner was messaged, because an advisory position holds
  the owner's own shares and the bot may not sell them
  (services/execution.py::check_exits).

Only the first reached the UI. So on 28 Sept 2026 eight of thirteen real
holdings sat below their stop, Telegram had said so for each, and both the
Dashboard and My Holdings reported "nothing needs attention" — the most urgent
state the app can be in rendered as silence.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services.execution import position_action

HEADERS = {"X-API-Key": "test-api-key"}
EXIT_CONFIDENCE = 0.35


def test_a_sent_exit_alert_reads_as_exit_not_as_the_confidence_view(  ):
    """A breached stop is a fact about price, so it outranks whatever the model
    currently thinks. Here confidence is a healthy 68% — which would otherwise
    read "bullish" — and the position must still read "exit"."""
    code, label = position_action(
        entry_confidence=0.70,
        last_confidence=0.68,
        alert_sent=False,
        holding_days=3,
        horizon_days=5,
        exit_confidence=EXIT_CONFIDENCE,
        exit_alert_sent=True,
    )

    assert code == "exit"
    assert label, "the row needs a sentence saying why it wants out"


def test_positions_detailed_marks_an_alerted_advisory_holding_as_exit(client, db_session):
    """The wiring the outage came down to: the endpoint that feeds both
    "Needs attention" panels never passed `advisory_alert_sent_at` into the
    action read, so a holding the app had already messaged about came back
    looking like any other. This is the end-to-end proof it no longer does."""
    strategy = Strategy(
        # The My Holdings book is selected by this exact name
        # (api/v1/endpoints/portfolio.py::_scope_to_book).
        name="real_trading",
        strategy_type="ml_swing",
        mode="live",
        execution_mode="advisory",
        is_active=True,
    )
    db_session.add(strategy)
    db_session.flush()

    instrument = Instrument(
        instrument_token=555_777, tradingsymbol="TESTSTOPPED", exchange="NSE", is_watchlisted=True
    )
    db_session.add(instrument)
    db_session.flush()

    # Priced below its stop and already messaged about — exactly the state the
    # eight real holdings were in.
    db_session.add(
        Position(
            strategy_id=strategy.id,
            instrument_id=instrument.id,
            mode="live",
            quantity=10,
            entry_price=100.0,
            current_price=89.0,
            stop_loss=90.0,
            entry_confidence=0.70,
            last_confidence=0.68,
            advisory_alert_sent_at=datetime.now(UTC),
            entry_at=datetime.now(UTC),
            status=PositionStatus.OPEN,
        )
    )
    db_session.commit()

    response = client.get("/api/v1/portfolio/positions/detailed?book=real", headers=HEADERS)

    assert response.status_code == 200
    row = next(r for r in response.json() if r["symbol"] == "TESTSTOPPED")
    assert row["action_code"] == "exit", (
        "a holding the app already sent an exit alert for must count as needing "
        f"attention, got {row['action_code']!r} ({row.get('action_label')!r})"
    )
