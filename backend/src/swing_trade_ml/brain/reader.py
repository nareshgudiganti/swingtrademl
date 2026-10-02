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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.connectors import FEEDS
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.feeds import (
    BlockDeal,
    DailyDelivery,
    InstitutionalFlow,
    TradingRestriction,
    UpcomingEvent,
)
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
        self._context_checked = False
        self._bundles: dict[tuple[str, str], dict | None] = {}

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

    def _cached_index_last(self):
        """Newest NIFTY bar in v1's market-context cache, or None if not cached."""
        from swing_trade_ml.ml import market_context

        cached = market_context._symbol_cache.get((settings.BENCHMARK_INDEX_SYMBOL, "day"))
        if cached is None or cached.empty:
            return None
        return pd.Timestamp(cached["ts"].iloc[-1]).to_pydatetime()

    def _db_index_last(self):
        return self.db.execute(
            select(func.max(Candle.ts))
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL, Candle.interval == "day")
        ).scalar_one_or_none()

    def refresh_context_if_stale(self) -> None:
        """v1's market-context loaders cache whole histories per process, and
        v1's 15:40 ingest job refreshes them in the worker. The brain must not
        clear that shared cache on every run — v1's scan may be reading it on
        another thread — so it clears only when the cache is behind the
        database (in practice: the API process, where no scan runs). Checked
        once per run."""
        if self._context_checked:
            return
        self._context_checked = True
        cached = self._cached_index_last()
        if cached is None:
            return  # nothing cached: the loaders will read fresh data
        latest = self._db_index_last()
        if latest is not None and latest > cached:
            from swing_trade_ml.ml import market_context

            market_context.clear_cache()
            log.info("brain.reader.context_refreshed", cached=str(cached), latest=str(latest))

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

    def event_rows(self, symbols) -> list:
        """Results dates and price-resetting corporate actions for these stocks,
        as known by as_of (rows stored later are a future the run cannot see)."""
        from swing_trade_ml.brain.modules.m13_news.calendar import EventRow

        rows = self.db.execute(
            select(UpcomingEvent.symbol, UpcomingEvent.kind, UpcomingEvent.event_date, UpcomingEvent.detail)
            .where(UpcomingEvent.symbol.in_(list(symbols)), UpcomingEvent.created_at <= self.as_of)
            .order_by(UpcomingEvent.event_date)
        ).all()
        return [EventRow(symbol=s, kind=k, day=d, detail=detail or "") for s, k, d, detail in rows]

    def restriction_rows(self, symbols) -> list:
        """ASM/GSM rows for these stocks dated on or before the run's IST date."""
        from swing_trade_ml.brain.modules.m13_news.calendar import RestrictionRow

        upto = self.as_of.astimezone(IST).date()
        rows = self.db.execute(
            select(
                TradingRestriction.symbol,
                TradingRestriction.kind,
                TradingRestriction.stage,
                TradingRestriction.as_of,
            ).where(TradingRestriction.symbol.in_(list(symbols)), TradingRestriction.as_of <= upto)
        ).all()
        return [RestrictionRow(symbol=s, kind=k, stage=stage or "", as_of=d) for s, k, stage, d in rows]

    def delivery_rows(self, symbols, days: int = 40) -> dict[str, list]:
        """Each stock's (day, delivery %) for the last `days` calendar weeks'
        worth of sessions up to the run's IST date, ordinary (EQ) series only."""
        from datetime import timedelta

        upto = self.as_of.astimezone(IST).date()
        rows = self.db.execute(
            select(DailyDelivery.symbol, DailyDelivery.trade_date, DailyDelivery.delivery_pct)
            .where(
                DailyDelivery.symbol.in_(list(symbols)),
                DailyDelivery.series == "EQ",
                DailyDelivery.trade_date <= upto,
                DailyDelivery.trade_date > upto - timedelta(days=days * 7 // 5 + 7),
            )
            .order_by(DailyDelivery.trade_date)
        ).all()
        out: dict[str, list] = {}
        for symbol, day, pct in rows:
            out.setdefault(symbol, []).append((day, None if pct is None else float(pct)))
        return out

    def deal_rows(self, symbols, days: int = 10) -> list:
        """Bulk and block deals in these stocks over the last `days` trading
        days (with a margin; the caller counts trading days), up to the run's date."""
        from datetime import timedelta

        from swing_trade_ml.brain.modules.m12_stock.signals import DealRow

        upto = self.as_of.astimezone(IST).date()
        rows = self.db.execute(
            select(
                BlockDeal.symbol,
                BlockDeal.trade_date,
                BlockDeal.client_name,
                BlockDeal.side,
                BlockDeal.quantity,
            ).where(
                BlockDeal.symbol.in_(list(symbols)),
                BlockDeal.trade_date <= upto,
                BlockDeal.trade_date > upto - timedelta(days=days * 2 + 7),
            )
        ).all()
        return [DealRow(symbol=s, day=d, client=cl, side=side, quantity=int(q)) for s, d, cl, side, q in rows]

    def feed_latest(self) -> dict[str, object]:
        """Newest day each side feed has, on or before as_of's IST date."""
        upto = self.as_of.astimezone(IST).date()
        return {feed.name: feed.latest(self.db, upto) for feed in FEEDS}

    def _closes(self, symbol: str) -> pd.Series:
        closes = (
            self.db.execute(
                select(Candle.close)
                .join(Instrument, Instrument.id == Candle.instrument_id)
                .where(Instrument.tradingsymbol == symbol, Candle.interval == "day", Candle.ts <= self.as_of)
                .order_by(Candle.ts.asc())
            )
            .scalars()
            .all()
        )
        return pd.Series([float(x) for x in closes], dtype=float)

    def index_closes(self) -> pd.Series:
        return self._closes(settings.BENCHMARK_INDEX_SYMBOL)

    def sector_closes(self) -> dict[str, pd.Series]:
        """Closing prices of every sector index the stock map uses, up to as_of.
        Indices with no bars are left out."""
        from swing_trade_ml.ml.sector_map import SECTOR_INDEX_MAP

        out = {}
        for index in sorted(set(SECTOR_INDEX_MAP.values())):
            closes = self._closes(index)
            if not closes.empty:
                out[index] = closes
        return out

    def vix_closes(self) -> pd.Series:
        return self._closes("INDIA VIX")

    def breadth_series(self) -> pd.Series:
        """Share of watchlist stocks above their 50-day average, per day, to as_of."""
        from swing_trade_ml.ml import market_context

        frame = market_context.load_market_breadth(self.db, upto=pd.Timestamp(self.as_of))
        if frame.empty:
            return pd.Series(dtype=float)
        return frame["breadth_pct_above_sma50"].astype(float).reset_index(drop=True)

    def fii_net(self, days: int = 20) -> list[float]:
        """FII net buying (crore) for the last `days` sessions to as_of, oldest first."""
        upto = self.as_of.astimezone(IST).date()
        rows = (
            self.db.execute(
                select(InstitutionalFlow.net_value)
                .where(InstitutionalFlow.category == "FII", InstitutionalFlow.trade_date <= upto)
                .order_by(InstitutionalFlow.trade_date.desc())
                .limit(days)
            )
            .scalars()
            .all()
        )
        return [float(v) for v in reversed(rows)]

    def portfolio_numbers(self, book: str) -> dict | None:
        """Account value, cash, drawdown and free slots — "now" data, so live
        runs only (a replay gets None rather than today's account)."""
        if not self.live:
            return None
        from swing_trade_ml.services import risk
        from swing_trade_ml.services.limits import limits_for
        from swing_trade_ml.services.portfolio import portfolio_value_and_cash

        value, cash = portfolio_value_and_cash(self.db, book)
        limits = limits_for(value)
        return {
            "value": value,
            "cash": cash,
            "drawdown_pct": risk.current_drawdown(self.db, book, value),
            "free_slots": max(0, limits.max_positions - risk.open_position_count(self.db, book)),
        }

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
            select(
                Instrument.tradingsymbol,
                Position.quantity,
                Position.entry_price,
                Position.stop_loss,
                Position.take_profit,
                Position.scaled_out_at,
            )
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(Position.mode == book, Position.status == PositionStatus.OPEN)
            .order_by(Instrument.tradingsymbol, Position.id)
        ).all()
        return tuple(
            c.Holding(
                symbol=sym,
                qty=int(qty),
                avg_price=float(price),
                stop=None if stop is None else float(stop),
                target=None if target is None else float(target),
                scaled_out=scaled is not None,
            )
            for sym, qty, price, stop, target, scaled in rows
        )

    def model_bundle(self, name: str, version: str) -> dict | None:
        """A saved model's bundle (estimator, scaler, feature names) by name and
        version, or None when it is not registered or its file is unreachable.
        Loaded once per run."""
        from swing_trade_ml.db.models.ml import MLModel
        from swing_trade_ml.ml.registry import load_artifact

        key = (name, version)
        if key not in self._bundles:
            path = self.db.execute(
                select(MLModel.artifact_path).where(MLModel.name == name, MLModel.version == version).limit(1)
            ).scalar_one_or_none()
            try:
                self._bundles[key] = load_artifact(path) if path else None
            except OSError as exc:
                log.warning("brain.reader.bundle_unavailable", model=f"{name} {version}", error=str(exc))
                self._bundles[key] = None
        return self._bundles[key]

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
