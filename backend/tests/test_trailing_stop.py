"""Trailing-stop tests.

trail_stop() ratchets a position's active stop up as price advances,
preserving the original entry-time risk distance below the highest price
seen since entry. It must never move the stop down, and must degrade to a
no-op — not an error — whenever the fields it needs aren't there.
"""

from __future__ import annotations

from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services.execution import trail_stop


def _position(entry_price, initial_stop_loss, highest_price, stop_loss=None):
    return Position(
        entry_price=entry_price,
        initial_stop_loss=initial_stop_loss,
        stop_loss=initial_stop_loss if stop_loss is None else stop_loss,
        highest_price=highest_price,
    )


def test_price_never_advanced_leaves_stop_untouched():
    """highest_price == entry_price: the trailed level equals the original
    stop exactly, so this must not (harmlessly) nudge anything either."""
    p = _position(entry_price=100.0, initial_stop_loss=90.0, highest_price=100.0)
    trail_stop(p)
    assert p.stop_loss == 90.0


def test_price_advanced_ratchets_stop_up_by_the_same_distance():
    """The actual gap this closes: entry 100, initial stop 90 (10-rupee
    risk). Price runs to 120 — the stop should trail to 110, preserving
    that same 10-rupee distance, not stay pinned at 90."""
    p = _position(entry_price=100.0, initial_stop_loss=90.0, highest_price=120.0)
    trail_stop(p)
    assert p.stop_loss == 110.0


def test_stop_never_moves_down_from_a_later_pullback():
    """highest_price only ever grows (see check_exits), but stop_loss might
    already have been trailed past what a stale/lower highest_price would
    imply — trail_stop must take the max, never regress it."""
    p = _position(entry_price=100.0, initial_stop_loss=90.0, highest_price=105.0, stop_loss=98.0)
    trail_stop(p)
    assert p.stop_loss == 98.0  # trailed-from-105 would be 95 — lower, so ignored


def test_missing_initial_stop_loss_is_a_no_op():
    """Positions opened before this migration (or any future manual-entry
    path that doesn't set it) have no anchor to trail from — must not
    fabricate one or crash, just leave the stop as-is."""
    p = Position(entry_price=100.0, initial_stop_loss=None, stop_loss=90.0, highest_price=120.0)
    trail_stop(p)
    assert p.stop_loss == 90.0


def test_missing_stop_loss_is_a_no_op():
    p = Position(entry_price=100.0, initial_stop_loss=90.0, stop_loss=None, highest_price=120.0)
    trail_stop(p)
    assert p.stop_loss is None


def test_missing_highest_price_is_a_no_op():
    p = Position(entry_price=100.0, initial_stop_loss=90.0, stop_loss=90.0, highest_price=None)
    trail_stop(p)
    assert p.stop_loss == 90.0


def test_nonpositive_entry_distance_is_a_no_op_guard():
    """A malformed stop at or above entry (should never happen, but the
    subtraction below would otherwise produce a trailed stop *above* the
    current price on a rising trade) is guarded rather than trusted."""
    p = _position(entry_price=100.0, initial_stop_loss=100.0, highest_price=120.0)
    trail_stop(p)
    assert p.stop_loss == 100.0
