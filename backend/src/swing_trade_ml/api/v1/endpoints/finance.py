"""Personal finance: statement upload, categorized transactions, analytics.

Unrelated to the trading engine — a personal expense tracker bolted onto the
same app so it shares infrastructure instead of running as a second service.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.finance import FinanceIngestedFile, FinanceTransaction
from swing_trade_ml.schemas import (
    FinanceCategorySummary,
    FinanceIngestedFileOut,
    FinanceIngestResult,
    FinanceMerchantSummary,
    FinanceMonthlyCategorySummary,
    FinanceMonthlySummary,
    FinanceTransactionOut,
    FinanceTransactionUpdate,
    MessageResponse,
)
from swing_trade_ml.services.finance import analytics, categorizer
from swing_trade_ml.services.finance.ingestion import FinanceIngestError, ingest_statement, transactions_dataframe

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
    stmt = select(FinanceTransaction).order_by(FinanceTransaction.txn_date.desc())
    if month:
        stmt = stmt.where(FinanceTransaction.month == month)
    if category:
        stmt = stmt.where(FinanceTransaction.category == category)
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
    """Union of the bundled rule-file categories and any category already
    present in the DB — so the recategorize dropdown always offers the full
    standard set, not just categories some transaction already has."""
    rule_categories = set(categorizer.load_rules()["category"].unique())
    rule_categories.add("Income / Credit")
    rule_categories.add("Uncategorised")
    db_categories = set(db.execute(select(FinanceTransaction.category).distinct()).scalars().all())
    return sorted(rule_categories | db_categories)


@router.get("/summary/monthly", response_model=list[FinanceMonthlySummary])
def monthly_summary(db: DbSession) -> list[dict[str, Any]]:
    df = transactions_dataframe(db)
    if df.empty:
        return []
    return analytics.monthly_summary(df).to_dict(orient="records")


@router.get("/summary/categories", response_model=list[FinanceCategorySummary])
def category_summary(db: DbSession) -> list[dict[str, Any]]:
    df = transactions_dataframe(db)
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
def merchant_summary(db: DbSession, top_n: int = Query(20, le=100)) -> list[dict[str, Any]]:
    df = transactions_dataframe(db)
    if df.empty:
        return []
    return analytics.merchant_summary(df, top_n=top_n).to_dict(orient="records")


@router.get("/insights", response_model=list[str])
def insights(db: DbSession) -> list[str]:
    df = transactions_dataframe(db)
    if df.empty:
        return ["No expense transactions found yet."]
    return analytics.generate_insights(df)


@router.get("/statements", response_model=list[FinanceIngestedFileOut])
def list_statements(db: DbSession, limit: int = Query(50, le=200)) -> list[FinanceIngestedFile]:
    stmt = select(FinanceIngestedFile).order_by(FinanceIngestedFile.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.delete("/statements/{ingested_file_id}", response_model=MessageResponse)
def delete_statement(ingested_file_id: int, db: DbSession) -> MessageResponse:
    """Undo a bad import — cascades to delete its transactions."""
    ingested_file = db.get(FinanceIngestedFile, ingested_file_id)
    if ingested_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    file_name = ingested_file.file_name
    db.delete(ingested_file)
    db.commit()
    return MessageResponse(message=f"Deleted statement '{file_name}' and its transactions")
