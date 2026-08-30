"""Dual-source reconciliation: a PhonePe statement and a bank statement (CSV
here, standing in for ICICI) covering the same month should not double-count
the same real payment — the bank statement is authoritative."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from swing_trade_ml.core.enums import FinanceSourceType
from swing_trade_ml.db.models.finance import FinanceIngestedFile, FinanceTransaction
from swing_trade_ml.services.finance.ingestion import ingest_statement, transactions_dataframe

BANK_CSV_JAN = (
    b"date,description,amount,direction\n"
    b"2026-01-05,UPI-Swiggy Food Order,550,DEBIT\n"
)

# Same real payment, different narration/source as PhonePe would report it.
PHONEPE_DF_JAN = pd.DataFrame(
    [
        {
            "date": pd.Timestamp("2026-01-05"),
            "month": "2026-01",
            "description": "Paid to Swiggy",
            "amount": 550.0,
            "direction": "DEBIT",
            "status": "SUCCESS",
            "transaction_id": "PHONEPE-JAN-1",
            "source": "PhonePe",
            "raw_text": "Paid to Swiggy",
        }
    ]
)

PHONEPE_DF_FEB = pd.DataFrame(
    [
        {
            "date": pd.Timestamp("2026-02-10"),
            "month": "2026-02",
            "description": "Paid to Amazon",
            "amount": 1200.0,
            "direction": "DEBIT",
            "status": "SUCCESS",
            "transaction_id": "PHONEPE-FEB-1",
            "source": "PhonePe",
            "raw_text": "Paid to Amazon",
        }
    ]
)


def _ingest_fake_phonepe(db_session, filename: str, df: pd.DataFrame):
    with patch(
        "swing_trade_ml.services.finance.ingestion.detect_and_parse",
        return_value=(df, FinanceSourceType.PHONEPE_PDF),
    ):
        return ingest_statement(db_session, filename, b"fake pdf bytes")


def test_bank_statement_uploaded_after_phonepe_marks_overlapping_month_reference_only(db_session):
    _ingest_fake_phonepe(db_session, "phonepe_jan.pdf", PHONEPE_DF_JAN)
    ingest_statement(db_session, "bank_jan.csv", BANK_CSV_JAN)

    phonepe_txn = db_session.query(FinanceTransaction).filter_by(transaction_id="PHONEPE-JAN-1").one()
    assert phonepe_txn.is_reference_only is True

    # Excluded from totals...
    df = transactions_dataframe(db_session)
    assert len(df) == 1  # only the bank row counts
    assert df.iloc[0]["description"] == "UPI-Swiggy Food Order"


def test_phonepe_uploaded_after_bank_statement_is_also_marked_reference_only(db_session):
    ingest_statement(db_session, "bank_jan.csv", BANK_CSV_JAN)
    _ingest_fake_phonepe(db_session, "phonepe_jan.pdf", PHONEPE_DF_JAN)

    phonepe_txn = db_session.query(FinanceTransaction).filter_by(transaction_id="PHONEPE-JAN-1").one()
    assert phonepe_txn.is_reference_only is True


def test_non_overlapping_months_are_never_marked_reference_only(db_session):
    ingest_statement(db_session, "bank_jan.csv", BANK_CSV_JAN)
    _ingest_fake_phonepe(db_session, "phonepe_feb.pdf", PHONEPE_DF_FEB)

    feb_txn = db_session.query(FinanceTransaction).filter_by(transaction_id="PHONEPE-FEB-1").one()
    assert feb_txn.is_reference_only is False

    df = transactions_dataframe(db_session)
    assert len(df) == 2  # bank Jan row + PhonePe Feb row both count


def test_reference_only_rows_stay_visible_but_excluded_from_totals(db_session):
    _ingest_fake_phonepe(db_session, "phonepe_jan.pdf", PHONEPE_DF_JAN)
    ingest_statement(db_session, "bank_jan.csv", BANK_CSV_JAN)

    all_txns = db_session.query(FinanceTransaction).all()
    assert len(all_txns) == 2  # still visible in the raw table

    totals_df = transactions_dataframe(db_session)
    assert len(totals_df) == 1  # but excluded from totals


def test_deleting_the_bank_statement_flips_phonepe_rows_back_to_authoritative(db_session):
    _ingest_fake_phonepe(db_session, "phonepe_jan.pdf", PHONEPE_DF_JAN)
    ingest_statement(db_session, "bank_jan.csv", BANK_CSV_JAN)

    phonepe_txn = db_session.query(FinanceTransaction).filter_by(transaction_id="PHONEPE-JAN-1").one()
    assert phonepe_txn.is_reference_only is True

    from datetime import UTC, datetime

    from sqlalchemy import update

    bank_file = db_session.query(FinanceIngestedFile).filter_by(file_name="bank_jan.csv").one()
    now = datetime.now(UTC)
    bank_file.deleted_at = now
    db_session.execute(
        update(FinanceTransaction).where(FinanceTransaction.ingested_file_id == bank_file.id).values(deleted_at=now)
    )
    db_session.commit()

    from swing_trade_ml.services.finance.ingestion import reconcile_source_priority

    reconcile_source_priority(db_session)

    db_session.refresh(phonepe_txn)
    assert phonepe_txn.is_reference_only is False
