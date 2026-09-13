"""Generic CSV statement parsing — flexible column-name detection so exports
from most banks/UPI apps normalize into the same schema the PDF parsers
produce.
"""

from __future__ import annotations

import hashlib
import io
import re

import pandas as pd

ISO_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def _parse_date_column(series: pd.Series) -> pd.Series:
    """`dayfirst=True` (needed for Indian DD-MM-YYYY exports) misreads
    unambiguous ISO `YYYY-MM-DD` dates — pandas silently swaps month/day or
    drops the row outright. ISO-looking values are parsed without dayfirst;
    everything else keeps the dayfirst behavior the rest of this function
    relies on."""
    text = series.astype(str).str.strip()
    iso_mask = text.str.match(ISO_DATE_RE)
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if iso_mask.any():
        parsed.loc[iso_mask] = pd.to_datetime(text.loc[iso_mask], errors="coerce")
    if (~iso_mask).any():
        parsed.loc[~iso_mask] = pd.to_datetime(text.loc[~iso_mask], dayfirst=True, errors="coerce")
    return parsed

PROVIDER_KEYWORDS = {
    "CRED": ["cred"],
    "Google Pay": ["google pay", "gpay", "googlepay"],
    "PhonePe": ["phonepe", "phone pe"],
    "Paytm": ["paytm"],
    "UPI": ["upi"],
}


def infer_transaction_source(description: str) -> str:
    text = str(description or "").strip().lower()
    if not text:
        return "Bank Statement"

    for provider, keywords in PROVIDER_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return provider
    return "Bank Statement"


