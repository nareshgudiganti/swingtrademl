"""A holding you have already sold must stop warning you about itself.

`import_real_holdings` only ever added rows: a tracked advisory position whose
stock had left the Zerodha account stayed OPEN forever, kept getting a daily
model read, kept breaching its stop, and kept producing both a Telegram alert
and a "needs attention" row — for shares the owner no longer held.

Found live on 2026-09-28: 13 tracked holdings against 10 actually in Zerodha,
and all three ghosts (ACC, J&KBANK, SUZLON) were sitting in the nine rows the
app was asking the owner to act on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.api.v1.endpoints import portfolio as portfolio_api
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy

HEADERS = {"X-API-Key": "test-api-key"}


def _real_strategy(db):
    strategy = Strategy(
        name="real_trading", strategy_type="ml_swing", mode="live",
        execution_mode="advisory", is_active=True,
    )
    db.add(strategy)
    db.flush()
    return strategy


def _tracked(db, strategy, symbol: str, token: int) -> Position:
    instrument = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True
    )
    db.add(instrument)
    db.flush()
    position = Position(
        strategy_id=strategy.id, instrument_id=instrument.id, mode="live",
        quantity=10, entry_price=100.0, current_price=90.0, stop_loss=95.0,
        entry_at=datetime.now(UTC), status=PositionStatus.OPEN,
    )
    db.add(position)
    db.flush()
    return position


def test_a_holding_no_longer_in_zerodha_is_closed_and_one_still_held_is_not(
    client, db_session, monkeypatch
):
    strategy = _real_strategy(db_session)
    kept = _tracked(db_session, strategy, "ZZZSTILLHELD", 771_001)
    sold = _tracked(db_session, strategy, "ZZZALREADYSOLD", 771_002)
    db_session.commit()

    # Zerodha reports only the one still owned — the other was sold by hand.
    monkeypatch.setattr(
        portfolio_api, "_load_kite_holdings",
        lambda db: [
            {"tradingsymbol": "ZZZSTILLHELD", "exchange": "NSE", "quantity": 10, "average_price": 100.0},
        ],
    )

    response = client.post(
        f"/api/v1/portfolio/positions/import-holdings?strategy_id={strategy.id}", headers=HEADERS
    )
    assert response.status_code in (200, 201), response.text

    db_session.expire_all()
    assert db_session.get(Position, kept.id).status == PositionStatus.OPEN
    assert db_session.get(Position, sold.id).status == PositionStatus.CLOSED, (
        "a stock that has left the Zerodha account must stop being tracked as open, "
        "or it keeps warning about shares that are not held"
    )


def test_a_closed_ghost_no_longer_appears_in_the_holdings_book(client, db_session, monkeypatch):
    """The point of the close: it must drop out of the book the "needs
    attention" panels read, so nothing asks you to sell what you already did."""
    strategy = _real_strategy(db_session)
    _tracked(db_session, strategy, "ZZZGHOST", 771_003)
    db_session.commit()

    monkeypatch.setattr(portfolio_api, "_load_kite_holdings", lambda db: [])

    client.post(
        f"/api/v1/portfolio/positions/import-holdings?strategy_id={strategy.id}", headers=HEADERS
    )

    rows = client.get("/api/v1/portfolio/positions/detailed?book=real", headers=HEADERS).json()
    assert not [r for r in rows if r["symbol"] == "ZZZGHOST"]
