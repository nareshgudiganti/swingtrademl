"""Phase B candidate runner (evidence plan section 3): built and tested on synthetic data only.

No test here reads the local database or real market data. Phase B runs from 2026-11-09, once,
after the rules are locked; until then the runner refuses real runs (see the guard tests).
"""

from __future__ import annotations

import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from swing_trade_ml.brain import phase_b as pb
from swing_trade_ml.brain.replay_scoring import StrictOutcome

REPO = Path(__file__).resolve().parents[2]
SPLIT_DIR = REPO / "docs" / "brain" / "evidence" / "stock_split"
LEDGER = REPO / "docs" / "brain" / "EXPOSURE-LEDGER.md"
BOTH_TAGS = {"evidence-defs-v1", "evidence-defs-v2"}


# ---------------------------------------------------------------- synthetic market


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _walk(days: list[date], seed: int, drift: float = 0.0, vol: float = 0.02) -> pd.DataFrame:
    rng = random.Random(seed)
    rows, close = [], 100.0
    for d in days:
        o = close * (1 + rng.gauss(0, vol / 4))
        c = o * (1 + rng.gauss(drift, vol))
        rows.append({"day": d, "open": o, "high": max(o, c) * 1.01, "low": min(o, c) * 0.99, "close": c})
        close = c
    return pd.DataFrame(rows)


def _flat(days: list[date], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"day": d, "open": c, "high": c, "low": c, "close": c} for d, c in zip(days, closes, strict=True)]
    )


# ---------------------------------------------------------------- the guard


def test_real_run_is_refused_before_9_november_2026_even_with_tags_and_split():
    reasons = pb.refusal_reasons(today=date(2026, 11, 8), tags=BOTH_TAGS, split_dir=SPLIT_DIR)
    assert len(reasons) == 1
    assert "9 November 2026" in reasons[0]


def test_real_run_is_refused_when_a_definitions_tag_is_missing():
    reasons = pb.refusal_reasons(today=date(2026, 11, 9), tags={"evidence-defs-v1"}, split_dir=SPLIT_DIR)
    assert any("evidence-defs-v2" in r for r in reasons)


def test_real_run_is_refused_when_the_split_file_is_missing(tmp_path):
    reasons = pb.refusal_reasons(today=date(2026, 11, 9), tags=BOTH_TAGS, split_dir=tmp_path)
    assert any("stock split" in r for r in reasons)


def test_real_run_is_refused_when_the_split_file_does_not_match_its_recorded_hash(tmp_path):
    for f in SPLIT_DIR.iterdir():
        shutil.copy(f, tmp_path / f.name)
    js = tmp_path / "stock_split_ev15.json"
    js.write_bytes(js.read_bytes().replace(b'"seed": 7', b'"seed": 8'))
    reasons = pb.refusal_reasons(today=date(2026, 11, 9), tags=BOTH_TAGS, split_dir=tmp_path)
    assert any("hash" in r for r in reasons)


def test_real_run_is_allowed_from_9_november_with_both_tags_and_the_locked_split():
    assert pb.refusal_reasons(today=date(2026, 11, 9), tags=BOTH_TAGS, split_dir=SPLIT_DIR) == []


def test_the_guard_raises_a_plain_english_refusal():
    with pytest.raises(pb.RealRunRefusedError) as exc:
        pb.check_real_run_allowed(today=date(2026, 10, 21), tags=set(), split_dir=SPLIT_DIR)
    text = str(exc.value)
    assert text.startswith("Phase B refused")
    assert "9 November 2026" in text and "evidence-defs-v2" in text
    assert "--dry-run" in text


def test_today_is_taken_in_india_time():
    from datetime import UTC, datetime

    # 2026-11-08 19:00 UTC is already 9 November in India
    assert pb.ist_today(datetime(2026, 11, 8, 19, 0, tzinfo=UTC)) == date(2026, 11, 9)


# ---------------------------------------------------------------- the split and leakage


def test_the_locked_split_loads_with_its_hash():
    split = pb.load_split(SPLIT_DIR)
    assert len(split["used_49"]) == 49
    assert len(split["reject_set"]) == 129
    assert len(split["extra_training_set"]) == 128
    assert len(split["sha256"]) == 64


def test_b2_trains_on_177_stocks_and_never_on_the_reject_set():
    split = pb.load_split(SPLIT_DIR)
    b2 = pb.training_symbols("B2", split)
    assert len(b2) == 177
    assert not set(b2) & set(split["reject_set"])
    assert pb.training_symbols("B1", split) == split["used_49"]
    assert pb.training_symbols("B3", split) == split["used_49"]


