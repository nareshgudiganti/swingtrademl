"""The Company and news tab: what a company has filed, in plain words.

Free source first: NSE's own filings (announcements, shareholding). Results (sales, profit, margins)
are NOT collected yet: NSE's structured results feed lags by years for some stocks (KEI stopped at
Dec 2024), so that block says "Not available" rather than show old numbers as current.

Display only. Nothing here feeds a pick, order, stop, size or limit, and the words never say buy,
sell, cheap or expensive. Every block carries its source and its "as of" date; a block whose data is
missing or old says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.company import CompanyAnnouncement, CompanyShareholding
from swing_trade_ml.db.models.market import Candle, Instrument

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

SOURCE = "nse"
#: The first stock the tab is proven on (owner decision 2: prove it on one stock before the whole list).
COMPANY_SYMBOLS = ("KEI",)

HOME_URL = "https://www.nseindia.com/get-quotes/equity?symbol={symbol}"
ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"
SHAREHOLDING_URL = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={symbol}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json,text/html,*/*",
}
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

KEEP_ANNOUNCEMENTS = 60
SHOWN_ANNOUNCEMENTS = 5
#: Older than this, a block says "Out of date" instead of looking current.
ANNOUNCEMENTS_STALE_DAYS = 60
SHAREHOLDING_STALE_DAYS = 140  # quarterly filing, due within 21 days of quarter end
#: Shareholding that does not add up to 100% (give or take rounding) is a bad filing: rejected.
SHAREHOLDING_TOLERANCE = 0.5


# ---------------------------------------------------------------- parsing --


def _number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _date(text: object, *formats: str) -> date | None:
    for fmt in formats:
        try:
            return datetime.strptime(str(text).strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_announcements(rows: list[dict]) -> list[dict]:
    """Rows ready to store, newest first. A row without an id or a readable time is dropped."""
    out: list[dict] = []
    for r in rows:
        seq = str(r.get("seq_id") or "").strip()
        try:
            at = datetime.strptime(str(r.get("an_dt", "")).strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
        except ValueError:
            continue
        if not seq:
            continue
        out.append(
            {
                "symbol": str(r.get("symbol", "")).upper(),
                "source": SOURCE,
                "seq_id": seq,
                "announced_at": at,
                "category": str(r.get("desc") or "")[:160],
                "summary": str(r.get("attchmntText") or "").strip()[:600],
                "attachment_url": (r.get("attchmntFile") or None),
            }
        )
    out.sort(key=lambda x: x["announced_at"], reverse=True)
    return out[:KEEP_ANNOUNCEMENTS]


def parse_shareholding(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """(rows to store, reasons for rows rejected). One row per quarter end; if a quarter was filed
    twice, the later filing wins. A filing whose two shares do not add up to 100% is rejected."""
    best: dict[date, dict] = {}
    rejected: list[str] = []
    for r in rows:
        as_of = _date(r.get("date"), "%d-%b-%Y")
        filed = _date(r.get("submissionDate"), "%d-%b-%Y")
        promoter = _number(r.get("pr_and_prgrp"))
        public = _number(r.get("public_val"))
        symbol = str(r.get("symbol", "")).upper()
        if as_of is None or filed is None or promoter is None or public is None:
            rejected.append(f"{symbol} {r.get('date')}: a field is missing")
            continue
        if abs(promoter + public - 100) > SHAREHOLDING_TOLERANCE:
            rejected.append(f"{symbol} {as_of}: shares add to {promoter + public:.1f}%, not 100%")
            continue
        row = {
            "symbol": symbol,
            "source": SOURCE,
            "as_of": as_of,
            "filed_on": filed,
            "promoter_pct": promoter,
            "public_pct": public,
        }
        if as_of not in best or filed >= best[as_of]["filed_on"]:
            best[as_of] = row
    return sorted(best.values(), key=lambda x: x["as_of"], reverse=True), rejected


# ------------------------------------------------------------- collecting --


def fetch_nse(symbol: str) -> tuple[list[dict], list[dict]]:
    """(announcements, shareholding) as NSE returns them. NSE wants the page visited first to hand
    out its cookies; any failure raises so the caller can report it."""
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        client.get(HOME_URL.format(symbol=symbol)).raise_for_status()
        ref = {"Referer": "https://www.nseindia.com/"}
        ann = client.get(ANNOUNCEMENTS_URL.format(symbol=symbol), headers=ref)
        ann.raise_for_status()
        sh = client.get(SHAREHOLDING_URL.format(symbol=symbol), headers=ref)
        sh.raise_for_status()
        return ann.json(), sh.json()


@dataclass
class RefreshResult:
    symbol: str
    announcements_added: int = 0
    shareholding_added: int = 0
    rejected: list[str] = field(default_factory=list)


def store(db: Session, symbol: str, announcements: list[dict], shareholding: list[dict]) -> RefreshResult:
    """Save parsed rows; reloading the same rows adds nothing."""
    result = RefreshResult(symbol=symbol)
    ann_rows = parse_announcements(announcements)
    share_rows, result.rejected = parse_shareholding(shareholding)
    if ann_rows:
        got = db.execute(
            insert(CompanyAnnouncement)
            .values(ann_rows)
            .on_conflict_do_nothing(index_elements=["source", "seq_id"])
            .returning(CompanyAnnouncement.id)
        )
        result.announcements_added = len(got.all())
    if share_rows:
        got = db.execute(
            insert(CompanyShareholding)
            .values(share_rows)
            .on_conflict_do_nothing(index_elements=["symbol", "source", "as_of"])
            .returning(CompanyShareholding.id)
        )
        result.shareholding_added = len(got.all())
    db.commit()
    for why in result.rejected:
        log.warning("company_filings.rejected", reason=why)
    return result


def refresh_company(db: Session, symbol: str) -> RefreshResult:
    announcements, shareholding = fetch_nse(symbol)
    return store(db, symbol.upper(), announcements, shareholding)


# ---------------------------------------------------------------- wording --


def price_position_text(price: float, high: float, low: float) -> str:
    """Where the price sits in its 1-year range, in plain words. Facts only."""
    below_high = (high - price) / high * 100 if high else 0.0
    span = high - low
    near_low = span > 0 and (price - low) / span <= 0.10
    if below_high < 3:
        return "At or very close to its 1-year high"
    text = f"{below_high:.0f}% below its 1-year high"
    return f"{text}, close to its lowest point of the year" if near_low else text


def ownership_text(promoter_pct: float, public_pct: float) -> str:
    return f"Founders and promoters hold {promoter_pct:g}%; everyone else holds {public_pct:g}%"


def headline_text(facts: list[str]) -> str | None:
    """One plain sentence from the facts we have, or None when we have none. No advice words."""
    if not facts:
        return None
    return "From the company's own filings: " + "; ".join(facts) + "."


# ------------------------------------------------------------------- view --


def _state(as_of: date | None, today: date, stale_days: int) -> str:
    if as_of is None:
        return "not_available"
    return "out_of_date" if (today - as_of).days > stale_days else "ok"


def build_view(db: Session, symbol: str, today: date) -> dict:
    """Everything the tab shows for one stock, each block with its source, its date and its state."""
    symbol = symbol.upper()
    facts: list[str] = []

    # Where is the price: our own stored daily candles over the last year (IST dates).
    price_block: dict = {"state": "not_available", "source": "Our price history", "as_of": None, "text": None}
    inst = db.execute(
        select(Instrument).where(Instrument.tradingsymbol == symbol, Instrument.exchange == "NSE")
    ).scalar_one_or_none()
    if inst is not None:
        since = datetime.combine(today - timedelta(days=366), datetime.min.time(), tzinfo=IST)
        bars = db.execute(
            select(Candle.ts, Candle.high, Candle.low, Candle.close)
            .where(Candle.instrument_id == inst.id, Candle.interval == "day", Candle.ts >= since)
            .order_by(Candle.ts)
        ).all()
        if bars:
            last_ts, _, _, last_close = bars[-1]
            high, low = max(b.high for b in bars), min(b.low for b in bars)
            as_of = last_ts.astimezone(IST).date()
            text = price_position_text(last_close, high, low)
            price_block = {
                "state": _state(as_of, today, 7),
                "source": "Our price history",
                "as_of": as_of,
                "text": text,
                "price": last_close,
                "high_1y": high,
                "low_1y": low,
            }
            if price_block["state"] == "ok":
                facts.append(text[0].lower() + text[1:])

    sh = db.execute(
        select(CompanyShareholding)
        .where(CompanyShareholding.symbol == symbol)
        .order_by(CompanyShareholding.as_of.desc())
        .limit(1)
    ).scalar_one_or_none()
    own_block: dict = {
        "state": "not_available",
        "source": "NSE shareholding filing",
        "as_of": None,
        "text": None,
    }
    if sh is not None:
        own_block = {
            "state": _state(sh.as_of, today, SHAREHOLDING_STALE_DAYS),
            "source": "NSE shareholding filing",
            "as_of": sh.as_of,
            "filed_on": sh.filed_on,
            "text": ownership_text(sh.promoter_pct, sh.public_pct),
            "promoter_pct": sh.promoter_pct,
            "public_pct": sh.public_pct,
        }
        if own_block["state"] == "ok":
            facts.append(f"founders and promoters hold {sh.promoter_pct:g}%")

    anns = (
        db.execute(
            select(CompanyAnnouncement)
            .where(CompanyAnnouncement.symbol == symbol)
            .order_by(CompanyAnnouncement.announced_at.desc())
            .limit(SHOWN_ANNOUNCEMENTS)
        )
        .scalars()
        .all()
    )
    newest = anns[0].announced_at.astimezone(IST).date() if anns else None
    ann_block = {
        "state": _state(newest, today, ANNOUNCEMENTS_STALE_DAYS),
        "source": "NSE announcements",
        "as_of": newest,
        "items": [
            {
                "at": a.announced_at,
                "category": a.category,
                "summary": a.summary,
                "attachment_url": a.attachment_url,
            }
            for a in anns
        ],
    }

    return {
        "symbol": symbol,
        "headline": headline_text(facts),
        "price_position": price_block,
        "ownership": own_block,
        "announcements": ann_block,
        # Not collected yet: NSE's structured results feed is years behind for some stocks, so we show
        # nothing rather than old numbers that look current.
        "results": {
            "state": "not_available",
            "source": "NSE results",
            "as_of": None,
            "why": "Results are not collected yet, because the free NSE results feed is out of date.",
        },
        "coming_soon": [
            "What outside experts say",
            "Was the profit a surprise?",
            "Is the price fair?",
            "News about the company",
        ],
        "note": "Information from the company's filings. It does not change the brain's call.",
    }
