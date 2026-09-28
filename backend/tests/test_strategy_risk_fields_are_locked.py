"""Risk and exit rules are identical for every strategy and cannot be set per strategy.

The owner's decision (2026-09-28): a configuration choice may change which
stocks are considered, never how much money is at risk or when a position is
closed. Those rules are global settings, and v1 is defined as the frozen,
safest baseline.

The API did not enforce that. `PATCH /strategies/{id}` accepted
`stop_loss_pct`, `take_profit_pct`, `max_positions`, `capital_allocation` and
`allow_pyramiding`, and `update_strategy` setattr'd whatever arrived onto the
row. For the three ML strategies those fields happened to be inert — ml_swing
reads the global settings and ignores the columns — but "it is ignored
downstream" is not a boundary, it is a coincidence. sma_crossover does read
`config.stop_loss_pct`, so the benchmark's stop really was editable.

Rejecting at the schema means the request never reaches the row, and the
message says why rather than failing with a generic "extra field".
"""

from __future__ import annotations

import pytest

from swing_trade_ml.db.models.trading import Strategy

HEADERS = {"X-API-Key": "test-api-key"}

LOCKED = {
    "stop_loss_pct": 0.02,
    "take_profit_pct": 0.20,
    "max_positions": 40,
    "capital_allocation": 0.95,
    "allow_pyramiding": True,
}


@pytest.fixture
def strategy(db_session) -> Strategy:
    row = Strategy(
        name="locked_fields_probe",
        strategy_type="ml_swing",
        mode="paper",
        is_active=True,
        execution_mode="auto",
        params={"model_name": "swing_classifier"},
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.mark.parametrize("field,value", sorted(LOCKED.items()))
def test_patch_rejects_every_risk_and_exit_field(client, strategy, field, value):
    response = client.patch(
        f"/api/v1/strategies/{strategy.id}", json={field: value}, headers=HEADERS
    )

    assert response.status_code == 422
    assert field in response.text
    assert "same for every strategy" in response.text


@pytest.mark.parametrize("field,value", sorted(LOCKED.items()))
def test_create_rejects_every_risk_and_exit_field(client, field, value):
    response = client.post(
        "/api/v1/strategies",
        json={"name": f"new_{field}", "strategy_type": "ml_swing", field: value},
        headers=HEADERS,
    )

    assert response.status_code == 422
    assert field in response.text


def test_a_locked_knob_smuggled_inside_params_is_rejected_too(client, strategy):
    """`params` is a free-form dict, so it is the obvious way around a
    top-level block. Both doors have to be shut or neither is."""
    response = client.patch(
        f"/api/v1/strategies/{strategy.id}",
        json={"params": {"model_name": "swing_classifier", "stop_loss_pct": 0.02}},
        headers=HEADERS,
    )

    assert response.status_code == 422
    assert "stop_loss_pct" in response.text


def test_the_row_is_untouched_when_a_request_is_rejected(client, db_session, strategy):
    """A rejected PATCH must not half-apply: the legal fields in the same
    request are discarded with the illegal one."""
    response = client.patch(
        f"/api/v1/strategies/{strategy.id}",
        json={"description": "should not stick", "stop_loss_pct": 0.02},
        headers=HEADERS,
    )

    assert response.status_code == 422
    db_session.refresh(strategy)
    assert strategy.description != "should not stick"


def test_selection_and_housekeeping_fields_still_work(client, db_session, strategy):
    """The boundary must not become a wall. Which stocks a strategy looks at,
    what it is called, and whether it runs are all still editable."""
    response = client.patch(
        f"/api/v1/strategies/{strategy.id}",
        json={
            "description": "large caps only",
            "symbols": ["TCS", "INFY"],
            "is_active": False,
            "params": {"model_name": "swing_classifier", "min_confidence": 0.65},
        },
        headers=HEADERS,
    )

    assert response.status_code == 200
    db_session.refresh(strategy)
    assert strategy.symbols == ["TCS", "INFY"]
    assert strategy.params["min_confidence"] == 0.65
    assert strategy.is_active is False
