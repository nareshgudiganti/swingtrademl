"""Loan/EMI amortization math, ported verbatim from the standalone finance
dashboard's `app.py`. Outstanding balance, closure estimates, and interest
are always computed fresh from a loan's stored terms — never persisted —
so editing a loan's numbers is reflected immediately on the next read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from swing_trade_ml.db.models.finance import FinanceLoan


def calculate_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    monthly_rate = annual_rate / 100 / 12
    if tenure_months <= 0:
        return 0.0
    if monthly_rate == 0:
        return principal / tenure_months
    factor = (1 + monthly_rate) ** tenure_months
    return principal * monthly_rate * factor / (factor - 1)


def loan_summary(principal: float, annual_rate: float, tenure_months: int, emi: float) -> dict[str, float]:
    monthly_rate = annual_rate / 100 / 12
    first_month_interest = principal * monthly_rate
    total_payment = emi * tenure_months
    total_interest = max(total_payment - principal, 0)
    return {
        "monthly_interest": first_month_interest,
        "yearly_interest": first_month_interest * 12,
        "total_interest": total_interest,
        "total_payment": total_payment,
    }


def months_to_close_loan(principal: float, annual_rate: float, monthly_payment: float) -> int | None:
    if principal <= 0:
        return 0
    monthly_rate = annual_rate / 100 / 12
    if monthly_payment <= principal * monthly_rate:
        return None

    balance = principal
    months = 0
    while balance > 0 and months < 1200:
        interest = balance * monthly_rate
        balance = balance + interest - monthly_payment
        months += 1
    return months if balance <= 0 else None


def interest_to_close_loan(principal: float, annual_rate: float, monthly_payment: float) -> float | None:
    if principal <= 0:
        return 0.0
    monthly_rate = annual_rate / 100 / 12
    if monthly_payment <= principal * monthly_rate:
        return None

    balance = principal
    interest_paid = 0.0
    months = 0
    while balance > 0 and months < 1200:
        interest = balance * monthly_rate
        principal_paid = monthly_payment - interest
        balance -= principal_paid
        interest_paid += interest
        months += 1
    return interest_paid if balance <= 0 else None


def elapsed_months_since(start_date: datetime) -> int:
    start = pd.Timestamp(start_date)
    today = pd.Timestamp.now(tz=start.tz)
    return max((today.year - start.year) * 12 + (today.month - start.month), 0)


def outstanding_balance(principal: float, annual_rate: float, monthly_payment: float, paid_months: int) -> float:
    balance = float(principal)
    monthly_rate = annual_rate / 100 / 12
    for _ in range(max(int(paid_months), 0)):
        if balance <= 0:
            return 0.0
        interest = balance * monthly_rate
        balance = balance + interest - monthly_payment
    return max(balance, 0.0)


def format_months(months: int | None) -> str:
    if months is None:
        return "Not closing"
    years, remaining_months = divmod(max(int(months), 0), 12)
    if years and remaining_months:
        return f"{years} years {remaining_months} months"
    if years:
        return f"{years} years"
    return f"{remaining_months} months"


def loan_projection(
    principal: float,
    annual_rate: float,
    tenure_months: int,
    emi: float,
    extra_payment: float,
    start_date: datetime,
) -> dict[str, object]:
    start = pd.Timestamp(start_date)
    scheduled_end = start + pd.DateOffset(months=int(tenure_months))
    monthly_payment = emi + extra_payment
    elapsed_months = min(elapsed_months_since(start), int(tenure_months))
    outstanding = outstanding_balance(principal, annual_rate, monthly_payment, elapsed_months)
    pending_months = months_to_close_loan(outstanding, annual_rate, monthly_payment)
    estimated_interest = interest_to_close_loan(outstanding, annual_rate, monthly_payment)
    now = pd.Timestamp.now(tz=start.tz)
    estimated_close = now + pd.DateOffset(months=pending_months) if pending_months is not None else None
    scheduled_pending = max(int(tenure_months) - elapsed_months, 0)
    return {
        "scheduled_end": scheduled_end.date(),
        "estimated_close": estimated_close.date() if estimated_close is not None else None,
        "elapsed_months": elapsed_months,
        "scheduled_pending_months": scheduled_pending,
        "outstanding": outstanding,
        "estimated_interest": estimated_interest,
        "pending_months": pending_months,
    }


def loan_projection_dict(loan: FinanceLoan) -> dict[str, object]:
    """One flat dict of every derived figure for a loan — id/name/terms plus
    the live projection. This is what the API returns per loan (JSON, not a
    display DataFrame like the original Streamlit table)."""
    summary = loan_summary(loan.principal, loan.annual_rate, loan.tenure_months, loan.emi)
    projection = loan_projection(
        loan.principal, loan.annual_rate, loan.tenure_months, loan.emi, loan.extra_payment, loan.start_date
    )
    estimated_interest = projection["estimated_interest"]
    total_interest = summary["total_interest"]
    return {
        "id": loan.id,
        "account_number": loan.account_number,
        "name": loan.name,
        "principal": loan.principal,
        "annual_rate": loan.annual_rate,
        "tenure_months": loan.tenure_months,
        "emi": loan.emi,
        "extra_payment": loan.extra_payment,
        "start_date": loan.start_date,
        "outstanding": projection["outstanding"],
        "scheduled_end": projection["scheduled_end"],
        "estimated_close": projection["estimated_close"],
        "scheduled_pending_label": format_months(projection["scheduled_pending_months"]),
        "pending_label": format_months(projection["pending_months"]),
        "monthly_interest": summary["monthly_interest"],
        "yearly_interest": summary["yearly_interest"],
        "total_interest": total_interest,
        "estimated_interest": estimated_interest if estimated_interest is not None else 0.0,
        "interest_saved": max(total_interest - (estimated_interest if estimated_interest is not None else total_interest), 0.0),
        "total_payable": summary["total_payment"],
    }


def total_outstanding(loans: list[FinanceLoan]) -> float:
    """Sum of every loan's current outstanding balance — the Net Worth
    endpoint's liability figure."""
    return sum(loan_projection_dict(loan)["outstanding"] for loan in loans)


__all__ = [
    "calculate_emi",
    "elapsed_months_since",
    "format_months",
    "interest_to_close_loan",
    "loan_projection",
    "loan_projection_dict",
    "loan_summary",
    "months_to_close_loan",
    "outstanding_balance",
    "total_outstanding",
]
