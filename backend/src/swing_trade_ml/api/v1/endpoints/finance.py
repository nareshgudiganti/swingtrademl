"""Personal finance: statement upload, categorized transactions, analytics,
loans/EMI tracking, net worth, and custom categorization rules.

Unrelated to the trading engine — a personal expense tracker bolted onto the
same app so it shares infrastructure instead of running as a second service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select, update

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.finance import (
    FinanceCustomRule,
    FinanceDailyCategory,
    FinanceIngestedFile,
    FinanceLoan,
    FinanceRecurringBill,
    FinanceRecurringBillPayment,
    FinanceTransaction,
)
from swing_trade_ml.schemas import (
    FinanceBillPaymentIn,
    FinanceCalculationSummary,
    FinanceCategorySummary,
    FinanceCustomRuleIn,
    FinanceCustomRuleOut,
    FinanceDailyCategoryIn,
    FinanceDailyCategoryOut,
    FinanceDailyExpenseIn,
    FinanceIngestedFileOut,
    FinanceIngestResult,
    FinanceLoanCreate,
    FinanceLoanOut,
    FinanceLoanUpdate,
    FinanceMerchantSummary,
    FinanceMonthlyCategorySummary,
    FinanceMonthlySummary,
    FinanceNetWorth,
    FinanceRecategorizeResult,
    FinanceRecurringBillCreate,
    FinanceRecurringBillOut,
    FinanceRecurringBillUpdate,
    FinanceRuleUpsertResult,
    FinanceTransactionOut,
    FinanceTransactionUpdate,
    MessageResponse,
)
from swing_trade_ml.services.finance import analytics, categorizer
from swing_trade_ml.services.finance import loans as loans_service
from swing_trade_ml.services.finance import recurring as recurring_service
from swing_trade_ml.services.finance.ingestion import (
    FinanceIngestError,
    ingest_statement,
    recategorize_all,
    reconcile_source_priority,
    transactions_dataframe,
)

router = APIRouter(prefix="/finance", tags=["finance"])


@router.post("/statements", response_model=FinanceIngestResult, status_code=status.HTTP_201_CREATED)
async def upload_statement(
    db: DbSession,
    file: UploadFile = File(...),
    password: str | None = Form(None),
) -> FinanceIngestResult:
    """Upload a PhonePe PDF, ICICI bank PDF, or generic CSV statement.

    Parsing happens fully in memory — nothing is written to disk. Re-uploading
    an already-imported file (by content hash) or an already-imported
    transaction (by its dedup key) is a no-op, so this is safe to retry.
    """
    content = await file.read()
    max_bytes = settings.FINANCE_MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.FINANCE_MAX_UPLOAD_MB}MB limit",
        )

    try:
        result = ingest_statement(db, file.filename or "statement", content, password)
    except FinanceIngestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return FinanceIngestResult(
        file_name=result.file_name,
        source_type=result.source_type,
        already_imported=result.already_imported,
        transactions_parsed=result.transactions_parsed,
        transactions_imported=result.transactions_imported,
        duplicates_skipped=result.duplicates_skipped,
        message=result.message,
    )


@router.get("/transactions", response_model=list[FinanceTransactionOut])
def list_transactions(
    db: DbSession,
    month: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    search: str | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
) -> list[FinanceTransaction]:
    stmt = (
        select(FinanceTransaction)
        .where(FinanceTransaction.deleted_at.is_(None))
        .order_by(FinanceTransaction.txn_date.desc())
    )
    if month:
        stmt = stmt.where(FinanceTransaction.month == month)
    if category:
        stmt = stmt.where(FinanceTransaction.category == category)
    else:
        # Sweeps aren't real spend and would otherwise clutter every view —
        # hidden unless explicitly asked for via category=Internal Transfer.
        stmt = stmt.where(FinanceTransaction.category.notin_(analytics.EXCLUDED_CATEGORIES))
    if direction:
        stmt = stmt.where(FinanceTransaction.direction == direction.upper())
    if search:
        stmt = stmt.where(FinanceTransaction.description.ilike(f"%{search}%"))
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.patch("/transactions/{transaction_id}", response_model=FinanceTransactionOut)
def recategorize_transaction(
    transaction_id: int, payload: FinanceTransactionUpdate, db: DbSession
) -> FinanceTransaction:
    txn = db.get(FinanceTransaction, transaction_id)
    if txn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    txn.category = payload.category
    txn.is_manual_override = True
    db.commit()
    db.refresh(txn)
    return txn


@router.get("/categories", response_model=list[str])
def list_categories(db: DbSession) -> list[str]:
    """Union of the bundled rule-file categories, custom rule categories, and
    any category already present in the DB — so the recategorize dropdown
    always offers the full standard set."""
    rule_categories = set(categorizer.load_rules()["category"].unique())
    rule_categories.add("Income / Credit")
    rule_categories.add("Uncategorised")
    custom_categories = set(db.execute(select(FinanceCustomRule.category).distinct()).scalars().all())
    db_categories = set(db.execute(select(FinanceTransaction.category).distinct()).scalars().all())
    return sorted(rule_categories | custom_categories | db_categories)


@router.get("/summary/monthly", response_model=list[FinanceMonthlySummary])
def monthly_summary(
    db: DbSession, category: str | None = None, direction: str | None = None
) -> list[dict[str, Any]]:
    """Always spans every month — this chart's job is showing change over
    time, so it deliberately ignores a month filter (collapsing it to one
    month would defeat the point). Category/direction still narrow it."""
    df = transactions_dataframe(db, category=category, direction=direction)
    if df.empty:
        return []
    return analytics.monthly_summary(df).to_dict(orient="records")


@router.get("/summary/categories", response_model=list[FinanceCategorySummary])
def category_summary(
    db: DbSession, month: str | None = None, direction: str | None = None
) -> list[dict[str, Any]]:
    df = transactions_dataframe(db, month=month, direction=direction)
    if df.empty:
        return []
    return analytics.category_summary(df).to_dict(orient="records")


@router.get("/summary/monthly-categories", response_model=list[FinanceMonthlyCategorySummary])
def monthly_category_summary(db: DbSession) -> list[dict[str, Any]]:
    df = transactions_dataframe(db)
    if df.empty:
        return []
    return analytics.monthly_category_summary(df).to_dict(orient="records")


@router.get("/merchants", response_model=list[FinanceMerchantSummary])
def merchant_summary(
    db: DbSession,
    month: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    top_n: int = Query(20, le=100),
) -> list[dict[str, Any]]:
    df = transactions_dataframe(db, month=month, category=category, direction=direction)
    if df.empty:
        return []
    return analytics.merchant_summary(df, top_n=top_n).to_dict(orient="records")


@router.get("/insights", response_model=list[str])
def insights(
    db: DbSession, month: str | None = None, category: str | None = None, direction: str | None = None
) -> list[str]:
    df = transactions_dataframe(db, month=month, category=category, direction=direction)
    if df.empty:
        return ["No expense transactions found yet."]
    return analytics.generate_insights(df)


@router.get("/calculation", response_model=FinanceCalculationSummary)
def calculation(
    db: DbSession, month: str | None = None, category: str | None = None, direction: str | None = None
) -> FinanceCalculationSummary:
    """The Calculation tab's whole job: for whatever is selected, how much
    went out, how much came in, and what's left over. Excludes Internal
    Transfer and cross-source duplicate (reference-only) rows the same way
    every other total does."""
    df = transactions_dataframe(db, month=month, category=category, direction=direction)
    if df.empty:
        return FinanceCalculationSummary(total_debits=0.0, total_credits=0.0, net=0.0, transaction_count=0)

    debits = analytics.expense_df(df)
    credits = analytics.income_df(df)
    total_debits = float(debits["amount"].sum())
    total_credits = float(credits["amount"].sum())
    return FinanceCalculationSummary(
        total_debits=total_debits,
        total_credits=total_credits,
        net=total_credits - total_debits,
        transaction_count=len(debits) + len(credits),
    )


@router.get("/net-worth", response_model=FinanceNetWorth)
def net_worth(
    db: DbSession, month: str | None = None, category: str | None = None, direction: str | None = None
) -> FinanceNetWorth:
    """income - expenses + investments - loan liabilities, all scoped to the
    same filter as the rest of the page. Matches the original app's actual
    (simpler than a full balance sheet) definition."""
    df = transactions_dataframe(db, month=month, category=category, direction=direction)
    if df.empty:
        income_total = 0.0
        expense_total = 0.0
        investments_total = 0.0
    else:
        prepared = analytics.prepare(df)
        income_total = float(prepared.loc[prepared["direction"].eq("CREDIT"), "amount"].sum())
        expenses = analytics.expense_df(df)
        expense_total = float(expenses["amount"].sum())
        investments_total = float(
            expenses.loc[expenses["category"].isin(["Investments", "SIPs"]), "amount"].sum()
        )

    loans = list(db.execute(select(FinanceLoan)).scalars().all())
    liabilities = loans_service.total_outstanding(loans)
    cash_surplus = income_total - expense_total

    return FinanceNetWorth(
        income_total=income_total,
        expense_total=expense_total,
        cash_surplus=cash_surplus,
        investments_total=investments_total,
        liabilities=liabilities,
        net_worth=cash_surplus + investments_total - liabilities,
    )


@router.get("/statements", response_model=list[FinanceIngestedFileOut])
def list_statements(
    db: DbSession, deleted: bool = False, limit: int = Query(50, le=200)
) -> list[FinanceIngestedFile]:
    """`deleted=false` (default) lists active statements; `deleted=true`
    lists the "Recently deleted" trash for the Statement tab's restore UI."""
    stmt = select(FinanceIngestedFile).order_by(FinanceIngestedFile.created_at.desc()).limit(limit)
    stmt = stmt.where(FinanceIngestedFile.deleted_at.isnot(None) if deleted else FinanceIngestedFile.deleted_at.is_(None))
    return list(db.execute(stmt).scalars().all())


