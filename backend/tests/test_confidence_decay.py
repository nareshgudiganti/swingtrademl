"""Confidence-decay alert tests.

The whole point of this feature is to fire on a real decline and stay
silent on ordinary noise — especially the day right after a purchase. These
tests pin exactly that boundary.
"""

from __future__ import annotations

from swing_trade_ml.services.execution import confidence_decay_status, position_action

# Matches ml_swing's default exit_confidence and settings.ML_MIN_CONFIDENCE,
# so the "weakening zone" midpoint is (0.60 + 0.35) / 2 = 0.475.
EXIT_CONFIDENCE = 0.35
MIN_CONFIDENCE = 0.60
DROP_THRESHOLD = 0.15


def _status(entry, current, already_alerted=False):
    return confidence_decay_status(
        entry, current, EXIT_CONFIDENCE, already_alerted, MIN_CONFIDENCE, DROP_THRESHOLD
    )


def test_normal_day_after_purchase_jitter_stays_silent():
    """The exact scenario the user was worried about: buy at 66%, next day
    reads 63% — ordinary noise, must not alert."""
    assert _status(entry=0.66, current=0.63) == "none"


def test_a_real_decline_into_the_weak_zone_alerts():
    """The actual ADANIPORTS case: 61.2% -> 42.7%."""
    assert _status(entry=0.612, current=0.427) == "alert"


def test_big_drop_that_has_not_yet_reached_the_weak_zone_stays_silent():
    """A large-looking drop that still lands above the midpoint is not yet
    a "weakening" signal — the zone check matters as much as the drop size."""
    # midpoint is 0.475; 0.50 is still above it despite an 18-point drop.
    assert _status(entry=0.68, current=0.50) == "none"


def test_small_drop_into_the_weak_zone_stays_silent():
    """Landing in the weak zone alone isn't enough without a real decline —
    e.g. a position opened right at a borderline confidence."""
    assert _status(entry=0.50, current=0.40) == "none"  # only a 10-point drop


def test_already_alerted_does_not_alert_again():
    assert _status(entry=0.612, current=0.427, already_alerted=True) == "none"


def test_recovery_out_of_the_weak_zone_resets_the_alert_flag():
    assert _status(entry=0.612, current=0.55, already_alerted=True) == "reset"


def test_no_entry_confidence_never_alerts():
    """A position without a tracked entry confidence (e.g. some manual
    trades) has nothing to compare against — must degrade to silence, not
    error or false-positive."""
    assert confidence_decay_status(None, 0.30, EXIT_CONFIDENCE, False) == "none"


def test_exact_threshold_drop_alerts():
    """Boundary: exactly drop_threshold and exactly at the zone edge."""
    entry = 0.475 + DROP_THRESHOLD  # 0.625
    current = 0.47  # just inside the weak zone (< 0.475)
    assert _status(entry=entry, current=current) == "alert"


# ------------------------------------------------------------- position_action --
# The Positions page's single "what should I do" read. Leads with the MODEL'S
# CURRENT confidence (a fresh re-ask, not a memory of the original call) —
# bullish (>= 60% buy bar) / weak (below the 47.5% midpoint, approaching the
# 35% exit floor) / dip (a modest, early decline) / hold (steady, below the
# buy bar but not weak). "Day X elapsed" is folded in as a note, never the
# headline — the whole point is that elapsed time alone answers nothing.
# Priority above all of that: a pending exit signal, then an already-sent
# decay alert.


def _action(entry, last, alert_sent=False, holding_days=1, horizon_days=5, exit_signal_pending=False):
    return position_action(
        entry, last, alert_sent, holding_days, horizon_days,
        exit_confidence=EXIT_CONFIDENCE, exit_signal_pending=exit_signal_pending,
    )


def test_pending_exit_signal_wins_regardless_of_everything_else():
    code, _ = _action(entry=0.70, last=0.68, exit_signal_pending=True)
    assert code == "exit"


def test_alert_already_sent_outranks_the_fresh_confidence_read():
    """Even though 40% would otherwise read as "weak" rather than fully
    exit-worthy, an alert already having fired takes priority — the user
    was already notified of a real decline, so that's what the label says."""
    code, label = _action(entry=0.66, last=0.40, alert_sent=True, holding_days=6, horizon_days=5)
    assert code == "alert"
    assert "40%" in label


def test_confidence_still_above_buy_bar_reads_bullish_even_past_horizon():
    """The actual gap this was built to close: 'day 5 of 5, still red' is not
    itself informative. What matters is today's confidence — if the model
    would still buy this fresh, that's a real, current bullish read, not a
    stale one, regardless of P&L or elapsed days."""
    code, label = _action(entry=0.60, last=0.665, holding_days=5, horizon_days=5)
    assert code == "bullish"
    assert "67%" in label or "66%" in label  # 0.665 rounds to 66% or 67% depending on the platform
    assert "5-day call has passed" in label


def test_confidence_below_buy_bar_but_above_warning_zone_is_a_neutral_hold():
    code, label = _action(entry=0.50, last=0.48, holding_days=1, horizon_days=5)
    assert code == "hold"
    assert "48%" in label


def test_confidence_in_the_warning_zone_reads_as_weak():
    """The ADANIPORTS case: below the 47.5% midpoint but not yet alerted —
    genuinely closer to the exit floor than the other tiers."""
    code, label = _action(entry=0.612, last=0.427, holding_days=5, horizon_days=5)
    assert code == "weak"
    assert "43%" in label or "42%" in label


def test_early_dip_shows_before_the_real_alert_threshold():
    """An 11-point drop that's still above the warning-zone midpoint — real
    movement, not yet weak, worth a soft "easing" cue rather than silence."""
    code, label = _action(entry=0.66, last=0.55, holding_days=2, horizon_days=5)
    assert code == "dip"
    assert "66%" in label and "55%" in label


def test_ordinary_day_after_purchase_jitter_does_not_read_as_weak_or_dip():
    """Mirrors confidence_decay_status's own noise boundary: a 3-point drop
    must not look alarming here either — it lands as bullish (still above
    the buy bar), the best-case tier, not a warning."""
    code, _ = _action(entry=0.66, last=0.63, holding_days=1, horizon_days=5)
    assert code == "bullish"


def test_no_confidence_reading_reports_a_plain_hold():
    """Manual trades with no tracked confidence have nothing to read
    directionally — must degrade cleanly, not error or fabricate a read."""
    code, label = _action(entry=None, last=None, holding_days=3, horizon_days=None)
    assert code == "hold"
    assert "day 3" in label
