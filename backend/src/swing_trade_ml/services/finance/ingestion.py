"""Orchestrates a statement upload: hash-dedup -> parse -> categorize -> upsert.

Mirrors the upsert idiom `services/ingestion.py` already uses for instrument
sync (`postgresql.insert(...).on_conflict_do_nothing`), so this isn't a new
pattern in the codebase — just a new table.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd
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
    categorized = categorizer.categorize_transactions(df, categorizer.load_rules())

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


def transactions_dataframe(db: Session) -> pd.DataFrame:
    """Loads every transaction into a DataFrame shaped for `analytics.py`."""
    rows = db.query(
        FinanceTransaction.txn_date,
        FinanceTransaction.month,
        FinanceTransaction.description,
        FinanceTransaction.amount,
        FinanceTransaction.direction,
        FinanceTransaction.category,
    ).all()
    return pd.DataFrame(
        rows, columns=["date", "month", "description", "amount", "direction", "category"]
    )


__all__ = [
    "FinanceIngestError",
    "IngestResult",
    "compute_dedup_key",
    "compute_file_hash",
    "detect_and_parse",
    "ingest_statement",
    "transactions_dataframe",
]
