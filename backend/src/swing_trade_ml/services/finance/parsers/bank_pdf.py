"""ICICI bank-statement PDF parsing.

Two strategies, tried in order: a line-based heuristic that reads each row
starting with a `DD-MM-YYYY` date and infers direction from the running
balance delta, then (if that yields too few rows for the layout at hand) a
fallback to pdfplumber's table extraction with header-name mapping. Both
paths converge on `normalize_csv` so the result matches every other
statement source's schema.
"""

from __future__ import annotations

import io
import re
from typing import BinaryIO

import pandas as pd
import pdfplumber
from dateutil import parser as date_parser

from swing_trade_ml.services.finance.parsers.csv_parser import normalize_csv
from swing_trade_ml.services.finance.parsers.phonepe_pdf import PhonePeParseError

AMOUNT_RE = re.compile(r"(-?[0-9]{1,3}(?:,[0-9]{2,3})*(?:\.\d{1,2})?)")
MONEY_RE = re.compile(r"(?<![A-Za-z0-9/.-])(\(?-?\d[\d,]*\.\d{2}\)?)(?![A-Za-z0-9/.-])")
ROW_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}\b")

BANK_KEYWORDS = [
    "icici bank",
    "icici",
    "statement of account",
    "bank statement",
    "transaction details",
    "available balance",
]

HEADER_MAP = {
    "value date": "value_date",
    "txn date": "date",
    "transaction date": "date",
    "posting date": "date",
    "date": "date",
    "transaction details": "description",
    "transaction detail": "description",
    "narration": "description",
    "particulars": "description",
    "remarks": "description",
    "description": "description",
    "debit amount": "debit",
    "debit": "debit",
    "withdrawal": "debit",
    "dr": "debit",
    "credit amount": "credit",
    "credit": "credit",
    "deposit": "credit",
    "cr": "credit",
    "amount": "amount",
    "txn amount": "amount",
    "transaction amount": "amount",
    "dr/cr": "direction",
    "debit/credit": "direction",
    "debit credit": "direction",
    "type": "direction",
    "status": "direction",
}

DATE_PATTERNS = [
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
    r"\b[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}\b",
    r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
]
DATE_RE = re.compile("|".join(f"({p})" for p in DATE_PATTERNS), re.IGNORECASE)
SKIP_LINE_PATTERNS = [
    re.compile(r"^page \d+ of \d+$", re.IGNORECASE),
    re.compile(r"^mr\.", re.IGNORECASE),
    re.compile(r"^statement of transactions", re.IGNORECASE),
    re.compile(r"^date mode", re.IGNORECASE),
    re.compile(r"^account details", re.IGNORECASE),
]
CREDIT_HINTS = [
    "payment from",
    "rev sweep from",
    "neft",
    "imps",
    "salary",
    "refund",
    "interest",
    "deposit",
    "cash deposit",
    "cashback",
]
DEBIT_HINTS = [
    "payment to",
    "sweep to",
    "bill",
    "trade",
    "ach/",
    "loan",
    "emi",
    "withdrawal",
]
FOOTER_CUTOFFS = [
    "account related other information",
    "sincerely, team icici bank",
    "this is a system-generated statement",
    "legends for transactions",
]


def _read_pdf_text(file_obj: BinaryIO | bytes, password: str | None = None) -> str:
    if isinstance(file_obj, bytes):
        file_obj = io.BytesIO(file_obj)

    try:
        with pdfplumber.open(file_obj, password=password or None) as pdf:
            parts = []
            for page in pdf.pages:
                parts.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
            return "\n".join(parts)
    except Exception as exc:
        message = str(exc).lower()
        if "password" in message or "decrypt" in message or "encrypted" in message:
            raise PhonePeParseError(
                "This PDF looks password-protected. Enter the statement password and try again."
            ) from exc
        raise PhonePeParseError(f"Unable to read PDF: {exc}") from exc


def _looks_like_bank_statement(text: str) -> bool:
    if not text:
        return False
    normalized = text.lower()
    return any(keyword in normalized for keyword in BANK_KEYWORDS)


