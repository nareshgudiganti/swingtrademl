"""Sweep/internal-transfer detection: a sweep-in (CREDIT) and sweep-out
(DEBIT) both land in "Internal Transfer", and that category is excluded
from every total."""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.services.finance import analytics
from swing_trade_ml.services.finance.categorizer import categorize_transactions, load_rules


def _txn(description: str, amount: float, direction: str, raw_text: str = ""):
    return {
        "date": "2026-03-10",
        "month": "2026-03",
        "description": description,
        "amount": amount,
        "direction": direction,
        "status": "",
        "transaction_id": "",
        "source": "Bank Statement",
        "raw_text": raw_text or description,
    }


def test_sweep_out_debit_is_categorized_as_internal_transfer():
    df = pd.DataFrame([_txn("OD Sweep to linked account", 25000.0, "DEBIT")])
    result = categorize_transactions(df, load_rules())
    assert result.iloc[0]["category"] == "Internal Transfer"


def test_sweep_in_credit_is_categorized_as_internal_transfer_not_income():
    # Without the CREDIT_OVERRIDE_CATEGORIES fix this would stay
    # "Income / Credit" — a sweep-in is not income.
    df = pd.DataFrame([_txn("Rev Sweep from linked account", 25000.0, "CREDIT")])
    result = categorize_transactions(df, load_rules())
    assert result.iloc[0]["category"] == "Internal Transfer"


def test_ordinary_credit_is_unaffected_by_the_sweep_override():
    df = pd.DataFrame([_txn("Salary Credit", 90000.0, "CREDIT")])
    result = categorize_transactions(df, load_rules())
    assert result.iloc[0]["category"] == "Income"


def test_expense_df_excludes_internal_transfer_from_debit_totals():
    df = pd.DataFrame(
        [
            {**_txn("OD Sweep out", 25000.0, "DEBIT"), "category": "Internal Transfer"},
            {**_txn("Swiggy Food Order", 500.0, "DEBIT"), "category": "Food / Restaurants"},
        ]
    )
    exp = analytics.expense_df(df)
    assert len(exp) == 1
    assert exp.iloc[0]["category"] == "Food / Restaurants"
    assert exp["amount"].sum() == 500.0


def test_income_df_excludes_internal_transfer_from_credit_totals():
    df = pd.DataFrame(
        [
            {**_txn("Rev Sweep in", 25000.0, "CREDIT"), "category": "Internal Transfer"},
            {**_txn("Salary Credit", 90000.0, "CREDIT"), "category": "Income"},
        ]
    )
    inc = analytics.income_df(df)
    assert len(inc) == 1
    assert inc.iloc[0]["category"] == "Income"
    assert inc["amount"].sum() == 90000.0


def test_generate_insights_never_mentions_internal_transfer_as_top_category():
    df = pd.DataFrame(
        [
            {**_txn("OD Sweep out", 100000.0, "DEBIT"), "category": "Internal Transfer"},
            {**_txn("Swiggy Food Order", 500.0, "DEBIT"), "category": "Food / Restaurants"},
        ]
    )
    insights = analytics.generate_insights(df)
    assert not any("Internal Transfer" in line for line in insights)
