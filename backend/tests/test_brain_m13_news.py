"""M13 news and events brain: results windows, corporate actions, restrictions."""

from __future__ import annotations

from datetime import UTC, date, datetime

from brain_fakes import FakeReader, registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m13_news.calendar import (
    EventRow,
    RestrictionRow,
    read_calendar,
    trading_days_until,
)
from swing_trade_ml.brain.modules.m13_news.module import EventsBrain
from swing_trade_ml.brain.runner import execute

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


# --- the module and the reader --------------------------------------------------------

RUN_AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)  # 17:30 IST, Monday 5 Oct


class EventReader(FakeReader):
    def __init__(self, events=(), restrictions=(), **kw):
        super().__init__(**kw)
        self.as_of = RUN_AT
        self._events, self._restrictions = list(events), list(restrictions)

    def event_rows(self, symbols):
        return [e for e in self._events if e.symbol in symbols]

    def restriction_rows(self, symbols):
        return [r for r in self._restrictions if r.symbol in symbols]


def _run(reader, universe=("ABC", "XYZ"), holdings=()):
    req = c.RunRequest(run_id="t", kind="nightly", as_of=RUN_AT, universe=universe, live=True)
    reader._holdings = holdings
    return execute(req, reader, registry(EventsBrain), {"M13": Mode.ON})


def test_m13_is_a_recognise_plugin_that_starts_on():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M13") is EventsBrain
    m = EventsBrain.manifest
    assert m.step is Step.RECOGNISE and m.kind == "plugin" and m.default_mode is Mode.ON


def test_the_module_writes_situations_restrictions_and_card_lines():
    reader = EventReader(
        events=[_results(date(2026, 10, 8))],
        restrictions=[RestrictionRow("XYZ", "ASM", "Stage I", date(2026, 10, 5))],
    )
    ctx = _run(reader)
    assert [(s.subject, s.label) for s in ctx.situations] == [("ABC", "results soon")]
    assert ctx.stocks["XYZ"].restrictions == ("ASM (Stage I)",)
    (note,) = [o for o in ctx.opinions if o.source == "event"]
    assert note.symbol == "ABC" and note.reasons == ("Results on 08 Oct.",)


def test_holdings_get_their_event_lines_too():
    reader = EventReader(events=[_results(date(2026, 10, 8), symbol="HELD")])
    ctx = _run(reader, universe=("ABC",), holdings=(c.Holding(symbol="HELD", qty=5, avg_price=100.0),))
    assert {o.symbol for o in ctx.opinions if o.source == "event"} == {"HELD"}


def test_a_quiet_calendar_adds_nothing():
    ctx = _run(EventReader())
    assert not ctx.situations and not ctx.opinions and not ctx.stocks


def test_replays_do_not_see_events_stored_later(db_session):
    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.db.models.feeds import TradingRestriction, UpcomingEvent

    db_session.add_all(
        [
            UpcomingEvent(
                symbol="M13A",
                kind="results",
                event_date=date(2026, 10, 8),
                detail="Results",
                created_at=datetime(2026, 10, 1, 3, 0, tzinfo=UTC),
            ),
            UpcomingEvent(
                symbol="M13A",
                kind="corporate_action",
                event_date=date(2026, 10, 7),
                detail="Bonus",
                created_at=datetime(2026, 10, 6, 3, 0, tzinfo=UTC),
            ),  # stored after the run
            TradingRestriction(symbol="M13A", kind="GSM", stage="Stage 0", as_of=date(2026, 10, 5)),
            TradingRestriction(symbol="M13A", kind="ASM", stage="Stage II", as_of=date(2026, 10, 6)),  # later
        ]
    )
    db_session.flush()
    reader = DatedReader(db_session, RUN_AT, live=False)
    assert [(e.kind, e.day) for e in reader.event_rows(["M13A"])] == [("results", date(2026, 10, 8))]
    assert [(r.kind, r.as_of) for r in reader.restriction_rows(["M13A"])] == [("GSM", date(2026, 10, 5))]
