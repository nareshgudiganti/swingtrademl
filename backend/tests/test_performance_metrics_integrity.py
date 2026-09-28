"""The scorecard has to be trustworthy before anything else can be judged by it.

Three defects made the paper report unreadable: a max drawdown taken as the
largest value any snapshot row ever *stored* (so one bad row poisoned it
forever, long after the account recovered), Sharpe and Sortino annualised by
sqrt(252) over a handful of days, and snapshot-derived figures that are
account-wide sitting in the same response as trade figures filtered to the
bot's own book — two populations under one heading.

The combination is what produced "Sharpe 2.47, Sortino 7.40, max drawdown
70.9%" on an account that was down about 2%.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.trading import PortfolioSnapshot
from swing_trade_ml.services.portfolio import MIN_SNAPSHOTS_FOR_RATIOS, performance_stats


def _snapshots(db_session, values: list[float], *, stored_drawdowns: list[float] | None = None):
    """An equity curve, one snapshot per day, oldest first.

    `stored_drawdowns` overrides the drawdown_pct column so a row can carry a
    figure that disagrees with its own total_value — which is exactly what a
    poisoned historical row looks like.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    peak = 0.0
    rows = []
    for i, value in enumerate(values):
        peak = max(peak, value)
        rows.append(
            PortfolioSnapshot(
                mode="paper",
                ts=start + timedelta(days=i),
                cash=value,
                holdings_value=0.0,
                total_value=value,
                peak_value=peak,
                drawdown_pct=(
                    stored_drawdowns[i]
                    if stored_drawdowns is not None
                    else ((peak - value) / peak if peak else 0.0)
                ),
            )
        )
    db_session.add_all(rows)
    db_session.flush()
    return rows


def test_max_drawdown_comes_from_the_equity_curve_not_a_stored_column(db_session):
    """A row claiming a 70.9% drawdown cannot outvote the values beside it.

    The old code took max(s.drawdown_pct), so a single row written with a
    wrong peak_value — a broker glitch, a mid-migration snapshot — set the
    headline drawdown permanently, even though every total_value in the
    series says the account never fell more than 2%.
    """
    values = [1_000_000.0] * 5 + [980_000.0] + [1_000_000.0] * 5
    poisoned = [0.0] * 5 + [0.709] + [0.0] * 5
    _snapshots(db_session, values, stored_drawdowns=poisoned)

    stats = performance_stats(db_session, mode="paper")

    assert stats["max_drawdown_pct"] == 0.02


def test_a_one_day_value_collapse_that_instantly_recovers_is_treated_as_bad_data(db_session):
    """A real crash does not undo itself the next morning.

    A snapshot far below both of its neighbours is a valuation failure (a
    quote feed returning zero, holdings priced before they settled), not a
    drawdown. Keeping it turns one bad afternoon into a permanent 70% stain.
    A genuine fall is covered by the test below — only the V-shaped spike is
    dropped.
    """
    values = [1_000_000.0] * 4 + [300_000.0] + [1_000_000.0] * 4
    _snapshots(db_session, values)

    stats = performance_stats(db_session, mode="paper")

    assert stats["max_drawdown_pct"] == 0.0
    assert stats["snapshots_excluded"] == 1


def test_a_genuine_sustained_fall_is_still_reported(db_session):
    """The anomaly guard must not hide a real drawdown.

    Same 70% depth as the spike above, but the account stays down. That is a
    catastrophe the report has to show, so nothing is excluded.
    """
    values = [1_000_000.0] * 4 + [300_000.0] * 5
    _snapshots(db_session, values)

    stats = performance_stats(db_session, mode="paper")

    assert stats["max_drawdown_pct"] == 0.7
    assert stats["snapshots_excluded"] == 0


def test_sharpe_and_sortino_are_none_until_the_sample_is_long_enough(db_session):
    """Annualising a three-day sample by sqrt(252) is not an estimate.

    Returning None says "not enough data yet". Returning 0.0, as the old code
    did, reads as "measured, and flat" — the one thing it cannot mean.
    """
    _snapshots(db_session, [1_000_000.0, 1_002_000.0, 1_004_000.0])

    stats = performance_stats(db_session, mode="paper")

    assert stats["sharpe_ratio"] is None
    assert stats["sortino_ratio"] is None
    assert stats["ratios_reliable"] is False
    assert "3" in stats["ratios_note"] and str(MIN_SNAPSHOTS_FOR_RATIOS) in stats["ratios_note"]


def test_a_long_enough_sample_reports_ratios_and_marks_them_reliable(db_session):
    """Past the minimum, the numbers are published with the same formula as
    services/backtest.py so live and replay figures stay comparable."""
    daily = [0.015, -0.008, 0.004, -0.014]
    values = [1_000_000.0]
    for i in range(39):
        values.append(values[-1] * (1 + daily[i % len(daily)]))
    _snapshots(db_session, values)

    stats = performance_stats(db_session, mode="paper")

    assert stats["sharpe_ratio"] is not None
    assert stats["ratios_reliable"] is True


def test_snapshot_derived_figures_are_labelled_account_wide(db_session):
    """`book=bot` filters the trade figures but cannot filter a snapshot — one
    row stores one total per mode. The response has to say so, or the UI shows
    the bot's P&L beside the whole account's drawdown under one heading."""
    _snapshots(db_session, [1_000_000.0, 990_000.0, 1_000_000.0])

    stats = performance_stats(db_session, mode="paper", bot_book_only=True)

    assert stats["snapshot_scope"] == "account"