def test_the_leakage_check_stops_a_run_that_trained_on_a_reject_stock():
    with pytest.raises(pb.LeakageError, match="ZZREJ"):
        pb.assert_no_leakage(["AAA", "ZZREJ"], reject=["ZZREJ", "YYREJ"], where="fold 2025-02-01")
    pb.assert_no_leakage(["AAA"], reject=["ZZREJ"], where="fold 2025-02-01")  # clean: no error


def test_there_are_exactly_three_candidates():
    assert sorted(pb.CANDIDATES) == ["B1", "B2", "B3"]
    with pytest.raises(ValueError):
        pb.training_symbols("B4", pb.load_split(SPLIT_DIR))


def test_the_locked_numbers_are_the_plan_numbers():
    assert pb.SCORE_LINE == 0.80
    assert pb.TOP_K == 5
    assert pb.WEAK_BREADTH == 0.30
    assert pb.BREADTH_SMA == 50
    assert pb.RANDOM_DRAWS == 1000 and pb.RANDOM_SEED == 7
    assert pb.PORTFOLIO_DRAWS == 200
    assert pb.MIN_DAYS == 30
    assert (date(2025, 2, 1), date(2026, 8, 15)) == (pb.DEV_START, pb.DEV_END)
    assert date(2026, 11, 9) == pb.PHASE_B_START
    assert pb.HORIZON == 15


# ---------------------------------------------------------------- breadth and selection


def test_breadth_counts_only_stocks_with_50_closes_and_compares_with_their_own_average():
    days = _weekdays(date(2025, 1, 1), 60)
    up = _flat(days, [100.0] * 59 + [110.0])  # above its 50-day average on the last day
    down = _flat(days, [100.0] * 59 + [90.0])  # below
    young = _flat(days[-10:], [100.0] * 9 + [200.0])  # under 50 closes: not counted
    out = pb.breadth_by_day({"UP": up, "DOWN": down, "YOUNG": young}, [days[-1]])
    assert out[days[-1]] == pytest.approx(0.5)


def test_breadth_uses_nothing_after_the_decision_day():
    days = _weekdays(date(2025, 1, 1), 70)
    a = _walk(days, 1)
    b = a.copy()
    b.loc[b.index[-5:], "close"] = 1.0  # a crash after the decision day
    d = days[60]
    assert pb.breadth_by_day({"A": a}, [d]) == pb.breadth_by_day({"A": b}, [d])


def test_breadth_is_none_when_no_stock_has_enough_history():
    days = _weekdays(date(2025, 1, 1), 10)
    assert pb.breadth_by_day({"A": _flat(days, [1.0] * 10)}, [days[-1]]) == {days[-1]: None}


def test_b1_takes_every_stock_at_or_above_0_80_and_skips_days_without_one():
    d1, d2 = date(2025, 3, 3), date(2025, 3, 4)
    scores = {"A": {d1: 0.80, d2: 0.5}, "B": {d1: 0.79, d2: 0.6}, "C": {d1: 0.95}}
    assert pb.select_b1(scores, [d1, d2]) == {d1: ["C", "A"]}


def test_model_best_5_by_day_skips_days_without_scores():
    d1, d2 = date(2025, 3, 3), date(2025, 3, 4)
    scores = {s: {d1: i / 10} for i, s in enumerate("ABCDEFG")}
    assert pb.select_top_k(scores, [d1, d2]) == {d1: ["G", "F", "E", "D", "C"]}


def test_b3_trades_the_best_5_only_on_market_weak_days():
    d1, d2, d3 = date(2025, 3, 3), date(2025, 3, 4), date(2025, 3, 5)
    scores = {s: {d1: i / 10, d2: i / 10, d3: i / 10} for i, s in enumerate("ABCDEFG")}
    breadth = {d1: 0.29, d2: 0.30, d3: None}  # under 30% is weak; exactly 30% and unknown are not
    assert pb.select_b3(scores, [d1, d2, d3], breadth) == {d1: ["G", "F", "E", "D", "C"]}


# ---------------------------------------------------------------- labels


def test_development_data_can_never_be_labelled_pass():
    assert pb.label(True) == "NO WARNING (diagnostic)"
    assert pb.label(False) == "FAIL"
    assert pb.label(None) == "INCONCLUSIVE"
    assert "PASS" not in {pb.label(x) for x in (True, False, None)}


def test_a_confidence_range_that_spans_the_line_is_inconclusive():
    assert pb.label_from_range(0.001, 0.02) == "NO WARNING (diagnostic)"
    assert pb.label_from_range(-0.02, -0.001) == "FAIL"
    assert pb.label_from_range(-0.01, 0.01) == "INCONCLUSIVE"
    assert pb.label_from_range(None, None) == "INCONCLUSIVE"


# ---------------------------------------------------------------- trade-level comparisons


def _o(r: float | None, status: str = "timeout", exit_day: date | None = None) -> StrictOutcome:
    return StrictOutcome(
        status if r is not None else "open", r, 15 if r is not None else None, False, False, exit_day
    )