def _normalize_lines(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines


def _skip_line(line: str) -> bool:
    lower = line.lower()
    if any(pattern.match(line) for pattern in SKIP_LINE_PATTERNS):
        return True
    return (
        "statement summary" in lower
        or "relationship balance" in lower
        or "account type" in lower
        or "total balance" in lower
    )


def _normalize_header(cell: str | None) -> str | None:
    if not cell:
        return None
    text = str(cell).strip().lower()
    text = re.sub(r"\s+", " ", text)
    for key, normalized in HEADER_MAP.items():
        if key == text or key in text:
            return normalized
    return None


def _is_header_row(row: list[str]) -> bool:
    normalized = [str(cell).strip().lower() for cell in row if cell is not None]
    if not normalized:
        return False
    has_date = any("date" in cell for cell in normalized)
    has_amount = any(word in cell for cell in normalized for word in ["debit", "credit", "amount", "dr", "cr"])
    has_desc = any(
        word in cell
        for cell in normalized
        for word in ["description", "narration", "particulars", "transaction details", "remarks", "details"]
    )
    return has_date and has_amount and has_desc


def _parse_date(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    if isinstance(value, str):
        value = value.strip()
    if not value:
        return None
    if DATE_RE.search(str(value)) is None:
        return None
    try:
        return pd.Timestamp(date_parser.parse(str(value), dayfirst=True, fuzzy=True)).normalize()
    except Exception:
        return None


def _clean_amount(value: str | None) -> float | None:
    if value is None:
        return None
    raw = str(value).replace("₹", "").replace("INR", "").replace("Rs.", "").replace("Rs", "").replace("-", "-").strip()
    raw = raw.replace("(", "-").replace(")", "")
    raw = raw.replace(",", "")
    match = AMOUNT_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _clean_money_token(value: str) -> float | None:
    raw = str(value).replace("(", "-").replace(")", "").replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _split_transaction_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    in_transactions = False

    for line in lines:
        lower = line.lower()
        if "date mode" in lower and "balance" in lower:
            in_transactions = True
            continue
        if not in_transactions:
            continue
        if _skip_line(line):
            continue
        if ROW_DATE_RE.match(line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)

    if current:
        blocks.append(current)
    return blocks


def _infer_direction(description: str, amount: float, balance: float, previous_balance: float | None) -> str:
    lower = description.lower()
    if "(-)" in lower:
        return "DEBIT"
    if previous_balance is not None:
        if abs((previous_balance + amount) - balance) <= 1.0:
            return "CREDIT"
        if abs((previous_balance - amount) - balance) <= 1.0:
            return "DEBIT"
    if any(token in lower for token in CREDIT_HINTS):
        return "CREDIT"
    if any(token in lower for token in DEBIT_HINTS):
        return "DEBIT"
    return "DEBIT"


def _block_to_record(block: list[str], previous_balance: float | None) -> tuple[dict[str, object] | None, float | None]:
    joined = " ".join(block)
    lower_joined = joined.lower()
    for cutoff in FOOTER_CUTOFFS:
        if cutoff in lower_joined:
            joined = joined[: lower_joined.index(cutoff)].strip()
            lower_joined = joined.lower()
            break
    if not joined:
        return None, previous_balance
    if " total " in f" {lower_joined} " and ("account related" in lower_joined or "team icici bank" in lower_joined):
        return None, previous_balance

    if " b/f " in f" {joined.lower()} ":
        amounts = [_clean_money_token(match.group(1)) for match in MONEY_RE.finditer(joined)]
        amounts = [value for value in amounts if value is not None]
        return None, amounts[-1] if amounts else previous_balance

    date_match = ROW_DATE_RE.match(block[0])
    if not date_match:
        return None, previous_balance
    date_value = _parse_date(date_match.group(0))
    if date_value is None:
        return None, previous_balance

    amount_matches = list(MONEY_RE.finditer(joined))
    if len(amount_matches) < 2:
        return None, previous_balance
    if " total " in f" {lower_joined} " and len(amount_matches) > 2:
        return None, previous_balance

    money_values = [_clean_money_token(match.group(1)) for match in amount_matches]
    money_values = [value for value in money_values if value is not None]
    if len(money_values) < 2:
        return None, previous_balance

    amount = abs(money_values[-2])
    balance = money_values[-1]
    between_amount_and_balance = joined[amount_matches[-2].end() : amount_matches[-1].start()]
    if "(-)" in between_amount_and_balance:
        balance = -abs(balance)
    description = joined[len(date_match.group(0)) : amount_matches[-2].start()].strip(" -")
    description = re.sub(r"\s+", " ", description).strip()
    if not description:
        description = "ICICI Bank transaction"

    direction = _infer_direction(joined, amount, balance, previous_balance)
    record = {
        "date": date_value,
        "description": description[:220],
        "amount": amount,
        "direction": direction,
        "raw_text": joined,
        "source": "Bank Statement",
    }
    return record, balance


def _row_to_record(row: dict[str, object]) -> dict[str, object] | None:
    date_value = _parse_date(str(row.get("date", "") or row.get("value_date", "") or ""))
    if date_value is None:
        return None

    description = " ".join(
        str(row.get(key, "") or "").strip()
        for key in ["description", "transaction_details", "narration", "particulars", "remarks", "details"]
    ).strip()
    description = description or "ICICI Bank transaction"

    debit_value = _clean_amount(str(row.get("debit", "") or ""))
    credit_value = _clean_amount(str(row.get("credit", "") or ""))
    amount_value = _clean_amount(str(row.get("amount", "") or ""))
    direction_value = str(row.get("direction", "") or "").strip().upper()

    if debit_value is not None and debit_value > 0:
        return {
            "date": date_value,
            "description": description,
            "amount": debit_value,
            "direction": "DEBIT",
        }
    if credit_value is not None and credit_value > 0:
        return {
            "date": date_value,
            "description": description,
            "amount": credit_value,
            "direction": "CREDIT",
        }
    if amount_value is not None:
        if direction_value in {"CR", "CREDIT"}:
            direction = "CREDIT"
        elif direction_value in {"DR", "DEBIT"}:
            direction = "DEBIT"
        else:
            direction = "DEBIT"
        return {
            "date": date_value,
            "description": description,
            "amount": amount_value,
            "direction": direction,
        }
    return None


def _parse_table(table: list[list[str] | None]) -> list[dict[str, object]]:
    if not table:
        return []

    cleaned_rows = [
        [str(cell).strip() if cell is not None else "" for cell in row]
        for row in table
        if row and any(cell is not None and str(cell).strip() for cell in row)
    ]

    if len(cleaned_rows) < 2:
        return []

    header_index = next((index for index, row in enumerate(cleaned_rows) if _is_header_row(row)), None)
    if header_index is None:
        return []

    header_row = cleaned_rows[header_index]
    normalized_headers = [_normalize_header(cell) for cell in header_row]
    records: list[dict[str, object]] = []

    for row in cleaned_rows[header_index + 1 :]:
        row_map = {
            normalized_headers[i]: row[i]
            for i in range(min(len(normalized_headers), len(row)))
            if normalized_headers[i]
        }
        record = _row_to_record(row_map)
        if record is not None:
            records.append(record)

    return records


def parse_icici_pdf(file_obj: BinaryIO | bytes, password: str | None = None) -> pd.DataFrame:
    text = _read_pdf_text(file_obj, password=password)
    if not _looks_like_bank_statement(text):
        raise PhonePeParseError(
            "This PDF does not appear to be an ICICI bank statement. Use a CSV export if possible."
        )

    lines = _normalize_lines(text)
    blocks = _split_transaction_blocks(lines)
    records: list[dict[str, object]] = []
    previous_balance: float | None = None

    for block in blocks:
        record, previous_balance = _block_to_record(block, previous_balance)
        if record is not None:
            records.append(record)

    table_records: list[dict[str, object]] = []
    if len(records) < 50:
        # Fallback to table extraction for unexpected PDF layouts.
        if isinstance(file_obj, bytes):
            file_obj = io.BytesIO(file_obj)
        with pdfplumber.open(file_obj, password=password or None) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables or []:
                    table_records.extend(_parse_table(table))
                if not table_records:
                    alt_settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
                    tables = page.extract_tables(table_settings=alt_settings)
                    for table in tables or []:
                        table_records.extend(_parse_table(table))
                if not table_records:
                    alt_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
                    tables = page.extract_tables(table_settings=alt_settings)
                    for table in tables or []:
                        table_records.extend(_parse_table(table))
        if len(table_records) > len(records):
            records = table_records

    if not records:
        raise PhonePeParseError(
            "Could not extract transactions from the ICICI PDF. Convert the statement to CSV and upload the CSV instead."
        )

    return normalize_csv(pd.DataFrame(records))


def is_bank_statement_pdf(file_obj: BinaryIO | bytes, password: str | None = None) -> bool:
    text = _read_pdf_text(file_obj, password=password)
    return _looks_like_bank_statement(text)
