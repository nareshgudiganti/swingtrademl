"""Golden day: one fixed trading day on a synthetic market, run through the
whole brain, must keep producing the same decisions.

The fingerprint is a sha256 of the sorted (symbol, word) pairs plus the banner
mode (`validation.decision_fingerprint`). It deliberately ignores scores and
prices. If this test fails, the brain now says something different about the
same data: look at the actual pairs in the assertion message, decide whether
the change is intended, and only then update the expected values.

To regenerate DELIBERATELY after an intended change:
  1. run only this test; the assertion message prints the actual banner, the
     (symbol, word) pairs and the new fingerprint;
  2. check the pairs make sense (a changed word is a changed decision);
  3. paste them into EXPECTED_BANNER / EXPECTED_PAIRS / EXPECTED_FINGERPRINT
     below and say why in the commit message.
Never regenerate just to turn a red run green without reading the pairs.

No production data: every stock and bar is built here, in the test database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.brain import service, validation
from swing_trade_ml.brain.replay_week import run_replay_week
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Candle, Instrument

IST = ZoneInfo("Asia/Kolkata")
GOLDEN_DAY = date(2026, 9, 25)  # a Friday, not a holiday

# name, token, start price, daily drift (fraction)
STOCKS = [
    ("GOLDUP", 993001, 100.0, 0.004),
    ("GOLDFLAT", 993002, 200.0, 0.0),
    ("GOLDDOWN", 993003, 300.0, -0.004),
]

# With no trained model and no fundamentals in the fixture the brain correctly
# says WAIT for all three and turns DEFENSIVE: cautious, not a fault.
EXPECTED_BANNER = "DEFENSIVE"
EXPECTED_PAIRS = [("GOLDDOWN", "WAIT"), ("GOLDFLAT", "WAIT"), ("GOLDUP", "WAIT")]
EXPECTED_FINGERPRINT = "6f302ab90ffba1dd15d9aa343c0c406ce8d54fad0a4a62997d41993d9c7e67c8"


def _build_market(db) -> None:
    """Daily bars per stock for the 60 days up to and including GOLDEN_DAY, plus a benchmark index."""
    names = [*STOCKS, (settings.BENCHMARK_INDEX_SYMBOL, 993099, 20000.0, 0.001)]
    for symbol, token, start, drift in names:
        inst = Instrument(
            instrument_token=token,
            tradingsymbol=symbol,
            exchange="NSE",
            is_watchlisted=symbol != settings.BENCHMARK_INDEX_SYMBOL,
            is_active=True,
        )
        db.add(inst)
        db.flush()
        price = start
        for i in range(60, -1, -1):
            day = GOLDEN_DAY - timedelta(days=i)
            if day.weekday() >= 5:
                continue
            price *= 1 + drift
            ts = datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)
            db.add(
                Candle(
                    instrument_id=inst.id,
                    interval="day",
                    ts=ts,
                    open=price,
                    high=price * 1.005,
                    low=price * 0.995,
                    close=price,
                    volume=100_000,
                )
            )
    db.commit()


def _replay(db):
    (row,) = run_replay_week(db, start=GOLDEN_DAY, end=GOLDEN_DAY, symbols=[s[0] for s in STOCKS])
    pairs = sorted((d.symbol, d.word) for d in service.decisions_for(db, row.run_id))
    return row, pairs


@pytest.fixture()
def golden_result(db_session):
    _build_market(db_session)
    return _replay(db_session)


def test_golden_day_is_deterministic(db_session, golden_result):
    """Two replays of the same day on the same data give the same fingerprint."""
    row, pairs = golden_result
    again, pairs2 = _replay(db_session)
    assert validation.decision_fingerprint(pairs, row.banner) == validation.decision_fingerprint(
        pairs2, again.banner
    )


def test_golden_day_fingerprint_is_unchanged(golden_result):
    row, pairs = golden_result
    actual = validation.decision_fingerprint(pairs, row.banner)
    assert (row.banner, pairs, actual) == (EXPECTED_BANNER, EXPECTED_PAIRS, EXPECTED_FINGERPRINT), (
        f"Golden day changed. Actual banner={row.banner!r} pairs={pairs!r} fingerprint={actual}. "
        "If intended, follow the regeneration steps in this file's docstring."
    )


def test_fingerprint_changes_when_a_word_or_the_banner_changes():
    base = [("A", "WAIT"), ("B", "TRADE")]
    f = validation.decision_fingerprint
    assert f(base, "NORMAL") == f(list(reversed(base)), "NORMAL")  # order never matters
    assert f(base, "NORMAL") != f([("A", "WAIT"), ("B", "WATCH")], "NORMAL")
    assert f(base, "NORMAL") != f(base, "DEFENSIVE")
