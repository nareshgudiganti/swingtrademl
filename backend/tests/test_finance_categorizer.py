"""Keyword-rule categorization against the actual bundled category_rules.csv.

Ported from the standalone finance-dashboard app's own categorizer test,
plus edge cases specific to the priority/whole-word/credit-protection rules
that `categorize_transactions` implements.
"""

from __future__ import annotations

import pandas as pd
import pytest

from swing_trade_ml.services.finance.categorizer import categorize_transactions, load_rules


def _txn(description: str, amount: float = 100.0, direction: str = "DEBIT", raw_text: str = ""):
    return {
        "date": "2026-07-05",
        "month": "2026-07",
        "description": description,
        "amount": amount,
        "direction": direction,
        "status": "",
        "transaction_id": "",
        "source": "UPI",
        "raw_text": raw_text,
    }


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def test_customer_merchant_aliases_map_to_expected_categories(rules):
    transactions = pd.DataFrame(
        [
            _txn("UPI payment to Smart Bazaar", 420.0),
            _txn("South India Shopping saree purchase", 3400.0),
            _txn("Amazon order", 1299.0),
            _txn("Zomato dinner", 650.0),
        ]
    )

    categorized = categorize_transactions(transactions, rules)

    assert categorized.iloc[0]["category"] == "Groceries"
    assert categorized.iloc[1]["category"] == "Shopping"
    assert categorized.iloc[2]["category"] == "Ecommerce"
    assert categorized.iloc[3]["category"] == "Food / Restaurants"


def test_credit_rows_default_to_income_credit(rules):
    transactions = pd.DataFrame([_txn("Random narration with no keyword match", 500.0, direction="CREDIT")])
    categorized = categorize_transactions(transactions, rules)
    assert categorized.iloc[0]["category"] == "Income / Credit"


def test_credit_rows_are_not_overwritten_by_a_non_income_keyword_match(rules):
    # "food" is a Food / Restaurants keyword, but this row is a CREDIT — it
    # must stay Income / Credit, not get reclassified just because the
    # narration happens to contain the word.
    transactions = pd.DataFrame([_txn("Refund for food order", 550.0, direction="CREDIT")])
    categorized = categorize_transactions(transactions, rules)
    # "refund" is itself an income-category keyword, so it IS allowed to win.
    assert categorized.iloc[0]["category"] == "Refund"


def test_credit_rows_with_only_a_non_income_keyword_stay_income_credit(rules):
    transactions = pd.DataFrame([_txn("Zomato reversal for cancelled order", 300.0, direction="CREDIT")])
    categorized = categorize_transactions(transactions, rules)
    # "zomato" -> Food / Restaurants is not an income category, so it must
    # not override the CREDIT default.
    assert categorized.iloc[0]["category"] == "Income / Credit"


def test_whole_word_boundary_does_not_match_inside_a_longer_word():
    rules = pd.DataFrame([{"keyword": "food", "category": "Food / Restaurants", "priority": 50}])
    transactions = pd.DataFrame([_txn("Foodie App Subscription", 199.0)])
    categorized = categorize_transactions(transactions, rules)
    assert categorized.iloc[0]["category"] == "Uncategorised"


def test_whole_word_boundary_matches_food_as_a_standalone_word():
    rules = pd.DataFrame([{"keyword": "food", "category": "Food / Restaurants", "priority": 50}])
    transactions = pd.DataFrame([_txn("Food court payment", 199.0)])
    categorized = categorize_transactions(transactions, rules)
    assert categorized.iloc[0]["category"] == "Food / Restaurants"


def test_load_rules_defaults_priority_to_50_when_column_is_absent(tmp_path):
    csv_path = tmp_path / "rules.csv"
    csv_path.write_text("keyword,category\nswiggy,Food / Restaurants\n")
    rules = load_rules(csv_path)
    assert rules.iloc[0]["priority"] == 50


def test_higher_priority_rule_wins_over_lower_priority_rule():
    rules = pd.DataFrame(
        [
            {"keyword": "amazon", "category": "Ecommerce", "priority": 50},
            {"keyword": "amazon pay", "category": "Payments / UPI", "priority": 90},
        ]
    ).sort_values(["priority", "keyword"], ascending=[False, False])
    transactions = pd.DataFrame([_txn("Amazon Pay recharge")])
    categorized = categorize_transactions(transactions, rules)
    assert categorized.iloc[0]["category"] == "Payments / UPI"
