"""Paper performance figures describe the CURRENT trial, not every trade the
database has ever held.

The 70 paper trades closed before 28 September 2026 were booked by a scan
whose position sizing and buy-slot allocation were both broken (78fe87b) and
whose entry rules changed part-way through. Their -2% is a true fact about
code that no longer runs, so folding it into today's headline answers a
question nobody asked: it makes a working bot look broken and would make a
broken one look merely unlucky.

So the window is a reporting boundary, never a delete. Every figure stays
reachable through `all_time=true`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import PortfolioSnapshot, Trade
from swing_trade_ml.services import portfolio as portfolio_service

HEADERS = {"X-API-Key": "test-api-key"}

TRIAL_START = datetime(2026, 9, 28, tzinfo=portfolio_service.IST)
BEFORE = TRIAL_START - timedelta(days=3)
AFTER = TRIAL_START + timedelta(days=1)

# What the account was worth the evening before the trial opened. The windowed
# return has to measure from here, not from the account's original funding,
# or it would re-report the old run's losses as this trial's.
OPENING_EQUITY = 979_791.66


@pytest.fixture()
def trial(monkeypatch):
    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", TRIAL_START.date())
    monkeypatch.setattr(settings, "PAPER_STARTING_CAPITAL", 1_000_000.0)


def _trade(instrument_id: int, *, symbol: str, exit_at: datetime, net_pnl: float) -> Trade:
    return Trade(
        instrument_id=instrument_id,
        mode="paper",
        symbol=symbol,
        quantity=10,
        entry_price=100.0,
        exit_price=100.0 + net_pnl / 10,
        entry_at=exit_at - timedelta(days=5),
        exit_at=exit_at,
        holding_days=5,
        gross_pnl=net_pnl,
        charges=0.0,
        net_pnl=net_pnl,
        return_pct=net_pnl / 1000.0,
        is_win=net_pnl > 0,
    )


@pytest.fixture()
def book(db_session):
    """One heavy loss from the replaced system, one win from the new trial,
    and the equity curve either side of the boundary."""
    instrument = Instrument(
        instrument_token=771001, tradingsymbol="TRIALCO", exchange="NSE", is_watchlisted=True
    )
    db_session.add(instrument)
    db_session.flush()

    db_session.add_all(
        [
            _trade(instrument.id, symbol="OLDLOSS", exit_at=BEFORE, net_pnl=-20_208.34),
            _trade(instrument.id, symbol="NEWWIN", exit_at=AFTER, net_pnl=1_500.0),
            PortfolioSnapshot(
                mode="paper",
                ts=BEFORE,
                cash=OPENING_EQUITY,
                holdings_value=0.0,
                total_value=OPENING_EQUITY,
                peak_value=1_000_000.0,
                drawdown_pct=0.02,
            ),
            PortfolioSnapshot(
                mode="paper",
                ts=AFTER,
                cash=OPENING_EQUITY + 1_500.0,
                holdings_value=0.0,
                total_value=OPENING_EQUITY + 1_500.0,
                peak_value=1_000_000.0,
                drawdown_pct=0.0,
            ),
        ]
    )
    db_session.commit()
    return instrument


def test_headline_counts_only_the_trial(trial, book, db_session):
    stats = portfolio_service.performance_stats(db_session, "paper")

    assert stats["total_trades"] == 1
    assert stats["winning_trades"] == 1
    assert stats["win_rate"] == 1.0
    assert stats["realized_pnl"] == pytest.approx(1_500.0)
    assert stats["measured_since"] == "2026-09-28"


def test_return_measures_from_the_trial_opening_equity(trial, book, db_session):
    """The pre-trial loss must not show up a second time as a negative return.

    Starting from PAPER_STARTING_CAPITAL would report -1.9% for a trial that
    has only ever made money, because the account opened the trial already
    ₹20K down from the run being excluded.
    """
    stats = portfolio_service.performance_stats(db_session, "paper")

    assert stats["starting_capital"] == pytest.approx(OPENING_EQUITY)
    assert stats["total_return_pct"] > 0


def test_all_time_still_returns_the_whole_record(trial, book, db_session):
    stats = portfolio_service.performance_stats(db_session, "paper", all_time=True)

    assert stats["total_trades"] == 2
    assert stats["realized_pnl"] == pytest.approx(-18_708.34)
    assert stats["starting_capital"] == pytest.approx(1_000_000.0)
    assert stats["measured_since"] is None


def test_drawdown_does_not_inherit_the_replaced_run(trial, book, db_session):
    """The old system drew the account down 2%. Reporting that as the trial's
    drawdown would describe code that no longer runs."""
    stats = portfolio_service.performance_stats(db_session, "paper")
    assert stats["max_drawdown_pct"] == 0.0

    all_time = portfolio_service.performance_stats(db_session, "paper", all_time=True)
    assert all_time["max_drawdown_pct"] == pytest.approx(0.02)


def test_live_figures_are_never_windowed(trial, db_session):
    """Real money has no restarts — a live account's record is its record."""
    assert portfolio_service.trial_start("live") is None


def test_window_is_midnight_ist_not_utc(trial):
    """A trade closed at 23:00 IST on the 27th belongs to the old run. Midnight
    UTC would be 05:30 IST on the 28th and would sweep it into the trial."""
    boundary = portfolio_service.trial_start("paper")

    assert boundary is not None
    assert boundary.utcoffset() == timedelta(hours=5, minutes=30)
    assert boundary.astimezone(UTC).isoformat() == "2026-09-27T18:30:00+00:00"


def test_unset_trial_start_measures_all_time(monkeypatch, book, db_session):
    """Clearing the setting has to restore the old behaviour exactly, so the
    boundary can be retired without a code change."""
    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", None)

    stats = portfolio_service.performance_stats(db_session, "paper")

    assert stats["total_trades"] == 2
    assert stats["measured_since"] is None


def test_trades_endpoint_agrees_with_the_headline(trial, book, client):
    """A trade list showing rows the summary's counts exclude is how you get
    someone comparing two numbers that were never measuring the same thing."""
    scoped = client.get("/api/v1/portfolio/trades", headers=HEADERS)
    assert scoped.status_code == 200
    assert [row["symbol"] for row in scoped.json()] == ["NEWWIN"]

    every = client.get("/api/v1/portfolio/trades?all_time=true", headers=HEADERS)
    assert every.status_code == 200
    assert {row["symbol"] for row in every.json()} == {"NEWWIN", "OLDLOSS"}


def test_equity_curve_starts_at_the_trial(trial, book, client):
    """Only the post-boundary point survives. The endpoint has always labelled
    points by their UTC date, so the 29th 00:00 IST point reads "2026-09-28";
    this asserts which point came back, not how it is labelled."""
    every = client.get("/api/v1/portfolio/equity-curve?days=1825&all_time=true", headers=HEADERS)
    assert every.status_code == 200
    assert len(every.json()) == 2

    scoped = client.get("/api/v1/portfolio/equity-curve?days=1825", headers=HEADERS)
    assert scoped.status_code == 200
    assert scoped.json() == [every.json()[-1]]
