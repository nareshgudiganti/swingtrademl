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
    FinanceIngestedFile,
    FinanceLoan,
    FinanceTransaction,
)
from swing_trade_ml.schemas import (
    FinanceCalculationSummary,
    FinanceCategorySummary,
    FinanceCustomRuleIn,
    FinanceCustomRuleOut,
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
    FinanceRuleUpsertResult,
    FinanceTransactionOut,
    FinanceTransactionUpdate,
    MessageResponse,
)
from swing_trade_ml.services.finance import analytics, categorizer
from swing_trade_ml.services.finance import loans as loans_service
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
