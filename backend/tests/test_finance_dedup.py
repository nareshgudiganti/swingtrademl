"""compute_dedup_key: the practical identity of a transaction across
re-uploads of the same or overlapping statements."""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.services.finance.ingestion import compute_dedup_key


def _row(**overrides):
    base = {
        "date": pd.Timestamp("2026-07-05"),
        "description": "Swiggy Order",
        "amount": 550.0,
        "source": "UPI",
        "transaction_id": "",
    }
    base.update(overrides)
    return pd.Series(base)


def test_uses_transaction_id_when_present():
    key = compute_dedup_key(_row(transaction_id="TXN12345"))
    assert key == "TXN12345"


def test_falls_back_to_composite_key_when_transaction_id_is_blank():
    key = compute_dedup_key(_row(transaction_id=""))
    assert key == "2026-07-05|Swiggy Order|550.00|UPI"


def test_composite_key_is_stable_across_calls():
    a = compute_dedup_key(_row())
    b = compute_dedup_key(_row())
    assert a == b


def test_composite_key_changes_when_amount_changes():
    a = compute_dedup_key(_row(amount=550.0))
    b = compute_dedup_key(_row(amount=551.0))
    assert a != b


def test_composite_key_changes_when_description_changes():
    a = compute_dedup_key(_row(description="Swiggy Order"))
    b = compute_dedup_key(_row(description="Zomato Order"))
    assert a != b


def test_composite_key_ignores_raw_text_and_status():
    # raw_text/status don't participate in identity — two rows differing only
    # in those fields must dedup to the same key.
    a = compute_dedup_key(_row())
    row_with_extra = _row()
    row_with_extra["raw_text"] = "something completely different"
    row_with_extra["status"] = "PENDING"
    b = compute_dedup_key(row_with_extra)
    assert a == b


def test_whitespace_only_transaction_id_is_treated_as_blank():
    key = compute_dedup_key(_row(transaction_id="   "))
    assert key == "2026-07-05|Swiggy Order|550.00|UPI"
