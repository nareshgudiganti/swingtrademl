"""fd-protocol-v1 tool (brain/five_day.py): hold length apart from label length, the prod buy rule as a
pick mode, the decision rule, the tag guard. Synthetic candles only: no real data, no real 5-day result."""

from __future__ import annotations

import math
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from swing_trade_ml.brain import five_day as fd
from swing_trade_ml.brain import walk_forward as wf
from swing_trade_ml.brain.replay_scoring import NORMAL

REPUBLIC_DAY = date(2024, 1, 26)  # a Friday holiday: no bar


def _weekdays(start: date, n: int, skip: set[date] = frozenset({REPUBLIC_DAY})) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5 and d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bars(days, closes, *, volume=500_000.0, spread=0.001) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "day": d,
                "open": c,
                "high": c * (1 + spread),
                "low": c * (1 - spread),
                "close": c,
                "volume": volume,
            }
            for d, c in zip(days, closes, strict=True)
        ]
    )


# ---------------------------------------------------------------- 30 calendar days -> the time-stop day


def test_time_stop_is_day_30_when_it_is_a_trading_day():
    cal = _weekdays(date(2024, 1, 1), 60)
    assert fd.time_stop_day(date(2024, 1, 2), cal) == date(2024, 2, 1)  # Tue + 30 = Thu


def test_a_weekend_day_30_moves_on_to_the_monday():
    cal = _weekdays(date(2024, 1, 1), 60)
    assert fd.time_stop_day(date(2024, 1, 4), cal) == date(2024, 2, 5)  # +30 is Saturday 3 Feb


def test_a_holiday_day_30_moves_on_to_the_next_trading_day():
    cal = _weekdays(date(2023, 12, 1), 80)
    assert REPUBLIC_DAY not in cal
    assert fd.time_stop_day(date(2023, 12, 27), cal) == date(2024, 1, 29)  # +30 is Republic Day (Fri)


def test_time_stop_day_is_unknown_until_the_calendar_reaches_it():
    cal = _weekdays(date(2024, 1, 1), 20)
    assert fd.time_stop_day(date(2024, 1, 2), cal) is None


def test_the_time_stop_and_exit_line_are_prods_code_defaults():
    from swing_trade_ml.core.config import Settings
    from swing_trade_ml.services.exit_policy import DEFAULT_TIME_STOP_DAYS

    assert fd.TIME_STOP_DAYS == DEFAULT_TIME_STOP_DAYS == 30
    assert fd.prod_exit_confidence() == Settings.model_fields["ML_EXIT_CONFIDENCE"].default == 0.35


# ---------------------------------------------------------------- one trade, as prod manages it


def _one(df, decide, *, weak=None, variant="hold", cal=None):
    cal = cal if cal is not None else list(df["day"])
    outs, exits = fd.outcomes_prod({"A": df}, [decide], cal, {"A": weak or set()}, variant=variant)
    return outs[("A", decide)], exits.get(("A", decide))


def test_a_flat_trade_is_sold_at_the_open_of_the_time_stop_day():
    days = _weekdays(date(2023, 12, 20), 70)
    df = _bars(days, [100.0] * len(days))
    decide = date(2023, 12, 26)  # buy at the next open, 27 Dec; +30 = Republic Day -> Mon 29 Jan
    out, ex = _one(df, decide)
    assert out.status == "timeout" and out.exit_day == date(2024, 1, 29)
    assert ex == fd.Exit(date(2024, 1, 29), 100.0, "timeout")  # the open price
    assert out.days == sum(1 for d in days if date(2023, 12, 27) <= d <= date(2024, 1, 29))
    five, _ = _one(df, decide, variant="day5")
    assert five.status == "timeout" and five.days == 5 and five.exit_day == days[days.index(decide) + 5]


def test_target_and_stop_on_the_same_day_count_as_the_stop():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[3, ["high", "low"]] = [106.0, 94.0]  # both +2% and -4% touched on one day
    out, ex = _one(df, days[0])
    assert (
        out.status == "stop" and out.exit_day == days[3] and ex.price == pytest.approx(96.05)
    )  # trailed by the 100.1 highs
    assert _one(df, days[0], variant="day5")[0].status == "stop"


