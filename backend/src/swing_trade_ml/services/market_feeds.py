"""NSE's free daily information feeds: delivery %, bulk/block deals, FII/DII.

Sources are NSE's static archive files, which are dated and stable, rather than
the website's pages, which block bots and change without notice. A feed that
fails is reported, never papered over — stale data that looks fresh is worse
than a gap.

Point-in-time: bhavcopy can be back-filled because NSE keeps a file per date.
Bulk/block deals and FII/DII are only published for the latest day, so their
history starts the day we start recording; nothing here pretends otherwise.
"""

from __future__ import annotations

import csv
import hashlib
import io
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from swing_trade_ml.core.holidays import is_trading_holiday
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.feeds import BlockDeal, DailyDelivery, InstitutionalFlow

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

BHAVCOPY_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day}.csv"
BULK_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
BLOCK_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"

# NSE serves a bot-blocking page to clients without a browser-like agent.
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
#: Series worth keeping: EQ is normal trading, BE/BZ are trade-for-trade — a
#: restriction the entry filter needs to be able to see.
KEPT_SERIES = frozenset({"EQ", "BE", "BZ"})
BACKFILL_PAUSE_SECONDS = 0.4


def fetch(url: str) -> bytes | None:
    """The body, or None when NSE has no such file (holiday, weekend, or not
    published yet). Any other failure raises so the caller can report it."""
    response = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def _number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _integer(text: str) -> int | None:
    value = _number(text)
    return None if value is None else int(value)


# ---------------------------------------------------------------- bhavcopy --


