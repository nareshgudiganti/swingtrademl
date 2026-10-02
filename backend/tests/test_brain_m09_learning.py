"""M09 learning loop, task 1: pure outcome scoring and the DB scoring service.

Locked rule — same conventions as `ml.features.build_label` and
`m05_memory.cases`: entry at the decision day's close; +8% target against -4%
stop within 15 trading bars; a bar touching both barriers counts as the stop;
no hit within the bars available means the outcome is not known yet.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from swing_trade_ml.brain.modules.m09_learn.failures import failure_patterns
from swing_trade_ml.brain.modules.m09_learn.outcomes import score
from swing_trade_ml.brain.modules.m09_learn.report import by_band, by_week, by_word, one_per_day
from swing_trade_ml.brain.modules.m09_learn.scoring import score_pending
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

IST = ZoneInfo("Asia/Kolkata")


def _bars(closes, spread: float = 0.01, start: str = "2026-09-02") -> pd.DataFrame:
    closes = list(closes)
    days = list(pd.bdate_range(start=start, periods=len(closes)).date)
    return pd.DataFrame(
        {
            "day": days,
            "high": [c * (1 + spread) for c in closes],
            "low": [c * (1 - spread) for c in closes],
            "close": closes,
        }
    )


# --- outcomes.score (pure) --------------------------------------------------


def test_target_hit_reports_the_day_return_and_the_path_extremes():
    entry = 100.0
    closes = [entry * 1.01**k for k in range(1, 16)]
    bars = _bars(closes)
    out = score(entry, bars)
    examined = closes[:7]
    expected_max_up = max(c * 1.01 / entry - 1 for c in examined)
    expected_max_down = min(c * 0.99 / entry - 1 for c in examined)
    assert out.outcome == "target" and out.days == 7
    assert out.ret == pytest.approx(0.08)
    assert out.max_up == pytest.approx(expected_max_up)
    assert out.max_down == pytest.approx(expected_max_down)
    assert out.resolved_on == bars["day"].iloc[6]


def test_stop_hit_before_target_on_a_steady_fall():
    entry = 100.0
    closes = [entry * (1 - 0.01 * k) for k in range(1, 16)]
    bars = _bars(closes)
    out = score(entry, bars)
    assert out.outcome == "stop" and out.days == 4
    assert out.ret == pytest.approx(-0.04)
    assert out.resolved_on == bars["day"].iloc[3]


def test_same_bar_touching_both_barriers_counts_as_a_stop():
    entry = 100.0
    bars = pd.DataFrame(
        {
            "day": [date(2026, 9, 3)],
            "high": [entry * 1.09],
            "low": [entry * 0.95],
            "close": [entry * 1.02],
        }
    )
    out = score(entry, bars)
    assert out.outcome == "stop" and out.days == 1
    assert out.ret == pytest.approx(-0.04)


def test_timeout_reports_the_bar_fifteen_return_and_the_path_extremes():
    entry = 100.0
    closes = [100, 100, 100, 100, 104] + [101] * 10
    bars = _bars(closes)
    out = score(entry, bars)
    assert out.outcome == "timeout" and out.days == 15
    assert out.ret == pytest.approx(0.01)
    assert out.max_up == pytest.approx(0.0504)
    assert out.max_down == pytest.approx(-0.01)
    assert out.resolved_on == bars["day"].iloc[14]


def test_fewer_than_the_horizon_with_no_hit_is_not_known_yet():
    entry = 100.0
    bars = _bars([100] * 10)
    assert score(entry, bars) is None


# --- scoring.score_pending (DB) --------------------------------------------

DECISION_AS_OF = datetime(2026, 9, 1, 10, 20, tzinfo=UTC)  # 15:50 IST, same IST day
DECISION_DAY = DECISION_AS_OF.astimezone(IST).date()
AFTER_DAYS = list(pd.bdate_range(start=DECISION_DAY, periods=16).date)[1:]  # 15 bdates after
AFTER_CLOSES = [100.0 * 1.01**k for k in range(1, 16)]  # hits target on bar 7, same as the pure test


def _ist_ts(d: date) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC)


def _insert_candles(db, symbol: str, token: int, days_closes) -> Instrument:
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True, is_active=True
    )
    db.add(inst)
    db.flush()
    for d, close in days_closes:
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=_ist_ts(d),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=100_000,
            )
        )
    db.flush()
    return inst


def _run(db, run_id: str, kind: str, live: bool, as_of: datetime) -> None:
    db.add(
        BrainRun(id=run_id, kind=kind, as_of=as_of, book="paper", live=live, started_at=as_of, status="done")
    )
    db.flush()


def _idea_decision(db, run_id: str, symbol: str) -> BrainDecision:
    d = BrainDecision(run_id=run_id, symbol=symbol, kind="idea", word="TRADE", reasons=["r"])
    db.add(d)
    db.flush()
    return d


def test_only_live_nightly_ideas_are_scored(db_session):
    _insert_candles(
        db_session,
        "ABC",
        910001,
        [(DECISION_DAY, 100.0), *zip(AFTER_DAYS, AFTER_CLOSES, strict=True)],
    )
    _run(db_session, "fx-nightly-live", "nightly", True, DECISION_AS_OF)
    nightly = _idea_decision(db_session, "fx-nightly-live", "ABC")
    _run(db_session, "fx-replay", "nightly", False, DECISION_AS_OF)
    replay = _idea_decision(db_session, "fx-replay", "ABC")
    _run(db_session, "fx-why", "why", True, DECISION_AS_OF)
    why = _idea_decision(db_session, "fx-why", "ABC")
    db_session.commit()

    scored = score_pending(db_session, AFTER_DAYS[-1])

    assert scored == 1
    assert nightly.outcome == "target" and nightly.outcome_days == 7
    assert replay.outcome is None
    assert why.outcome is None


def test_unresolved_decisions_stay_unscored(db_session):
    short_days = AFTER_DAYS[:5]
    _insert_candles(db_session, "XYZ", 910002, [(DECISION_DAY, 100.0)] + [(d, 100.0) for d in short_days])
    _run(db_session, "fx-nightly-live-2", "nightly", True, DECISION_AS_OF)
    decision = _idea_decision(db_session, "fx-nightly-live-2", "XYZ")
    db_session.commit()

    scored = score_pending(db_session, short_days[-1])

    assert scored == 0
    assert decision.outcome is None


# --- report.py (pure) -------------------------------------------------------


def _report_rows(records: list[dict]) -> pd.DataFrame:
    """records: dicts overriding run_started/decision_day/symbol/word/
    confidence/outcome/ret defaults."""
    defaults = {
        "run_started": datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        "decision_day": date(2026, 9, 1),
        "symbol": "ABC",
        "word": "TRADE",
        "confidence": 0.5,
        "outcome": "target",
        "ret": 0.08,
    }
    rows = [{**defaults, **r} for r in records]
    return pd.DataFrame(rows)


def test_one_decision_per_stock_per_day():
    rows = _report_rows(
        [
            {
                "symbol": "ABC",
                "decision_day": date(2026, 9, 1),
                "run_started": datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
                "outcome": "stop",
                "ret": -0.04,
            },
            {
                "symbol": "ABC",
                "decision_day": date(2026, 9, 1),
                "run_started": datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
                "outcome": "target",
                "ret": 0.08,
            },
            {"symbol": "XYZ", "decision_day": date(2026, 9, 1), "outcome": "stop", "ret": -0.04},
        ]
    )
    kept = one_per_day(rows)
    assert len(kept) == 2
    abc = kept[kept["symbol"] == "ABC"].iloc[0]
    assert abc["outcome"] == "target" and abc["ret"] == pytest.approx(0.08)


def test_by_band_calls_one_per_day_itself():
    rows = _report_rows(
        [
            {
                "symbol": "ABC",
                "decision_day": date(2026, 9, 1),
                "run_started": datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
                "confidence": 0.55,
                "outcome": "stop",
                "ret": -0.04,
            },
            {
                "symbol": "ABC",
                "decision_day": date(2026, 9, 1),
                "run_started": datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
                "confidence": 0.55,
                "outcome": "target",
                "ret": 0.08,
            },
        ]
    )
    bands = by_band(rows)
    assert len(bands) == 1
    assert bands[0]["n"] == 1
    assert bands[0]["hit"] == pytest.approx(1.0)


def test_by_band_groups_by_confidence_and_computes_hit_and_avg_r():
    rows = _report_rows(
        [
            {"symbol": "A1", "confidence": 0.52, "outcome": "target", "ret": 0.08},
            {"symbol": "A2", "confidence": 0.58, "outcome": "stop", "ret": -0.04},
            {"symbol": "A3", "confidence": 0.65, "outcome": "target", "ret": 0.08},
        ]
    )
    bands = by_band(rows)
    assert [b["band"] for b in bands] == ["50-60%", "60-70%"]
    fifty = bands[0]
    assert fifty["n"] == 2
    assert fifty["said"] == pytest.approx((0.52 + 0.58) / 2)
    assert fifty["hit"] == pytest.approx(0.5)
    assert fifty["avg_r"] == pytest.approx(((0.08 / 0.04) + (-0.04 / 0.04)) / 2)
    sixty = bands[1]
    assert sixty["n"] == 1 and sixty["hit"] == pytest.approx(1.0)


def test_by_band_skips_rows_without_confidence_and_empty_bands():
    rows = _report_rows(
        [
            {"symbol": "A1", "confidence": None, "outcome": "target", "ret": 0.08},
            {"symbol": "A2", "confidence": 0.9, "outcome": "stop", "ret": -0.04},
        ]
    )
    bands = by_band(rows)
    assert len(bands) == 1
    assert bands[0]["band"] == "70%+"
    assert bands[0]["n"] == 1


def test_by_word_orders_trade_watch_wait_avoid_and_skips_missing():
    rows = _report_rows(
        [
            {"symbol": "A1", "word": "AVOID", "outcome": "stop", "ret": -0.04},
            {"symbol": "A2", "word": "TRADE", "outcome": "target", "ret": 0.08},
            {"symbol": "A3", "word": "WATCH", "outcome": "target", "ret": 0.08},
        ]
    )
    words = by_word(rows)
    assert [w["word"] for w in words] == ["TRADE", "WATCH", "AVOID"]
    assert words[0]["n"] == 1 and words[0]["hit"] == pytest.approx(1.0)


def test_by_week_ascending_by_iso_week():
    rows = _report_rows(
        [
            {"symbol": "A1", "decision_day": date(2026, 9, 29), "outcome": "target", "ret": 0.08},  # W40
            {"symbol": "A2", "decision_day": date(2026, 9, 7), "outcome": "stop", "ret": -0.04},  # W37
        ]
    )
    weeks = by_week(rows)
    assert [w["week"] for w in weeks] == ["2026-W37", "2026-W40"]
    assert weeks[0]["n"] == 1 and weeks[0]["hit"] == pytest.approx(0.0)
    assert weeks[1]["hit"] == pytest.approx(1.0)


# --- failures.py (pure) ------------------------------------------------------


def _failure_rows(records: list[dict]) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(records):
        row = {
            "run_started": datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            "decision_day": date(2026, 9, 1),
            "symbol": f"SYM{i}",
            "outcome": "target",
            "market": None,
            "sector": None,
        }
        row.update(r)
        rows.append(row)
    return pd.DataFrame(rows)


def test_failure_pattern_found_when_one_market_label_is_over_represented():
    records = (
        [{"market": "correction", "outcome": "stop"}] * 6
        + [{"market": "calm", "outcome": "stop"}] * 4
        + [{"market": "calm", "outcome": "target"}] * 10
    )
    rows = _failure_rows(records)
    assert failure_patterns(rows) == [
        "6 of 10 stop-outs came when the market was in a correction (correction was 30% of all ideas)."
    ]


def test_no_failure_pattern_when_stops_are_spread_evenly():
    records = (
        [{"market": "correction", "outcome": "stop"}] * 3
        + [{"market": "correction", "outcome": "target"}] * 7
        + [{"market": "calm", "outcome": "stop"}] * 3
        + [{"market": "calm", "outcome": "target"}] * 7
    )
    rows = _failure_rows(records)
    assert failure_patterns(rows) == []


def test_no_failure_pattern_below_min_stops():
    records = [{"market": "correction", "outcome": "stop"}] * 2 + [
        {"market": "calm", "outcome": "target"}
    ] * 18
    rows = _failure_rows(records)
    assert failure_patterns(rows) == []


def test_failure_patterns_orders_most_striking_first_and_names_sectors_plainly():
    stop_rows = (
        [{"market": "correction", "sector": "BANK", "outcome": "stop"}] * 3
        + [{"market": "correction", "sector": "IT", "outcome": "stop"}] * 3
        + [{"market": "calm", "sector": "IT", "outcome": "stop"}] * 2
    )
    target_rows = [{"market": "correction", "sector": "BANK", "outcome": "target"}] * 2 + [
        {"market": "calm", "sector": "IT", "outcome": "target"}
    ] * 10
    rows = _failure_rows(stop_rows + target_rows)
    assert failure_patterns(rows) == [
        "6 of 8 stop-outs came when the market was in a correction (correction was 40% of all ideas).",
        "3 of 8 stop-outs were Banks stocks (Banks were 25% of all ideas).",
    ]
