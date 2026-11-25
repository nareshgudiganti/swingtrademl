"""#486 (from the #240 verification): a position nobody has priced is not shown as exactly flat.

The row still carries the entry price as its stand-in (totals and old callers keep working), but now says so:
`price_status` is "none" and `has_price` is false, so a screen can say "No price yet" instead of "0.0%".
Failed on `5de3b9c` (the row had no such field); passes with the fix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy

KEY = {"X-API-Key": "test-api-key"}
_tokens = count(486_900)


def _position(db, symbol: str, current_price):
    strat = Strategy(
        name=f"s486-{symbol}", strategy_type="ml_swing", mode="paper", execution_mode="auto", is_active=True
    )
    inst = Instrument(instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add_all([strat, inst])
    db.flush()
    db.add(
        Position(
            strategy_id=strat.id,
            instrument_id=inst.id,
            mode="paper",
            status="OPEN",
            quantity=10,
            entry_price=100.0,
            entry_at=datetime.now(UTC) - timedelta(days=2),
            current_price=current_price,
            stop_loss=96.0,
            take_profit=108.0,
            total_charges=1.0,
        )
    )
    db.commit()


def _rows(client):
    return {r["symbol"]: r for r in client.get("/api/v1/portfolio/positions/detailed", headers=KEY).json()}


def test_a_never_priced_position_says_it_has_no_price(client, db_session):
    _position(db_session, "NOPRICE486", None)
    row = _rows(client)["NOPRICE486"]
    assert row["has_price"] is False and row["price_status"] == "none"


def test_a_priced_position_says_so(client, db_session):
    _position(db_session, "PRICED486", 103.0)
    row = _rows(client)["PRICED486"]
    assert row["has_price"] is True and row["price_status"] == "ok"
    assert row["current_price"] == 103.0 and round(row["unrealized_pnl_pct"], 4) == 0.03


def test_the_stand_in_numbers_stay_so_totals_and_older_callers_are_unchanged(client, db_session):
    _position(db_session, "STANDIN486", None)
    row = _rows(client)["STANDIN486"]
    assert (
        row["current_price"] == 100.0 and row["unrealized_pnl_pct"] == 0.0
    )  # the entry price, flagged by has_price