def test_levels_come_from_the_decision_days_close_not_the_fill():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[1, ["open", "high", "low", "close"]] = [101.0, 101.0, 100.5, 101.0]  # buy at 101
    df.loc[2, ["open", "high", "low", "close"]] = [101.0, 102.0, 100.8, 101.0]  # 102 = close 100 x 1.02
    out, ex = _one(df, days[0])
    assert out.status == "target" and ex.price == pytest.approx(102.0) and ex.day == days[2]


def test_the_hold_runs_past_day_5_while_the_day_5_variant_does_not():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[10, "high"] = 103.0  # +3% on the 10th bar after entry: only the 30-day hold sees it
    hold, _ = _one(df, days[0])
    five, _ = _one(df, days[0], variant="day5")
    assert hold.status == "target" and hold.days == 10 and hold.net_return == pytest.approx(0.02, abs=0.004)
    assert five.status == "timeout" and five.days == 5


def test_no_half_out_the_2_percent_target_is_the_whole_exit():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[2, "high"] = 110.0  # a bar reaching +5% sells everything at +2%, nothing at +5%
    out, _ = _one(df, days[0])
    assert out.status == "target" and not out.half_out and out.net_return < 0.02


def test_the_trailing_stop_follows_the_high_from_the_next_day():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[2, ["high", "low", "close"]] = [101.8, 99.0, 101.0]  # highest 101.8: stop rises to ~97.75
    df.loc[3, ["open", "high", "low", "close"]] = [100.0, 100.0, 97.5, 98.0]
    out, ex = _one(df, days[0])
    fill = 100.0 * 1.0005  # 5 bps buy slippage
    assert out.status == "stop" and ex.day == days[3]
    assert ex.price == pytest.approx(101.8 - (fill - 96.0))  # above the first stop of 96


def test_a_raised_trailing_stop_counts_the_same_day_only_when_the_close_is_below_it():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[2, ["high", "low", "close"]] = [101.9, 97.0, 99.0]  # low could be before the high: unknown
    out, _ = _one(df, days[0])
    assert out.exit_day != days[2]
    df.loc[2, "close"] = 97.5  # the close is below the raised stop: it was surely crossed after the high
    out, ex = _one(df, days[0])
    assert out.status == "stop" and ex.day == days[2] and ex.price == pytest.approx(101.9 - (100.05 - 96.0))


def test_a_weak_score_sells_at_the_next_open():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[5, "open"] = 100.5
    out, ex = _one(df, days[0], weak={days[4]})  # the close of day 4 scores at or below 0.35
    assert out.status == "confidence" and ex == fd.Exit(days[5], 100.5, "confidence")
    five, _ = _one(df, days[0], weak={days[4]}, variant="day5")
    assert five.status == "confidence" and five.exit_day == days[5]


def test_a_weak_score_before_the_buy_or_after_the_time_stop_is_ignored():
    days = _weekdays(date(2023, 12, 20), 70)
    df = _bars(days, [100.0] * len(days))
    decide = date(2023, 12, 26)
    out, _ = _one(df, decide, weak={decide, date(2024, 1, 29), date(2024, 2, 5)})
    assert out.status == "timeout" and out.exit_day == date(2024, 1, 29)


def test_the_confidence_exit_uses_only_scores_known_at_each_close():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    scores = {"A": {days[3]: 0.50, days[4]: 0.30, days[6]: 0.10}}
    weak = fd.weak_days(scores)
    assert weak == {"A": {days[4], days[6]}}
    out, _ = _one(df, days[0], weak=weak["A"])
    assert out.exit_day == days[5]  # sold after the first weak close, not later ones


def test_a_trade_whose_time_stop_day_is_not_known_yet_is_open():
    days = _weekdays(date(2024, 3, 1), 15)
    df = _bars(days, [100.0] * len(days))
    out, ex = _one(df, days[0])
    assert out.status == "open" and out.net_return is None and ex is None


