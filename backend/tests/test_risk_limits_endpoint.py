"""GET /risk/limits — the read side of the account-size ladder.

check_entry enforces these numbers; this endpoint just reports them, so a
frontend can show the capital ladder without duplicating any of the logic
in services/limits.py or services/deployable.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy

HEADERS = {"X-API-Key": "test-api-key"}


def test_requires_auth(client):
    resp = client.get("/api/v1/risk/limits")
    assert resp.status_code in (401, 403)


def test_returns_limits_for_the_current_paper_account(client, db_session):
    resp = client.get("/api/v1/risk/limits", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    # PAPER_STARTING_CAPITAL in the test .env is 10L — check_entry's own
    # portfolio_value_and_cash() is what this endpoint reads, so this is
    # the same figure risk.check_entry would size a trade against.
    assert body["portfolio_value"] > 0
    assert body["max_positions"] >= 1
    assert 0 < body["deployable_fraction"] <= 1
    assert body["sectors"] == []  # nothing open yet


def test_reflects_open_positions_by_sector(client, db_session):
    inst = Instrument(
        instrument_token=999001, tradingsymbol="ICICIBANK", exchange="NSE", is_watchlisted=True
    )
    db_session.add(inst)
    db_session.flush()
    strat = Strategy(name="limits_test_strategy", strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    db_session.add(
        Position(
            strategy_id=strat.id, instrument_id=inst.id, mode="paper",
            status="OPEN", quantity=10, entry_price=1000.0,
            entry_at=datetime.now(UTC), current_price=1000.0,
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/risk/limits", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["open_positions"] == 1
    assert body["invested_inr"] == 10_000.0
    sectors = {s["sector"]: s["value_inr"] for s in body["sectors"]}
    assert sectors.get("Banking") == 10_000.0


def test_unmapped_symbol_is_reported_unclassified_not_dropped(client, db_session):
    inst = Instrument(
        instrument_token=999002, tradingsymbol="ZZZNOTASECTOR", exchange="NSE", is_watchlisted=True
    )
    db_session.add(inst)
    db_session.flush()
    strat = Strategy(name="limits_test_unmapped", strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    db_session.add(
        Position(
            strategy_id=strat.id, instrument_id=inst.id, mode="paper",
            status="OPEN", quantity=5, entry_price=200.0,
            entry_at=datetime.now(UTC), current_price=200.0,
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/risk/limits", headers=HEADERS)
    assert resp.status_code == 200
    sectors = {s["sector"]: s["value_inr"] for s in resp.json()["sectors"]}
    assert sectors.get("Unclassified") == 1_000.0