def _market(n_days: int = 40, stocks: str = "ABCDEFGH"):
    """Outcomes where stock A always earns +2%, every other stock 0% - 1% by letter."""
    days = _weekdays(date(2025, 3, 3), n_days)
    outcomes = {}
    for d in days:
        for i, s in enumerate(stocks):
            outcomes[(s, d)] = _o(0.02 if s == "A" else -0.001 * i)
    everyone = {d: list(stocks) for d in days}
    return days, outcomes, everyone


def test_trade_summary_counts_ideas_days_and_gives_a_confidence_range_on_the_edge():
    days, outcomes, everyone = _market()
    picks = {d: ["A"] for d in days}
    s = pb.trade_summary(picks, outcomes, everyone)
    assert s["ideas"] == 40 and s["days"] == 40
    assert s["avg_net"] == pytest.approx(0.02)
    every_avg = sum(outcomes[(x, days[0])].net_return for x in "ABCDEFGH") / 8
    assert s["edge_per_day"] == pytest.approx(0.02 - every_avg)
    assert s["edge_low"] == pytest.approx(s["edge_per_day"])  # constant edge: no spread
    assert s["edge_high"] == pytest.approx(s["edge_per_day"])
    assert s["period"] == [days[0].isoformat(), days[-1].isoformat()]


def test_trade_summary_has_no_confidence_range_on_too_few_days():
    days, outcomes, everyone = _market(n_days=10)
    s = pb.trade_summary({d: ["A"] for d in days}, outcomes, everyone)
    assert s["edge_low"] is None and s["edge_high"] is None


def test_unfinished_ideas_are_not_counted():
    d = date(2025, 3, 3)
    s = pb.trade_summary({d: ["A", "B"]}, {("A", d): _o(0.01), ("B", d): _o(None)}, {d: ["A", "B"]})
    assert s["ideas"] == 1


def test_random_5_is_seeded_and_reports_the_share_of_draws_beaten():
    days, outcomes, everyone = _market()
    a = pb.random5_trade(days, everyone, outcomes, candidate_avg=0.02, draws=50)
    b = pb.random5_trade(days, everyone, outcomes, candidate_avg=0.02, draws=50)
    assert a == b
    assert a["draws"] == 50
    assert a["share_beaten"] == pytest.approx(1.0)  # +2% beats any mix of 5 that includes losers
    assert a["p5"] <= a["avg_net_mean"] <= a["p95"]


def test_volatility_thirds_split_the_days_stocks_by_20_day_volatility():
    days = _weekdays(date(2025, 1, 1), 30)
    bars = {
        "CALM": _walk(days, 1, vol=0.001),
        "MID": _walk(days, 2, vol=0.02),
        "WILD": _walk(days, 3, vol=0.08),
    }
    vol = pb.vol20_by_day(bars, [days[-1]])
    thirds = pb.vol_thirds(vol, days[-1], ["CALM", "MID", "WILD"])
    assert thirds == {"CALM": 0, "MID": 1, "WILD": 2}
    assert pb.vol20_by_day(bars, [days[5]])["CALM"] == {}  # not enough history yet


def test_risk_matched_random_only_draws_from_the_same_sector_and_volatility_third():
    d = date(2025, 3, 3)
    outcomes = {("A", d): _o(0.05), ("B", d): _o(-0.03), ("C", d): _o(0.04), ("D", d): _o(0.10)}
    buckets = {"A": "BANK", "B": "BANK", "C": "BANK", "D": "IT"}
    vol = {"A": {d: 0.03}, "B": {d: 0.031}, "C": {d: 0.001}, "D": {d: 0.03}}
    # by volatility (ties by name): C, A, D, B -> thirds C 0, A 0, D 1, B 2
    out = pb.risk_matched_random({d: ["A"]}, {d: list("ABCD")}, outcomes, buckets, vol, draws=40)
    # A's match is a BANK stock in A's third: A itself or C, never B (other third) or D (other sector)
    assert out["unmatched"] == 0
    assert set(out["draw_values"]) <= {0.05, 0.04}


def test_nifty_matched_uses_the_same_entry_open_exit_day_and_costs():
    days = _weekdays(date(2025, 3, 3), 20)
    nifty = _flat(days, [100.0] * 10 + [110.0] * 10)
    picks = {days[0]: ["A"]}
    outcomes = {("A", days[0]): _o(0.03, "target", exit_day=days[12])}
    out = pb.nifty_matched(picks, outcomes, nifty)
    assert out["ideas"] == 1
    assert 0.09 < out["avg_net"] < 0.10  # +10% less slippage and charges
    flat = pb.nifty_matched(picks, outcomes, _flat(days, [100.0] * 20))
    assert -0.01 < flat["avg_net"] < 0


