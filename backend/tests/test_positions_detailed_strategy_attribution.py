"""positions/detailed exposes which strategy opened each position — see
docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5c."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy

HEADERS = {"X-API-Key": "test-api-key"}


def test_open_position_carries_strategy_name_and_cap_tier(client, db_session):
    strat = Strategy(
        name="ml_swing_midcap",
        strategy_type="ml_swing",
        mode="paper",
        is_active=True,
        params={"model_name": "swing_classifier_midcap"},
    )
    db_session.add(strat)
    db_session.flush()

    inst = Instrument(instrument_token=555001, tradingsymbol="TESTMID", exchange="NSE", is_watchlisted=True)
    db_session.add(inst)
    db_session.flush()

    position = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        quantity=10,
        entry_price=100.0,
        current_price=110.0,
        stop_loss=90.0,
        entry_at=datetime.now(UTC),
        status=PositionStatus.OPEN,
    )
    db_session.add(position)
    db_session.commit()

    resp = client.get("/api/v1/portfolio/positions/detailed", headers=HEADERS)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["symbol"] == "TESTMID")
    assert row["strategy_name"] == "ml_swing_midcap"
    assert row["cap_tier"] == "midcap"
