"""Getting real Zerodha trades into `broker_fills`.

Two doors, one key. Kite's API returns only today's trades, so a daily capture
builds history going forward; Zerodha's Console "Tradebook" file fills in the
past. Both carry Zerodha's trade_id, so a trade seen through both is stored
once (ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.fills import BrokerFill

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class StoreResult:
    added: int
    already_stored: int
    skipped: int  # not a delivery equity trade, or unreadable


def _store(db: Session, rows: list[dict], skipped: int) -> StoreResult:
    added = 0
    for row in rows:
        inserted = db.execute(
            insert(BrokerFill)
            .values(**row)
            .on_conflict_do_nothing(index_elements=["trade_id"])
            .returning(BrokerFill.id)
        ).scalar_one_or_none()
        added += inserted is not None
    db.commit()
    return StoreResult(added=added, already_stored=len(rows) - added, skipped=skipped)


def _as_ist(value: datetime) -> datetime:
    return value.replace(tzinfo=IST) if value.tzinfo is None else value.astimezone(IST)


def store_kite_trades(db: Session, trades: list[dict]) -> StoreResult:
    """Persist the shape `kite.trades()` returns. Delivery (CNC) only — the
    cost model and the whole report are about shares held, not day trades."""
    rows: list[dict] = []
    skipped = 0
    for t in trades:
        side = str(t.get("transaction_type", "")).upper()
        stamp = t.get("fill_timestamp") or t.get("exchange_timestamp") or t.get("order_timestamp")
        if t.get("product") != "CNC" or side not in ("BUY", "SELL") or not t.get("trade_id") or not stamp:
            skipped += 1
            continue
        if isinstance(stamp, str):
            stamp = datetime.fromisoformat(stamp)
        rows.append(
            {
                "trade_id": str(t["trade_id"]),
                "order_id": str(t["order_id"]) if t.get("order_id") else None,
                "symbol": t["tradingsymbol"],
                "exchange": t.get("exchange", "NSE"),
                "side": side,
                "quantity": int(t["quantity"]),
                "price": float(t["average_price"]),
                "product": "CNC",
                "executed_at": _as_ist(stamp),
                "source": "api",
            }
        )
    return _store(db, rows, skipped)


def capture_todays_fills(db: Session) -> StoreResult:
    from swing_trade_ml.brokers.kite import kite_broker

    return store_kite_trades(db, kite_broker.get_trades(db))


class TradebookError(ValueError):
    """The uploaded file is not a Zerodha tradebook we can read."""


def parse_tradebook_csv(content: bytes) -> tuple[list[dict], int]:
    """Read Zerodha Console's tradebook CSV into fill rows.

    Returns (rows, skipped). Zerodha may put a few title lines above the header,
    so the header row is located by its column names rather than assumed.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TradebookError("That file is not a text/CSV file.") from exc

    lines = list(csv.reader(io.StringIO(text)))
    header_at = next(
        (
            i
            for i, line in enumerate(lines)
            if {"symbol", "trade_type", "quantity", "price"} <= {c.strip().lower() for c in line}
        ),
        None,
    )
    if header_at is None:
        raise TradebookError(
            "This does not look like a Zerodha tradebook. Download 'Tradebook' as CSV "
            "from Console > Reports > Tradebook (Equity) and upload that."
        )
    header = [c.strip().lower() for c in lines[header_at]]

    rows: list[dict] = []
    skipped = 0
    for line in lines[header_at + 1 :]:
        if not any(line):
            continue
        rec = dict(zip(header, (c.strip() for c in line), strict=False))
        side = rec.get("trade_type", "").upper()
        segment = rec.get("segment", "EQ").upper()
        stamp_text = rec.get("order_execution_time") or rec.get("trade_date") or ""
        try:
            stamp = _as_ist(datetime.fromisoformat(stamp_text.replace("Z", "")))
            quantity = int(float(rec["quantity"]))
            price = float(rec["price"])
        except (ValueError, KeyError):
            skipped += 1
            continue
        if side not in ("BUY", "SELL") or segment not in ("EQ", "") or quantity <= 0:
            skipped += 1
            continue
        symbol = rec["symbol"]
        trade_id = rec.get("trade_id") or f"csv:{symbol}:{stamp.isoformat()}:{side}:{quantity}:{price}"
        rows.append(
            {
                "trade_id": trade_id,
                "order_id": rec.get("order_id") or None,
                "symbol": symbol,
                "exchange": rec.get("exchange") or "NSE",
                "side": side,
                "quantity": quantity,
                "price": price,
                "product": None,
                "executed_at": stamp,
                "source": "csv",
            }
        )
    return rows, skipped


def import_tradebook_csv(db: Session, content: bytes) -> StoreResult:
    rows, skipped = parse_tradebook_csv(content)
    return _store(db, rows, skipped)
