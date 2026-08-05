"""Backtest engine — replays a strategy against stored historical candles.

The gap this closes: today the only way to see how a strategy performs is to
let PaperBroker run forward in real time, which takes six months to produce
six months of evidence. This replays years of already-ingested candles in
seconds instead, using the same cost model, sizing formula, and exit
priority order as the live paper path — so a backtest result and a paper
result mean the same thing.

What is intentionally NOT shared with the live path: nothing gets written to
`signals`, `orders`, `positions`, or `trades`. A five-year backtest across 50
symbols would otherwise flood those tables with rows that have nothing to do
with actual paper trading. Portfolio state lives entirely in memory for the
duration of one run and is returned as a `BacktestResult`, never persisted.

Known approximations, worth remembering when reading results:
* Exits are checked once per day against that day's high/low, approximating
  the live system's continuous intraday check_exits(). If both stop and
  target fall inside the same day's range, the stop is assumed to have hit
  first — the same conservative assumption, not something inferable from
  daily OHLC alone.
* An entry signal fills at that day's close plus slippage, mirroring the live
  system's post-close scan (15:45 IST) filling near-immediately at the
  live quote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType, TradingMode
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy as StrategyModel
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.services.costs import apply_slippage as _apply_slippage
from swing_trade_ml.services.costs import compute_charges as _charges
from swing_trade_ml.services.risk import calculate_quantity
from swing_trade_ml.strategies import get_strategy

log = get_logger(__name__)

TRADING_DAYS_PER_YEAR = 252


@dataclass(slots=True)
class BacktestTrade:
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    charges: float
    net_pnl: float
    return_pct: float
    holding_days: int
    exit_reason: str


@dataclass(slots=True)
class _OpenPosition:
    instrument_id: int
    symbol: str
    quantity: int
    entry_price: float
    entry_date: date
    stop_loss: float | None
    take_profit: float | None
    charges_so_far: float


@dataclass(slots=True)
class BacktestResult:
    starting_capital: float
    ending_value: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _last_close(df: pd.DataFrame, day: date) -> float:
    mask = df["ts"].dt.date <= day
    if not mask.any():
        return 0.0
    return float(df.loc[mask, "close"].iloc[-1])


def _close_position(
    pos: _OpenPosition,
    exit_price: float,
    trades: list[BacktestTrade],
    reason: str,
    exit_date: date,
) -> float:
    """Fill the exit at adverse slippage, charge costs, record the trade.

    Returns the net cash proceeds to add back to the ledger.
    """
    fill_price = _apply_slippage(exit_price, "SELL")
    turnover = fill_price * pos.quantity
    brokerage, taxes = _charges(turnover)
    total_charges = pos.charges_so_far + brokerage + taxes
    gross_pnl = (fill_price - pos.entry_price) * pos.quantity
    net_pnl = gross_pnl - total_charges
    invested = pos.entry_price * pos.quantity

    trades.append(
        BacktestTrade(
            symbol=pos.symbol,
            entry_date=pos.entry_date,
            exit_date=exit_date,
            entry_price=round(pos.entry_price, 2),
            exit_price=round(fill_price, 2),
            quantity=pos.quantity,
            gross_pnl=round(gross_pnl, 2),
            charges=round(total_charges, 2),
            net_pnl=round(net_pnl, 2),
            return_pct=round(net_pnl / invested, 4) if invested else 0.0,
            holding_days=(exit_date - pos.entry_date).days,
            exit_reason=reason,
        )
    )
    return turnover - brokerage - taxes


def _compute_stats(
    trades: list[BacktestTrade],
    equity_curve: list[dict[str, Any]],
    starting_capital: float,
    ending_value: float,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "starting_capital": starting_capital,
        "ending_value": round(ending_value, 2),
        "total_return_pct": (ending_value / starting_capital - 1) if starting_capital else 0.0,
        "total_trades": len(trades),
    }

    if trades:
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))
        stats |= {
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(trades),
            "avg_win": gross_profit / len(wins) if wins else 0.0,
            "avg_loss": -gross_loss / len(losses) if losses else 0.0,
            "largest_win": max((t.net_pnl for t in wins), default=0.0),
            "largest_loss": min((t.net_pnl for t in losses), default=0.0),
            "profit_factor": (gross_profit / gross_loss) if gross_loss else float("inf"),
            "avg_holding_days": float(np.mean([t.holding_days for t in trades])),
            "avg_return_pct": float(np.mean([t.return_pct for t in trades])),
            "total_charges": sum(t.charges for t in trades),
            "expectancy": sum(t.net_pnl for t in trades) / len(trades),
        }
    else:
        stats |= {
            "winning_trades": 0, "losing_trades": 0, "win_rate": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "largest_win": 0.0, "largest_loss": 0.0,
            "profit_factor": 0.0, "avg_holding_days": 0.0, "avg_return_pct": 0.0,
            "total_charges": 0.0, "expectancy": 0.0,
        }

    if len(equity_curve) > 1:
        values = np.array([e["total_value"] for e in equity_curve], dtype=float)
        daily_returns = np.diff(values) / values[:-1]
        running_peak = np.maximum.accumulate(values)
        drawdowns = np.divide(
            running_peak - values, running_peak, out=np.zeros_like(values), where=running_peak != 0
        )
        stats["max_drawdown_pct"] = float(drawdowns.max())

        std = daily_returns.std()
        # Annualised, risk-free rate assumed zero — same convention as
        # services/portfolio.py's live performance_stats, so the two numbers
        # are directly comparable.
        stats["sharpe_ratio"] = (
            float(daily_returns.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std else 0.0
        )
        downside = daily_returns[daily_returns < 0]
        stats["sortino_ratio"] = (
            float(daily_returns.mean() / downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
            if len(downside) and downside.std()
            else 0.0
        )
    else:
        stats |= {"max_drawdown_pct": 0.0, "sharpe_ratio": 0.0, "sortino_ratio": 0.0}

    return stats


def run_backtest(
    db: Session,
    strategy_type: str,
    symbols: list[str],
    start: date,
    end: date,
    params: dict[str, Any] | None = None,
    interval: str = "day",
    starting_capital: float | None = None,
) -> BacktestResult:
    """Replay one strategy over [start, end] against stored candles.

    `symbols` must already have ingested history (`swingtrade backfill`) —
    this reads only what is already in the `candles` table, same as the live
    scan. History before `start` is loaded too, deliberately: a strategy like
    ml_swing needs ~260 warm-up bars before it can evaluate day 1 of the
    window, exactly as it needs 260 bars of lookback in live scanning.
    """
    starting_capital = starting_capital or settings.PAPER_STARTING_CAPITAL

    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.tradingsymbol.in_([s.upper() for s in symbols]))
        )
        .scalars()
        .all()
    )
    if not instruments:
        raise ValueError("No matching instruments for the given symbols")

    # Never persisted — a throwaway config object so evaluate()/calculate_quantity
    # see the same shape they would from a real Strategy row.
    strategy_row = StrategyModel(
        name=f"backtest-{strategy_type}",
        strategy_type=strategy_type,
        params=params or {},
        symbols=symbols,
        mode=TradingMode.PAPER,
    )
    impl = get_strategy(strategy_row)
    min_bars = impl.min_bars_required()

    history: dict[int, pd.DataFrame] = {}
    for inst in instruments:
        df = load_candles(db, inst.id, interval)
        if df.empty:
            continue
        history[inst.id] = df[df["ts"].dt.date <= end].reset_index(drop=True)

    if not history:
        raise ValueError("No candle history found for the given symbols — run backfill first")

    all_dates = sorted(
        {d.date() for df in history.values() for d in df["ts"] if start <= d.date() <= end}
    )
    if not all_dates:
        raise ValueError("No candles fall inside the requested date range")

    cash = starting_capital
    open_positions: dict[int, _OpenPosition] = {}
    trades: list[BacktestTrade] = []
    equity_curve: list[dict[str, Any]] = []
    peak = starting_capital

    for day in all_dates:
        # ---- mechanical exits first: stop-loss > target > time-stop, same
        # priority order as services/execution.check_exits ----
        for inst_id, pos in list(open_positions.items()):
            bar_rows = history[inst_id][history[inst_id]["ts"].dt.date == day]
            if bar_rows.empty:
                continue
            bar = bar_rows.iloc[0]

            reason: str | None = None
            exit_price: float | None = None
            if pos.stop_loss and bar["low"] <= pos.stop_loss:
                reason, exit_price = "STOP_LOSS_HIT", pos.stop_loss
            elif pos.take_profit and bar["high"] >= pos.take_profit:
                reason, exit_price = "TARGET_HIT", pos.take_profit
            elif (day - pos.entry_date).days >= 60:
                reason, exit_price = "TIME_STOP", float(bar["close"])

            if reason is not None:
                cash += _close_position(pos, exit_price, trades, reason, day)
                del open_positions[inst_id]

        # ---- signal-driven exits and entries ----
        for inst in instruments:
            df = history.get(inst.id)
            if df is None:
                continue
            window = df[df["ts"].dt.date <= day]
            if len(window) < min_bars or window["ts"].dt.date.iloc[-1] != day:
                continue

            decision = impl.evaluate(window, inst, db)
            if decision is None:
                continue

            existing = open_positions.get(inst.id)

            if decision.signal == SignalType.BUY and existing is None:
                holdings_value = sum(
                    p.quantity * _last_close(history[i], day) for i, p in open_positions.items()
                )
                portfolio_value = cash + holdings_value
                max_positions = strategy_row.max_positions or settings.MAX_OPEN_POSITIONS
                drawdown = (peak - portfolio_value) / peak if peak else 0.0

                if len(open_positions) >= max_positions:
                    continue
                if drawdown >= settings.MAX_PORTFOLIO_DRAWDOWN_PCT:
                    continue

                qty, _note = calculate_quantity(
                    decision.price, decision.stop_loss, portfolio_value, cash, strategy_row
                )
                if qty < 1:
                    continue

                fill_price = _apply_slippage(decision.price, "BUY")
                turnover = fill_price * qty
                brokerage, taxes = _charges(turnover)
                cost = turnover + brokerage + taxes
                if cost > cash:
                    continue

                cash -= cost
                open_positions[inst.id] = _OpenPosition(
                    instrument_id=inst.id,
                    symbol=inst.tradingsymbol,
                    quantity=qty,
                    entry_price=fill_price,
                    entry_date=day,
                    stop_loss=decision.stop_loss,
                    take_profit=decision.take_profit,
                    charges_so_far=brokerage + taxes,
                )

            elif decision.signal in (SignalType.EXIT, SignalType.SELL) and existing is not None:
                cash += _close_position(existing, decision.price, trades, "SIGNAL_EXIT", day)
                del open_positions[inst.id]

        holdings_value = sum(
            p.quantity * _last_close(history[i], day) for i, p in open_positions.items()
        )
        total_value = cash + holdings_value
        peak = max(peak, total_value)
        equity_curve.append(
            {"date": day.isoformat(), "total_value": round(total_value, 2), "cash": round(cash, 2)}
        )

    # Liquidate anything still open at period end at the last available close,
    # so the reported return isn't inflated by marking unrealised gains at
    # face value the way an open position otherwise would.
    for inst_id, pos in list(open_positions.items()):
        last_price = _last_close(history[inst_id], end)
        if last_price > 0:
            cash += _close_position(pos, last_price, trades, "BACKTEST_END", end)

    ending_value = cash
    stats = _compute_stats(trades, equity_curve, starting_capital, ending_value)

    log.info(
        "backtest.done",
        strategy=strategy_type,
        symbols=len(instruments),
        days=len(all_dates),
        trades=len(trades),
        return_pct=round(stats["total_return_pct"], 4),
    )

    return BacktestResult(
        starting_capital=starting_capital,
        ending_value=round(ending_value, 2),
        trades=trades,
        equity_curve=equity_curve,
        stats=stats,
    )
