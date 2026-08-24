"""Spending analytics over categorized transactions.

Ported from the standalone finance-dashboard app, trimmed to the v1 "core"
scope: no loans/EMI/investment-specific breakdowns (`expense_df` here simply
excludes non-expense directions, unlike the source app's version which also
carved out EMI/interest rows for a separate loans view that doesn't exist
here).
"""

from __future__ import annotations

import pandas as pd


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])
    if data["date"].dt.tz is not None:
        data["date"] = data["date"].dt.tz_localize(None)
    data["month"] = data["date"].dt.to_period("M").astype(str)
    data["amount"] = pd.to_numeric(data["amount"], errors="coerce").fillna(0.0)
    data["direction"] = data["direction"].fillna("UNKNOWN").str.upper()
    return data


def expense_df(df: pd.DataFrame) -> pd.DataFrame:
    data = prepare(df)
    return data[data["direction"].isin(["DEBIT", "UNKNOWN"])].copy()


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    exp = expense_df(df)
    return (
        exp.groupby("month", as_index=False)
        .agg(total_expense=("amount", "sum"), transaction_count=("amount", "size"), avg_transaction=("amount", "mean"))
        .sort_values("month")
    )


def category_summary(df: pd.DataFrame) -> pd.DataFrame:
    exp = expense_df(df)
    return (
        exp.groupby("category", as_index=False)
        .agg(total_expense=("amount", "sum"), transaction_count=("amount", "size"), avg_transaction=("amount", "mean"))
        .sort_values("total_expense", ascending=False)
    )


def monthly_category_summary(df: pd.DataFrame) -> pd.DataFrame:
    exp = expense_df(df)
    return (
        exp.groupby(["month", "category"], as_index=False)
        .agg(total_expense=("amount", "sum"), transaction_count=("amount", "size"))
        .sort_values(["month", "total_expense"], ascending=[True, False])
    )


def merchant_summary(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    exp = expense_df(df)
    return (
        exp.groupby("description", as_index=False)
        .agg(total_expense=("amount", "sum"), transaction_count=("amount", "size"))
        .sort_values("total_expense", ascending=False)
        .head(top_n)
    )


def generate_insights(df: pd.DataFrame) -> list[str]:
    exp = expense_df(df)
    if exp.empty:
        return ["No expense transactions found yet."]

    monthly = monthly_summary(exp)
    category = category_summary(exp)
    merchants = merchant_summary(exp, top_n=5)

    total = exp["amount"].sum()
    avg_month = monthly["total_expense"].mean() if not monthly.empty else 0
    highest_month = monthly.sort_values("total_expense", ascending=False).iloc[0]
    top_category = category.iloc[0]
    top_merchant = merchants.iloc[0]

    insights = [
        f"Total tracked expenses: ₹{total:,.0f} across {len(exp):,} transactions.",
        f"Average monthly expense: ₹{avg_month:,.0f}.",
        f"Highest spending month: {highest_month['month']} with ₹{highest_month['total_expense']:,.0f}.",
        f"Top category: {top_category['category']} at ₹{top_category['total_expense']:,.0f}.",
        f"Top merchant/description: {top_merchant['description']} at ₹{top_merchant['total_expense']:,.0f}.",
    ]

    uncategorised = exp[exp["category"].eq("Uncategorised")]["amount"].sum()
    if uncategorised > 0:
        insights.append(f"₹{uncategorised:,.0f} is still uncategorised. Add rules for better accuracy.")

    return insights