def test_breakeven_hit_rate_is_two_in_three_before_costs_and_more_after():
    be = fd.breakeven_hit_rate()
    assert be["before_costs"] == pytest.approx(2 / 3)
    assert be["after_costs"] > be["before_costs"]
    assert be["win_net"] < 0.02 and be["loss_net"] < -0.04


# ---------------------------------------------------------------- the endpoint label (prod models 2, 16, 17)


def test_fold_models_are_trained_on_the_endpoint_question(monkeypatch):
    from swing_trade_ml.brain import five_day_train as fdt

    seen = {}
    monkeypatch.setattr(fdt, "train_endpoint_model", lambda db, **kw: seen.update(kw) or "model")
    assert fd._train(None, date(2023, 6, 30)) == "model"
    assert (seen["horizon_days"], seen["target_return"], seen["cutoff"]) == (5, 0.02, date(2023, 6, 30))
    assert seen["name"] == "fd_h5_20230630"


def _dataset():
    return pd.DataFrame(
        {"target": [1, 0, 1, 0], "forward_return": [0.019, 0.02, -0.05, 0.03], "ts": range(4)}
    )


def test_endpoint_label_is_forward_return_at_least_the_target():
    from swing_trade_ml.brain.five_day_train import endpoint_target

    out = endpoint_target(_dataset(), 0.02)
    assert list(out["target"]) == [0, 1, 0, 1]  # close 5 days later at least +2%; the barrier answer ignored
    assert list(_dataset()["target"]) == [1, 0, 1, 0]


def test_the_wrapper_reuses_v1_dataset_and_split_and_trains_on_the_endpoint_answer(monkeypatch):
    import swing_trade_ml.ml.dataset as dataset_mod
    from swing_trade_ml.brain.five_day_train import train_endpoint_model

    got = {}

    def build(db, **kw):
        got["build"] = kw
        return _dataset()

    def split(df, test_size, embargo_days):
        got["target"], got["split"] = list(df["target"]), (test_size, embargo_days)
        raise RuntimeError("stop")

    monkeypatch.setattr(dataset_mod, "build_training_dataset", build)
    monkeypatch.setattr(dataset_mod, "chronological_split", split)
    with pytest.raises(RuntimeError, match="stop"):
        train_endpoint_model(None, name="t", cutoff=date(2023, 6, 30), horizon_days=5, target_return=0.02)
    assert got["build"]["cutoff"] == date(2023, 6, 30) and got["build"]["horizon_days"] == 5
    assert got["target"] == [0, 1, 0, 1] and got["split"] == (0.2, 5)


def test_v1_training_code_is_untouched():
    import inspect

    from swing_trade_ml.ml.train import train_model

    assert "label_kind" not in inspect.signature(train_model).parameters


# ---------------------------------------------------------------- the prod buy rule


def test_the_buy_rule_is_read_from_the_strategy_not_copied():
    from swing_trade_ml.core.config import Settings
    from swing_trade_ml.strategies.ml_swing import MLSwingStrategy

    r = fd.prod_buy_rule()
    p = MLSwingStrategy.default_params
    assert r.min_confidence == Settings.model_fields["ML_MIN_CONFIDENCE"].default == 0.60
    assert r.bear_boost == p["bear_market_confidence_boost"] == 0.10
    assert (r.min_avg_volume, r.max_volatility, r.falling_knife) == (
        p["min_avg_volume"],
        p["max_volatility"],
        p["falling_knife_return_5d_pct"],
    )
    assert r.min_bars == 260


GOOD = {"bars": 300, "avg_volume": 500_000.0, "daily_vol": 0.02, "atr": 2.0, "ret5": 0.0}


def test_score_line_and_the_bear_market_boost():
    rule = fd.prod_buy_rule()
    assert fd.passes_buy_rule(0.60, GOOD, bear=False, rule=rule)
    assert not fd.passes_buy_rule(0.59, GOOD, bear=False, rule=rule)
    assert not fd.passes_buy_rule(0.65, GOOD, bear=True, rule=rule)  # needs 0.70 in a downtrend
    assert fd.passes_buy_rule(0.71, GOOD, bear=True, rule=rule)


