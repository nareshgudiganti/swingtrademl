"""Soft delete: reversible via /restore-style calls into the service layer;
only a filename-confirmed permanent delete actually removes rows."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update

from swing_trade_ml.db.models.finance import FinanceIngestedFile, FinanceTransaction
from swing_trade_ml.services.finance.ingestion import ingest_statement, transactions_dataframe

SAMPLE_CSV = (
    b"date,description,amount,direction\n"
    b"2026-01-05,Swiggy Food Order,550,DEBIT\n"
    b"2026-01-31,Salary Credit,180000,CREDIT\n"
)


def _soft_delete(db_session, ingested_file: FinanceIngestedFile) -> None:
    now = datetime.now(UTC)
    ingested_file.deleted_at = now
    db_session.execute(
        update(FinanceTransaction)
        .where(FinanceTransaction.ingested_file_id == ingested_file.id)
        .values(deleted_at=now)
    )
    db_session.commit()


def _restore(db_session, ingested_file: FinanceIngestedFile) -> None:
    ingested_file.deleted_at = None
    db_session.execute(
        update(FinanceTransaction)
        .where(FinanceTransaction.ingested_file_id == ingested_file.id)
        .values(deleted_at=None)
    )
    db_session.commit()


def test_soft_deleted_statement_disappears_from_transactions_and_totals(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)
    ingested_file = db_session.execute(select(FinanceIngestedFile)).scalar_one()

    _soft_delete(db_session, ingested_file)

    df = transactions_dataframe(db_session)
    assert df.empty

    remaining = db_session.execute(
        select(FinanceTransaction).where(FinanceTransaction.deleted_at.is_(None))
    ).scalars().all()
    assert remaining == []


def test_restoring_a_soft_deleted_statement_brings_it_back(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)
    ingested_file = db_session.execute(select(FinanceIngestedFile)).scalar_one()

    _soft_delete(db_session, ingested_file)
    _restore(db_session, ingested_file)

    df = transactions_dataframe(db_session)
    assert len(df) == 2

    db_session.refresh(ingested_file)
    assert ingested_file.deleted_at is None


def test_reuploading_a_soft_deleted_file_restores_it(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)
    ingested_file = db_session.execute(select(FinanceIngestedFile)).scalar_one()
    _soft_delete(db_session, ingested_file)

    result = ingest_statement(db_session, "statement.csv", SAMPLE_CSV)

    assert result.already_imported is True
    assert "restored" in result.message.lower()
    db_session.refresh(ingested_file)
    assert ingested_file.deleted_at is None
    assert len(transactions_dataframe(db_session)) == 2


def test_soft_deleted_rows_are_untouched_by_hard_delete_semantics(db_session):
    # Soft-deleting must not remove the row from the database at all — the
    # whole point is that it's recoverable without re-uploading.
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)
    ingested_file = db_session.execute(select(FinanceIngestedFile)).scalar_one()
    _soft_delete(db_session, ingested_file)

    still_in_db = db_session.get(FinanceIngestedFile, ingested_file.id)
    assert still_in_db is not None
    assert still_in_db.deleted_at is not None

    txns_in_db = db_session.execute(
        select(FinanceTransaction).where(FinanceTransaction.ingested_file_id == ingested_file.id)
    ).scalars().all()
    assert len(txns_in_db) == 2
    assert all(t.deleted_at is not None for t in txns_in_db)
