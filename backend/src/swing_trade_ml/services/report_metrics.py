"""Shared P&L, win-rate and return arithmetic for four report paths (#322 slice 1).

Four paths used to carry their own copy of this arithmetic: `services/real_report.py` (real Zerodha fills),
`services/weekly_paper_report.py` (paper trades of one week), `services/portfolio.py` (`performance_stats` and
`strategy_performance_stats`, behind `/portfolio/summary`) and the Observatory, which reads
`performance_stats` through `brain_observatory/evidence.paper`. They now call the functions below. Nothing
here reads the database, and every function keeps the operation order of the code it replaced, so no
displayed number moves.

NOT YET MIGRATED, and still carrying their own copy of some of this arithmetic:
`services/tester_paper.py` (the manual testing book's stats), `services/beginner_views.py` (the evidence
summary's wins and win rate) and `services/insights.py` (finished, wins and net P&L per period). Moving them
is a later slice; this module is the shared code of the four paths above, not yet the only place these
numbers are worked out.

WHERE THE PATHS DELIBERATELY DIFFER (named and tested in tests/test_report_metrics.py, never unified):

* Zero profit. A trade that made exactly 0 is NOT a win in any path. `performance_stats` and
  `strategy_performance_stats` then count it on the losing side (losing = "not a win", from the stored
  `Trade.is_win`); `real_report` and the weekly report count a loss only when the net is below 0, so a zero
  trade is neither a win nor a loss there.
* Costs. `real_report` works charges out from the fills with the cost model (`services/costs`). The weekly
  report and `performance_stats` use the charges stored on each Trade row.
* Open versus closed. Realized P&L is closed trades only. Open P&L is a separate figure in every path and is
  never added to it, except `performance_stats.total_pnl`, which is realized plus unrealized by name.
* Mode and window. `performance_stats` is for one broker mode and the current trial window; the weekly report
  is paper only and one week; `real_report` is the real account's fills over the period asked for.
* Return scale. `Trade.return_pct` is a fraction (0.02 is 2%); the weekly report shows it times 100;
  `real_report` reports a percentage per matched slice.
* Rounding to 2 decimals. `real_report` rounds every matched slice to 2 decimals before it sums them, so its
  total is the sum of the rounded slices; the weekly report rounds a total once; `performance_stats` sums the
  stored values unrounded. Totals can therefore differ by a paisa or so when slices carry fractions of one.
* Averages. `performance_stats` averages with numpy, the other paths with a plain sum over a count; the two
  can differ in the last bit of a float, which is why both are kept as they were.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


def is_win(net_pnl: float) -> bool:
    """A win made money. A trade that made exactly 0 is not a win."""
    return net_pnl > 0


def is_loss(net_pnl: float) -> bool:
    """A strict loss: below 0. A zero trade is neither a win nor a strict loss."""
    return net_pnl < 0


def total(values: Iterable[float]) -> float:
    """Plain sum, in the order given."""
    return sum(values)


def win_count(nets: Iterable[float]) -> int:
    return sum(1 for n in nets if is_win(n))


def strict_loss_count(nets: Iterable[float]) -> int:
    return sum(1 for n in nets if is_loss(n))


def win_rate(wins: int, trades: int) -> float:
    """Wins over trades. The caller decides what an empty list shows (the paths differ: 0.0 or no row)."""
    return wins / trades


def mean(values: Sequence[float]) -> float:
    """Plain sum over a count (real_report and the weekly report)."""
    return sum(values) / len(values)


def mean_numpy(values: Sequence[float]) -> float:
    """numpy mean (performance_stats): kept so its floats stay exactly as they were."""
    return float(np.mean(list(values)))


def percent_of(amount: float, base: float) -> float:
    """`amount` as a percentage of `base`; 0.0 when there is no base."""
    return amount / base * 100 if base else 0.0


def fraction_as_percent(fraction: float) -> float:
    """A stored fraction (0.02) as a percentage (2.0)."""
    return fraction * 100


def profit_factor(gross_profit: float, gross_loss: float) -> float:
    """Gross profit per rupee of gross loss; infinite when nothing was lost. `gross_loss` is positive."""
    return (gross_profit / gross_loss) if gross_loss else float("inf")


@dataclass(frozen=True)
class WinLoss:
    """Wins and not-wins of a list of closed trades, worked out from each trade's own win flag."""

    wins: int
    not_wins: int
    win_rate: float
    gross_profit: float
    gross_loss: float  # a positive amount
    avg_win: float
    avg_loss: float  # negative, or 0.0 with no losses
    largest_win: float
    largest_loss: float
    profit_factor: float


def win_loss(nets: Sequence[float], flags: Sequence[bool]) -> WinLoss:
    """The win/loss block of `performance_stats` and `strategy_performance_stats`.

    `flags[i]` says whether trade i is a win (the stored `Trade.is_win`); every other trade is "not a win",
    zero included. Needs at least one trade."""
    won = [n for n, f in zip(nets, flags, strict=True) if f]
    lost = [n for n, f in zip(nets, flags, strict=True) if not f]
    gross_profit = sum(won)
    gross_loss = abs(sum(lost))
    return WinLoss(
        wins=len(won),
        not_wins=len(lost),
        win_rate=win_rate(len(won), len(nets)),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        avg_win=gross_profit / len(won) if won else 0.0,
        avg_loss=-gross_loss / len(lost) if lost else 0.0,
        largest_win=max(won, default=0.0),
        largest_loss=min(lost, default=0.0),
        profit_factor=profit_factor(gross_profit, gross_loss),
    )
