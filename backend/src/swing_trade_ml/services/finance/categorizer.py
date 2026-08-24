"""Keyword-rule based transaction categorization.

Ported from the standalone finance-dashboard app, minus its optional TF-IDF/
Naive Bayes fallback (out of scope here — pure keyword rules only).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "category_rules.csv"
INCOME_CATEGORIES = {"Income", "Income / Credit", "Refund", "Rewards / Cashback"}


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
        if category not in INCOME_CATEGORIES:
            mask = mask & ~credit_mask
        mask = mask & (priority > assigned_priority)
        result.loc[mask, "category"] = category
        assigned_priority.loc[mask] = priority

    return result
