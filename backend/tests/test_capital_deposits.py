"""Money the owner adds to the paper account is never profit.

A top-up raises cash and account value by the same amount. Day P&L, returns and the drawdown
peak are all built from account value, so each one has to take the deposit out. A loss after a
top-up must still show as a loss, and a top-up must never hide or create a drawdown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.brokers import paper_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.trading import PortfolioSnapshot
from swing_trade_ml.services import capital
from swing_trade_ml.services import portfolio as portfolio_service

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.fixture()
def funded(monkeypatch):
    """Paper account first funded with ₹10 lakh, no trial boundary."""
    monkeypatch.setattr(settings, "PAPER_STARTING_CAPITAL", 1_000_000.0)
    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", None)


def _snapshot(db, ts, value, *, peak=None, drawdown=0.0):
    row = PortfolioSnapshot(
        mode="paper", ts=ts, cash=value, holdings_value=0.0, total_value=value,
        peak_value=peak if peak is not None else value, drawdown_pct=drawdown,
    )
    db.add(row)
    db.commit()
    return row


def _value_now(monkeypatch, value):
    monkeypatch.setattr(
        portfolio_service, "portfolio_value_and_cash", lambda db, mode, **kw: (value, value)
    )


# ---- the arithmetic, no database --------------------------------------------


def test_restate_adds_only_the_money_that_came_later():
    deposits = [(T0 + DAY, 100.0), (T0 + 3 * DAY, 50.0)]
    assert capital.restate(1000.0, T0, deposits) == 1150.0
    assert capital.restate(1000.0, T0 + 2 * DAY, deposits) == 1050.0
    assert capital.restate(1000.0, T0 + 3 * DAY, deposits) == 1000.0


def test_time_weighted_return_ignores_the_size_and_timing_of_a_top_up():
    points = [(T0, 100.0), (T0 + DAY, 110.0), (T0 + 2 * DAY, 210.0), (T0 + 3 * DAY, 231.0)]
    deposits = [(T0 + 2 * DAY, 100.0)]
    # +10%, then 0% (the whole jump is the deposit), then +10%.
    assert capital.time_weighted_return(points, deposits) == pytest.approx(0.21)


def test_time_weighted_return_with_no_deposits_is_plain_growth():
    assert capital.time_weighted_return([(T0, 100.0), (T0 + DAY, 90.0)], []) == pytest.approx(-0.10)
    assert capital.time_weighted_return([(T0, 100.0)], []) == 0.0


# ---- cash ----------------------------------------------------------------


def test_a_top_up_must_be_more_than_zero(funded, db_session):
    with pytest.raises(ValueError):
        capital.add_deposit(db_session, 0)
    with pytest.raises(ValueError):
        capital.add_deposit(db_session, -5)


def test_paper_cash_grows_by_the_amount_added(funded, db_session):
    before = paper_broker.get_available_cash(db_session)
    capital.add_deposit(db_session, 4_000_000, ts=T0)
    assert paper_broker.get_available_cash(db_session) == pytest.approx(before + 4_000_000)


# ---- the daily snapshot --------------------------------------------------


def test_top_up_is_not_day_profit_and_lifts_the_peak(funded, monkeypatch, db_session):
    _snapshot(db_session, datetime.now(UTC) - 3 * DAY, 1_000_000.0)
    capital.add_deposit(db_session, 4_000_000, ts=datetime.now(UTC) - 2 * DAY)
    _value_now(monkeypatch, 5_010_000.0)  # the top-up plus ₹10,000 of real gain

    snap = portfolio_service.take_snapshot(db_session, "paper")

    assert snap.day_pnl == pytest.approx(10_000.0)
    assert snap.peak_value == pytest.approx(5_010_000.0)
    assert snap.drawdown_pct == 0.0


def test_a_loss_after_a_top_up_still_shows_as_a_loss(funded, monkeypatch, db_session):
    _snapshot(db_session, datetime.now(UTC) - 3 * DAY, 1_000_000.0)
    capital.add_deposit(db_session, 4_000_000, ts=datetime.now(UTC) - 2 * DAY)
    _value_now(monkeypatch, 4_900_000.0)  # ₹1 lakh lost on a ₹50 lakh account

    snap = portfolio_service.take_snapshot(db_session, "paper")

    assert snap.day_pnl == pytest.approx(-100_000.0)
    assert snap.peak_value == pytest.approx(5_000_000.0)
    assert snap.drawdown_pct == pytest.approx(0.02)


def test_the_first_snapshot_after_funding_counts_every_top_up_as_money_in(funded, monkeypatch, db_session):
    capital.add_deposit(db_session, 4_000_000, ts=datetime.now(UTC) - DAY)
    _value_now(monkeypatch, 5_020_000.0)

    snap = portfolio_service.take_snapshot(db_session, "paper")

    assert snap.day_pnl == pytest.approx(20_000.0)


# ---- the report ----------------------------------------------------------


def test_report_separates_profit_from_money_added(funded, monkeypatch, db_session):
    _snapshot(db_session, T0, 1_000_000.0)
    _snapshot(db_session, T0 + DAY, 1_100_000.0)  # +10%
    capital.add_deposit(db_session, 4_000_000, ts=T0 + DAY + timedelta(hours=6))
    _snapshot(db_session, T0 + 2 * DAY, 5_100_000.0)  # flat: the jump is the deposit
    _snapshot(db_session, T0 + 3 * DAY, 5_610_000.0)  # +10%
    _value_now(monkeypatch, 5_610_000.0)

    stats = portfolio_service.performance_stats(db_session, "paper")

    assert stats["money_added"] == pytest.approx(4_000_000.0)
    assert stats["money_in"] == pytest.approx(5_000_000.0)
    assert stats["total_return_pct"] == pytest.approx(5_610_000 / 5_000_000 - 1)
    assert stats["time_weighted_return_pct"] == pytest.approx(1.1 * 1.0 * 1.1 - 1)
    assert stats["max_drawdown_pct"] == 0.0


def test_report_with_no_top_ups_is_unchanged(funded, monkeypatch, db_session):
    _snapshot(db_session, T0, 1_000_000.0)
    _snapshot(db_session, T0 + DAY, 1_050_000.0)
    _value_now(monkeypatch, 1_050_000.0)

    stats = portfolio_service.performance_stats(db_session, "paper")

    assert stats["money_added"] == 0.0
    assert stats["money_in"] == pytest.approx(1_000_000.0)
    assert stats["total_return_pct"] == pytest.approx(0.05)
    assert stats["time_weighted_return_pct"] == pytest.approx(0.05)


# ---- the 15% halt --------------------------------------------------------


def test_a_top_up_neither_hides_nor_creates_a_drawdown(funded, db_session):
    from swing_trade_ml.services.risk import current_drawdown

    _snapshot(db_session, T0, 1_000_000.0, peak=1_000_000.0)
    capital.add_deposit(db_session, 4_000_000, ts=T0 + DAY)

    # Peak is restated to today's capital: ₹10L + ₹40L.
    assert portfolio_service.drawdown_peak(db_session, "paper") == pytest.approx(5_000_000.0)
    assert current_drawdown(db_session, "paper", current_value=5_000_000.0) == 0.0
    assert current_drawdown(db_session, "paper", current_value=4_250_000.0) == pytest.approx(0.15)


# ---- the API ------------------------------------------------------------

API_KEY = {"X-API-Key": "test-api-key"}


def test_api_records_a_top_up_and_lists_it(funded, client, db_session):
    posted = client.post(
        "/api/v1/portfolio/capital-added",
        json={"amount": 4_000_000, "note": "phase 1 top-up"},
        headers=API_KEY,
    )
    assert posted.status_code == 201, posted.text
    assert posted.json()["added"] == 4_000_000

    listed = client.get("/api/v1/portfolio/capital-added", headers=API_KEY).json()
    assert listed["total_added"] == 4_000_000
    assert listed["starting_capital"] == 1_000_000.0
    assert len(listed["added"]) == 1


def test_api_refuses_a_zero_or_negative_top_up(funded, client):
    for amount in (0, -100):
        r = client.post("/api/v1/portfolio/capital-added", json={"amount": amount}, headers=API_KEY)
        assert r.status_code == 422
