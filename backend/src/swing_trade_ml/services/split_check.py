"""Read-only split/bonus contamination check on raw candles (Phase 0 B0).

Flags one-day close moves above a threshold on corporate-action ex-dates from
``upcoming_events``. Large moves on split/bonus days usually mean unadjusted
prices in ``candles`` — gap #3 urgency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Candle, Instrument
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_THRESHOLD = 0.30


@dataclass(frozen=True, slots=True)
class SplitCheckHit:
    symbol: str
    event_date: date
    detail: str
    prev_close: float
    close: float
    move_pct: float


@dataclass(frozen=True, slots=True)
class SplitCheckReport:
    threshold: float
    events_checked: int
    hits: tuple[SplitCheckHit, ...]
    generated_at: datetime

    @property
    def hit_count(self) -> int:
        return len(self.hits)


def _bar_ts(trading_day: date) -> datetime:
    """Daily candle timestamp: IST midnight of the trading day (stored UTC)."""
    return datetime.combine(trading_day, time(0, 0), tzinfo=IST).astimezone(ZoneInfo("UTC"))


def _is_split_or_bonus(detail: str) -> bool:
    lower = detail.lower()
    return any(word in lower for word in ("split", "bonus"))


def run_split_contamination_check(
    db: Session,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    since: date | None = None,
    until: date | None = None,
) -> SplitCheckReport:
    until = until or date.today()
    since = since or (until - timedelta(days=365 * 5))
    events = db.execute(
        select(UpcomingEvent)
        .where(
            UpcomingEvent.kind == "corporate_action",
            UpcomingEvent.event_date >= since,
            UpcomingEvent.event_date <= until,
        )
        .order_by(UpcomingEvent.event_date, UpcomingEvent.symbol)
    ).scalars()
    hits: list[SplitCheckHit] = []
    checked = 0
    for ev in events:
        if not _is_split_or_bonus(ev.detail):
            continue
        checked += 1
        inst = db.execute(
            select(Instrument.id).where(
                Instrument.tradingsymbol == ev.symbol,
                Instrument.exchange == "NSE",
                Instrument.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if inst is None:
            continue
        ex_ts = _bar_ts(ev.event_date)
        # Walk back to the previous stored bar (weekends/holidays).
        prev_row = db.execute(
            select(Candle.close)
            .where(
                Candle.instrument_id == inst,
                Candle.interval == "day",
                Candle.ts < ex_ts,
            )
            .order_by(Candle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        ex_row = db.execute(
            select(Candle.close).where(
                Candle.instrument_id == inst,
                Candle.interval == "day",
                Candle.ts == ex_ts,
            )
        ).scalar_one_or_none()
        if prev_row is None or ex_row is None:
            continue
        prev_close, close = float(prev_row), float(ex_row)
        if prev_close <= 0:
            continue
        move = (close - prev_close) / prev_close
        if abs(move) >= threshold:
            hits.append(
                SplitCheckHit(
                    symbol=ev.symbol,
                    event_date=ev.event_date,
                    detail=ev.detail,
                    prev_close=prev_close,
                    close=close,
                    move_pct=move,
                )
            )
    return SplitCheckReport(
        threshold=threshold,
        events_checked=checked,
        hits=tuple(hits),
        generated_at=datetime.now(IST),
    )


def format_report(report: SplitCheckReport) -> str:
    lines = [
        "# Split / bonus contamination check (B0)",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        f"Threshold: {report.threshold:.0%} one-day close move on ex-date",
        f"Split/bonus events checked: {report.events_checked}",
        f"Suspicious moves: {report.hit_count}",
        "",
    ]
    if not report.hits:
        lines.append("No suspicious moves found on recorded split/bonus ex-dates.")
    else:
        lines.append("| Symbol | Ex-date | Move | Prev close | Close | Detail |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for h in report.hits:
            lines.append(
                f"| {h.symbol} | {h.event_date} | {h.move_pct:+.1%} | {h.prev_close:.2f} | "
                f"{h.close:.2f} | {h.detail[:80]} |"
            )
    lines.append("")
    return "\n".join(lines)
