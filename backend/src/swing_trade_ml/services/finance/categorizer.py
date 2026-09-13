"""Keyword-rule based transaction categorization.

Ported from the standalone finance-dashboard app, minus its optional TF-IDF/
Naive Bayes fallback (out of scope here — pure keyword rules only).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.finance import FinanceCustomRule

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "category_rules.csv"
INCOME_CATEGORIES = {"Income", "Income / Credit", "Refund", "Rewards / Cashback"}
# A sweep-in is a CREDIT-direction row like any other income, so it needs the
# same permission to override the CREDIT default — otherwise every sweep-in
# stays miscategorized as "Income / Credit" instead of "Internal Transfer".
CREDIT_OVERRIDE_CATEGORIES = INCOME_CATEGORIES | {"Internal Transfer"}


def normalize_text(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def keyword_pattern(keyword: str) -> str:
    escaped = re.escape(normalize_text(keyword))
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"


def load_rules(path: str | Path | None = None) -> pd.DataFrame:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    rules = pd.read_csv(rules_path)
    rules["keyword"] = rules["keyword"].apply(normalize_text)
    rules["category"] = rules["category"].astype(str).str.strip()
    if "priority" not in rules.columns:
        rules["priority"] = 50
    rules["priority"] = pd.to_numeric(rules["priority"], errors="coerce").fillna(50).astype(int)
    rules = rules.dropna().drop_duplicates()
    rules["keyword_length"] = rules["keyword"].str.len()
    rules = rules.sort_values(["priority", "keyword_length"], ascending=[False, False])
    return rules


def custom_rules_df(db: Session) -> pd.DataFrame:
    rows = db.execute(select(FinanceCustomRule.keyword, FinanceCustomRule.category, FinanceCustomRule.priority)).all()
    return pd.DataFrame(rows, columns=["keyword", "category", "priority"])


def combined_rules(db: Session, path: str | Path | None = None) -> pd.DataFrame:
    """Bundled CSV rules plus the user's own custom rules, re-normalized and
    re-sorted together. Custom rules default to priority 90 (see
    `FinanceCustomRule`) so a user's own correction naturally outranks the
    bundled rules' default 50 without needing to know the priority scheme."""
    base = pd.read_csv(Path(path) if path else DEFAULT_RULES_PATH)
    custom = custom_rules_df(db)
    rules = pd.concat([base, custom], ignore_index=True)
    rules["keyword"] = rules["keyword"].apply(normalize_text)
    rules["category"] = rules["category"].astype(str).str.strip()
    if "priority" not in rules.columns:
        rules["priority"] = 50
    rules["priority"] = pd.to_numeric(rules["priority"], errors="coerce").fillna(50).astype(int)
    rules = rules.dropna().drop_duplicates()
    rules["keyword_length"] = rules["keyword"].str.len()
    return rules.sort_values(["priority", "keyword_length"], ascending=[False, False])


def categorize_transactions(df: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """Assign a `category` to every row.

    CREDIT rows default to "Income / Credit" and can only be overwritten by a
    rule whose category is itself an income/refund/reward category — a
    keyword match like "food" must never reclassify a salary credit just
    because the narration happens to mention it.
    """
    result = df.copy()
    result["category"] = "Uncategorised"

    credit_mask = result["direction"].str.upper().eq("CREDIT")
    result.loc[credit_mask, "category"] = "Income / Credit"

    description = result["description"].fillna("").apply(normalize_text)
    raw_text = result.get("raw_text", pd.Series([""] * len(result))).fillna("").apply(normalize_text)
    search_text = description + " " + raw_text
    assigned_priority = pd.Series([0] * len(result), index=result.index)

    for _, rule in rules.iterrows():
        keyword = normalize_text(rule["keyword"])
        category = str(rule["category"]).strip()
        priority = int(rule.get("priority", 50))
        if not keyword or not category:
            continue
        mask = search_text.str.contains(keyword_pattern(keyword), regex=True, na=False)
        if category not in CREDIT_OVERRIDE_CATEGORIES:
            mask = mask & ~credit_mask
        mask = mask & (priority > assigned_priority)
        result.loc[mask, "category"] = category
        assigned_priority.loc[mask] = priority

    return result