@pytest.mark.parametrize(
    ("key", "value"),
    [("avg_volume", 99_999.0), ("daily_vol", 0.061), ("atr", 0.0), ("ret5", -0.08), ("bars", 259)],
)
def test_each_filter_blocks_a_confident_score(key, value):
    assert not fd.passes_buy_rule(0.95, {**GOOD, key: value}, bear=False, rule=fd.prod_buy_rule())


def test_a_missing_filter_value_blocks_nothing_as_in_the_strategy():
    assert fd.passes_buy_rule(0.95, {**GOOD, "avg_volume": math.nan}, bear=False, rule=fd.prod_buy_rule())


def _nifty(n_up=260, n_down=120):
    days = _weekdays(date(2022, 1, 3), n_up + n_down)
    closes = [100.0 + i for i in range(n_up)] + [100.0 + n_up - 3 * i for i in range(1, n_down + 1)]
    return pd.DataFrame({"day": days, "open": closes, "high": closes, "low": closes, "close": closes})


def test_nifty_downtrend_is_point_in_time():
    nifty = _nifty()
    full = fd.nifty_downtrend(nifty)
    flips = [d for d, v in full.items() if v]
    assert flips, "the falling leg turns the 50-day average below the 200-day one"
    first_bear = flips[0]
    for d in (first_bear - timedelta(days=1), first_bear, first_bear + timedelta(days=10)):
        if d in full:
            cut = fd.nifty_downtrend(nifty[nifty["day"] <= d])
            assert cut[d] == full[d]  # later prices never change a day's answer
    assert not full[nifty["day"].iloc[250]]  # still rising there


def test_stock_filters_use_only_the_past():
    days = _weekdays(date(2023, 1, 2), 300)
    closes = [100.0 + math.sin(i / 3) for i in range(300)]
    df = _bars(days, closes)
    full = fd.stock_filters(df).set_index("day")
    cut = fd.stock_filters(df.iloc[:280]).set_index("day")
    d = days[279]
    pd.testing.assert_series_equal(full.loc[d], cut.loc[d])


def test_buy_rule_picks_best_score_first_and_counts_unknown_nifty_days_as_downtrend():
    nifty = _nifty(n_up=300, n_down=0)  # rising: no downtrend
    days = list(nifty["day"])
    bars = {s: _bars(days, [100.0 + 0.01 * i for i in range(len(days))]) for s in ("A", "B", "C")}
    d, missing = days[280], days[281]
    nifty = nifty[nifty["day"] != missing]
    scores = {"A": {d: 0.62, missing: 0.65}, "B": {d: 0.80, missing: 0.75}, "C": {d: 0.50}}
    picks, counts = fd.buy_rule_picks(scores, bars, nifty, [d, missing])
    assert picks[d] == ["B", "A"]  # C under 0.60
    assert picks[missing] == ["B"]  # NIFTY unknown: the 0.70 line applies, A's 0.65 is out
    assert counts == {"days": 2, "bear_days": 1, "nifty_unknown_days": 1}


def test_buy_rule_ignores_a_stock_with_too_little_history():
    nifty = _nifty(n_up=300, n_down=0)
    days = list(nifty["day"])
    bars = {"A": _bars(days, [100.0] * len(days))}
    picks, _ = fd.buy_rule_picks({"A": {days[200]: 0.9, days[270]: 0.9}}, bars, nifty, [days[200], days[270]])
    assert picks == {days[200]: [], days[270]: ["A"]}  # 201 bars < 260 on the first day


# ---------------------------------------------------------------- the decision rule (section 6)


def _decide(**over):
    base = {
        "skill_eligible": 20,
        "skill_wins": 12,
        "skill_trades": 500,
        "edge_low": 0.001,
        "money_eligible": 15,
        "money_wins": 9,
        "money_trades": 200,
        "money_avg_per_trade": 0.001,
    }
    return fd.decide(**{**base, **over})


