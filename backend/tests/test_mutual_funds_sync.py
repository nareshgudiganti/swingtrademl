"""AMFI NAVAll.txt parsing and sync — see
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §4, §6."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav

SAMPLE_NAVALL = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Large Cap Fund)

100033;INF204K01UN8;-;Test Bluechip Fund - Direct Growth;45.6700;01-Jan-2026
100034;INF204K01UN9;-;Test Bluechip Fund - Regular Growth;44.1200;01-Jan-2026

Open Ended Schemes(Debt Scheme - Liquid Fund)

200011;INF109K01234;-;Test Liquid Fund - Direct Growth;1234.5600;01-Jan-2026
"""


def test_parse_navall_extracts_rows_with_category():
    from swing_trade_ml.services.finance.mutual_funds import parse_navall

    rows = parse_navall(SAMPLE_NAVALL)

    assert len(rows) == 3
    first = rows[0]
    assert first["scheme_code"] == "100033"
    assert first["name"] == "Test Bluechip Fund - Direct Growth"
    assert first["nav"] == 45.67
    assert first["date"] == date(2026, 1, 1)
    assert first["category"] == "Equity Scheme - Large Cap Fund"
    assert rows[2]["category"] == "Debt Scheme - Liquid Fund"


REAL_FORMAT_NAVALL = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Children's Fund - Childrens' Fund)

Axis Mutual Fund

135762;INF846K01WO1;-;Axis Children's Fund;Direct Plan;Growth Option;29.9628;11-Sep-2026
"""


def test_parse_navall_handles_the_live_plan_option_column_format():
    """AMFI's current live NAVAll.txt inserts Plan/Option columns before NAV
    and Date (8 fields, not the older 6) and prints an AMC-name banner line
    (no ';') between the category header and its scheme rows — verified
    against a live download on 2026-09-13. NAV/Date must still parse
    correctly and the AMC banner must not stomp the category."""
    from swing_trade_ml.services.finance.mutual_funds import parse_navall

    rows = parse_navall(REAL_FORMAT_NAVALL)

    assert len(rows) == 1
    assert rows[0]["scheme_code"] == "135762"
    assert rows[0]["name"] == "Axis Children's Fund"
    assert rows[0]["nav"] == 29.9628
    assert rows[0]["date"] == date(2026, 9, 11)
    assert rows[0]["category"] == "Children's Fund - Childrens' Fund"


def test_sync_nav_snapshot_only_appends_navs_for_tracked_schemes(db_session):
    from swing_trade_ml.services.finance.mutual_funds import sync_nav_snapshot

    tracked = MutualFund(scheme_code="100033", name="old name", is_tracked=True)
    db_session.add(tracked)
    db_session.commit()

    count = sync_nav_snapshot(db_session, raw_text=SAMPLE_NAVALL)

    # 3 schemes seen in the feed -> 3 MutualFund rows upserted (name/category
    # kept fresh for all of them), but NAV history only appended for the one
    # already marked is_tracked.
    assert db_session.query(MutualFund).count() == 3
    assert count == 1
    nav_rows = db_session.query(MutualFundNav).filter_by(scheme_id=tracked.id).all()
    assert len(nav_rows) == 1
    assert nav_rows[0].nav == 45.67

    db_session.refresh(tracked)
    assert tracked.name == "Test Bluechip Fund - Direct Growth"  # kept in sync


def test_sync_nav_snapshot_is_idempotent_for_the_same_date(db_session):
    from swing_trade_ml.services.finance.mutual_funds import sync_nav_snapshot

    tracked = MutualFund(scheme_code="100033", name="Test Bluechip Fund - Direct Growth", is_tracked=True)
    db_session.add(tracked)
    db_session.commit()

    sync_nav_snapshot(db_session, raw_text=SAMPLE_NAVALL)
    sync_nav_snapshot(db_session, raw_text=SAMPLE_NAVALL)  # same date, run twice

    nav_rows = db_session.query(MutualFundNav).filter_by(scheme_id=tracked.id).all()
    assert len(nav_rows) == 1  # not duplicated


def test_holding_value_computes_absolute_and_annualized_return():
    from swing_trade_ml.services.finance.mutual_funds import holding_value

    holding = MutualFundHolding(units=100.0, purchase_nav=40.0, purchase_date=date(2025, 1, 1))
    result = holding_value(holding, latest_nav=44.0)

    assert result["current_value"] == 4400.0
    assert result["cost_basis"] == 4000.0
    assert result["absolute_return"] == 400.0
    assert round(result["absolute_return_pct"], 4) == 0.10


def test_holding_risk_computes_volatility_and_drawdown():
    from swing_trade_ml.services.finance.mutual_funds import holding_risk

    # Rises to 110, falls to 90 (an 18.2% drawdown from the 110 peak), recovers to 100.
    result = holding_risk([100, 105, 110, 95, 90, 100])

    assert result["volatility"] > 0
    assert round(result["max_drawdown"], 3) == -0.182