@router.delete("/statements/{ingested_file_id}", response_model=MessageResponse)
def delete_statement(ingested_file_id: int, db: DbSession) -> MessageResponse:
    """Soft delete — reversible via /restore. Hides the statement and its
    transactions from every view and total immediately, but keeps the rows
    in the database so nothing is actually lost by a stray click."""
    ingested_file = db.get(FinanceIngestedFile, ingested_file_id)
    if ingested_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    if ingested_file.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Statement is already deleted")

    now = datetime.now(UTC)
    ingested_file.deleted_at = now
    db.execute(
        update(FinanceTransaction)
        .where(FinanceTransaction.ingested_file_id == ingested_file.id)
        .values(deleted_at=now)
    )
    db.commit()
    reconcile_source_priority(db)
    return MessageResponse(
        message=f"Moved '{ingested_file.file_name}' to Recently Deleted",
        detail="Restore it from the Statement tab, or delete it permanently.",
    )


@router.post("/statements/{ingested_file_id}/restore", response_model=FinanceIngestedFileOut)
def restore_statement(ingested_file_id: int, db: DbSession) -> FinanceIngestedFile:
    ingested_file = db.get(FinanceIngestedFile, ingested_file_id)
    if ingested_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    if ingested_file.deleted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Statement is not deleted")

    ingested_file.deleted_at = None
    db.execute(
        update(FinanceTransaction)
        .where(FinanceTransaction.ingested_file_id == ingested_file.id)
        .values(deleted_at=None)
    )
    db.commit()
    db.refresh(ingested_file)
    reconcile_source_priority(db)
    return ingested_file


