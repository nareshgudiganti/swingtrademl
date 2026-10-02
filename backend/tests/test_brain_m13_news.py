"""M13 news and events brain: results windows, corporate actions, restrictions."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.brain.modules.m13_news.calendar import (
    EventRow,
    RestrictionRow,
    read_calendar,
    trading_days_until,
)

TODAY = date(2026, 10, 5)  # a Monday


def _results(day, symbol="ABC"):
    return EventRow(symbol=symbol, kind="results", day=day, detail="Financial Results")


def _action(day, detail="Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"):
    return EventRow(symbol="ABC", kind="corporate_action", day=day, detail=detail)


def _labels(ev):
    return [s.label for s in ev.situations]


def test_the_window_counts_trading_days():
    # Mon 5 Oct -> Mon 12 Oct is 5 trading days away (weekend skipped).
    assert trading_days_until(TODAY, date(2026, 10, 12)) == 5
    assert trading_days_until(TODAY, TODAY) == 0


def test_results_within_five_trading_days_is_results_soon_with_the_date():
    ev = read_calendar("ABC", TODAY, [_results(date(2026, 10, 8))], [])
    (sit,) = ev.situations
    assert sit.label == "results soon" and sit.scope == "stock" and sit.subject == "ABC"
    assert sit.evidence[0] == "Results on 08 Oct: the brain avoids new trades 5 trading days before results"
    assert ev.notes == ("Results on 08 Oct.",)


def test_the_blackout_boundary_is_five_in_six_out():
    assert _labels(read_calendar("ABC", TODAY, [_results(date(2026, 10, 12))], [])) == ["results soon"]
    six_out = read_calendar("ABC", TODAY, [_results(date(2026, 10, 13))], [])
    assert _labels(six_out) == [] and six_out.notes == ("Results on 13 Oct.",)


def test_past_and_far_results_add_nothing():
    assert read_calendar("ABC", TODAY, [_results(date(2026, 10, 1))], []).notes == ()
    assert read_calendar("ABC", TODAY, [_results(date(2026, 11, 20))], []).notes == ()


def test_other_stocks_events_are_ignored():
    assert read_calendar("ABC", TODAY, [_results(date(2026, 10, 8), symbol="XYZ")], []).situations == ()


def test_a_corporate_action_in_two_trading_days_is_an_event_blackout():
    ev = read_calendar("ABC", TODAY, [_action(date(2026, 10, 7))], [])
    assert _labels(ev) == ["event blackout"]
    assert "07 Oct" in ev.situations[0].evidence[0] and "Split" in ev.situations[0].evidence[0]
    assert _labels(read_calendar("ABC", TODAY, [_action(date(2026, 10, 8))], [])) == []


def test_after_an_ex_date_the_price_reset_is_named():
    ev = read_calendar("ABC", TODAY, [_action(date(2026, 10, 1))], [])  # Thu, 2 trading days ago
    assert _labels(ev) == ["price reset"]
    assert ev.notes and "not a fall in value" in ev.notes[0]
    assert _labels(read_calendar("ABC", TODAY, [_action(date(2026, 9, 25))], [])) == []


def test_restrictions_name_the_list_and_stage():
    ev = read_calendar("ABC", TODAY, [], [RestrictionRow("ABC", "ASM", "Stage I", date(2026, 10, 3))])
    assert ev.restrictions == ("ASM (Stage I)",)


def test_old_restriction_lists_are_ignored():
    ev = read_calendar("ABC", TODAY, [], [RestrictionRow("ABC", "GSM", "Stage 0", date(2026, 9, 28))])
    assert ev.restrictions == ()
