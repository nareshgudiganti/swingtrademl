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


# ---------------------------------------------------------------- 30 calendar days -> trading days


def test_hold_ends_on_day_30_when_it_is_a_trading_day():
    cal = _weekdays(date(2024, 1, 1), 60)
    assert fd.hold_end(date(2024, 1, 2), cal) == date(2024, 2, 1)  # Tue + 30 = Thu


def test_a_weekend_day_30_moves_back_to_the_friday():
    cal = _weekdays(date(2024, 1, 1), 60)
    assert fd.hold_end(date(2024, 1, 4), cal) == date(2024, 2, 2)  # +30 is Saturday 3 Feb


def test_a_holiday_day_30_moves_back_to_the_last_trading_day_before_it():
    cal = _weekdays(date(2023, 12, 1), 80)
    assert REPUBLIC_DAY not in cal
    assert fd.hold_end(date(2023, 12, 27), cal) == date(2024, 1, 25)  # +30 is Republic Day


def test_hold_end_is_unknown_until_the_calendar_reaches_day_30():
    cal = _weekdays(date(2024, 1, 1), 20)
    assert fd.hold_end(date(2024, 1, 2), cal) is None


def test_hold_bars_count_the_stocks_own_bars_through_the_end_day():
    cal = _weekdays(date(2023, 12, 1), 80)
    k = cal.index(date(2023, 12, 27))
    n = fd.hold_bars(cal, k, cal)
    assert cal[k + n - 1] == date(2024, 1, 25)
    assert n == sum(
        1 for d in cal if date(2023, 12, 27) <= d <= date(2024, 1, 25)
    )  # holidays and weekends skipped
    assert 16 <= n <= 22


def test_the_time_stop_is_the_settled_30_calendar_days():
    from swing_trade_ml.services.exit_policy import DEFAULT_TIME_STOP_DAYS

    assert fd.TIME_STOP_DAYS == DEFAULT_TIME_STOP_DAYS == 30


# ---------------------------------------------------------------- outcomes


def test_a_flat_trade_is_sold_at_the_close_of_the_last_trading_day_within_30_days():
    days = _weekdays(date(2023, 12, 20), 70)
    df = _bars(days, [100.0] * len(days))
    decide = date(2023, 12, 26)  # enter at the next open, 27 Dec
    out = fd.outcomes_hold({"A": df}, [decide], days)[("A", decide)]
    assert out.status == "timeout" and out.exit_day == date(2024, 1, 25)
    assert out.days == sum(1 for d in days if date(2023, 12, 27) <= d <= date(2024, 1, 25))
    five = fd.outcomes_day5({"A": df}, [decide])[("A", decide)]
    assert five.status == "timeout" and five.days == 5 and five.exit_day == days[days.index(decide) + 5]


def test_target_and_stop_on_the_same_day_count_as_the_stop():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[3, ["high", "low"]] = [106.0, 94.0]  # both +2% and -4% touched on one day
    out = fd.outcomes_hold({"A": df}, [days[0]], days)[("A", days[0])]
    assert out.status == "stop" and out.exit_day == days[3] and out.net_return < -0.04
    assert fd.outcomes_day5({"A": df}, [days[0]])[("A", days[0])].status == "stop"


def test_the_hold_runs_past_day_5_while_the_day_5_variant_does_not():
    days = _weekdays(date(2024, 3, 1), 40)
    closes = [100.0] * len(days)
    df = _bars(days, closes)
    df.loc[10, "high"] = 103.0  # +3% on the 10th bar after entry: only the 30-day hold sees it
    hold = fd.outcomes_hold({"A": df}, [days[0]], days)[("A", days[0])]
    five = fd.outcomes_day5({"A": df}, [days[0]])[("A", days[0])]
    assert hold.status == "target" and hold.days == 10 and hold.net_return == pytest.approx(0.02, abs=0.004)
    assert five.status == "timeout" and five.days == 5


def test_no_half_out_the_2_percent_target_is_the_whole_exit():
    days = _weekdays(date(2024, 3, 1), 40)
    df = _bars(days, [100.0] * len(days))
    df.loc[2, "high"] = 110.0  # a bar reaching +5% sells everything at +2%, nothing at +5%
    out = fd.outcomes_hold({"A": df}, [days[0]], days)[("A", days[0])]
    assert out.status == "target" and not out.half_out and out.net_return < 0.02


def test_a_trade_whose_30_days_have_not_passed_is_open():
    days = _weekdays(date(2024, 3, 1), 15)
    df = _bars(days, [100.0] * len(days))
    out = fd.outcomes_hold({"A": df}, [days[0]], days)[("A", days[0])]
    assert out.status == "open" and out.net_return is None


def test_breakeven_hit_rate_is_two_in_three_before_costs_and_more_after():
    be = fd.breakeven_hit_rate()
    assert be["before_costs"] == pytest.approx(2 / 3)
    assert be["after_costs"] > be["before_costs"]
    assert be["win_net"] < 0.02 and be["loss_net"] < -0.04


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


def test_an_allowed_run_writes_once_then_refuses(tmp_path):
    inp = _inputs()
    kw = {"random_draws": 5, "portfolio_draws": 1, "stresses": (NORMAL,)}
    first, last = inp.folds[0].start, inp.folds[-1].end
    md, js = fd.run(
        None,
        first_start=first,
        last_end=last,
        out_dir=tmp_path,
        state=(True, []),
        collect_fn=lambda db, a, b: inp,
        commit_fn=lambda: ("abc1234", False),
        **kw,
    )
    assert md.exists() and js.exists() and "abc1234" in md.read_text(encoding="utf-8")
    with pytest.raises(fd.RunRefusedError, match="runs once"):
        fd.run(
            None,
            first_start=first,
            last_end=last,
            out_dir=tmp_path,
            state=(True, []),
            collect_fn=lambda *a: inp,
            **kw,
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


def test_portfolio_sim_without_hold_bars_is_unchanged():
    from swing_trade_ml.brain.portfolio_sim import Pick, simulate

    days = _weekdays(date(2024, 3, 1), 60)
    bars = {"A": _bars(days, [100.0 * 1.003**i for i in range(60)], spread=0.01)}
    picks = [Pick(days[0], "A", 1.0, "x"), Pick(days[20], "A", 1.0, "x")]
    plain = simulate(picks, bars, days, capital=1_000_000.0)
    same = simulate(picks, bars, days, capital=1_000_000.0, hold_bars=lambda s, d: None)
    assert plain.summary() == same.summary() and plain.closed == same.closed


def test_portfolio_sim_hold_bars_sets_each_positions_own_holding_time():
    from swing_trade_ml.brain.portfolio_sim import Pick, simulate

    days = _weekdays(date(2024, 3, 1), 60)
    bars = {"A": _bars(days, [100.0] * 60)}
    r = simulate(
        [Pick(days[0], "A", 1.0, "x")],
        bars,
        days,
        capital=1_000_000.0,
        horizon=fd.NEVER,
        half_out=math.inf,
        hold_bars=lambda s, d: 7,
    )
    assert r.closed[0].status == "timeout" and r.closed[0].exit_day == days[7]


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