def test_both_parts_pass_at_exactly_60_percent_with_the_extra_checks():
    v = _decide()
    assert (v["predictive"]["word"], v["economic"]["word"]) == ("pass", "pass")
    assert "layer 2" in v["reading"]


def test_under_60_percent_or_a_failed_extra_check_fails():
    assert _decide(skill_wins=11)["predictive"]["word"] == "fail"
    assert _decide(edge_low=0.0)["predictive"]["word"] == "fail"
    assert _decide(money_wins=8)["economic"]["word"] == "fail"
    assert _decide(money_avg_per_trade=-0.0001)["economic"]["word"] == "fail"


def test_too_few_folds_or_trades_is_insufficient_never_fail():
    assert _decide(skill_eligible=11, skill_wins=11)["predictive"]["word"] == "insufficient"
    assert _decide(skill_trades=99)["predictive"]["word"] == "insufficient"
    assert _decide(edge_low=None)["predictive"]["word"] == "insufficient"
    assert _decide(money_eligible=11, money_wins=11)["economic"]["word"] == "insufficient"
    assert _decide(money_trades=99)["economic"]["word"] == "insufficient"
    v = _decide(money_trades=99)
    assert v["predictive"]["word"] == "pass"  # the parts are independent


def test_a_fold_needs_10_test_days_and_20_finished_trades():
    assert fd.fold_eligible(10, 20)
    assert not fd.fold_eligible(9, 50)
    assert not fd.fold_eligible(19, 19)


def test_thresholds_are_the_15_day_protocols():
    assert (wf.MIN_FOLDS, wf.MIN_IDEAS, wf.MIN_FOLD_DAYS, wf.MIN_FOLD_IDEAS, wf.FOLDS_SHARE) == (
        12,
        100,
        10,
        20,
        0.6,
    )
    assert (fd.HOLD_BLOCK, fd.DAY5_BLOCK) == (21, 5)


# ---------------------------------------------------------------- a full run on synthetic candles


def _inputs(n_days=420):
    days = _weekdays(date(2023, 1, 2), n_days)
    nc = [100.0 + 0.1 * i for i in range(n_days)]
    nifty = pd.DataFrame({"day": days, "open": nc, "high": nc, "low": nc, "close": nc})
    bars = {}
    for j, sym in enumerate(("UP1", "UP2", "FLAT1", "FLAT2", "DOWN1", "DOWN2")):
        drift = (0.004, 0.003, 0.0, 0.0, -0.003, -0.004)[j]
        closes = [100.0 * (1 + drift) ** i for i in range(n_days)]
        bars[sym] = _bars(days, closes, spread=0.004)
    folds = wf.make_folds(days[300], days[380])
    good = {"UP1": 0.9, "UP2": 0.85, "FLAT1": 0.62, "FLAT2": 0.5, "DOWN1": 0.4, "DOWN2": 0.3}
    scores = {s: {d: good[s] for d in days if folds[0].start <= d <= folds[-1].end} for s in bars}
    return fd.Inputs(
        bars=bars,
        nifty=nifty,
        scores=scores,
        folds=folds,
        models=[{"name": "fake", "cutoff": f.cutoff.isoformat(), "auc": 0.6} for f in folds],
        buckets={s: s for s in bars},
    )


@pytest.fixture(scope="module")
def result():
    return fd.evaluate(_inputs(), random_draws=20, portfolio_draws=3, stresses=(NORMAL,))


def test_full_run_scores_both_pick_modes_per_fold(result):
    assert result["protocol"] == "fd-protocol-v1" and result["horizon"] == "5-day"
    assert not result["counts_for_pass_fail"]  # synthetic dates are not the confirmation sample
    assert len(result["folds"]) >= 3
    for f in result["folds"]:
        assert f["skill"]["model"]["ideas"] > 0
        assert f["skill"]["model"]["avg_net"] > f["skill"]["every_stock"]["avg_net"]
    # the buy rule takes UP1, UP2 and FLAT1 (score >= 0.60, NIFTY rising), never the fallers
    assert result["money"]["model"]["ideas"] > 0
    assert result["money"]["days"]["bear_days"] == 0
    assert result["skill"]["model"]["avg_net"] > result["skill"]["every_stock"]["avg_net"]
    assert result["skill"]["day5"]["note"].startswith("reported only")
    assert result["verdict"]["predictive"]["word"] == "insufficient"  # 3 folds < 12
    assert result["portfolio"]["random_5_accounts"]["runs"] == 3
    assert result["portfolio"]["rules_only"].startswith("missing")