def parse_bhavcopy(content: bytes) -> list[dict]:
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
    header = [c.strip().upper() for c in next(reader, [])]
    rows: list[dict] = []
    for line in reader:
        rec = dict(zip(header, (c.strip() for c in line), strict=False))
        series = rec.get("SERIES", "")
        if series not in KEPT_SERIES or not rec.get("SYMBOL"):
            continue
        try:
            trade_date = datetime.strptime(rec["DATE1"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        rows.append(
            {
                "symbol": rec["SYMBOL"],
                "series": series,
                "trade_date": trade_date,
                "close_price": _number(rec.get("CLOSE_PRICE", "")),
                "traded_qty": _integer(rec.get("TTL_TRD_QNTY", "")),
                "turnover_lacs": _number(rec.get("TURNOVER_LACS", "")),
                "trades": _integer(rec.get("NO_OF_TRADES", "")),
                "delivery_qty": _integer(rec.get("DELIV_QTY", "")),
                "delivery_pct": _number(rec.get("DELIV_PER", "")),
            }
        )
    return rows


def _insert_ignoring_duplicates(db: Session, model, rows: list[dict], conflict: list[str]) -> int:
    if not rows:
        return 0
    added = 0
    # Chunked: one statement per few thousand rows keeps the parameter count sane.
    for start in range(0, len(rows), 2000):
        chunk = rows[start : start + 2000]
        result = db.execute(
            insert(model).values(chunk).on_conflict_do_nothing(index_elements=conflict).returning(model.id)
        )
        added += len(result.all())
    db.commit()
    return added


def load_bhavcopy(db: Session, day: date) -> int | None:
    """Rows added for `day`, or None when NSE has no file for it."""
    content = fetch(BHAVCOPY_URL.format(day=day.strftime("%d%m%Y")))
    if content is None:
        return None
    rows = [r for r in parse_bhavcopy(content) if r["trade_date"] == day]
    return _insert_ignoring_duplicates(db, DailyDelivery, rows, ["symbol", "series", "trade_date"])


# ------------------------------------------------------------ bulk / block --


def parse_deals(content: bytes, kind: str) -> list[dict]:
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
    header = [c.strip().lower() for c in next(reader, [])]
    rows: list[dict] = []
    for line in reader:
        rec = dict(zip(header, (c.strip() for c in line), strict=False))
        try:
            trade_date = datetime.strptime(rec["date"], "%d-%b-%Y").date()
            quantity = int(float(rec["quantity traded"].replace(",", "")))
            price = float(rec["trade price / wght. avg. price"].replace(",", ""))
        except (KeyError, ValueError):
            continue
        side = rec.get("buy/sell", "").upper()
        if side not in ("BUY", "SELL") or not rec.get("symbol"):
            continue
        client = rec.get("client name", "")
        key = hashlib.sha1(
            f"{kind}|{trade_date}|{rec['symbol']}|{client}|{side}|{quantity}|{price}".encode()
        ).hexdigest()
        rows.append(
            {
                "deal_key": key,
                "trade_date": trade_date,
                "symbol": rec["symbol"],
                "kind": kind,
                "client_name": client[:255],
                "side": side,
                "quantity": quantity,
                "price": price,
            }
        )
    return rows


def load_deals(db: Session) -> int:
    added = 0
    for url, kind in ((BULK_URL, "bulk"), (BLOCK_URL, "block")):
        content = fetch(url)
        if content:
            added += _insert_ignoring_duplicates(db, BlockDeal, parse_deals(content, kind), ["deal_key"])
    return added


# ----------------------------------------------------------------- FII/DII --


def parse_fii_dii(payload: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in payload:
        category = "FII" if str(item.get("category", "")).upper().startswith("FII") else "DII"
        try:
            rows.append(
                {
                    "trade_date": datetime.strptime(item["date"], "%d-%b-%Y").date(),
                    "category": category,
                    "buy_value": float(str(item["buyValue"]).replace(",", "")),
                    "sell_value": float(str(item["sellValue"]).replace(",", "")),
                    "net_value": float(str(item["netValue"]).replace(",", "")),
                }
            )
        except (KeyError, ValueError):
            continue
    return rows


def load_fii_dii(db: Session) -> int:
    import json

    content = fetch(FII_DII_URL)
    if not content:
        return 0
    return _insert_ignoring_duplicates(
        db, InstitutionalFlow, parse_fii_dii(json.loads(content)), ["trade_date", "category"]
    )


# ------------------------------------------------------------------ driver --


@dataclass
class FeedRun:
    added: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _weekdays_back(today: date, days: int) -> list[date]:
    return [
        d
        for d in (today - timedelta(days=i) for i in range(days))
        if d.weekday() < 5 and not is_trading_holiday(d)
    ]


def stored_delivery_dates(db: Session, since: date) -> set[date]:
    return set(
        db.execute(
            select(DailyDelivery.trade_date).where(DailyDelivery.trade_date >= since).distinct()
        ).scalars()
    )


def run_daily_feeds(db: Session, today: date | None = None) -> FeedRun:
    """Top up every feed. Each is isolated so one bad source cannot starve the
    others; a missing bhavcopy for a real trading day is left for the retry."""
    today = today or datetime.now(IST).date()
    run = FeedRun()

    try:
        wanted = _weekdays_back(today, 5)
        have = stored_delivery_dates(db, today - timedelta(days=6))
        added = 0
        for day in wanted:
            if day in have:
                continue
            result = load_bhavcopy(db, day)
            added += result or 0
        run.added["delivery"] = added
    except Exception as exc:  # noqa: BLE001
        run.errors["delivery"] = str(exc)

    for name, loader in (("deals", load_deals), ("institutional_flows", load_fii_dii)):
        try:
            run.added[name] = loader(db)
        except Exception as exc:  # noqa: BLE001
            run.errors[name] = str(exc)
    return run


def latest_expected_delivery_day(today: date, now: datetime | None = None) -> date:
    """The trading day whose file should exist by now (NSE publishes in the evening)."""
    now = now or datetime.now(IST)
    day = today if now.hour >= 20 else today - timedelta(days=1)
    while day.weekday() >= 5 or is_trading_holiday(day):
        day -= timedelta(days=1)
    return day


def backfill_bhavcopy(db: Session, start: date, end: date) -> dict[str, int]:
    """One file per date. Slow on purpose: NSE rate-limits aggressive clients."""
    have = stored_delivery_dates(db, start)
    loaded = missing = 0
    day = start
    while day <= end:
        if day.weekday() < 5 and not is_trading_holiday(day) and day not in have:
            try:
                result = load_bhavcopy(db, day)
            except Exception as exc:  # noqa: BLE001
                log.warning("feeds.backfill.failed", day=day.isoformat(), error=str(exc))
                result = None
            if result is None:
                missing += 1
            else:
                loaded += 1
            time.sleep(BACKFILL_PAUSE_SECONDS)
        day += timedelta(days=1)
    return {"days_loaded": loaded, "days_missing": missing}


def backfill_history_step(
    db: Session, today: date | None = None, lookback_days: int = 400, max_fetches: int = 120
) -> dict[str, int]:
    """Fill the newest missing days first, a bounded number per call, so a fresh
    install builds its history over a few nights instead of in one long run."""
    today = today or datetime.now(IST).date()
    start = today - timedelta(days=lookback_days)
    have = stored_delivery_dates(db, start)
    missing = [
        d
        for d in _weekdays_back(today, lookback_days)
        if d not in have
    ]
    fetched = loaded = 0
    for day in missing[:max_fetches]:
        fetched += 1
        try:
            if load_bhavcopy(db, day) is not None:
                loaded += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("feeds.history.failed", day=day.isoformat(), error=str(exc))
        time.sleep(BACKFILL_PAUSE_SECONDS)
    return {"still_missing": max(len(missing) - fetched, 0), "days_loaded": loaded}


def feed_status(db: Session) -> dict[str, dict]:
    def latest(model, column):
        return db.execute(select(func.max(column))).scalar_one_or_none()

    return {
        "delivery": {
            "latest": latest(DailyDelivery, DailyDelivery.trade_date),
            "rows": db.execute(select(func.count(DailyDelivery.id))).scalar_one(),
        },
        "deals": {
            "latest": latest(BlockDeal, BlockDeal.trade_date),
            "rows": db.execute(select(func.count(BlockDeal.id))).scalar_one(),
        },
        "institutional_flows": {
            "latest": latest(InstitutionalFlow, InstitutionalFlow.trade_date),
            "rows": db.execute(select(func.count(InstitutionalFlow.id))).scalar_one(),
        },
    }
