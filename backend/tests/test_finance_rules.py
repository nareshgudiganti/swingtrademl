"""Custom category rules: merging with the bundled CSV, and the
recategorization pass a rule change triggers."""

from __future__ import annotations

from swing_trade_ml.db.models.finance import FinanceCustomRule, FinanceTransaction
from swing_trade_ml.services.finance import categorizer
from swing_trade_ml.services.finance.ingestion import ingest_statement, recategorize_all

SAMPLE_CSV = (
    b"date,description,amount,direction\n"
    b"2026-01-05,Smart Bazaar order,420,DEBIT\n"
    b"2026-01-06,Totally Unknown Merchant XYZ,300,DEBIT\n"
)


def test_combined_rules_includes_both_bundled_and_custom_keywords(db_session):
    db_session.add(FinanceCustomRule(keyword="totallyunknownmerchant", category="Miscellaneous", priority=90))
    db_session.commit()

    rules = categorizer.combined_rules(db_session)
    keywords = set(rules["keyword"])
    assert "smart" in keywords  # from the bundled CSV
    assert "totallyunknownmerchant" in keywords  # from the DB


def test_custom_rule_outranks_a_lower_priority_bundled_rule(db_session):
    # "smart" (bundled, priority 50) -> Groceries. Add a custom rule on the
    # same keyword at the default custom priority (90) and confirm it wins.
    db_session.add(FinanceCustomRule(keyword="smart", category="Custom Override Category", priority=90))
    db_session.commit()

    rules = categorizer.combined_rules(db_session)
    smart_rows = rules[rules["keyword"] == "smart"]
    assert len(smart_rows) == 2  # the bundled row (50) and the custom override (90)
    assert (smart_rows["priority"] == 90).any()
    # Within the "smart" keyword's own rows, the custom (90) one must sort
    # ahead of the bundled (50) one — this is what makes it actually win
    # during categorization, not just exist in the combined table.
    assert smart_rows.iloc[0]["category"] == "Custom Override Category"
    assert smart_rows.iloc[0]["priority"] == 90


def test_upserting_a_rule_recategorizes_existing_unmatched_transactions(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)

    unknown = db_session.query(FinanceTransaction).filter_by(description="Totally Unknown Merchant XYZ").one()
    assert unknown.category == "Uncategorised"

    db_session.add(FinanceCustomRule(keyword="unknown", category="Miscellaneous", priority=90))
    db_session.commit()

    updated_count = recategorize_all(db_session)
    assert updated_count == 1

    db_session.refresh(unknown)
    assert unknown.category == "Miscellaneous"


def test_recategorize_all_never_touches_manually_overridden_rows(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)

    smart_txn = db_session.query(FinanceTransaction).filter_by(description="Smart Bazaar order").one()
    smart_txn.category = "My Own Category"
    smart_txn.is_manual_override = True
    db_session.commit()

    # Add a rule that would otherwise reclassify this same transaction.
    db_session.add(FinanceCustomRule(keyword="smart", category="Something Else Entirely", priority=95))
    db_session.commit()
    recategorize_all(db_session)

    db_session.refresh(smart_txn)
    assert smart_txn.category == "My Own Category"


def test_recategorize_all_returns_zero_when_nothing_changes(db_session):
    ingest_statement(db_session, "statement.csv", SAMPLE_CSV)
    # No new rules added — re-running should change nothing.
    assert recategorize_all(db_session) == 0