def _decode_csv_bytes(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def read_uploaded_csv(file_bytes: bytes) -> pd.DataFrame:
    """Decode arbitrary bank/UPI CSV export bytes into a raw DataFrame.

    Skips any preamble rows (bank exports often prepend account-summary
    lines) by scanning for the first line that looks like a real transaction
    header.
    """
    text = _decode_csv_bytes(file_bytes)
    lines = text.splitlines()

    def _looks_like_transaction_header(line: str) -> bool:
        normalized = [part.strip().lower() for part in line.split(",")]
        has_date = "date" in normalized
        has_desc = any(part in normalized for part in ["particulars", "description", "narration", "details", "remarks"])
        has_amount = any(
            part in normalized
            for part in ["amount", "deposits", "deposit", "withdrawals", "withdrawal", "debit", "credit"]
        )
        return has_date and has_desc and has_amount

    start_index = 0
    for idx, line in enumerate(lines):
        if _looks_like_transaction_header(line):
            start_index = idx
            break

    candidate_text = "\n".join(lines[start_index:]).strip()
    if not candidate_text:
        raise ValueError("CSV file is empty.")

    last_error: Exception | None = None
    for kwargs in (
        {"engine": "python"},
        {"engine": "python", "on_bad_lines": "skip"},
    ):
        try:
            return pd.read_csv(io.StringIO(candidate_text), **kwargs)
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Could not read CSV format: {last_error}")


def normalize_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize CSVs from banks/UPI exports into the standard schema:
    date, month, description, amount, direction, status, transaction_id,
    source, raw_text.
    """
    data = df.copy()
    data["_source_row"] = range(1, len(data) + 1)

    col_map = {}
    for c in data.columns:
        normalized = str(c).strip().lower()
        if normalized in {"date", "transaction_date", "txn_date", "transaction date", "txn date"}:
            col_map[c] = "date"
        elif normalized in {"narration", "description", "details", "merchant", "remarks", "particulars"}:
            col_map[c] = "description"
        elif normalized in {"amount", "txn amount", "transaction amount", "value"}:
            col_map[c] = "amount"
        elif normalized in {"debit amount", "debit", "withdrawal", "withdrawals", "dr"}:
            col_map[c] = "debit"
        elif normalized in {"credit amount", "credit", "deposit", "deposits", "cr"}:
            col_map[c] = "credit"
        elif normalized in {"type", "direction", "dr_cr", "credit_debit", "dr cr", "credit debit"}:
            col_map[c] = "direction"
        elif normalized in {"mode", "channel", "payment mode"}:
            col_map[c] = "mode"
        elif normalized == "status":
            col_map[c] = "status"
        elif normalized == "transaction_id":
            col_map[c] = "transaction_id"
        elif normalized == "raw_text":
            col_map[c] = "raw_text"
        elif normalized == "source":
            col_map[c] = "source"

    data = data.rename(columns=col_map)

    if "date" not in data.columns or "description" not in data.columns:
        missing = {"date", "description"} - set(data.columns)
        raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")

    data["date"] = _parse_date_column(data["date"])

    def _series_from_value(value):
        if isinstance(value, pd.Series):
            return value
        if value is None:
            return pd.Series([0] * len(data), index=data.index, dtype=float)
        return pd.Series([value] * len(data), index=data.index)

    def _clean_numeric(series: pd.Series) -> pd.Series:
        text = series.fillna("").astype(str).str.strip()
        text = text.str.replace(",", "", regex=False)
        text = text.str.replace("Rs.", "", regex=False)
        text = text.str.replace("INR", "", regex=False)
        text = text.str.replace(r"[^\d.\-Ee+]", "", regex=True)
        return pd.to_numeric(text, errors="coerce").fillna(0)

    debit_amount = _clean_numeric(_series_from_value(data.get("debit", 0)))
    credit_amount = _clean_numeric(_series_from_value(data.get("credit", 0)))
    if "amount" not in data.columns:
        data["amount"] = debit_amount.abs().where(debit_amount.abs() > 0, credit_amount.abs())
    else:
        data["amount"] = _clean_numeric(data["amount"]).abs()
        if "debit" in data.columns or "credit" in data.columns:
            explicit_amount = debit_amount.abs().where(debit_amount.abs() > 0, credit_amount.abs())
            if len(explicit_amount) == len(data["amount"]):
                data["amount"] = explicit_amount.where(explicit_amount > 0, data["amount"])

    if data["amount"].eq(0).all():
        raise ValueError("CSV did not contain any valid transaction amounts.")

    data["description"] = data["description"].astype(str)
    if "mode" in data.columns:
        data["mode"] = data["mode"].fillna("").astype(str).str.strip()
    else:
        data["mode"] = ""
    if "source" not in data.columns:
        data["source"] = (data["description"] + " " + data["mode"]).apply(infer_transaction_source)
    else:
        data["source"] = data["source"].fillna("").astype(str).str.strip()
        inferred_source = (data["description"] + " " + data["mode"]).apply(infer_transaction_source)
        data.loc[data["source"] == "", "source"] = inferred_source

    if "direction" not in data.columns:
        data["direction"] = "DEBIT"
        data.loc[credit_amount.abs() > 0, "direction"] = "CREDIT"
        data.loc[(credit_amount.abs() == 0) & (debit_amount.abs() == 0) & (data["amount"] > 0), "direction"] = "DEBIT"
    else:
        data["direction"] = data["direction"].fillna("").astype(str).str.upper()
        data["direction"] = data["direction"].replace({"DR": "DEBIT", "CR": "CREDIT", "D": "DEBIT", "C": "CREDIT"})
        if data["direction"].eq("").any():
            data.loc[data["direction"].eq(""), "direction"] = "DEBIT"

    data["status"] = data.get("status", "UNKNOWN")
    data["transaction_id"] = data.get("transaction_id", "")
    if "raw_text" in data.columns:
        data["raw_text"] = data["raw_text"].fillna("").astype(str)
    else:
        combined_text = data["description"].fillna("").astype(str)
        if "mode" in data.columns:
            combined_text = (data["mode"].fillna("").astype(str) + " " + combined_text).str.strip()
        data["raw_text"] = combined_text
    data = data.dropna(subset=["date", "amount"])
    data = data[data["amount"] > 0]
    data["month"] = data["date"].dt.to_period("M").astype(str)

    blank_txn = data["transaction_id"].fillna("").astype(str).str.strip().eq("")
    if blank_txn.any():
        data.loc[blank_txn, "transaction_id"] = data.loc[blank_txn].apply(
            lambda row: "csv-"
            + hashlib.sha1(
                "|".join(
                    [
                        pd.to_datetime(row["date"]).strftime("%Y-%m-%d"),
                        str(row["description"]),
                        f"{float(row['amount']):.2f}",
                        str(row["direction"]),
                        str(row["source"]),
                    ]
                ).encode("utf-8")
            ).hexdigest()[:16],
            axis=1,
        )

    return data[["date", "month", "description", "amount", "direction", "status", "transaction_id", "source", "raw_text"]]