def test_b3_reports_losses_avoided_and_profitable_trades_missed_on_skipped_days():
    d1, d2, d3 = date(2025, 3, 3), date(2025, 3, 4), date(2025, 3, 5)
    scores = {s: {d1: i / 10, d2: i / 10, d3: i / 10} for i, s in enumerate("ABCDEF")}
    breadth = {d1: 0.10, d2: 0.50, d3: 0.60}
    outcomes = {(s, d): _o(0.02 if s in "EF" else -0.04) for s in "ABCDEF" for d in (d1, d2, d3)}
    out = pb.b3_skipped_days(scores, [d1, d2, d3], breadth, outcomes)
    assert out["days"] == 2 and out["ideas"] == 10  # best 5 (B..F) on the two strong days
    assert out["losses_avoided"] == {"count": 6, "avg_net": pytest.approx(-0.04)}
    assert out["profits_missed"] == {"count": 4, "avg_net": pytest.approx(0.02)}


# ---------------------------------------------------------------- portfolio level


def _portfolio_market():
    days = _weekdays(date(2025, 1, 1), 120)
    bars = {s: _walk(days, i + 1, drift=0.001) for i, s in enumerate("ABCDEFGH")}
    return days, bars


def test_portfolio_strategy_gives_the_four_risk_numbers():
    days, bars = _portfolio_market()
    picks = {d: ["A", "B"] for d in days[60:80]}
    out = pb.portfolio_strategy(picks, bars, days, buckets={})
    assert set(out) >= {"final_net_return", "max_drawdown", "halt_triggered", "days_halted", "trades"}
    assert out["trades"] > 0


def test_portfolio_random_5_is_seeded_and_gives_median_and_5th_to_95th():
    days, bars = _portfolio_market()
    pool = {d: list("ABCDEFGH") for d in days[60:90]}
    a = pb.portfolio_random5(pool, bars, days, buckets={}, draws=5)
    assert a == pb.portfolio_random5(pool, bars, days, buckets={}, draws=5)
    assert a["runs"] == 5
    assert a["p5"] <= a["final_net_return_median"] <= a["p95"]
    assert set(a) >= {"max_drawdown_median", "halt_triggered_runs", "days_halted_median"}


def test_nifty_buy_and_hold_pays_one_round_trip_and_tracks_its_fall():
    days = _weekdays(date(2025, 1, 1), 10)
    up = pb.nifty_buy_and_hold(_flat(days, [100.0] * 5 + [110.0] * 5), days)
    assert 0.09 < up["final_net_return"] < 0.10
    assert up["max_drawdown"] == pytest.approx(0.0, abs=1e-3)
    down = pb.nifty_buy_and_hold(_flat(days, [100.0] * 5 + [80.0] * 5), days)
    assert down["max_drawdown"] > 0.19
    assert down["halt_triggered"] is None  # buy and hold has no halt rule


def test_cash_is_zero_everything():
    assert pb.CASH == {
        "final_net_return": 0.0,
        "max_drawdown": 0.0,
        "halt_triggered": False,
        "days_halted": 0,
    }


# ---------------------------------------------------------------- checks and survival


def test_the_reject_set_check_can_only_reject():
    assert pb.reject_label(cand_avg=-0.02, every_avg=-0.01, days=40) == "FAIL"
    assert pb.reject_label(cand_avg=0.00, every_avg=-0.01, days=40) == "NO WARNING (diagnostic)"
    assert pb.reject_label(cand_avg=-0.01, every_avg=-0.01, days=40) == "NO WARNING (diagnostic)"  # not worse
    assert pb.reject_label(cand_avg=0.05, every_avg=-0.01, days=29) == "INCONCLUSIVE"
    assert pb.reject_label(cand_avg=None, every_avg=-0.01, days=40) == "INCONCLUSIVE"


def test_coverage_needs_100_finished_ideas_and_one_a_week():
    assert pb.coverage_label(ideas=99, weeks=10) == "INCONCLUSIVE"
    assert pb.coverage_label(ideas=100, weeks=101) == "FAIL"
    assert pb.coverage_label(ideas=100, weeks=100) == "NO WARNING (diagnostic)"


def test_consistency_drops_the_best_5_percent_and_caps_one_stock_at_20_percent_of_profit():
    spread = [(f"S{i % 10}", 0.01) for i in range(100)]
    assert pb.consistency(spread)["label"] == "NO WARNING (diagnostic)"
    lucky = [("A", 0.50)] * 5 + [(f"S{i % 10}", -0.001) for i in range(95)]
    assert pb.consistency(lucky)["profitable_without_best_5pct"] is False
    assert pb.consistency(lucky)["label"] == "FAIL"
    one_stock = [("A", 0.05)] * 30 + [(f"S{i % 10}", 0.001) for i in range(70)]
    c = pb.consistency(one_stock)
    assert c["largest_stock_share"] > 0.2 and c["label"] == "FAIL"


