"""CAS (Consolidated Account Statement) import — turns CAMS/KFintech
transaction history into this app's per-lot mutual fund holdings. See
docs/superpowers/specs/2026-09-13-cas-import-design.md."""

from __future__ import annotations

from datetime import date

import pytest
from casparser.types import TransactionType

from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding


def _txn(type_, units=None, nav=None, txn_date=date(2026, 1, 1)):
    return {"type": type_, "units": units, "nav": nav, "date": txn_date}


# ------------------------------------------------------------ pure FIFO --


def test_build_lots_creates_one_lot_per_purchase():
    from swing_trade_ml.services.finance.cas_import import build_lots_from_transactions

    transactions = [
        _txn(TransactionType.PURCHASE, units=100.0, nav=10.0, txn_date=date(2026, 1, 1)),
        _txn(TransactionType.PURCHASE_SIP, units=50.0, nav=11.0, txn_date=date(2026, 2, 1)),
    ]

    lots = build_lots_from_transactions(transactions)

    assert lots == [
        {"units": 100.0, "purchase_nav": 10.0, "purchase_date": date(2026, 1, 1)},
        {"units": 50.0, "purchase_nav": 11.0, "purchase_date": date(2026, 2, 1)},
    ]


def test_build_lots_fifo_reduces_earliest_lot_on_partial_redemption():
    from swing_trade_ml.services.finance.cas_import import build_lots_from_transactions

    transactions = [
        _txn(TransactionType.PURCHASE, units=100.0, nav=10.0, txn_date=date(2026, 1, 1)),
        _txn(TransactionType.PURCHASE, units=100.0, nav=12.0, txn_date=date(2026, 2, 1)),
        _txn(TransactionType.REDEMPTION, units=50.0, nav=13.0, txn_date=date(2026, 3, 1)),
    ]

    lots = build_lots_from_transactions(transactions)

    assert lots == [
        {"units": 50.0, "purchase_nav": 10.0, "purchase_date": date(2026, 1, 1)},
        {"units": 100.0, "purchase_nav": 12.0, "purchase_date": date(2026, 2, 1)},
    ]


def test_build_lots_removes_lot_entirely_when_fully_redeemed():
    from swing_trade_ml.services.finance.cas_import import build_lots_from_transactions

    transactions = [
        _txn(TransactionType.PURCHASE, units=100.0, nav=10.0, txn_date=date(2026, 1, 1)),
        _txn(TransactionType.REDEMPTION, units=100.0, nav=13.0, txn_date=date(2026, 3, 1)),
    ]

    lots = build_lots_from_transactions(transactions)

    assert lots == []


def test_build_lots_redemption_spanning_multiple_lots():
    from swing_trade_ml.services.finance.cas_import import build_lots_from_transactions

    transactions = [
        _txn(TransactionType.PURCHASE, units=50.0, nav=10.0, txn_date=date(2026, 1, 1)),
        _txn(TransactionType.PURCHASE, units=50.0, nav=12.0, txn_date=date(2026, 2, 1)),
        _txn(TransactionType.REDEMPTION, units=70.0, nav=13.0, txn_date=date(2026, 3, 1)),
    ]

    lots = build_lots_from_transactions(transactions)

    assert lots == [
        {"units": 30.0, "purchase_nav": 12.0, "purchase_date": date(2026, 2, 1)},
    ]


def test_build_lots_ignores_transactions_without_a_unit_effect():
    """Dividend payouts and tax lines carry an amount but no unit change —
    they must not disturb the FIFO queue."""
    from swing_trade_ml.services.finance.cas_import import build_lots_from_transactions

    transactions = [
        _txn(TransactionType.PURCHASE, units=100.0, nav=10.0, txn_date=date(2026, 1, 1)),
        _txn(TransactionType.DIVIDEND_PAYOUT, units=None, nav=None, txn_date=date(2026, 1, 15)),
        _txn(TransactionType.STT_TAX, units=None, nav=None, txn_date=date(2026, 1, 15)),
    ]

    lots = build_lots_from_transactions(transactions)

    assert lots == [{"units": 100.0, "purchase_nav": 10.0, "purchase_date": date(2026, 1, 1)}]


# ------------------------------------------------------------- DB import --


