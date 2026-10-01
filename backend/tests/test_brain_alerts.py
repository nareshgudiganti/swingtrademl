"""M16's pure alert logic: what changed since the previous run, and one
plain message for it."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.brain.alerts.compose import compose
from swing_trade_ml.brain.alerts.detectors import (
    DETECTORS,
    AlertItem,
    DecisionView,
    Detector,
    RunView,
    detect,
)


def _d(symbol, word, kind="idea", reason="Because.", **kw) -> DecisionView:
    return DecisionView(symbol=symbol, kind=kind, word=word, reason=reason, **kw)


def _run(mode="NORMAL", headline="Up-trend.", decisions=(), run_id="r2") -> RunView:
    return RunView(
        run_id=run_id,
        started_at=datetime(2026, 10, 1, 10, 20, tzinfo=UTC),
        banner_mode=mode,
        banner_headline=headline,
        decisions={d.symbol: d for d in decisions},
    )


def _keys(items: list[AlertItem]) -> set[str]:
    return {i.key for i in items}


def test_the_first_run_announces_banner_trades_and_worried_holdings_only():
    current = _run(
        decisions=[
            _d("ABC", "TRADE", qty=10, entry_low=99.0, entry_high=101.0, target=108.0, stop=96.0),
            _d("XYZ", "WAIT"),
            _d("HLD", "MONITOR", kind="holding", reason="Trailing NIFTY by 15%."),
            _d("OK", "HOLD", kind="holding"),
        ]
    )
    assert _keys(detect(current, None)) == {"banner:NORMAL", "trade:ABC", "holding:HLD:MONITOR"}


def test_an_unchanged_market_mode_is_not_repeated():
    prev = _run(mode="DEFENSIVE", run_id="r1")
    assert "banner:DEFENSIVE" not in _keys(detect(_run(mode="DEFENSIVE"), prev))
    assert "banner:NORMAL" in _keys(detect(_run(mode="NORMAL"), prev))


def test_a_trade_that_was_already_a_trade_is_not_repeated():
    prev = _run(decisions=[_d("ABC", "TRADE")], run_id="r1")
    assert "trade:ABC" not in _keys(detect(_run(decisions=[_d("ABC", "TRADE")]), prev))


def test_a_holding_that_got_worse_alerts_but_staying_the_same_does_not():
    prev = _run(decisions=[_d("HLD", "HOLD", kind="holding")], run_id="r1")
    worse = _run(decisions=[_d("HLD", "MONITOR", kind="holding")])
    assert "holding:HLD:MONITOR" in _keys(detect(worse, prev))
    same = _run(decisions=[_d("HLD", "MONITOR", kind="holding")])
    assert not _keys(detect(same, worse))


def test_a_stop_hit_is_announced_first():
    current = _run(
        decisions=[
            _d("ABC", "TRADE"),
            _d("HLD", "EXIT", kind="holding", reason="Stop hit: the price is below the stop."),
        ]
    )
    items = detect(current, None)
    assert items[0].key == "holding:HLD:EXIT"


def test_an_owner_overrule_is_the_word_that_counts():
    current = _run(decisions=[_d("ABC", "TRADE", overruled_word="AVOID")])
    assert "trade:ABC" not in _keys(detect(current, None))


def test_a_detector_can_be_switched_off_or_added():
    current = _run(decisions=[_d("ABC", "TRADE")])
    assert "trade:ABC" not in _keys(detect(current, None, disabled=frozenset({"new_trades"})))
    extra = Detector(
        "always", "Always say hello", lambda cur, prev: [AlertItem("hello", "info", None, "Hello", 9)]
    )
    assert "hello" in _keys(detect(current, None, detectors=[*DETECTORS, extra]))


def test_the_message_is_one_grouped_plain_message():
    current = _run(
        mode="DEFENSIVE",
        headline="NIFTY is in a down-trend.",
        decisions=[
            _d("ABC", "TRADE", qty=10, entry_low=99.0, entry_high=101.0, target=108.0, stop=96.0),
            _d("HLD", "MONITOR", kind="holding", reason="Trailing NIFTY by 15%."),
        ],
    )
    text = compose(detect(current, None), current)
    assert text.count("TradeMind brain") == 1
    assert "DEFENSIVE" in text and "ABC" in text and "Trailing NIFTY by 15%" in text
    assert "10 shares" in text and "target" in text


def test_dangerous_characters_are_escaped():
    current = _run(headline="A <b>bold</b> & risky day", decisions=[_d("A&B", "TRADE", qty=1)])
    text = compose(detect(current, None), current)
    assert "<b>bold</b>" not in text and "&lt;b&gt;" in text and "A&amp;B" in text


def test_nothing_changed_means_no_message():
    assert compose([], _run()) is None
