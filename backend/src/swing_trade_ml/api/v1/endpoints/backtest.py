"""Backtest a strategy against stored historical candles.

Synchronous by design, unlike /ml/train — a backtest reads only what is
already ingested and produces nothing to poll afterward (services/backtest.py
deliberately writes no rows). A handful of symbols over a few years typically
returns in seconds; the full watchlist over five years can take minutes and
is better run via `swingtrade backtest` on the CLI, which has no HTTP
timeout to race against.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, status

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.core.config import settings
from swing_trade_ml.schemas import BacktestRequest, BacktestResponse
from swing_trade_ml.services.backtest import run_backtest

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("", response_model=BacktestResponse)
def backtest(payload: BacktestRequest, db: DbSession) -> BacktestResponse:
    symbols = [s.upper() for s in payload.symbols] if payload.symbols else settings.watchlist
    end = payload.end or date.today()

    try:
        result = run_backtest(
            db,
            strategy_type=payload.strategy_type,
            symbols=symbols,
            start=payload.start,
            end=end,
            params=payload.params,
            interval=payload.interval,
            starting_capital=payload.starting_capital,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return BacktestResponse(
        strategy_type=payload.strategy_type,
        symbols=symbols,
        start=payload.start,
        end=end,
        starting_capital=result.starting_capital,
        ending_value=result.ending_value,
        stats=result.stats,
        trades=result.trades,
        equity_curve=result.equity_curve,
    )
