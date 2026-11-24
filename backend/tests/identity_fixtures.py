# ruff: noqa: E501 (long lines in test code)
"""Shared identity fixtures for acceptance tests (#389): one renamed stock and one stale stock, in a few lines.

Import by bare name (the tests folder is not a package): `from identity_fixtures import seed_renamed_stock`.
Everything is written through the identity writer and rolled back with the test's transaction.

    renamed = seed_renamed_stock(db)        # OLD symbol until 2026-11-09, NEW symbol from 2026-11-10, one security_id
    stale = seed_stale_stock(db)            # one stock scored on Friday's candle, one whose newest candle is Thursday's
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import count

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.services.identity import PROVIDER_KITE_TOKEN, writer

_tokens = count(395_000)
_serial = count(1)
FAR_PAST = date(2000, 1, 1)
FRIDAY, THURSDAY = date(2026, 11, 20), date(2026, 11, 19)


def instrument(db, symbol: str, *, name: str | None = None, token: int | None = None) -> Instrument:
    row = Instrument(
        instrument_token=token or next(_tokens),
        tradingsymbol=symbol,
        exchange="NSE",
        name=name or f"{symbol} Ltd",
        instrument_type="EQ",
        segment="NSE",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def daily_candle(db, inst: Instrument, day: date) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime(day.year, day.month, day.day, tzinfo=IST).astimezone(UTC),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
        )
    )
    db.flush()


@dataclass(frozen=True)
class RenamedStock:
    security_id: int
    instrument: Instrument
    old_symbol: str
    new_symbol: str
    renamed_on: date  # the first session under the new symbol

    @property
    def last_old_day(self) -> date:
        return date.fromordinal(self.renamed_on.toordinal() - 1)


def seed_renamed_stock(db, *, renamed_on: date = date(2026, 11, 10)) -> RenamedStock:
    """One security that traded as OLD until the day before `renamed_on` and as NEW from then on. The instrument row
    carries the new symbol and the Kite token (an alias of the same security), as after a sync."""
    n = next(_serial)
    old, new = f"OLDFX{n}", f"NEWFX{n}"
    security_id = writer.create_security(db, name=f"Renamed Fixture {n} Ltd")
    writer.set_symbol(db, security_id, old, FAR_PAST)
    writer.set_symbol(db, security_id, new, renamed_on)
    inst = instrument(db, new, name=f"Renamed Fixture {n} Ltd")
    writer.add_alias(db, security_id, PROVIDER_KITE_TOKEN, str(inst.instrument_token))
    return RenamedStock(security_id, inst, old, new, renamed_on)


@dataclass(frozen=True)
class StaleStock:
    fresh: Instrument  # newest candle is `fresh_session`
    stale: Instrument  # newest candle is `stale_session`: older than the scan's session
    fresh_session: date
    stale_session: date


def seed_stale_stock(db, *, fresh_session: date = FRIDAY, stale_session: date = THURSDAY) -> StaleStock:
    """Two stocks for one scan: one with the scan session's candle and one whose newest candle is a session older."""
    n = next(_serial)
    fresh, stale = instrument(db, f"FRESHFX{n}"), instrument(db, f"STALEFX{n}")
    daily_candle(db, fresh, fresh_session)
    daily_candle(db, stale, stale_session)
    return StaleStock(fresh, stale, fresh_session, stale_session)
