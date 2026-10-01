"""The only way brain code reads the database.

Every price question is bounded by the run's `as_of`, so a replay of a past
date can never see what happened after it (no look-ahead). Inputs that only
exist "now" — open holdings and the active model's score — are answered only
for live runs; a replay gets nothing rather than today's answer.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.connectors import FEEDS
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services import system_state

log = get_logger(__name__)

# Daily bars are stamped at IST midnight of their trading day (stored as 18:30
# UTC the day before), so a bar's trading day must be read in IST.
IST = ZoneInfo("Asia/Kolkata")

# The model the fallback asks when no reasoning module is installed — the same
# default the ml_swing strategy uses.
FALLBACK_MODEL_NAME = "swing_classifier"


class DatedReader:
    def __init__(self, db: Session, as_of: datetime, live: bool) -> None:
        self.db = db
        self.as_of = as_of
        self.live = live
        self._model = None
        self._model_loaded = False

    def universe(self) -> tuple[str, ...]:
        rows = self.db.execute(
            select(Instrument.tradingsymbol)
            .where(Instrument.is_watchlisted.is_(True), Instrument.is_active.is_(True))
            .order_by(Instrument.tradingsymbol)
        ).scalars()
        return tuple(dict.fromkeys(rows))

    def _instrument(self, symbol: str) -> Instrument | None:
        return self.db.execute(
            select(Instrument).where(Instrument.tradingsymbol == symbol).order_by(Instrument.id).limit(1)
        ).scalar_one_or_none()

    def instrument_id(self, symbol: str) -> int | None:
        inst = self._instrument(symbol)
        return inst.id if inst is not None else None

    def last_close(self, symbol: str) -> tuple[str, float] | None:
        row = self.db.execute(
            select(Candle.ts, Candle.close)
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Instrument.tradingsymbol == symbol, Candle.interval == "day", Candle.ts <= self.as_of)
            .order_by(Candle.ts.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return row.ts.astimezone(IST).date().isoformat(), float(row.close)

    def ohlcv(self, symbol: str, n: int = 400) -> pd.DataFrame:
        """The last `n` daily bars on or before as_of, ascending, in the shape
        the feature pipeline expects (ts, open, high, low, close, volume)."""
        rows = self.db.execute(
            select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Instrument.tradingsymbol == symbol, Candle.interval == "day", Candle.ts <= self.as_of)
            .order_by(Candle.ts.desc())
            .limit(n)
        ).all()
        frame = (
            pd.DataFrame(
                [
                    (r.ts, float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume or 0))
                    for r in rows
                ],
                columns=["ts", "open", "high", "low", "close", "volume"],
            )
            .iloc[::-1]
            .reset_index(drop=True)
        )
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        return frame

    def context_frames(self, symbol: str) -> dict[str, pd.DataFrame]:
        """NIFTY, the stock's sector index, India VIX and watchlist breadth,
        each cut at as_of — the same loaders the model's own scans use."""
        from swing_trade_ml.ml import market_context
        from swing_trade_ml.ml.sector_map import get_sector_index

        upto = pd.Timestamp(self.as_of)
        return {
            "index": market_context.load_index_candles(self.db, upto=upto),
            "sector": market_context.load_sector_candles(self.db, get_sector_index(symbol), upto=upto),
            "vix": market_context.load_vix_candles(self.db, upto=upto),
            "breadth": market_context.load_market_breadth(self.db, upto=upto),
        }

    def clear_context_cache(self) -> None:
        """The context loaders cache whole histories for the life of the
        process; a long-running worker would otherwise reuse yesterday's."""
        from swing_trade_ml.ml import market_context

        market_context.clear_cache()

    def recent_bars(self, symbol: str, n: int = 260) -> pd.DataFrame:
        """The last `n` daily bars on or before as_of, ascending, with each
        bar's trading day (IST) in a `day` column."""
        rows = self.db.execute(
            select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Instrument.tradingsymbol == symbol, Candle.interval == "day", Candle.ts <= self.as_of)
            .order_by(Candle.ts.desc())
            .limit(n)
        ).all()
        frame = pd.DataFrame(
            [
                {
                    "day": r.ts.astimezone(IST).date(),
                    "open": float(r.open),
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "volume": float(r.volume or 0),
                }
                for r in reversed(rows)
            ],
            columns=["day", "open", "high", "low", "close", "volume"],
        )
        return frame

    def action_days(self) -> dict[str, set]:
        """Ex-dates of splits, bonuses and similar price-resetting actions,
        by symbol — a big one-day move on such a day is not a data error."""
        rows = self.db.execute(
            select(UpcomingEvent.symbol, UpcomingEvent.event_date).where(
                UpcomingEvent.kind == "corporate_action"
            )
        ).all()
        out: dict[str, set] = {}
        for symbol, day in rows:
            out.setdefault(symbol, set()).add(day)
        return out

    def feed_latest(self) -> dict[str, object]:
        """Newest day each side feed has, on or before as_of's IST date."""
        upto = self.as_of.astimezone(IST).date()
        return {feed.name: feed.latest(self.db, upto) for feed in FEEDS}

    def index_closes(self) -> pd.Series:
        closes = (
            self.db.execute(
                select(Candle.close)
                .join(Instrument, Instrument.id == Candle.instrument_id)
                .where(
                    Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL,
                    Candle.interval == "day",
                    Candle.ts <= self.as_of,
                )
                .order_by(Candle.ts.asc())
            )
            .scalars()
            .all()
        )
        return pd.Series([float(x) for x in closes], dtype=float)

    def system_state(self) -> c.SystemState:
        state = system_state.get_state(self.db)
        return c.SystemState(
            entries_halted=not state.new_entries_enabled,
            halt_reason=state.halt_reason,
            exits_disabled=not state.exits_enabled,
        )

    def holdings(self, book: str) -> tuple[c.Holding, ...]:
        if not self.live:
            return ()
        rows = self.db.execute(
            select(Instrument.tradingsymbol, Position.quantity, Position.entry_price)
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(Position.mode == book, Position.status == PositionStatus.OPEN)
            .order_by(Instrument.tradingsymbol, Position.id)
        ).all()
        return tuple(c.Holding(symbol=s, qty=int(q), avg_price=float(p)) for s, q, p in rows)

    def model_probability(self, symbol: str) -> tuple[float, float, str] | None:
        """The active model's score for the latest bar, or None. Live only:
        the model always scores the newest bars."""
        if not self.live:
            return None
        from swing_trade_ml.ml.predict import predict_instrument
        from swing_trade_ml.ml.registry import get_active_model

        if not self._model_loaded:
            self._model = get_active_model(self.db, FALLBACK_MODEL_NAME)
            self._model_loaded = True
        instrument = self._instrument(symbol)
        if self._model is None or instrument is None:
            return None
        try:
            result = predict_instrument(self.db, instrument, self._model)
        except OSError as exc:
            # The model file itself is unreachable (e.g. it lives in the Docker
            # volume and this run is outside it). Every stock would fail the
            # same way, so stop asking for the rest of this run.
            log.warning("brain.reader.model_unavailable", model=self._model.name, error=str(exc))
            self._model = None
            return None
        except Exception as exc:  # noqa: BLE001 — a scoring failure means "no score", not a failed run
            log.warning("brain.reader.predict_failed", symbol=symbol, error=str(exc))
            return None
        if result is None:
            return None
        label = f"{self._model.name} {self._model.version}"
        return result.probability, settings.ML_MIN_CONFIDENCE, label