def _cas_data(scheme_amfi="100033", scheme_name="Test Fund - Direct Growth", folio="F1", transactions=None):
    from casparser.types import CASData, CASFileType, FileType, Folio, InvestorInfo, Scheme, SchemeValuation, StatementPeriod

    transactions = transactions if transactions is not None else [
        _txn(TransactionType.PURCHASE, units=100.0, nav=10.0, txn_date=date(2026, 1, 1)),
    ]
    scheme = Scheme(
        scheme=scheme_name,
        rta_code="RT1",
        rta="CAMS",
        isin="INF000X01ABC",
        amfi=scheme_amfi,
        open=0,
        close=sum(t["units"] or 0 for t in transactions if t["type"] in (TransactionType.PURCHASE, TransactionType.PURCHASE_SIP)),
        close_calculated=0,
        valuation=SchemeValuation(date=date(2026, 3, 1), nav=13.0, cost=1000, value=1300),
        transactions=[
            {"date": t["date"], "description": "txn", "type": t["type"], "units": t["units"], "nav": t["nav"]}
            for t in transactions
        ],
    )
    folio_obj = Folio(folio=folio, amc="Test AMC", schemes=[scheme])
    return CASData(
        statement_period=StatementPeriod(from_="2026-01-01", to="2026-03-01"),
        folios=[folio_obj],
        investor_info=InvestorInfo(name="Test User", email="t@example.com", address="-", mobile="-"),
        cas_type=CASFileType.DETAILED,
        file_type=FileType.CAMS,
    )


@pytest.fixture(autouse=True)
def _no_real_amfi_network(monkeypatch):
    """import_cas_data seeds a NAV snapshot via sync_nav_snapshot(db) the
    first time a scheme becomes tracked — patch the network call out, same
    as test_mutual_funds_api.py."""

    class _FakeResponse:
        text = (
            "Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;"
            "Scheme Name;Net Asset Value;Date\n"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        "swing_trade_ml.services.finance.mutual_funds.httpx.get",
        lambda *args, **kwargs: _FakeResponse(),
    )


def test_import_cas_data_matches_scheme_by_amfi_code_and_creates_holdings(db_session):
    from swing_trade_ml.services.finance.cas_import import import_cas_data

    fund = MutualFund(scheme_code="100033", name="Test Fund - Direct Growth", is_tracked=False)
    db_session.add(fund)
    db_session.commit()

    result = import_cas_data(db_session, _cas_data(scheme_amfi="100033"))

    assert result.schemes_matched == 1
    assert result.lots_created == 1
    assert result.unmatched_schemes == []

    holdings = db_session.query(MutualFundHolding).filter_by(scheme_id=fund.id).all()
    assert len(holdings) == 1
    assert holdings[0].units == 100.0
    assert holdings[0].purchase_nav == 10.0
    assert holdings[0].source == "cas"
    assert holdings[0].folio_number == "F1"

    db_session.refresh(fund)
    assert fund.is_tracked is True


def test_import_cas_data_flags_unmatched_scheme(db_session):
    from swing_trade_ml.services.finance.cas_import import import_cas_data

    result = import_cas_data(db_session, _cas_data(scheme_amfi="999999", scheme_name="Unknown Fund"))

    assert result.schemes_matched == 0
    assert result.unmatched_schemes == ["Unknown Fund"]


def test_import_cas_data_replaces_cas_holdings_without_touching_manual_ones(db_session):
    from swing_trade_ml.services.finance.cas_import import import_cas_data

    fund = MutualFund(scheme_code="100033", name="Test Fund - Direct Growth", is_tracked=True)
    db_session.add(fund)
    db_session.flush()
    manual = MutualFundHolding(
        scheme_id=fund.id, units=10.0, purchase_nav=5.0, purchase_date=date(2020, 1, 1), source="manual"
    )
    db_session.add(manual)
    db_session.commit()

    import_cas_data(db_session, _cas_data(scheme_amfi="100033"))
    import_cas_data(db_session, _cas_data(scheme_amfi="100033"))  # re-import must not duplicate

    holdings = db_session.query(MutualFundHolding).filter_by(scheme_id=fund.id).order_by(MutualFundHolding.source).all()
    assert len(holdings) == 2
    sources = sorted(h.source for h in holdings)
    assert sources == ["cas", "manual"]
    cas_holding = next(h for h in holdings if h.source == "cas")
    assert cas_holding.units == 100.0
