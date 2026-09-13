"""Loan/EMI amortization math — verified against hand-computed examples,
not just re-running the ported formulas against themselves."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.services.finance import loans as loans_service


def test_calculate_emi_matches_a_known_example():
    # Rs. 1,00,000 at 10% annual for 12 months -> a well-known EMI figure
    # (verified against a standard EMI calculator): ~8791.59.
    emi = loans_service.calculate_emi(100_000, 10.0, 12)
    assert emi == pytest.approx(8791.59, abs=0.05)


def test_calculate_emi_zero_interest_is_a_flat_split():
    assert loans_service.calculate_emi(120_000, 0.0, 12) == pytest.approx(10_000.0)


def test_calculate_emi_zero_tenure_is_zero():
    assert loans_service.calculate_emi(100_000, 10.0, 0) == 0.0


def test_loan_summary_total_interest_is_total_payment_minus_principal():
    emi = loans_service.calculate_emi(100_000, 10.0, 12)
    summary = loans_service.loan_summary(100_000, 10.0, 12, emi)
    assert summary["total_payment"] == pytest.approx(emi * 12)
    assert summary["total_interest"] == pytest.approx(summary["total_payment"] - 100_000)
    assert summary["yearly_interest"] == pytest.approx(summary["monthly_interest"] * 12)


def test_loan_summary_total_interest_never_negative():
    # total_payment (5,000) below principal (10,000) is an unrealistic input,
    # but the clamp must still hold rather than reporting negative interest.
    summary = loans_service.loan_summary(10_000, 10.0, 1, 5_000)
    assert summary["total_interest"] == 0.0


def test_months_to_close_loan_matches_the_original_tenure_when_paying_the_scheduled_emi():
    principal = 100_000
    rate = 10.0
    tenure = 12
    emi = loans_service.calculate_emi(principal, rate, tenure)
    months = loans_service.months_to_close_loan(principal, rate, emi)
    # Floating-point amortization can land a month off either side.
    assert months in (tenure - 1, tenure, tenure + 1)


def test_months_to_close_loan_is_none_when_payment_does_not_cover_interest():
    # A payment at or below the interest-only amount never closes the loan.
    principal = 100_000
    rate = 12.0
    interest_only = principal * (rate / 100 / 12)
    assert loans_service.months_to_close_loan(principal, rate, interest_only) is None


def test_extra_payment_shortens_closure_time():
    principal, rate, tenure = 100_000, 10.0, 24
    emi = loans_service.calculate_emi(principal, rate, tenure)
    without_extra = loans_service.months_to_close_loan(principal, rate, emi)
    with_extra = loans_service.months_to_close_loan(principal, rate, emi + 2_000)
    assert with_extra < without_extra


def test_outstanding_balance_decreases_each_paid_month():
    principal, rate = 100_000, 10.0
    emi = loans_service.calculate_emi(principal, rate, 12)
    after_0 = loans_service.outstanding_balance(principal, rate, emi, 0)
    after_6 = loans_service.outstanding_balance(principal, rate, emi, 6)
    after_12 = loans_service.outstanding_balance(principal, rate, emi, 12)
    assert after_0 == pytest.approx(principal)
    assert after_6 < after_0
    assert after_12 < after_6
    assert after_12 == pytest.approx(0.0, abs=1.0)


def test_format_months_renders_years_and_months():
    assert loans_service.format_months(None) == "Not closing"
    assert loans_service.format_months(0) == "0 months"
    assert loans_service.format_months(11) == "11 months"
    assert loans_service.format_months(12) == "1 years"
    assert loans_service.format_months(14) == "1 years 2 months"


def test_loan_projection_dict_on_a_freshly_started_loan_has_full_outstanding():
    class FakeLoan:
        id = 1
        account_number = None
        name = "Test loan"
        principal = 100_000.0
        annual_rate = 10.0
        tenure_months = 12
        emi = loans_service.calculate_emi(100_000.0, 10.0, 12)
        extra_payment = 0.0
        start_date = datetime.now(UTC)

    result = loans_service.loan_projection_dict(FakeLoan())
    # Started today: elapsed_months_since rounds to whole months, so a
    # same-day start can already register as month 0 of this calendar month.
    assert result["outstanding"] == pytest.approx(100_000.0, rel=0.01)
    assert result["total_interest"] > 0
    assert result["total_payable"] == pytest.approx(FakeLoan.emi * 12)


def test_total_outstanding_sums_across_loans():
    class FakeLoan:
        def __init__(self, principal):
            self.id = 1
            self.account_number = None
            self.name = "Loan"
            self.principal = principal
            self.annual_rate = 10.0
            self.tenure_months = 12
            self.emi = loans_service.calculate_emi(principal, 10.0, 12)
            self.extra_payment = 0.0
            self.start_date = datetime.now(UTC)

    total = loans_service.total_outstanding([FakeLoan(50_000), FakeLoan(30_000)])
    assert total == pytest.approx(80_000.0, rel=0.02)
