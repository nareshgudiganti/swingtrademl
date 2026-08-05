"""NSE equity-segment trading holidays.

Compiled from public NSE holiday calendars as of 2026-08-05 — not the
official circular. NSE typically finalises the *next* calendar year's
holidays only a few months ahead, and lunar-calendar festival dates
(Shivaratri, Ramzan Eid, etc.) shift every year, so this list needs a
fresh check against https://www.nseindia.com/resources/exchange-communication-holidays
at the start of each year. Missing or wrong dates fail safe — the same way
this always behaved before this module existed: a scan on an unlisted
holiday just finds no new candle and produces nothing, it does not place a
bad trade.
"""

from __future__ import annotations

from datetime import date

NSE_HOLIDAYS: dict[int, set[date]] = {
    2025: {
        date(2025, 2, 26),  # Mahashivratri
        date(2025, 3, 14),  # Holi
        date(2025, 3, 31),  # Eid-Ul-Fitr (Ramzan Id)
        date(2025, 4, 10),  # Shri Mahavir Jayanti
        date(2025, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 1),  # Maharashtra Day
        date(2025, 8, 15),  # Independence Day
        date(2025, 8, 27),  # Ganesh Chaturthi
        date(2025, 10, 2),  # Mahatma Gandhi Jayanti / Dussehra
        date(2025, 10, 21),  # Diwali Laxmi Pujan
        date(2025, 10, 22),  # Diwali Balipratipada
        date(2025, 11, 5),  # Prakash Gurpurb Sri Guru Nanak Dev
        date(2025, 12, 25),  # Christmas
    },
    2026: {
        date(2026, 1, 26),  # Republic Day
        date(2026, 3, 3),  # Holi
        date(2026, 3, 26),  # Shri Ram Navami
        date(2026, 3, 31),  # Shri Mahavir Jayanti
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
        date(2026, 5, 1),  # Maharashtra Day
        date(2026, 5, 28),  # Bakri Id
        date(2026, 6, 26),  # Muharram
        date(2026, 8, 15),  # Independence Day
        date(2026, 9, 14),  # Ganesh Chaturthi
        date(2026, 10, 2),  # Mahatma Gandhi Jayanti
        date(2026, 10, 20),  # Dussehra
        date(2026, 11, 10),  # Diwali Balipratipada
        date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
        date(2026, 12, 25),  # Christmas
    },
}


def is_trading_holiday(d: date) -> bool:
    """True on a known NSE equity holiday. Unknown years (not yet compiled
    above) always return False rather than raise — an un-modelled holiday
    degrades to "scan finds nothing new," never to an error."""
    return d in NSE_HOLIDAYS.get(d.year, set())
