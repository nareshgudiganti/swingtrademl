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
# The Positions page's single "what should I do" read — priority order:
# exit signal > alert already sent > horizon elapsed > early dip > hold.


def test_pending_exit_signal_wins_regardless_of_everything_else():
    code, _ = position_action(
        entry_confidence=0.70, last_confidence=0.68, alert_sent=False,
        holding_days=1, horizon_days=5, exit_signal_pending=True,
    )
    assert code == "exit"


def test_alert_already_sent_outranks_horizon_and_dip():
    code, label = position_action(
        entry_confidence=0.66, last_confidence=0.40, alert_sent=True,
        holding_days=6, horizon_days=5,
    )
    assert code == "alert"
    assert "40%" in label


def test_horizon_reached_outranks_early_dip():
    code, label = position_action(
        entry_confidence=0.66, last_confidence=0.60, alert_sent=False,
        holding_days=5, horizon_days=5,
    )
    assert code == "horizon"
    assert "5 of 5" in label


def test_early_dip_shows_before_the_real_alert_threshold():
    """A 6-point drop is real movement but below the 15-point alert
    threshold — should read as a soft "easing" cue, not silence."""
    code, label = position_action(
        entry_confidence=0.66, last_confidence=0.60, alert_sent=False,
        holding_days=2, horizon_days=5,
    )
    assert code == "dip"
    assert "66%" in label and "60%" in label


def test_ordinary_day_after_purchase_jitter_reads_as_hold():
    """Mirrors confidence_decay_status's own noise boundary: a 3-point drop
    must not look alarming here either."""
    code, label = position_action(
        entry_confidence=0.66, last_confidence=0.63, alert_sent=False,
        holding_days=1, horizon_days=5,
    )
    assert code == "hold"
    assert "day 1 of 5" in label


def test_no_entry_confidence_still_reports_a_plain_hold():
    """Manual trades with no tracked entry confidence must degrade cleanly,
    not error."""
    code, label = position_action(
        entry_confidence=None, last_confidence=None, alert_sent=False,
        holding_days=3, horizon_days=None,
    )
    assert code == "hold"
    assert "day 3" in label
