"""Orchestrates a statement upload: hash-dedup -> parse -> categorize -> upsert.

Mirrors the upsert idiom `services/ingestion.py` already uses for instrument
sync (`postgresql.insert(...).on_conflict_do_nothing`), so this isn't a new
pattern in the codebase — just a new table.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import FinanceIngestStatus, FinanceSourceType
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.finance import FinanceIngestedFile, FinanceTransaction
from swing_trade_ml.services.finance import categorizer
from swing_trade_ml.services.finance.parsers.bank_pdf import is_bank_statement_pdf, parse_icici_pdf
from swing_trade_ml.services.finance.parsers.csv_parser import normalize_csv, read_uploaded_csv
from swing_trade_ml.services.finance.parsers.phonepe_pdf import PhonePeParseError, parse_phonepe_pdf

log = get_logger(__name__)

# Bank/UPI-export sources are authoritative for totals over a PhonePe
# statement covering the same month — see reconcile_source_priority().
BANK_SOURCE_TYPES = {FinanceSourceType.ICICI_PDF, FinanceSourceType.CSV}


class FinanceIngestError(Exception):
    """Raised when a statement cannot be parsed by any supported parser."""


@dataclass
class IngestResult:
    file_name: str
    source_type: str
    already_imported: bool
    transactions_parsed: int
    transactions_imported: int
    duplicates_skipped: int
    message: str


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def compute_dedup_key(row: pd.Series) -> str:
    """Practical identity of a transaction across re-uploads: the source's
    own transaction id when present, else a composite of date/description/
    amount/source."""
    transaction_id = str(row.get("transaction_id") or "").strip()
    if transaction_id:
        return transaction_id
    date_value = pd.to_datetime(row["date"])
    return f"{date_value:%Y-%m-%d}|{row['description']}|{float(row['amount']):.2f}|{row.get('source', '')}"


def detect_and_parse(filename: str, file_bytes: bytes, password: str | None) -> tuple[pd.DataFrame, str]:
    """Returns (normalized_df, source_type)."""
    if filename.lower().endswith(".csv"):
        raw = read_uploaded_csv(file_bytes)
        return normalize_csv(raw), FinanceSourceType.CSV

    try:
        return parse_phonepe_pdf(file_bytes, password=password), FinanceSourceType.PHONEPE_PDF
    except PhonePeParseError as phonepe_exc:
        if is_bank_statement_pdf(file_bytes, password=password):
            try:
                return parse_icici_pdf(file_bytes, password=password), FinanceSourceType.ICICI_PDF
            except PhonePeParseError as icici_exc:
                raise FinanceIngestError(str(icici_exc)) from icici_exc
        raise FinanceIngestError(str(phonepe_exc)) from phonepe_exc


def ingest_statement(
    db: Session, filename: str, file_bytes: bytes, password: str | None = None
) -> IngestResult:
    file_hash = compute_file_hash(file_bytes)
    existing = (
        db.query(FinanceIngestedFile).filter(FinanceIngestedFile.file_hash == file_hash).one_or_none()
    )
    if existing is not None:
        if existing.deleted_at is not None:
            # Re-uploading a previously (soft-)deleted statement restores it,
            # rather than erroring or attempting a duplicate insert against
            # the same file_hash.
            existing.deleted_at = None
            db.execute(
                update(FinanceTransaction)
                .where(FinanceTransaction.ingested_file_id == existing.id)
                .values(deleted_at=None)
            )
            db.commit()
            reconcile_source_priority(db)
            return IngestResult(
                file_name=filename,
                source_type=existing.source_type,
                already_imported=True,
                transactions_parsed=existing.transaction_count,
                transactions_imported=0,
                duplicates_skipped=0,
                message=(
                    f"This file was previously deleted and has been restored "
                    f"({existing.transaction_count} transactions)."
                ),
            )
        return IngestResult(
            file_name=filename,
            source_type=existing.source_type,
            already_imported=True,
            transactions_parsed=existing.transaction_count,
            transactions_imported=0,
            duplicates_skipped=existing.transaction_count,
            message=f"This exact file was already imported on {existing.created_at:%Y-%m-%d}.",
        )

    df, source_type = detect_and_parse(filename, file_bytes, password)
    categorized = categorizer.categorize_transactions(df, categorizer.combined_rules(db))

    ingested_file = FinanceIngestedFile(
        file_hash=file_hash,
        file_name=filename,
        source_type=source_type,
        status=FinanceIngestStatus.SUCCESS,
        transaction_count=0,
    )
    db.add(ingested_file)
    db.flush()  # assigns ingested_file.id without committing

    rows = []
    for _, row in categorized.iterrows():
        rows.append(
            {
                "ingested_file_id": ingested_file.id,
                "dedup_key": compute_dedup_key(row),
                "txn_date": pd.to_datetime(row["date"]).to_pydatetime(),
                "month": row["month"],
                "description": row["description"],
                "amount": float(row["amount"]),
                "direction": str(row["direction"]).upper(),
                "status": row.get("status"),
                "transaction_id": str(row.get("transaction_id") or "") or None,
                "source": row.get("source"),
                "raw_text": row.get("raw_text"),
                "category": row["category"],
                "is_manual_override": False,
            }
        )

    imported_count = 0
    if rows:
        stmt = pg_insert(FinanceTransaction).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"]).returning(FinanceTransaction.id)
        imported_count = len(db.execute(stmt).fetchall())

    duplicates_skipped = len(rows) - imported_count
    ingested_file.transaction_count = imported_count
    ingested_file.message = (
        f"{len(rows)} parsed, {imported_count} imported, {duplicates_skipped} duplicates skipped."
    )
    db.commit()
    reconcile_source_priority(db)

    log.info(
        "finance.ingest.done",
        file_name=filename,
        source_type=source_type,
        parsed=len(rows),
        imported=imported_count,
        duplicates=duplicates_skipped,
    )

    return IngestResult(
        file_name=filename,
        source_type=source_type,
        already_imported=False,
        transactions_parsed=len(rows),
        transactions_imported=imported_count,
        duplicates_skipped=duplicates_skipped,
        message=ingested_file.message,
    )


def transactions_dataframe(
    db: Session,
    *,
    month: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    include_reference_only: bool = False,
) -> pd.DataFrame:
    """Loads transactions into a DataFrame shaped for `analytics.py`, optionally
    scoped by the same filters the transactions list endpoint accepts — every
    summary/insight endpoint shares this so a filter actually reaches every
    number on the page, not just the transaction table.

    Soft-deleted rows are always excluded. Reference-only rows (a PhonePe
    transaction demoted because a bank statement covers the same month — see
    reconcile_source_priority) are excluded by default so the same real
    payment isn't counted twice; they still show in the plain transaction
    list (list_transactions), just never in a total.
    """
    stmt = select(
        FinanceTransaction.txn_date,
        FinanceTransaction.month,
        FinanceTransaction.description,
        FinanceTransaction.amount,
        FinanceTransaction.direction,
        FinanceTransaction.category,
    ).where(FinanceTransaction.deleted_at.is_(None))
    if not include_reference_only:
        stmt = stmt.where(FinanceTransaction.is_reference_only.is_(False))
    if month:
        stmt = stmt.where(FinanceTransaction.month == month)
    if category:
        stmt = stmt.where(FinanceTransaction.category == category)
    if direction:
        stmt = stmt.where(FinanceTransaction.direction == direction.upper())
    rows = db.execute(stmt).all()
    return pd.DataFrame(
        rows, columns=["date", "month", "description", "amount", "direction", "category"]
    )


def reconcile_source_priority(db: Session) -> int:
    """Bank-statement months are authoritative for totals — if a PhonePe
    upload and a bank statement both cover the same month, the PhonePe rows
    for that month are marked reference-only so the same real payment isn't
    counted twice. Re-evaluated on every ingest/soft-delete/restore, in
    either upload order, since deleting or restoring a bank statement changes
    which months are authoritative. Returns how many rows changed.
    """
    bank_months = set(
        db.execute(
            select(FinanceTransaction.month)
            .join(FinanceIngestedFile, FinanceTransaction.ingested_file_id == FinanceIngestedFile.id)
            .where(
                FinanceIngestedFile.source_type.in_(BANK_SOURCE_TYPES),
                FinanceTransaction.deleted_at.is_(None),
                FinanceIngestedFile.deleted_at.is_(None),
            )
            .distinct()
        )
        .scalars()
        .all()
    )

    phonepe_txns = list(
        db.execute(
            select(FinanceTransaction)
            .join(FinanceIngestedFile, FinanceTransaction.ingested_file_id == FinanceIngestedFile.id)
            .where(
                FinanceIngestedFile.source_type == FinanceSourceType.PHONEPE_PDF,
                FinanceTransaction.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    changed = 0
    for txn in phonepe_txns:
        should_be_reference = txn.month in bank_months
        if txn.is_reference_only != should_be_reference:
            txn.is_reference_only = should_be_reference
            changed += 1
    if changed:
        db.commit()
    return changed


def recategorize_all(db: Session) -> int:
    """Re-runs categorization against the current combined rule set (bundled
    CSV + custom DB rules) for every transaction that hasn't been manually
    overridden. Manually-overridden rows are never touched — the same
    guarantee a statement re-upload gives. Returns how many rows actually
    changed category, so a "re-run categorization" action can report
    something meaningful."""
    txns = list(
        db.execute(
            select(FinanceTransaction).where(
                FinanceTransaction.is_manual_override.is_(False),
                FinanceTransaction.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    if not txns:
        return 0

    df = pd.DataFrame(
        {
            "description": [t.description for t in txns],
            "raw_text": [t.raw_text for t in txns],
            "direction": [t.direction for t in txns],
        }
    )
    recategorized = categorizer.categorize_transactions(df, categorizer.combined_rules(db))

    updated = 0
    for txn, new_category in zip(txns, recategorized["category"], strict=True):
        if txn.category != new_category:
            txn.category = new_category
            updated += 1
    db.commit()
    return updated


__all__ = [
    "BANK_SOURCE_TYPES",
    "FinanceIngestError",
    "IngestResult",
    "compute_dedup_key",
    "compute_file_hash",
    "detect_and_parse",
    "ingest_statement",
    "recategorize_all",
    "reconcile_source_priority",
    "transactions_dataframe",
]
