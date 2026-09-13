"""Shape tests for the mutual fund tables — see
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §5."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav


def test_mutual_fund_and_nav_and_holding_round_trip(db_session):
    fund = MutualFund(
        scheme_code="100033",
        name="Test Bluechip Fund - Direct Growth",
        amc_name="Test AMC",
        category="Equity",
        is_tracked=True,
    )
    db_session.add(fund)
    db_session.flush()

    nav_row = MutualFundNav(scheme_id=fund.id, date=date(2026, 1, 1), nav=45.67)
    holding = MutualFundHolding(
        scheme_id=fund.id, units=100.0, purchase_nav=40.0, purchase_date=date(2025, 6, 1),
    )
    db_session.add_all([nav_row, holding])
    db_session.flush()

    assert fund.is_tracked is True
    assert nav_row.nav == 45.67
    assert holding.units == 100.0