def test_report_labels_every_section_5_day_and_prints_the_protocol(result):
    text = fd.plain_report(result)
    assert "fd-protocol-v1" in text and "Not the confirmation sample" in text
    for line in text.splitlines():
        if line.startswith("#"):
            assert "5-day" in line or line.startswith("## Manifest") or line.startswith("## Limits"), line
    assert "Rules only" in text and "tv7" in text
    assert "break even" in text and "Worst eligible fold" in text and "Worst fall" in text
    assert "never scored with a 5-day rule" in text  # the section 5 sample limit
    assert "D6" in text and "tv22" in text


def test_the_confirmation_dates_are_the_only_pass_or_fail_sample():
    folds = wf.make_folds(*fd.CONFIRMATION)
    assert len(folds) == 21


# ---------------------------------------------------------------- the guard


def test_no_tag_refuses_and_says_why():
    reasons = fd.refusal_reasons(tag_on_head=False, changed_since_tag=[], already_ran=[])
    assert len(reasons) == 1 and "fd-protocol-v1" in reasons[0]
    assert fd.refusal_reasons(tag_on_head=True, changed_since_tag=[], already_ran=[]) == []
    assert fd.refusal_reasons(tag_on_head=True, changed_since_tag=["x.py"], already_ran=["r.md"])


def test_check_refuses_before_any_data_is_read(tmp_path):
    with pytest.raises(fd.RunRefusedError, match="not frozen"):
        fd.check_run_allowed(tmp_path, *fd.CONFIRMATION, state=(False, []))

    def boom(*a, **k):
        raise AssertionError("no data may be read before the guard passes")

    with pytest.raises(fd.RunRefusedError):
        fd.run(
            None,
            first_start=fd.CONFIRMATION[0],
            last_end=fd.CONFIRMATION[1],
            out_dir=tmp_path,
            state=(False, []),
            collect_fn=boom,
        )


def test_cli_refuses_without_the_tag(monkeypatch, capsys):
    monkeypatch.setattr(fd, "git_guard_state", lambda root: (False, []))
    assert fd.main(["--from", "2023-07-01", "--to", "2025-01-31"]) == 2
    assert "refused" in capsys.readouterr().out


def test_walk_forward_cli_hands_the_5_day_protocol_to_five_day(monkeypatch):
    seen = []
    monkeypatch.setattr(fd, "main", lambda argv: seen.append(argv) or 0)
    assert wf.main(["--protocol", "fd-protocol-v1", "--from", "2023-07-01", "--to", "2025-01-31"]) == 0
    assert seen == [["--from", "2023-07-01", "--to", "2025-01-31"]]


LEDGER = """# Exposure ledger

## Local data (development database)

| Dates | Looked at | Used for / decided | Date of use | Source |
|---|---|---|---|---|
| 2023-07-01 to 2025-01-31 | wf | spent | 2026-10-12 | `wf_v1/` |

## Prod
"""


