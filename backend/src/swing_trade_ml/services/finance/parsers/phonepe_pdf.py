"""PhonePe transaction-statement PDF parsing.

Ported from the standalone finance-dashboard app. PhonePe's PDF layout isn't
a table pdfplumber can extract directly, so this works off raw extracted
text: group lines into blocks starting at each detected date, then pull a
description/amount/direction/status/transaction-id out of each block with
regexes tuned against real PhonePe statements.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import BinaryIO, Iterable

import pandas as pd
import pdfplumber
from dateutil import parser as date_parser


class PhonePeParseError(Exception):
    """Raised when a statement PDF cannot be parsed."""


DATE_PATTERNS = [
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",  # 05 Mar 2025
    r"\b[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}\b",  # Mar 05, 2025
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",  # 05/03/2025
    r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",  # 2025-03-05
]
DATE_RE = re.compile("|".join(f"({p})" for p in DATE_PATTERNS), re.IGNORECASE)

# Indian rupee amounts: ₹1,234.00 / INR 1234 / Rs. 1,234
AMOUNT_RE = re.compile(
    r"(?:₹|INR|Rs\.?|RS\.?)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.\d{1,2})?|[0-9]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

TXN_ID_RE = re.compile(
    r"(?:transaction\s*id|txn\s*id|utr|upi\s*ref(?:erence)?\s*no\.?|reference\s*id)\s*[:#-]?\s*([A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)

DEBIT_WORDS = ["paid", "sent", "debited", "debit", "payment to", "transfer to", "recharge", "bill paid"]
CREDIT_WORDS = ["received", "credited", "credit", "cashback", "refund", "reversal"]
STATUS_WORDS = ["success", "successful", "completed", "failed", "pending"]


@dataclass
class ParsedTransaction:
    date: pd.Timestamp
    description: str
    amount: float
    direction: str
    status: str = "UNKNOWN"
    transaction_id: str = ""
    raw_text: str = ""
    source: str = "PhonePe"


def _read_pdf_text(file_obj: BinaryIO | bytes, password: str | None = None) -> str:
    if isinstance(file_obj, bytes):
        file_obj = io.BytesIO(file_obj)

    try:
        with pdfplumber.open(file_obj, password=password or None) as pdf:
            parts = []
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                parts.append(text)
            return "\n".join(parts)
    except Exception as exc:  # pdfplumber raises several password/parser errors
        message = str(exc).lower()
        if "password" in message or "decrypt" in message or "encrypted" in message:
            raise PhonePeParseError(
                "This PDF looks password-protected. Enter the PhonePe statement password and try again."
            ) from exc
        raise PhonePeParseError(f"Unable to read PDF: {exc}") from exc


def _normalize_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def _find_date(text: str) -> pd.Timestamp | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    try:
        return pd.Timestamp(date_parser.parse(match.group(0), dayfirst=True, fuzzy=True)).normalize()
    except Exception:
        return None


def _find_amounts(text: str) -> list[float]:
    values = []
    for match in AMOUNT_RE.finditer(text):
        value = match.group(1).replace(",", "")
        try:
            values.append(float(value))
        except ValueError:
            continue
    return values


def _direction(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in CREDIT_WORDS):
        return "CREDIT"
    if any(word in lower for word in DEBIT_WORDS):
        return "DEBIT"
    return "UNKNOWN"


def _status(text: str) -> str:
    lower = text.lower()
    for word in STATUS_WORDS:
        if word in lower:
            return word.upper()
    return "UNKNOWN"


def _transaction_id(text: str) -> str:
    match = TXN_ID_RE.search(text)
    return match.group(1) if match else ""


def _clean_description(block: str) -> str:
    desc = block
    desc = DATE_RE.sub(" ", desc)
    desc = AMOUNT_RE.sub(" ", desc)
    desc = TXN_ID_RE.sub(" ", desc)
    for word in STATUS_WORDS + ["transaction", "id", "utr", "upi", "ref", "reference", "successfully"]:
        desc = re.sub(rf"\b{re.escape(word)}\b", " ", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+", " ", desc).strip(" -:|•")
    return desc[:180] if desc else "PhonePe Transaction"


def _blocks_from_lines(lines: list[str]) -> Iterable[str]:
    """Create transaction-like blocks from extracted text.

    PhonePe PDF layouts can vary. This heuristic starts a block when a date is
    found, then keeps nearby lines until the next date.
    """
    current: list[str] = []
    for line in lines:
        has_date = bool(DATE_RE.search(line))
        has_amount = bool(AMOUNT_RE.search(line))

        if has_date and current:
            yield " ".join(current)
            current = [line]
        elif current:
            current.append(line)
        elif has_date or has_amount:
            current = [line]

    if current:
        yield " ".join(current)


def parse_phonepe_pdf(file_obj: BinaryIO | bytes, password: str | None = None) -> pd.DataFrame:
    """Parse a PhonePe PDF statement into normalized transactions.

    Returns columns: date, month, description, amount, direction, status,
    transaction_id, source, raw_text
    """
    text = _read_pdf_text(file_obj, password=password)
    lines = _normalize_lines(text)
    rows: list[ParsedTransaction] = []

    for block in _blocks_from_lines(lines):
        lower = block.lower()
        if any(skip in lower for skip in ["statement period", "opening balance", "closing balance", "page "]):
            continue

        date = _find_date(block)
        amounts = _find_amounts(block)
        if date is None or not amounts:
            continue

        # Pick the largest amount in the block — usually the transaction amount.
        amount = max(amounts)
        direction = _direction(block)
        txn = ParsedTransaction(
            date=date,
            description=_clean_description(block),
            amount=amount,
            direction=direction,
            status=_status(block),
            transaction_id=_transaction_id(block),
            raw_text=block,
        )
        rows.append(txn)

    if not rows:
        lower_text = text.lower()
        if any(
            keyword in lower_text
            for keyword in [
                "bank statement",
                "account summary",
                "transaction details",
                "debit card",
                "credit card",
                "account number",
                "ifsc",
            ]
        ):
            raise PhonePeParseError(
                "This PDF looks like a bank statement. Bank statement PDFs are not supported by this "
                "parser; try the ICICI parser or export the data as CSV and upload the CSV instead."
            )
        raise PhonePeParseError(
            "No transactions were detected. This parser supports PhonePe transaction PDFs. "
            "If the PDF is encrypted, verify the password. "
            "If this is a bank statement, export it as CSV and upload the CSV instead."
        )

    df = pd.DataFrame([r.__dict__ for r in rows])
    df = df.drop_duplicates(subset=["date", "description", "amount", "direction", "transaction_id"], keep="first")
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    return df
