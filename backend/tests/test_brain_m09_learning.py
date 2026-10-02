"""M09 learning loop, task 1: pure outcome scoring and the DB scoring service.

Locked rule — same conventions as `ml.features.build_label` and
`m05_memory.cases`: entry at the decision day's close; +8% target against -4%
stop within 15 trading bars; a bar touching both barriers counts as the stop;
no hit within the bars available means the outcome is not known yet.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import service
from swing_trade_ml.brain.module import Mode, Step
from swing_trade_ml.brain.modules.m09_learn import learn as learn_mod
from swing_trade_ml.brain.modules.m09_learn import scoring, store
from swing_trade_ml.brain.modules.m09_learn.drift import drift_lines, feature_drift, psi
from swing_trade_ml.brain.modules.m09_learn.failures import failure_patterns
from swing_trade_ml.brain.modules.m09_learn.outcomes import score
from swing_trade_ml.brain.modules.m09_learn.proposals import Draft, buy_level_proposal
from swing_trade_ml.brain.modules.m09_learn.report import by_band, by_week, by_word, one_per_day
from swing_trade_ml.brain.modules.m09_learn.scoring import score_pending
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

IST = ZoneInfo("Asia/Kolkata")
HEADERS = {"X-API-Key": "test-api-key"}


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


# --- drift.py (pure) ---------------------------------------------------------


def test_psi_is_near_zero_for_two_samples_of_the_same_normal():
    rng = np.random.default_rng(0)
    reference = rng.normal(size=2000)
    recent = rng.normal(size=2000)
    assert psi(reference, recent) < 0.1


def test_a_shifted_feature_is_flagged():
    rng = np.random.default_rng(0)
    reference = rng.normal(size=2000)
    recent = rng.normal(size=2000) + 1.0  # mean shifted by one SD
    assert psi(reference, recent) > 0.25


def test_psi_is_none_under_fifty_values():
    rng = np.random.default_rng(0)
    reference = rng.normal(size=49)
    recent = rng.normal(size=2000)
    assert psi(reference, recent) is None
    assert psi(recent, reference) is None


def test_psi_drops_nan_before_counting():
    rng = np.random.default_rng(0)
    reference = np.concatenate([rng.normal(size=60), [np.nan] * 20])
    recent = np.concatenate([rng.normal(size=60), [np.nan] * 20])
    assert psi(reference, recent) is not None


def _drift_frame(rng, n: int, shift: dict[str, float] | None = None) -> pd.DataFrame:
    shift = shift or {}
    cols = {
        name: rng.normal(size=n) + shift.get(name, 0.0)
        for name in [
            "rsi_14",
            "sma_50_ratio",
            "sma_200_ratio",
            "high_52w_dist",
            "relative_strength_20d",
            "vix_percentile_rank",
            "breadth_pct_above_sma50",
            "nifty_trend_regime",
        ]
    }
    return pd.DataFrame(cols)


def test_feature_drift_levels_and_ordering():
    rng = np.random.default_rng(1)
    reference = _drift_frame(rng, 2000)
    recent = _drift_frame(
        rng, 2000, shift={"high_52w_dist": 1.2, "rsi_14": 0.15}
    )  # one major shift, one moderate-ish, rest stable
    drift = feature_drift(reference, recent)
    assert next(d["feature"] for d in drift) == "high_52w_dist"
    assert drift[0]["level"] == "major"
    levels = {d["feature"]: d["level"] for d in drift}
    assert levels["nifty_trend_regime"] == "stable"
    psis = [d["psi"] for d in drift]
    assert psis == sorted(psis, reverse=True)


def test_feature_drift_skips_features_missing_on_either_side():
    rng = np.random.default_rng(2)
    reference = _drift_frame(rng, 2000).drop(columns=["vix_percentile_rank"])
    recent = _drift_frame(rng, 2000).drop(columns=["breadth_pct_above_sma50"])
    drift = feature_drift(reference, recent)
    names = {d["feature"] for d in drift}
    assert "vix_percentile_rank" not in names
    assert "breadth_pct_above_sma50" not in names


def test_drift_lines_wording_for_moderate_and_major_only():
    drift = [
        {"feature": "high_52w_dist", "psi": 0.41, "level": "major"},
        {"feature": "rsi_14", "psi": 0.18, "level": "moderate"},
        {"feature": "sma_50_ratio", "psi": 0.03, "level": "stable"},
    ]
    lines = drift_lines(drift)
    assert lines == [
        "high_52w_dist has shifted a lot from what the model learnt on (stability index 0.41).",
        "rsi_14 has shifted a little from what the model learnt on (stability index 0.18).",
    ]


# --- proposals.buy_level_proposal (pure) ------------------------------------


def _rows_at(confidence: float, n: int, outcome: str, ret: float) -> list[dict]:
    return [{"confidence": confidence, "outcome": outcome, "ret": ret}] * n


def test_raise_proposal_with_exact_wording():
    rows = pd.DataFrame(
        _rows_at(0.65, 15, "target", 0.08)
        + _rows_at(0.65, 5, "stop", -0.04)
        + _rows_at(0.6, 10, "stop", -0.04)
    )
    draft = buy_level_proposal(rows, current=0.6)
    assert draft.kind == "buy_level"
    assert draft.change == {"buy_level": 0.65}
    assert draft.title == "Raise the buy level to 65%"
    assert draft.evidence == (
        "Among 20 past ideas scored 65% or more, the average result was +1.25 R per trade, "
        "against +0.50 R for 30 ideas at the current 60%. It would have skipped 10 of 15 "
        "losing ideas and 0 of 15 winning ones."
    )


def test_lower_proposal_with_exact_wording():
    rows = pd.DataFrame(
        _rows_at(0.65, 5, "target", 0.08)
        + _rows_at(0.65, 15, "stop", -0.04)
        + _rows_at(0.6, 10, "target", 0.08)
        # Dragging 0.55's own average well below 0.6's keeps 0.6 the clear
        # best candidate even though 0.55 would otherwise see the same rows.
        + _rows_at(0.58, 50, "stop", -0.04)
    )
    draft = buy_level_proposal(rows, current=0.65)
    assert draft.kind == "buy_level"
    assert draft.change == {"buy_level": 0.6}
    assert draft.title == "Lower the buy level to 60%"
    assert draft.evidence == (
        "Among 30 past ideas scored 60% or more, the average result was +0.50 R per trade, "
        "against -0.25 R for 20 ideas at the current 65%. It would have added 0 of 15 "
        "losing ideas and 10 of 15 winning ones."
    )


def test_too_few_cases_propose_nothing():
    """Even though 0.55 has plenty of great cases, `current` itself (0.9) has
    too few to judge against — nothing is proposed."""
    rows = pd.DataFrame(_rows_at(0.9, 5, "stop", -0.04) + _rows_at(0.55, 30, "target", 0.08))
    assert buy_level_proposal(rows, current=0.9) is None


def test_no_proposal_when_the_gain_is_below_min_gain_r():
    rows = pd.DataFrame(_rows_at(0.65, 20, "stop", -0.04) + _rows_at(0.6, 5, "stop", -0.04))
    assert buy_level_proposal(rows, current=0.6) is None


def test_no_proposal_when_no_candidate_has_enough_cases():
    rows = pd.DataFrame(_rows_at(0.6, 25, "target", 0.08))
    assert buy_level_proposal(rows, current=0.6) is None


# --- store.py (DB) -----------------------------------------------------------


def _buy_level_draft(buy_level: float) -> Draft:
    return Draft(kind="buy_level", title="t", evidence="e", change={"buy_level": buy_level})


def test_create_deduplicates_open_proposals_with_the_same_change(db_session):
    first = store.create(db_session, _buy_level_draft(0.65))
    second = store.create(db_session, _buy_level_draft(0.65))
    assert first is not None
    assert second is None
    assert len(store.list_proposals(db_session, status="open")) == 1


def test_buy_level_changes_only_after_accept(db_session):
    proposal = store.create(db_session, _buy_level_draft(0.65))
    assert store.accepted_buy_level(db_session) is None

    other = store.create(db_session, _buy_level_draft(0.70))
    store.reject(db_session, other.id, by="owner")
    assert store.accepted_buy_level(db_session) is None

    store.accept(db_session, proposal.id, by="owner")
    assert store.accepted_buy_level(db_session) == pytest.approx(0.65)


def test_accepting_an_already_decided_proposal_raises(db_session):
    proposal = store.create(db_session, _buy_level_draft(0.65))
    store.accept(db_session, proposal.id, by="owner")
    with pytest.raises(ValueError):
        store.accept(db_session, proposal.id, by="owner")


def test_rejecting_an_already_decided_proposal_raises(db_session):
    proposal = store.create(db_session, _buy_level_draft(0.65))
    store.reject(db_session, proposal.id, by="owner")
    with pytest.raises(ValueError):
        store.reject(db_session, proposal.id, by="owner")


def test_accepting_a_module_mode_proposal_calls_set_mode(db_session):
    draft = Draft(kind="module_mode", title="t", evidence="e", change={"module": "M05", "mode": "shadow"})
    proposal = store.create(db_session, draft)
    store.accept(db_session, proposal.id, by="owner", note="try it out")
    assert service.load_modes(db_session)["M05"] == Mode.SHADOW
    assert proposal.status == "accepted"
    assert proposal.decided_by == "owner"
    assert proposal.decided_note == "try it out"


# --- reader.DatedReader.model_probability uses the accepted buy level ------


def test_model_probability_uses_the_accepted_buy_level(db_session, monkeypatch):
    from swing_trade_ml.core.enums import ModelStatus
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.ml import predict

    inst = Instrument(
        instrument_token=991099, tradingsymbol="BRAINBUY", exchange="NSE", is_watchlisted=True, is_active=True
    )
    db_session.add(inst)
    db_session.add(
        MLModel(
            name="swing_classifier",
            version="v9",
            algorithm="lightgbm",
            status=ModelStatus.ACTIVE,
            artifact_path="/nowhere/model.joblib",
            activated_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    db_session.commit()

    class _Result:
        probability = 0.77

    monkeypatch.setattr(predict, "predict_instrument", lambda *a, **k: _Result())

    as_of = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    before = DatedReader(db_session, as_of=as_of, live=True)
    _, threshold, _ = before.model_probability("BRAINBUY")
    assert threshold == settings.ML_MIN_CONFIDENCE

    proposal = store.create(db_session, _buy_level_draft(0.7))
    store.accept(db_session, proposal.id, by="owner")

    after = DatedReader(db_session, as_of=as_of, live=True)
    _, threshold_after, _ = after.model_probability("BRAINBUY")
    assert threshold_after == pytest.approx(0.7)


# --- module.py (M09 is the LEARN step, starts ON) ---------------------------


def test_m09_is_the_learn_step_and_starts_on():
    import swing_trade_ml.brain.modules  # noqa: F401
    from swing_trade_ml.brain.module import REGISTRY
    from swing_trade_ml.brain.modules.m09_learn.module import Learning

    assert REGISTRY.get("M09") is Learning
    m = Learning.manifest
    assert m.step is Step.LEARN and m.kind == "step" and m.default_mode is Mode.ON


def test_m09_run_contributes_nothing():
    from swing_trade_ml.brain.modules.m09_learn.module import Learning

    assert Learning().run(view=None) == c.Contribution()


# --- the after-run hook (service._sync_episodes) -----------------------------


def test_only_live_nightly_runs_score_pending(db_session, monkeypatch):
    calls = []

    def _fake(db, reader):
        calls.append(reader.live)
        return 0

    monkeypatch.setattr(scoring, "score_pending_from_reader", _fake)
    for kind, as_of in (("nightly", None), ("why", None), ("nightly", datetime(2026, 9, 1, 12, tzinfo=UTC))):
        service.run_brain(db_session, kind=kind, as_of=as_of, symbols=["ZZZ"])
    assert calls == [True]


# --- learn.learning_report (DB) ----------------------------------------------


def test_learning_report_shape_on_empty_db(db_session):
    report = learn_mod.learning_report(db_session)
    assert report == {
        "since": None,
        "n_scored": 0,
        "by_band": [],
        "by_word": [],
        "by_week": [],
        "failures": [],
        "drift": [],
        "drift_lines": [],
        "note": "Only 0 ideas have finished so far — too few to judge; keep collecting.",
    }


def _scored_run(
    db,
    run_id: str,
    symbol: str,
    confidence: float,
    outcome: str,
    ret: float,
    market: str | None = None,
    as_of: datetime = datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
) -> None:
    context = {"situations": [{"scope": "market", "label": market}]} if market else None
    db.add(
        BrainRun(
            id=run_id,
            kind="nightly",
            as_of=as_of,
            book="paper",
            live=True,
            started_at=as_of,
            status="done",
            context=context,
        )
    )
    db.flush()
    db.add(
        BrainDecision(
            run_id=run_id,
            symbol=symbol,
            kind="idea",
            word="TRADE",
            confidence=confidence,
            outcome=outcome,
            outcome_return=ret,
            reasons=["r"],
        )
    )


def test_learning_report_groups_a_scored_decision(db_session):
    _scored_run(db_session, "fx-learn-1", "ABC", 0.65, "target", 0.08, market="correction")
    db_session.commit()

    report = learn_mod.learning_report(db_session)
    assert report["n_scored"] == 1
    assert report["by_band"] == [
        {"band": "60-70%", "n": 1, "said": pytest.approx(0.65), "hit": 1.0, "avg_r": pytest.approx(2.0)}
    ]
    assert report["by_word"] == [{"word": "TRADE", "n": 1, "hit": 1.0, "avg_r": pytest.approx(2.0)}]
    expected_week = f"{date(2026, 9, 1).isocalendar()[0]}-W{date(2026, 9, 1).isocalendar()[1]:02d}"
    assert report["by_week"] == [{"week": expected_week, "n": 1, "hit": 1.0, "avg_r": pytest.approx(2.0)}]
    assert report["failures"] == []
    assert report["note"] == "Only 1 ideas have finished so far — too few to judge; keep collecting."


def test_learning_report_surfaces_failure_patterns_from_the_runs_market_label(db_session):
    i = 0
    for _ in range(6):
        _scored_run(db_session, f"fx-stop-correction-{i}", f"S{i}", 0.6, "stop", -0.04, market="correction")
        i += 1
    for _ in range(4):
        _scored_run(db_session, f"fx-stop-calm-{i}", f"C{i}", 0.6, "stop", -0.04, market="calm")
        i += 1
    for _ in range(10):
        _scored_run(db_session, f"fx-target-calm-{i}", f"T{i}", 0.6, "target", 0.08, market="calm")
        i += 1
    db_session.commit()

    report = learn_mod.learning_report(db_session)
    assert report["failures"] == [
        "6 of 10 stop-outs came when the market was in a correction (correction was 30% of all ideas)."
    ]


def test_scored_rows_resolves_sector_via_get_sector_bucket(db_session, monkeypatch):
    monkeypatch.setattr(learn_mod, "get_sector_bucket", lambda symbol: f"SECTOR-{symbol}")
    _scored_run(db_session, "fx-rows-1", "ABC", 0.6, "target", 0.08, market="calm")
    db_session.commit()

    rows = learn_mod._scored_rows(db_session, since=None)
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["market"] == "calm"
    assert row["sector"] == "SECTOR-ABC"
    assert row["decision_day"] == date(2026, 9, 1)


def test_learning_report_since_filters_by_decision_day(db_session):
    _scored_run(
        db_session, "fx-early", "ABC", 0.6, "target", 0.08, as_of=datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    )
    _scored_run(
        db_session, "fx-late", "DEF", 0.6, "target", 0.08, as_of=datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    )
    db_session.commit()

    report = learn_mod.learning_report(db_session, since=date(2026, 9, 1))
    assert report["n_scored"] == 1
    assert report["since"] == date(2026, 9, 1)


# --- learn.run_learning (DB) --------------------------------------------------


def test_run_learning_scores_pending_and_builds_the_report(db_session):
    _insert_candles(
        db_session, "RUNLEARN", 910501, [(DECISION_DAY, 100.0), *zip(AFTER_DAYS, AFTER_CLOSES, strict=True)]
    )
    _run(db_session, "fx-run-learning", "nightly", True, DECISION_AS_OF)
    _idea_decision(db_session, "fx-run-learning", "RUNLEARN")
    db_session.commit()

    report = learn_mod.run_learning(db_session)
    assert report["n_scored"] == 1
    assert report["new_proposals"] == []


def test_run_learning_creates_a_buy_level_proposal_when_warranted(db_session):
    i = 0
    for _ in range(15):
        _scored_run(db_session, f"fx-prop-t-{i}", f"T{i}", 0.65, "target", 0.08)
        i += 1
    for _ in range(5):
        _scored_run(db_session, f"fx-prop-u-{i}", f"U{i}", 0.65, "stop", -0.04)
        i += 1
    for _ in range(10):
        _scored_run(db_session, f"fx-prop-v-{i}", f"V{i}", 0.6, "stop", -0.04)
        i += 1
    db_session.commit()

    report = learn_mod.run_learning(db_session)
    assert len(report["new_proposals"]) == 1
    assert report["new_proposals"][0]["title"] == "Raise the buy level to 65%"
    open_proposals = store.list_proposals(db_session, status="open")
    assert len(open_proposals) == 1 and open_proposals[0].change == {"buy_level": 0.65}

    second = learn_mod.run_learning(db_session)
    assert second["new_proposals"] == []
    assert len(store.list_proposals(db_session, status="open")) == 1


# --- API: /brain/learning and /brain/proposals -------------------------------


def test_api_learning_report_shape_on_empty_db(client):
    r = client.get("/api/v1/brain/learning", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["n_scored"] == 0
    assert body["note"] == "Only 0 ideas have finished so far — too few to judge; keep collecting."
    assert body["by_band"] == [] and body["by_word"] == [] and body["by_week"] == []
    assert body["failures"] == [] and body["drift"] == [] and body["drift_lines"] == []


def test_api_proposals_list_accept_reject_and_errors(client, db_session):
    proposal = store.create(db_session, _buy_level_draft(0.65))
    other = store.create(db_session, _buy_level_draft(0.7))
    db_session.commit()

    listed = client.get("/api/v1/brain/proposals", headers=HEADERS).json()
    assert {p["id"] for p in listed} == {proposal.id, other.id}
    assert listed[0]["kind"] == "buy_level"

    open_only = client.get("/api/v1/brain/proposals", params={"status": "open"}, headers=HEADERS).json()
    assert {p["id"] for p in open_only} == {proposal.id, other.id}

    r = client.post(
        f"/api/v1/brain/proposals/{proposal.id}/accept", json={"note": "looks good"}, headers=HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert (
        body["status"] == "accepted"
        and body["decided_by"] == "owner"
        and body["decided_note"] == "looks good"
    )

    r = client.post(f"/api/v1/brain/proposals/{other.id}/reject", json={}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "dismissed"

    # 409: already decided
    r = client.post(f"/api/v1/brain/proposals/{proposal.id}/accept", json={}, headers=HEADERS)
    assert r.status_code == 409

    # 404: unknown id
    r = client.post("/api/v1/brain/proposals/999999999/accept", json={}, headers=HEADERS)
    assert r.status_code == 404
    r = client.post("/api/v1/brain/proposals/999999999/reject", json={}, headers=HEADERS)
    assert r.status_code == 404