def test_an_allowed_run_logs_the_ledger_first_writes_once_then_refuses(tmp_path):
    inp = _inputs()
    ledger = tmp_path / "LEDGER.md"
    ledger.write_text(LEDGER, encoding="utf-8")
    out = tmp_path / "fd_v1"
    kw = {"random_draws": 5, "portfolio_draws": 1, "stresses": (NORMAL,)}
    first, last = inp.folds[0].start, inp.folds[-1].end
    order = []

    def collect(db, a, b):
        order.append("data")
        return inp

    real_evaluate = fd.evaluate

    def evaluate(i, **k):
        order.append(
            "ledger row" if "fd-protocol-v1 layer 1" in ledger.read_text(encoding="utf-8") else "none"
        )
        return real_evaluate(i, **k)

    import unittest.mock as um

    with um.patch.object(fd, "evaluate", evaluate):
        md, js = fd.run(
            None,
            first_start=first,
            last_end=last,
            out_dir=out,
            ledger_path=ledger,
            state=(True, []),
            collect_fn=collect,
            commit_fn=lambda: ("abc1234", False),
            today=date(2026, 11, 1),
            **kw,
        )
    assert order == ["data", "ledger row"]  # the row is written before any result exists
    assert md.exists() and js.exists() and "abc1234" in md.read_text(encoding="utf-8")
    text = ledger.read_text(encoding="utf-8")
    assert text.index("fd-protocol-v1 layer 1") < text.index("## Prod")  # inside the local-data table
    with pytest.raises(fd.RunRefusedError, match="runs once"):
        fd.run(
            None, first_start=first, last_end=last, out_dir=out, ledger_path=ledger, state=(True, []), **kw
        )
    md.unlink()
    js.unlink()
    with pytest.raises(fd.RunRefusedError, match="ledger"):  # deleting the report does not allow a re-run
        fd.run(
            None, first_start=first, last_end=last, out_dir=out, ledger_path=ledger, state=(True, []), **kw
        )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def test_git_guard_needs_the_tag_in_heads_history_and_unchanged_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    for rel in fd.FROZEN_FILES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("v1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "protocol")
    assert fd.git_guard_state(repo) == (False, [])
    _git(repo, "tag", fd.TAG)
    assert fd.git_guard_state(repo) == (True, [])
    (repo / fd.FROZEN_FILES[0]).write_text("v2\n", encoding="utf-8")
    assert fd.git_guard_state(repo) == (True, [fd.FROZEN_FILES[0]])
    # a tag on a branch HEAD does not contain does not count
    _git(repo, "checkout", "-q", "--orphan", "other")
    _git(repo, "rm", "-r", "-q", "-f", "--cached", ".")
    (repo / "x.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-q", "-m", "other")
    assert fd.git_guard_state(repo)[0] is False


# ---------------------------------------------------------------- the 15-day defaults are untouched


def test_portfolio_sim_exit_plan_scripts_each_exit_and_none_holds_to_the_end():
    from swing_trade_ml.brain.portfolio_sim import Pick, simulate

    days = _weekdays(date(2024, 3, 1), 60)
    bars = {"A": _bars(days, [100.0] * 60), "B": _bars(days, [100.0] * 60)}
    plans = {("A", days[0]): (days[7], 103.0, "target")}
    r = simulate(
        [Pick(days[0], "A", 1.0, "x"), Pick(days[0], "B", 0.5, "y")],
        bars,
        days,
        capital=1_000_000.0,
        exit_plan=lambda s, d: plans.get((s, d)),
    )
    assert [(t.symbol, t.exit_day, t.status) for t in r.closed] == [("A", days[7], "target")]
    assert r.closed[0].net_return > 0.02 and r.still_open == 1  # B has no plan: still held


def test_walk_forward_defaults_are_the_frozen_15_day_rule():
    import inspect

    sig = inspect.signature(wf.run_walk_forward).parameters
    assert (sig["horizon"].default, sig["target"].default, sig["stop"].default) == (15, 0.08, 0.04)
    assert wf.PROTOCOL_VERSION == "wf-protocol-v1" and wf.BLOCK_DAYS == 15


def test_walk_forward_cli_without_protocol_stays_wf(monkeypatch):
    import swing_trade_ml.db.session as session

    called = []
    monkeypatch.setattr(fd, "main", lambda argv: called.append(argv) or 0)

    def wf_path():
        raise RuntimeError("wf path")

    monkeypatch.setattr(session, "SessionLocal", wf_path)
    with pytest.raises(RuntimeError, match="wf path"):
        wf.main(["--from", "2023-07-01", "--to", "2025-01-31"])
    assert called == []
