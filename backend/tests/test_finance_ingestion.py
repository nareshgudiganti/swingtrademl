"""ingest_statement(): the hash-dedup / upsert orchestration end to end
against a real database. Uses the same db_session fixture as test_engine.py —
one transaction per test, rolled back at teardown."""

from __future__ import annotations

from swing_trade_ml.db.models.finance import FinanceIngestedFile, FinanceTransaction
from swing_trade_ml.services.finance.ingestion import ingest_statement

SAMPLE_CSV = (
    b"date,description,amount,direction\n"
    b"2026-01-05,Swiggy Food Order,550,DEBIT\n"
    b"2026-01-31,Salary Credit,180000,CREDIT\n"
)


def test_ingest_statement_parses_categorizes_and_stores(db_session):
    result = ingest_statement(db_session, "statement.csv", SAMPLE_CSV)

    assert result.already_imported is False
    assert result.transactions_parsed == 2
    assert result.transactions_imported == 2
    assert result.duplicates_skipped == 0

    stored = db_session.query(FinanceTransaction).all()
    assert len(stored) == 2
    by_description = {t.description: t for t in stored}
    assert by_description["Swiggy Food Order"].category == "Food / Restaurants"
    # "salary" is its own keyword rule (more specific than the generic CREDIT
    # default), and "Income" is itself an income category so it's allowed to
    # override "Income / Credit".
    assert by_description["Salary Credit"].category == "Income"
    assert by_description["Salary Credit"].is_manual_override is False


def test_reuploading_the_same_file_is_a_no_op(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)
    result = ingest_statement(db_session, "statement.csv", SAMPLE_CSV)

    assert result.already_imported is True
    assert result.transactions_imported == 0
    assert db_session.query(FinanceTransaction).count() == 2
    assert db_session.query(FinanceIngestedFile).count() == 1


def test_manual_recategorization_survives_a_reupload(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)

    txn = db_session.query(FinanceTransaction).filter_by(description="Swiggy Food Order").one()
    txn.category = "Custom Category"
    txn.is_manual_override = True
    db_session.commit()

    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)

    refreshed = db_session.query(FinanceTransaction).filter_by(description="Swiggy Food Order").one()
    assert refreshed.category == "Custom Category"
    assert refreshed.is_manual_override is True


def test_overlapping_statement_only_imports_new_transactions(db_session):
    ingest_statement(db_session, "january.csv", SAMPLE_CSV)

    overlapping = (
        b"date,description,amount,direction\n"
        b"2026-01-05,Swiggy Food Order,550,DEBIT\n"  # duplicate of january.csv
        b"2026-02-02,Amazon Shopping,3200,DEBIT\n"  # new
    )
    result = ingest_statement(db_session, "february.csv", overlapping)

    assert result.already_imported is False
    assert result.transactions_parsed == 2
    assert result.transactions_imported == 1
    assert result.duplicates_skipped == 1
    assert db_session.query(FinanceTransaction).count() == 3
