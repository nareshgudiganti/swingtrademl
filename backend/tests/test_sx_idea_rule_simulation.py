"""Pure tests for the neutral ideas-per-fold simulation (no database, no price, no arm result)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sx_idea_rule_simulation.py"
_spec = importlib.util.spec_from_file_location("sx_idea_rule_simulation", _PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_calendar_is_the_thirty_counted_development_folds():
    cal = m.load_calendar_rows(5)
    assert len(cal) == 30
    assert len(cal[-1]) == 13 and sum(len(c) for c in cal) == 565
    assert all(45 <= n <= 47 for c in cal for n in c)


def test_min_independent_ideas_and_inverse():
    n = m.min_independent_ideas(2.85, 0.183, 0.60)
    assert 15 < n < 16.5
    assert m.p_win_at(n, 2.85, 0.183) == pytest.approx(0.60, abs=1e-9)
    assert m.min_independent_ideas(2.85, 0.183, 0.65) > n
    with pytest.raises(ValueError):
        m.min_independent_ideas(2.85, 0.183, 0.5)


def test_net_minus_gross_is_share_gap_times_round_trip():
    assert m.net_minus_gross_pp(0.0, 0.363) == 0.0
    assert m.net_minus_gross_pp(0.2, 0.363) == pytest.approx(0.0726)


def test_persistence_lowers_ideas_and_run_is_deterministic():
    a = m.evaluate(5, 0.0, 20, 1)
    b = m.evaluate(5, 0.9, 20, 1)
    assert a == m.evaluate(5, 0.0, 20, 1)
    assert a["new_idea_share_no_repeat"] > b["new_idea_share_no_repeat"]
    assert a["variants"]["raw_per_day"]["p_19day_fold_passes_ideas"] == 1.0
    assert a["variants"]["days_only"]["mean_eligible_folds"] == 30.0
