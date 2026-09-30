"""The only way brain code reads the database.

Every price question is bounded by the run's `as_of`, so a replay of a past
date can never see what happened after it (no look-ahead). Inputs that only
exist "now" — open holdings and the active model's score — are answered only
for live runs; a replay gets nothing rather than today's answer.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services import system_state

log = get_logger(__name__)

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
        return row.ts.date().isoformat(), float(row.close)

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