def test_market_conditions_fail_when_a_type_seen_in_3_windows_averages_below_minus_1_percent():
    ok = {"rising": {"windows": 3, "avg_net": 0.01}, "falling": {"windows": 2, "avg_net": -0.05}}
    assert pb.market_label(ok) == "NO WARNING (diagnostic)"  # falling seen in too few windows
    bad = {"rising": {"windows": 3, "avg_net": -0.011}}
    assert pb.market_label(bad) == "FAIL"
    assert pb.market_label({"rising": {"windows": 2, "avg_net": 0.02}}) == "INCONCLUSIVE"


def test_a_candidate_survives_only_when_it_beats_both_and_the_reject_check_does_not_warn():
    assert pb.survives(beats_label="NO WARNING (diagnostic)", reject="NO WARNING (diagnostic)") is True
    assert pb.survives(beats_label="FAIL", reject="NO WARNING (diagnostic)") is False
    assert pb.survives(beats_label="NO WARNING (diagnostic)", reject="FAIL") is False
    assert pb.survives(beats_label="NO WARNING (diagnostic)", reject="INCONCLUSIVE") is False
    assert pb.survives(beats_label="INCONCLUSIVE", reject="NO WARNING (diagnostic)") is False


# ---------------------------------------------------------------- the whole candidate on fake data

WIN = (date(2025, 2, 3), date(2025, 5, 30))


def _fake_inputs(*, rules_only=True, n49=12, n_reject=8) -> pb.Inputs:
    from swing_trade_ml.brain.walk_forward import make_folds

    days = _weekdays(date(2024, 9, 2), 230)  # history before the window and time to finish after it
    names = [f"S{i:02d}" for i in range(n49)]
    rejects = [f"R{i}" for i in range(n_reject)]
    bars = {s: _walk(days, i + 10, drift=0.0005) for i, s in enumerate(names)}
    reject_bars = {s: _walk(days, i + 100) for i, s in enumerate(rejects)}
    rng = random.Random(3)
    window = [d for d in days if WIN[0] <= d <= WIN[1]]
    scores = {s: {d: 0.5 + rng.random() / 2 for d in window} for s in names}
    reject_scores = {s: {d: 0.5 + rng.random() / 2 for d in window} for s in rejects}
    folds = make_folds(*WIN)
    return pb.Inputs(
        bars=bars,
        reject_bars=reject_bars,
        scores=scores,
        reject_scores=reject_scores,
        nifty=_walk(days, 999, drift=0.0003, vol=0.01),
        buckets={s: ("BANK" if i % 2 else "IT") for i, s in enumerate(names + rejects)},
        folds=folds,
        models=[
            {"name": f"fake_{f.cutoff}", "cutoff": f.cutoff.isoformat(), "trained_on": 12} for f in folds
        ],
        rules_only=dict.fromkeys(window, names[:3]) if rules_only else None,
        data_quality={"note": "fake"},
        window=WIN,
    )


def _manifest(cid: str) -> dict:
    return pb.build_manifest(
        cid,
        commit="abc1234",
        dirty=False,
        split={"used_49": ["S00"], "extra_training_set": ["E"], "reject_set": ["R0"], "sha256": "f" * 64},
        window=WIN,
        models=[{"name": "fake", "cutoff": "2025-02-02", "trained_on": 12}],
        ledger_row="| row |",
    )


@pytest.fixture(scope="module")
def b1_result() -> dict:
    return pb.evaluate("B1", _fake_inputs(), manifest=_manifest("B1"), random_draws=20, portfolio_draws=3)


def test_a_candidate_run_produces_every_required_section(b1_result):
    r = b1_result
    assert r["manifest"]["candidate"]["id"] == "B1"
    assert set(r["trade_level"]) == {
        "candidate",
        "every_stock",
        "random_5",
        "momentum",
        "nifty_matched",
        "cash",
        "model_only",
        "rules_only",
        "risk_matched_random",
        "mid_small_cap_index",
    }
    assert set(r["portfolio_level"]) == {
        "candidate",
        "random_5",
        "momentum_5",
        "model_only_5",
        "rules_only",
        "nifty_buy_and_hold",
        "cash",
    }
    assert r["trade_level"]["mid_small_cap_index"]["label"] == "NOT TESTABLE"
    assert {"reject_check", "market_types", "checks", "survives", "extra", "edge_vs_momentum"} <= set(r)


def test_every_trade_level_number_carries_its_count_and_period(b1_result):
    for name in ("candidate", "every_stock", "momentum", "model_only", "rules_only"):
        row = b1_result["trade_level"][name]
        assert {"ideas", "days", "period", "edge_low", "edge_high"} <= set(row), name
    assert b1_result["trade_level"]["candidate"]["days"] >= 30


