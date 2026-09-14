# backend/tests/test_trades_strategy_attribution.py
"""GET /portfolio/trades exposes which strategy made each trade — see
docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5c."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy, Trade

HEADERS = {"X-API-Key": "test-api-key"}


def test_trade_row_carries_strategy_name_and_cap_tier(client, db_session):
    strat = Strategy(
        name="ml_swing_smallcap",
        strategy_type="ml_swing",
        mode="paper",
        params={"model_name": "swing_classifier_smallcap"},
    )
    db_session.add(strat)
    db_session.flush()

    inst = Instrument(instrument_token=555002, tradingsymbol="TESTSMALL", exchange="NSE", is_watchlisted=True)
    db_session.add(inst)
    db_session.flush()

    now = datetime.now(UTC)
    trade = Trade(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        symbol="TESTSMALL",
        quantity=10,
        entry_price=100.0,
        exit_price=120.0,
        entry_at=now - timedelta(days=5),
        exit_at=now,
        holding_days=5,
        gross_pnl=200.0,
        charges=10.0,
        net_pnl=190.0,
        return_pct=0.19,
        is_win=True,
    )
    db_session.add(trade)
    db_session.commit()

    resp = client.get("/api/v1/portfolio/trades", headers=HEADERS)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["symbol"] == "TESTSMALL")
    assert row["strategy_name"] == "ml_swing_smallcap"
    assert row["cap_tier"] == "smallcap"
