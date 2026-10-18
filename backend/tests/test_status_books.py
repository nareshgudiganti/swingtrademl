"""/status counts open positions per book and never adds paper and real together."""

from __future__ import annotations

from datetime import UTC, datetime

from brain_m18_fixtures import instrument, v1_strategy
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.trading import Position

HEADERS = {"X-API-Key": "test-api-key"}


def _pos(db, strategy, inst, mode="paper", status=PositionStatus.OPEN):
    db.add(
        Position(
            strategy_id=strategy.id if strategy else None,
            instrument_id=inst.id,
            mode=mode,
            status=status,
            entry_price=100.0,
            quantity=1,
            entry_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    db.flush()


def _status(client):
    return client.get("/api/v1/status", headers=HEADERS).json()


def test_status_splits_open_positions_by_book(db_session, client):
    before = _status(client)["open_positions_by_book"]
    bot = v1_strategy(db_session, name="fxb-bot")
    testing = v1_strategy(db_session, name="fxb-tester", strategy_type="tester_paper", execution_mode="advisory")
    real = v1_strategy(db_session, name="real_trading", strategy_type="long_term_value", execution_mode="advisory")
    for i, (strat, n, mode) in enumerate([(bot, 2, "paper"), (testing, 3, "paper"), (real, 4, "live")]):
        for j in range(n):
            _pos(db_session, strat, instrument(db_session, f"FXB{i}{j}", 960000 + i * 10 + j), mode)
    _pos(db_session, bot, instrument(db_session, "FXBCLOSED", 960099), status=PositionStatus.CLOSED)
    db_session.commit()

    body = _status(client)
    books = body["open_positions_by_book"]
    assert books["bot"] - before["bot"] == 2
    assert books["testing"] - before["testing"] == 3
    assert books["real"] - before["real"] == 4
    # The old single number is the bot's own book only: no testing, no real holdings.
    assert body["open_positions"] == books["bot"]