def test_no_check_on_development_data_is_ever_labelled_pass(b1_result):
    labels = {c["label"] for c in b1_result["checks"]}
    assert "PASS" not in labels
    assert labels <= {"NO WARNING (diagnostic)", "FAIL", "INCONCLUSIVE", "NOT TESTABLE"}
    assert '"PASS"' not in json.dumps(b1_result, default=str)


def test_baselines_use_only_the_candidates_days(b1_result):
    cand_days = b1_result["trade_level"]["candidate"]["days"]
    assert b1_result["trade_level"]["every_stock"]["days"] == cand_days
    assert b1_result["trade_level"]["momentum"]["days"] <= cand_days


def test_b1_reports_ideas_per_week(b1_result):
    assert b1_result["extra"]["ideas_per_week"] > 0


def test_rules_only_is_not_testable_when_no_replay_was_given():
    r = pb.evaluate(
        "B2", _fake_inputs(rules_only=False), manifest=_manifest("B2"), random_draws=5, portfolio_draws=1
    )
    assert r["trade_level"]["rules_only"]["label"] == "NOT TESTABLE"
    assert r["portfolio_level"]["rules_only"]["label"] == "NOT TESTABLE"
    assert r["extra"]["leakage_check"] == "clean: no reject-set stock in any training fold"
    assert r["extra"]["data_quality"] == {"note": "fake"}


def test_b3_reports_what_it_skipped_and_how_often_it_trades():
    r = pb.evaluate("B3", _fake_inputs(), manifest=_manifest("B3"), random_draws=5, portfolio_draws=1)
    assert {"losses_avoided", "profits_missed", "trading_days_per_year", "weak_days"} <= set(r["extra"])


def test_too_few_days_with_ideas_makes_every_result_check_inconclusive_and_nothing_survives():
    inp = _fake_inputs()
    first = sorted(next(iter(inp.scores.values())))[:10]
    inp.scores = {s: {d: v for d, v in sc.items() if d in first} for s, sc in inp.scores.items()}
    inp.reject_scores = {
        s: {d: v for d, v in sc.items() if d in first} for s, sc in inp.reject_scores.items()
    }
    r = pb.evaluate("B2", inp, manifest=_manifest("B2"), random_draws=5, portfolio_draws=1)
    result_checks = [c for c in r["checks"] if c["id"] != "mid_small_cap_index"]
    assert {c["label"] for c in result_checks} == {"INCONCLUSIVE"}
    assert r["survives"] is False


def test_the_report_starts_with_the_evidence_manifest(b1_result):
    text = pb.plain_report(b1_result)
    first_section = text.split("\n## ")[1]
    assert first_section.startswith("Evidence manifest")
    for must in ("evidence-defs-v2", "abc1234", "2025-02-03 to 2025-05-30", "15 trading days", "| row |"):
        assert must in first_section, must
    assert "NO WARNING (diagnostic)" in text or "FAIL" in text or "INCONCLUSIVE" in text
    assert "PASS" not in text.replace("PASSED", "")


# ---------------------------------------------------------------- the exposure ledger


def test_the_ledger_row_goes_at_the_end_of_the_local_data_table(tmp_path):
    ledger = tmp_path / "EXPOSURE-LEDGER.md"
    shutil.copy(LEDGER, ledger)
    row = pb.ledger_row("B1", run_day=date(2026, 11, 9), report_name="phase_b_B1.md", window=WIN)
    pb.add_ledger_row(ledger, row, candidate_id="B1")
    text = ledger.read_text(encoding="utf-8")
    local = text.split("## Local data")[1].split("**Conclusion for local data:**")[0]
    assert local.rstrip().splitlines()[-1] == row
    assert "Phase B candidate B1" in row and "2026-11-09" in row


def test_a_second_run_of_the_same_candidate_is_refused_by_the_ledger(tmp_path):
    ledger = tmp_path / "EXPOSURE-LEDGER.md"
    shutil.copy(LEDGER, ledger)
    row = pb.ledger_row("B1", run_day=date(2026, 11, 9), report_name="x.md", window=WIN)
    pb.add_ledger_row(ledger, row, candidate_id="B1")
    with pytest.raises(pb.RealRunRefusedError, match="already"):
        pb.add_ledger_row(ledger, row, candidate_id="B1")


def test_report_shares_and_falls_carry_no_plus_sign(b1_result):
    text = pb.plain_report(b1_result)
    cand = next(ln for ln in text.splitlines() if ln.startswith("| candidate | ") and "%" in ln)
    hit = cand.split("|")[5].strip()
    assert not hit.startswith("+"), cand


# ---------------------------------------------------------------- the real-run path, with fakes only


