"""CSV statement parsing: encoding fallback, header-row detection with
preamble junk, and column-name mapping across bank/UPI export variants."""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.services.finance.parsers.csv_parser import (
    infer_transaction_source,
    normalize_csv,
    read_uploaded_csv,
)

STANDARD_COLUMNS = ["date", "month", "description", "amount", "direction", "status", "transaction_id", "source", "raw_text"]


def test_read_uploaded_csv_skips_preamble_before_the_real_header():
    text = (
        "Account Statement\n"
        "Account Number: XXXX1234\n"
        "\n"
        "date,description,amount,direction\n"
        "2026-01-05,Swiggy Order,550,DEBIT\n"
    )
    df = read_uploaded_csv(text.encode("utf-8"))
    assert list(df.columns) == ["date", "description", "amount", "direction"]
    assert len(df) == 1


def test_read_uploaded_csv_decodes_latin1_when_utf8_fails():
    # "café" encoded as latin-1 is not valid utf-8.
    text = "date,description,amount,direction\n2026-01-05,café order,100,DEBIT\n"
    raw = text.encode("latin-1")
    df = read_uploaded_csv(raw)
    assert "café" in df.iloc[0]["description"]


def test_normalize_csv_maps_common_column_name_variants():
    df = pd.DataFrame(
        [{"Txn Date": "05-01-2026", "Narration": "Swiggy Order", "Withdrawal": "550", "Deposit": ""}]
    )
    result = normalize_csv(df)
    assert list(result.columns) == STANDARD_COLUMNS
    row = result.iloc[0]
    assert row["description"] == "Swiggy Order"
    assert row["amount"] == 550.0
    assert row["direction"] == "DEBIT"


def test_normalize_csv_infers_credit_direction_from_deposit_column():
    df = pd.DataFrame([{"date": "31-01-2026", "particulars": "Salary Credit", "deposit": "180000"}])
    result = normalize_csv(df)
    assert result.iloc[0]["direction"] == "CREDIT"
    assert result.iloc[0]["amount"] == 180000.0


def test_normalize_csv_requires_date_and_description():
    df = pd.DataFrame([{"amount": "100"}])
    try:
        normalize_csv(df)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "date" in str(exc) and "description" in str(exc)


def test_normalize_csv_generates_deterministic_synthetic_transaction_id():
    df = pd.DataFrame([{"date": "05-01-2026", "description": "Swiggy Order", "amount": "550", "direction": "DEBIT"}])
    result_a = normalize_csv(df.copy())
    result_b = normalize_csv(df.copy())
    assert result_a.iloc[0]["transaction_id"] == result_b.iloc[0]["transaction_id"]
    assert result_a.iloc[0]["transaction_id"].startswith("csv-")


def test_normalize_csv_synthetic_id_changes_when_amount_changes():
    base = {"date": "05-01-2026", "description": "Swiggy Order", "amount": "550", "direction": "DEBIT"}
    changed = {**base, "amount": "551"}
    id_a = normalize_csv(pd.DataFrame([base])).iloc[0]["transaction_id"]
    id_b = normalize_csv(pd.DataFrame([changed])).iloc[0]["transaction_id"]
    assert id_a != id_b


def test_infer_transaction_source_recognizes_known_providers():
    assert infer_transaction_source("Paid via PhonePe to Swiggy") == "PhonePe"
    assert infer_transaction_source("UPI-9999@okhdfcbank") == "UPI"
    assert infer_transaction_source("NEFT to landlord") == "Bank Statement"
    assert infer_transaction_source("") == "Bank Statement"
