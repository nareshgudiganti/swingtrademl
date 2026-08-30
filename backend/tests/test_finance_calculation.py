"""The Calculation tab's numbers: debits, credits, and net for a filtered
scope — computed directly from analytics.expense_df/income_df, matching
what the /finance/calculation endpoint does."""

from __future__ import annotations

from swing_trade_ml.services.finance import analytics
from swing_trade_ml.services.finance.ingestion import ingest_statement, transactions_dataframe

FIXTURE_CSV = (
    b"date,description,amount,direction\n"
    b"2026-04-01,Swiggy Food Order,550,DEBIT\n"
    b"2026-04-05,Amazon Shopping,3200,DEBIT\n"
    b"2026-04-10,OD Sweep out,50000,DEBIT\n"
    b"2026-04-15,Rev Sweep in,50000,CREDIT\n"
    b"2026-04-30,Salary Credit,90000,CREDIT\n"
)


def _calculation_totals(df):
    debits = analytics.expense_df(df)
    credits = analytics.income_df(df)
    return {
        "total_debits": float(debits["amount"].sum()),
        "total_credits": float(credits["amount"].sum()),
        "net": float(credits["amount"].sum()) - float(debits["amount"].sum()),
        "transaction_count": len(debits) + len(credits),
    }


def test_calculation_totals_exclude_internal_transfer_sweeps(db_session):
    ingest_statement(db_session, "april.csv", FIXTURE_CSV)

    df = transactions_dataframe(db_session, month="2026-04")
    totals = _calculation_totals(df)

    # Debits: Swiggy (550) + Amazon (3200) = 3750 — the 50,000 sweep-out
    # must NOT be counted.
    assert totals["total_debits"] == 3750.0
    # Credits: Salary (90000) only — the 50,000 sweep-in must NOT be counted.
    assert totals["total_credits"] == 90000.0
    assert totals["net"] == 90000.0 - 3750.0
    assert totals["transaction_count"] == 3  # 2 real debits + 1 real credit


def test_calculation_totals_are_scoped_by_month_filter(db_session):
    ingest_statement(db_session, "april.csv", FIXTURE_CSV)

    df = transactions_dataframe(db_session, month="2026-05")
    totals = _calculation_totals(df) if not df.empty else {
        "total_debits": 0.0, "total_credits": 0.0, "net": 0.0, "transaction_count": 0,
    }

    assert totals == {"total_debits": 0.0, "total_credits": 0.0, "net": 0.0, "transaction_count": 0}


def test_calculation_totals_are_scoped_by_direction_filter(db_session):
    ingest_statement(db_session, "april.csv", FIXTURE_CSV)

    df = transactions_dataframe(db_session, direction="DEBIT")
    totals = _calculation_totals(df)

    assert totals["total_debits"] == 3750.0
    assert totals["total_credits"] == 0.0