class _FakeModel:
    def __init__(self, name, trained_on):
        self.name = name
        self.training_symbols = sorted(trained_on)
        self.roc_auc = 0.5


def _fake_world(tmp_path, monkeypatch, *, leak: bool = False):
    """A run_real world: the locked split's real names, synthetic prices, a 2-fold window."""
    from types import SimpleNamespace

    monkeypatch.setattr(pb, "DEV_START", date(2025, 2, 3))
    monkeypatch.setattr(pb, "DEV_END", date(2025, 3, 30))
    split = pb.load_split(SPLIT_DIR)
    days = _weekdays(date(2024, 10, 1), 160)
    rng = random.Random(5)
    calls: list[str] = []

    def load_fn(db, sp):
        calls.append("load")
        names = sp["used_49"][:8]  # a few of the 49 are enough to exercise the path
        rejects = sp["reject_set"][:6]
        return {
            "bars": {s: _walk(days, i) for i, s in enumerate(names)},
            "reject_bars": {s: _walk(days, 50 + i) for i, s in enumerate(rejects)},
            "nifty": _walk(days, 99, vol=0.01),
            "buckets": {},
            "instruments": {s: SimpleNamespace(tradingsymbol=s) for s in names + rejects},
            "data_quality": {"note": "fake"},
        }

    def train_fn(db, cutoff, symbols, cid):
        calls.append(f"train {cutoff}")
        trained = list(symbols) + ([split["reject_set"][0]] if leak else [])
        return _FakeModel(f"phaseb_{cid}_{cutoff}", trained)

    def score_fn(db, inst, model, after):
        return {d: 0.5 + rng.random() / 2 for d in days if d > after}

    def rules_only_fn(db, window_days):
        calls.append("rules-only")
        return dict.fromkeys(window_days, split["used_49"][:2])

    kwargs = {
        "db": None,
        "out_dir": tmp_path / "out",
        "ledger_path": tmp_path / "EXPOSURE-LEDGER.md",
        "split_dir": SPLIT_DIR,
        "today": date(2026, 11, 9),
        "tags": BOTH_TAGS,
        "load_fn": load_fn,
        "train_fn": train_fn,
        "score_fn": score_fn,
        "rules_only_fn": rules_only_fn,
        "commit_fn": lambda: ("feedbee", False),
        "random_draws": 5,
        "portfolio_draws": 1,
    }
    shutil.copy(LEDGER, kwargs["ledger_path"])
    return kwargs, calls


def test_a_real_run_checks_the_guard_before_touching_any_data(tmp_path, monkeypatch):
    kwargs, calls = _fake_world(tmp_path, monkeypatch)
    kwargs["today"] = date(2026, 10, 21)
    with pytest.raises(pb.RealRunRefusedError, match="9 November 2026"):
        pb.run_real("B1", **kwargs)
    assert calls == []
    assert not (tmp_path / "out").exists()


def test_a_real_run_stops_when_a_fold_model_trained_on_a_reject_stock(tmp_path, monkeypatch):
    kwargs, _ = _fake_world(tmp_path, monkeypatch, leak=True)
    before = kwargs["ledger_path"].read_text(encoding="utf-8")
    with pytest.raises(pb.LeakageError):
        pb.run_real("B2", **kwargs)
    assert kwargs["ledger_path"].read_text(encoding="utf-8") == before  # no row, no result
    assert not (tmp_path / "out").exists()


def test_the_ledger_row_is_written_before_any_result_exists(tmp_path, monkeypatch):
    kwargs, _ = _fake_world(tmp_path, monkeypatch)
    real_evaluate = pb.evaluate
    seen = {}

    def spy(cid, inp, **kw):
        seen["row_in_ledger"] = "Phase B candidate B2" in kwargs["ledger_path"].read_text(encoding="utf-8")
        seen["models"] = inp.models
        return real_evaluate(cid, inp, **kw)

    monkeypatch.setattr(pb, "evaluate", spy)
    md, js = pb.run_real("B2", **kwargs)
    assert seen["row_in_ledger"] is True
    assert len(seen["models"]) == 2 and all(m["leakage"] == "clean" for m in seen["models"])
    assert all(m["trained_on"] == 177 for m in seen["models"])
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# Phase B, candidate B2") and "\n## Evidence manifest" in text
    assert "feedbee" in text
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["manifest"]["code_commit"] == "feedbee"
    assert data["trade_level"]["rules_only"].get("label") != "NOT TESTABLE"  # the replay's ideas were used
    assert data["extra"]["data_quality"]["extra_training_set"]["requested"] == 128


def test_each_candidate_runs_once(tmp_path, monkeypatch):
    kwargs, _ = _fake_world(tmp_path, monkeypatch)
    pb.run_real("B1", **kwargs)
    with pytest.raises(pb.RealRunRefusedError, match="already"):
        pb.run_real("B1", **kwargs)