@router.delete("/statements/{ingested_file_id}/permanent", response_model=MessageResponse)
def permanently_delete_statement(ingested_file_id: int, confirm_filename: str, db: DbSession) -> MessageResponse:
    """The only irreversible action left — requires the exact file name to
    be passed as `confirm_filename`, not just a click, before it cascades to
    permanently remove the statement's transactions."""
    ingested_file = db.get(FinanceIngestedFile, ingested_file_id)
    if ingested_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    if confirm_filename != ingested_file.file_name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "confirm_filename must exactly match the statement's file name",
        )
    file_name = ingested_file.file_name
    db.delete(ingested_file)
    db.commit()
    return MessageResponse(message=f"Permanently deleted '{file_name}' and its transactions")


# ------------------------------------------------------------------ loans --


def _loan_start_date(value) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=UTC)


@router.get("/loans", response_model=list[FinanceLoanOut])
def list_loans(db: DbSession) -> list[dict[str, Any]]:
    loans = list(db.execute(select(FinanceLoan).order_by(FinanceLoan.created_at.desc())).scalars().all())
    return [loans_service.loan_projection_dict(loan) for loan in loans]


@router.post("/loans", response_model=FinanceLoanOut, status_code=status.HTTP_201_CREATED)
def create_loan(payload: FinanceLoanCreate, db: DbSession) -> dict[str, Any]:
    loan = FinanceLoan(
        account_number=payload.account_number,
        name=payload.name,
        principal=payload.principal,
        annual_rate=payload.annual_rate,
        tenure_months=payload.tenure_months,
        emi=payload.emi,
        extra_payment=payload.extra_payment,
        start_date=_loan_start_date(payload.start_date),
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loans_service.loan_projection_dict(loan)


@router.patch("/loans/{loan_id}", response_model=FinanceLoanOut)
def update_loan(loan_id: int, payload: FinanceLoanUpdate, db: DbSession) -> dict[str, Any]:
    loan = db.get(FinanceLoan, loan_id)
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loan not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("start_date") is not None:
        data["start_date"] = _loan_start_date(data["start_date"])
    for key, value in data.items():
        setattr(loan, key, value)
    db.commit()
    db.refresh(loan)
    return loans_service.loan_projection_dict(loan)


@router.delete("/loans/{loan_id}", response_model=MessageResponse)
def delete_loan(loan_id: int, db: DbSession) -> MessageResponse:
    loan = db.get(FinanceLoan, loan_id)
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loan not found")
    name = loan.name
    db.delete(loan)
    db.commit()
    return MessageResponse(message=f"Deleted loan '{name}'")


# ------------------------------------------------------------------ rules --


@router.get("/rules", response_model=list[FinanceCustomRuleOut])
def list_rules(db: DbSession) -> list[FinanceCustomRule]:
    stmt = select(FinanceCustomRule).order_by(FinanceCustomRule.priority.desc(), FinanceCustomRule.keyword)
    return list(db.execute(stmt).scalars().all())


@router.put("/rules", response_model=FinanceRuleUpsertResult)
def upsert_rule(payload: FinanceCustomRuleIn, db: DbSession) -> FinanceRuleUpsertResult:
    """Add or update a keyword->category rule, then immediately re-checks
    every non-manually-overridden transaction against the updated rule set —
    the same "teach it once, it applies everywhere" behavior the original
    app's rule editor had."""
    keyword = categorizer.normalize_text(payload.keyword)
    if not keyword:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Keyword cannot be empty")

    rule = db.execute(
        select(FinanceCustomRule).where(FinanceCustomRule.keyword == keyword)
    ).scalar_one_or_none()
    if rule is None:
        rule = FinanceCustomRule(keyword=keyword, category=payload.category, priority=payload.priority)
        db.add(rule)
    else:
        rule.category = payload.category
        rule.priority = payload.priority
    db.commit()
    db.refresh(rule)

    updated = recategorize_all(db)
    return FinanceRuleUpsertResult(rule=rule, recategorized_count=updated)


@router.delete("/rules/{keyword}", response_model=MessageResponse)
def delete_rule(keyword: str, db: DbSession) -> MessageResponse:
    normalized = categorizer.normalize_text(keyword)
    rule = db.execute(
        select(FinanceCustomRule).where(FinanceCustomRule.keyword == normalized)
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    db.delete(rule)
    db.commit()
    return MessageResponse(message=f"Deleted rule '{keyword}'")


@router.post("/rules/recategorize", response_model=FinanceRecategorizeResult)
def recategorize(db: DbSession) -> FinanceRecategorizeResult:
    """Manual "re-run categorization" action — same underlying pass that a
    rule upsert triggers automatically, exposed standalone for after adding
    several rules at once."""
    return FinanceRecategorizeResult(recategorized_count=recategorize_all(db))


# --------------------------------------------------------- recurring bills --


def _current_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _bill_out(bill: FinanceRecurringBill, payment: FinanceRecurringBillPayment | None) -> dict[str, Any]:
    return {
        "id": bill.id,
        "name": bill.name,
        "category": bill.category,
        "default_amount": bill.default_amount,
        "is_active": bill.is_active,
        "paid_this_month": payment is not None,
        "amount_this_month": payment.amount if payment else None,
        "paid_at": payment.paid_at if payment else None,
    }


@router.get("/recurring-bills", response_model=list[FinanceRecurringBillOut])
def list_recurring_bills(db: DbSession, month: str | None = None) -> list[dict[str, Any]]:
    """Every active bill, each resolved against `month` (default: this
    month) so the page can render a paid/unpaid checklist in one call."""
    month = month or _current_month()
    bills = list(
        db.execute(
            select(FinanceRecurringBill)
            .where(FinanceRecurringBill.is_active.is_(True))
            .order_by(FinanceRecurringBill.name)
        )
        .scalars()
        .all()
    )
    if not bills:
        return []
    payments = {
        p.bill_id: p
        for p in db.execute(
            select(FinanceRecurringBillPayment).where(
                FinanceRecurringBillPayment.bill_id.in_([b.id for b in bills]),
                FinanceRecurringBillPayment.month == month,
            )
        )
        .scalars()
        .all()
    }
    return [_bill_out(bill, payments.get(bill.id)) for bill in bills]


@router.post("/recurring-bills/defaults", response_model=list[FinanceRecurringBillOut])
def add_default_recurring_bills(db: DbSession) -> list[dict[str, Any]]:
    """Seeds the common household bills (rent, utilities, subscriptions…)
    that aren't already present, so the user checks them off and fills in
    the real amount instead of typing every bill from scratch."""
    created = recurring_service.seed_default_bills(db)
    return [_bill_out(bill, None) for bill in created]


@router.post("/recurring-bills", response_model=FinanceRecurringBillOut, status_code=status.HTTP_201_CREATED)
def create_recurring_bill(payload: FinanceRecurringBillCreate, db: DbSession) -> dict[str, Any]:
    bill = FinanceRecurringBill(
        name=payload.name, category=payload.category, default_amount=payload.default_amount
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return _bill_out(bill, None)


@router.patch("/recurring-bills/{bill_id}", response_model=FinanceRecurringBillOut)
def update_recurring_bill(bill_id: int, payload: FinanceRecurringBillUpdate, db: DbSession) -> dict[str, Any]:
    bill = db.get(FinanceRecurringBill, bill_id)
    if bill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(bill, key, value)
    db.commit()
    db.refresh(bill)
    payment = db.execute(
        select(FinanceRecurringBillPayment).where(
            FinanceRecurringBillPayment.bill_id == bill.id,
            FinanceRecurringBillPayment.month == _current_month(),
        )
    ).scalar_one_or_none()
    return _bill_out(bill, payment)


@router.delete("/recurring-bills/{bill_id}", response_model=MessageResponse)
def delete_recurring_bill(bill_id: int, db: DbSession) -> MessageResponse:
    """Removes the template only — past months' logged payments (and the
    transactions they created) are left alone, since deleting a bill you no
    longer pay shouldn't erase what you already spent on it."""
    bill = db.get(FinanceRecurringBill, bill_id)
    if bill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    name = bill.name
    db.delete(bill)
    db.commit()
    return MessageResponse(message=f"Deleted recurring bill '{name}'")


@router.post("/recurring-bills/{bill_id}/pay", response_model=FinanceRecurringBillOut)
def pay_recurring_bill(bill_id: int, payload: FinanceBillPaymentIn, db: DbSession) -> dict[str, Any]:
    bill = db.get(FinanceRecurringBill, bill_id)
    if bill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    paid_at = datetime.combine(payload.paid_at, datetime.min.time(), tzinfo=UTC) if payload.paid_at else datetime.now(UTC)
    payment = recurring_service.record_bill_payment(db, bill, payload.month, payload.amount, paid_at)
    return _bill_out(bill, payment)


@router.delete("/recurring-bills/{bill_id}/pay/{month}", response_model=MessageResponse)
def unpay_recurring_bill(bill_id: int, month: str, db: DbSession) -> MessageResponse:
    payment = db.execute(
        select(FinanceRecurringBillPayment).where(
            FinanceRecurringBillPayment.bill_id == bill_id, FinanceRecurringBillPayment.month == month
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No payment recorded for that month")
    recurring_service.unpay_bill(db, payment)
    return MessageResponse(message=f"Marked {month} unpaid")


# ------------------------------------------------------------- daily spend --


@router.get("/daily-categories", response_model=list[FinanceDailyCategoryOut])
def list_daily_categories(db: DbSession) -> list[FinanceDailyCategory]:
    stmt = (
        select(FinanceDailyCategory)
        .where(FinanceDailyCategory.is_active.is_(True))
        .order_by(FinanceDailyCategory.name)
    )
    return list(db.execute(stmt).scalars().all())


@router.post("/daily-categories", response_model=FinanceDailyCategoryOut, status_code=status.HTTP_201_CREATED)
def create_daily_category(payload: FinanceDailyCategoryIn, db: DbSession) -> FinanceDailyCategory:
    existing = db.execute(
        select(FinanceDailyCategory).where(FinanceDailyCategory.name == payload.name)
    ).scalar_one_or_none()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
        return existing
    category = FinanceDailyCategory(name=payload.name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/daily-categories/{category_id}", response_model=MessageResponse)
def delete_daily_category(category_id: int, db: DbSession) -> MessageResponse:
    category = db.get(FinanceDailyCategory, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    name = category.name
    category.is_active = False
    db.commit()
    return MessageResponse(message=f"Removed daily category '{name}'")


@router.post("/daily-expenses", response_model=FinanceTransactionOut, status_code=status.HTTP_201_CREATED)
def create_daily_expense(payload: FinanceDailyExpenseIn, db: DbSession) -> FinanceTransaction:
    spent_at = (
        datetime.combine(payload.spent_at, datetime.min.time(), tzinfo=UTC)
        if payload.spent_at
        else datetime.now(UTC)
    )
    return recurring_service.record_daily_expense(
        db, category=payload.category, amount=payload.amount, spent_at=spent_at, note=payload.note
    )