def test_scores_come_only_from_each_fold_own_model_and_days(tmp_path, monkeypatch):
    kwargs, _ = _fake_world(tmp_path, monkeypatch)
    captured = {}
    real_evaluate = pb.evaluate

    def spy(cid, inp, **kw):
        captured["inp"] = inp
        return real_evaluate(cid, inp, **kw)

    monkeypatch.setattr(pb, "evaluate", spy)
    pb.run_real("B3", **kwargs)
    inp = captured["inp"]
    all_days = {d for sc in inp.scores.values() for d in sc}
    assert min(all_days) >= date(2025, 2, 3) and max(all_days) <= date(2025, 3, 30)
    assert set(inp.reject_scores) and not set(inp.reject_scores) & set(inp.scores)


# ---------------------------------------------------------------- dry run and the command line


def test_dry_run_prints_dates_stocks_and_manifest_without_scoring():
    text = pb.dry_run_plan("B2", today=date(2026, 10, 21), tags={"evidence-defs-v1"}, commit=("abc", True))
    assert "DRY RUN" in text and "Nothing was scored" in text
    assert "2025-02-01 to 2026-08-15" in text
    assert "ADANIENT" in text  # one of the 49
    assert "177" in text and "129" in text
    assert "Evidence manifest" in text and "evidence-defs-v2" in text
    assert "Phase B refused" in text  # shows why a real run would not start today
    assert "%" not in text.split("Evidence manifest")[0].replace("30%", "")  # no results anywhere


def test_the_cli_parses_the_phase_b_command():
    from swing_trade_ml.cli import build_parser

    args = build_parser().parse_args(["brain", "phase-b", "--candidate", "B1", "--dry-run"])
    assert (args.brain_command, args.candidate, args.dry_run) == ("phase-b", "B1", True)
    with pytest.raises(SystemExit):
        build_parser().parse_args(["brain", "phase-b", "--candidate", "B4"])


def test_the_cli_dry_run_needs_no_database(monkeypatch, capsys):
    from swing_trade_ml import cli
    from swing_trade_ml.db import session as db_session_module

    def no_db(*a, **k):
        raise AssertionError("dry run must not open the database")

    monkeypatch.setattr(db_session_module, "session_scope", no_db)
    monkeypatch.setattr(db_session_module, "SessionLocal", no_db)
    args = cli.build_parser().parse_args(["brain", "phase-b", "--candidate", "B3", "--dry-run"])
    assert cli.cmd_brain(args) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_the_cli_refuses_a_real_run_now_in_plain_english(monkeypatch, capsys):
    from swing_trade_ml import cli
    from swing_trade_ml.db import session as db_session_module

    def no_db(*a, **k):
        raise AssertionError("a refused run must not open the database")

    monkeypatch.setattr(db_session_module, "session_scope", no_db)
    monkeypatch.setattr(db_session_module, "SessionLocal", no_db)
    monkeypatch.setattr(pb, "ist_today", lambda now=None: date(2026, 10, 21))
    args = cli.build_parser().parse_args(["brain", "phase-b", "--candidate", "B1"])
    assert cli.cmd_brain(args) == 1
    err = capsys.readouterr().err
    assert "Phase B refused" in err and "9 November 2026" in err


# ---------------------------------------------------------------- real loaders, synthetic test database


def test_load_real_reads_bars_nifty_and_instruments_for_the_split(db_session):
    from datetime import UTC, datetime, time
    from zoneinfo import ZoneInfo

    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.market import Candle, Instrument

    ist = ZoneInfo("Asia/Kolkata")
    days = _weekdays(date(2025, 1, 1), 30)
    for k, sym in enumerate(["PBTESTA", "PBTESTR", settings.BENCHMARK_INDEX_SYMBOL]):
        inst = Instrument(instrument_token=997000 + k, tradingsymbol=sym, exchange="NSE", is_active=True)
        db_session.add(inst)
        db_session.flush()
        for d in days:
            ts = datetime.combine(d, time(0, 0), tzinfo=ist).astimezone(UTC)
            db_session.add(
                Candle(
                    instrument_id=inst.id, interval="day", ts=ts, open=10, high=11, low=9, close=10, volume=1
                )
            )
    db_session.flush()
    split = {"used_49": ["PBTESTA"], "reject_set": ["PBTESTR"], "extra_training_set": []}
    data = pb.load_real(db_session, split)
    assert set(data["bars"]) == {"PBTESTA"} and set(data["reject_bars"]) == {"PBTESTR"}
    assert list(data["bars"]["PBTESTA"]["day"]) == days  # IST days
    assert len(data["nifty"]) == 30
    assert set(data["instruments"]) == {"PBTESTA", "PBTESTR"}
    assert data["data_quality"]["scored_49"]["with_bars"] == 1
