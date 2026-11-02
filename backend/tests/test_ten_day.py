# ruff: noqa: E501 (long test sentences)
"""td-protocol-v1 (10-day) history tool: the signed rule, costs, folds, guard and isolation."""

from __future__ import annotations

import ast
import itertools
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from swing_trade_ml.brain import ten_day as td
from swing_trade_ml.core.config import settings

REPO = Path(__file__).resolve().parents[2]


def bars_from(rows):
    """rows: (open, high, low, close) per day from the entry day on."""
    d0 = date(2024, 1, 1)
    return pd.DataFrame(
        [
            {"day": d0 + timedelta(days=i), "open": o, "high": h, "low": lo, "close": c}
            for i, (o, h, lo, c) in enumerate(rows)
        ]
    )


def test_the_signed_rule_is_pinned():
    assert (td.HORIZON_BARS, td.TARGET, td.STOP, td.TOP_K, td.BLOCK_DAYS) == (10, 0.06, 0.035, 5, 10)
    assert td.TAG == td.PROTOCOL_VERSION == "td-protocol-v1"
    assert (date(2023, 7, 1), date(2025, 1, 31)) == td.CONFIRMATION


def test_the_protocol_file_is_signed_with_the_chosen_setting():
    text = (REPO / td.SPEC).read_text(encoding="utf-8")
    assert "SIGNED 2026-11-02" in text and "T1-c" in text
    assert "- [ ] T" not in text  # all six decisions ticked


def test_a_day_touching_both_levels_counts_as_the_stop():
    flat = [(100, 100.2, 99.9, 100)] * 9
    out = td.score_trade(bars_from([(100, 107, 95, 100), *flat]))
    assert out.status == "stop" and out.net_return < 0


def test_the_target_pays_about_six_percent_less_costs_and_there_is_no_half_out():
    rows = [(100, 101, 99.5, 100.5), (100.5, 102, 100, 101), (101, 107.5, 100.8, 107)] + [
        (107, 107, 106, 106)
    ] * 7
    out = td.score_trade(bars_from(rows))
    assert out.status == "target" and not out.half_out
    assert 0.04 < out.net_return < 0.06


def test_touching_plus_five_percent_alone_does_not_sell_half():
    rows = [(100, 105.5, 99.5, 101)] + [(101, 102, 100.5, 101)] * 9
    out = td.score_trade(bars_from(rows))
    assert not out.half_out and out.status == "timeout" and out.days == 10


def test_a_trade_that_never_hits_either_level_ends_at_the_close_of_the_tenth_bar():
    out = td.score_trade(bars_from([(100, 101, 99.5, 100.2)] * 12))
    assert out.status == "timeout" and out.days == 10


def test_a_gap_down_through_the_stop_fills_at_the_open():
    rows = [(100, 100.5, 99.5, 100), (92, 93, 90, 91)] + [(91, 92, 90, 91)] * 8
    out = td.score_trade(bars_from(rows))
    assert out.status == "stop" and out.gap and out.net_return < -0.07


def test_fills_cost_ten_basis_points_each_way_in_total():
    assert settings.PAPER_SLIPPAGE_BPS == 5.0
    td.assert_costs_pinned()
    assert td.STRESS.extra_slip == pytest.approx(0.0005)
    assert settings.PAPER_SLIPPAGE_BPS / 10_000 + td.STRESS.extra_slip == pytest.approx(0.001)


def test_a_changed_slippage_setting_refuses_the_run(monkeypatch):
    monkeypatch.setattr(settings, "PAPER_SLIPPAGE_BPS", 9.0)
    with pytest.raises(td.RunRefusedError):
        td.assert_costs_pinned()


# ---------------------------------------------------------------- folds and chronology


def test_each_fold_trains_only_on_what_was_known_before_its_first_test_day():
    folds = td.make_folds(*td.CONFIRMATION)
    assert len(folds) == 21 and folds[0].start == date(2023, 7, 1) and folds[-1].end == date(2025, 1, 31)
    assert all(f.cutoff == f.start - timedelta(days=1) for f in folds)
    assert all(a.end < b.start for a, b in itertools.pairwise(folds))


def synthetic(n_days=420, n_stocks=12):
    start = date(2023, 1, 2)
    days = [start + timedelta(days=i) for i in range(n_days) if (start + timedelta(days=i)).weekday() < 5]
    out = {}
    for s in range(n_stocks):
        px, rows = 100.0, []
        for i, d in enumerate(days):
            drift = 0.002 if (i // 7 + s) % 3 == 0 else -0.001
            o = px
            px = px * (1 + drift)
            rows.append(
                {"day": d, "open": o, "high": max(o, px) * 1.004, "low": min(o, px) * 0.996, "close": px}
            )
        out[f"S{s}"] = pd.DataFrame(rows)
    return out


def test_evaluate_reports_the_rule_the_cutoffs_and_an_honest_verdict():
    bars = synthetic()
    folds = td.make_folds(date(2023, 9, 1), date(2024, 2, 29))
    seen = []

    def model_scores(fold):
        seen.append(fold)
        return {
            s: {d: float(i) for d in df["day"] if fold.start <= d <= fold.end}
            for i, (s, df) in enumerate(bars.items())
        }

    res = td.evaluate(bars, folds, model_scores)
    assert res["protocol"] == "td-protocol-v1"
    assert res["rule"] == {"horizon": 10, "target": 0.06, "stop": 0.035, "half_out": None, "block_days": 10}
    assert [f.cutoff for f in seen] == [f.cutoff for f in folds]
    assert (
        res["costs"] and res["verdict"]["predictive"]["word"] == "insufficient"
    )  # too few folds for an answer
    assert res["pooled"]["model"]["ideas"] > 0 and res["pooled"]["every_stock"]["ideas"] > 0


def test_picks_are_the_best_five_by_score_each_day():
    bars = synthetic()
    folds = td.make_folds(date(2023, 9, 1), date(2023, 10, 5))
    res = td.evaluate(
        bars,
        folds,
        lambda fold: {
            s: {d: float(i) for d in df["day"] if fold.start <= d <= fold.end}
            for i, (s, df) in enumerate(bars.items())
        },
    )
    f0 = res["folds"][0]
    assert f0["model"]["ideas"] <= 5 * f0["days"]


# ---------------------------------------------------------------- guard


def test_a_real_run_is_refused_before_the_tag_exists(tmp_path):
    with pytest.raises(td.RunRefusedError, match="td-protocol-v1"):
        td.check_run_allowed(tmp_path, *td.CONFIRMATION, state=(False, []))


def test_a_changed_frozen_file_or_an_earlier_run_is_refused(tmp_path):
    with pytest.raises(td.RunRefusedError, match="differs from the tagged version"):
        td.check_run_allowed(tmp_path, *td.CONFIRMATION, state=(True, [td.SPEC]))
    md, _js = td.output_paths(tmp_path, *td.CONFIRMATION)
    md.write_text("x", encoding="utf-8")
    with pytest.raises(td.RunRefusedError, match="already exists"):
        td.check_run_allowed(tmp_path, *td.CONFIRMATION, state=(True, []))


def test_a_clean_tagged_first_run_is_allowed(tmp_path):
    td.check_run_allowed(tmp_path, *td.CONFIRMATION, state=(True, []))


def test_the_dry_run_scores_nothing_and_says_whether_a_run_is_allowed(tmp_path):
    text = td.dry_run_plan(*td.CONFIRMATION, state=(False, []), out_dir=tmp_path)
    assert "21 folds" in text and "+6%" in text and "refused" in text and "no half-out" in text.lower()


# ---------------------------------------------------------------- isolation


def test_the_tool_imports_nothing_that_trades_or_serves():
    tree = ast.parse(Path(td.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    banned = (
        "api",
        "workers",
        "brokers",
        "services.execution",
        "services.risk",
        "strategies",
        "brain.service",
        "brain.modules",
    )
    # services.risk is imported only to fix the import order (a bare import, nothing from it is used)
    assert not [m for m in mods - {"swing_trade_ml.services.risk"} if any(b in m for b in banned)], mods


def test_the_tool_never_writes_to_the_database_or_activates_a_model():
    src = Path(td.__file__).read_text(encoding="utf-8")
    assert "auto_activate=False" in src
    assert "db.add(" not in src and "db.commit(" not in src and "activate_model" not in src


# ---------------------------------------------------------------- benchmarks and account replay


@pytest.mark.parametrize(
    "rows",
    [
        [(100, 107, 95, 100)] + [(100, 100.2, 99.9, 100)] * 9,  # stop and target the same day -> stop
        [(100, 101, 99.5, 100.5), (100.5, 102, 100, 101), (101, 107.5, 100.8, 107)]
        + [(107, 107, 106, 106)] * 7,
        [(100, 100.5, 99.5, 100), (92, 93, 90, 91)] + [(91, 92, 90, 91)] * 8,  # gap through the stop
        [(100, 101, 99.5, 100.2)] * 12,  # neither level: close of bar 10
        [(100, 101, 99.5, 100.2), (107, 108, 106, 107.5)]
        + [(107, 108, 106, 107)] * 8,  # gap up through the target
    ],
)
def test_the_scripted_exit_matches_the_scored_trade(rows):
    b = bars_from(rows)
    out, ex = td.score_trade(b), td.trade_exit(b)
    assert ex is not None and ex[2] == {"stop": "stop", "target": "target", "timeout": "timeout"}[out.status]
    assert ex[0] == out.exit_day


def test_an_unfinished_trade_has_no_scripted_exit():
    assert td.trade_exit(bars_from([(100, 101, 99.5, 100.2)] * 4)) is None
    assert td.trade_exit(bars_from([])) is None


def _nifty(bars):
    first = next(iter(bars.values()))
    return first[["day", "open", "high", "low", "close"]].copy()


def test_the_result_carries_every_benchmark_the_protocol_lists():
    bars = synthetic()
    folds = td.make_folds(date(2023, 9, 1), date(2023, 10, 5))

    def scores(fold):
        return {
            s: {d: float(i) for d in df["day"] if fold.start <= d <= fold.end}
            for i, (s, df) in enumerate(bars.items())
        }

    res = td.evaluate(
        bars,
        folds,
        scores,
        nifty=_nifty(bars),
        buckets=dict.fromkeys(bars, "A"),
        random_draws=5,
        account_draws=3,
    )
    b = res["benchmarks"]
    assert b["random_5"]["draws"] == 5 and b["cash"] == {"avg_net": 0.0}
    assert b["nifty_matched"]["ideas"] > 0
    acc = b["accounts"]
    assert set(acc) == {"best_5", "strongest_risers_5", "random_5_accounts", "nifty_held", "cash"}
    assert acc["random_5_accounts"]["runs"] == 3 and acc["cash"]["final_net_return"] == 0.0
    assert res["pooled"]["momentum"]["ideas"] > 0  # the 5 strongest 20-day risers, by trade
    assert "not_yet_reported" not in res


def test_a_missing_nifty_series_is_said_plainly_not_zero():
    bars = synthetic()
    folds = td.make_folds(date(2023, 9, 1), date(2023, 10, 5))
    res = td.evaluate(
        bars,
        folds,
        lambda f: {s: {d: 1.0 for d in df["day"] if f.start <= d <= f.end} for s, df in bars.items()},
        random_draws=2,
    )
    assert str(res["benchmarks"]["nifty_matched"]).startswith("missing")
    text = td.plain_report(res)
    assert "Beside the model" in text and "NIFTY 50 over the same holds: missing" in text
    assert str(res["benchmarks"]["accounts"]).startswith("missing")


def test_the_report_lists_the_benchmarks_and_the_two_questions():
    bars = synthetic()
    folds = td.make_folds(date(2023, 9, 1), date(2023, 10, 5))
    res = td.evaluate(
        bars,
        folds,
        lambda f: {
            s: {d: float(i) for d in df["day"] if f.start <= d <= f.end}
            for i, (s, df) in enumerate(bars.items())
        },
        nifty=_nifty(bars),
        buckets=dict.fromkeys(bars, "A"),
        random_draws=3,
        account_draws=2,
    )
    text = td.plain_report(res)
    for needle in (
        "Random 5 a day",
        "NIFTY 50 over the same holds",
        "Cash",
        "Account replay",
        "never proof",
        "Ranking and trading are different questions",
    ):
        assert needle in text, needle


# ---------------------------------------------------------------- the one real run: guard, ledger, record


def _inst(bars):
    from types import SimpleNamespace

    return [SimpleNamespace(tradingsymbol=s) for s in bars]


def _ledger(tmp_path):
    p = tmp_path / "EXPOSURE-LEDGER.md"
    p.write_text(
        "# Ledger\n\n## Local data (development database)\n\n| a | b |\n|---|---|\n| row | row |\n\n## Other\n",
        encoding="utf-8",
    )
    return p


def test_only_the_confirmation_window_is_allowed(tmp_path):
    with pytest.raises(td.RunRefusedError, match="only on the confirmation window"):
        td.check_run_allowed(tmp_path, date(2024, 1, 1), date(2024, 6, 1), state=(True, []))


def test_any_earlier_report_blocks_a_second_run_whatever_its_window(tmp_path):
    (tmp_path / "ten_day_2024-01-01_2024-06-01.json").write_text("x", encoding="utf-8")
    with pytest.raises(td.RunRefusedError, match="whatever the window"):
        td.check_run_allowed(tmp_path, *td.CONFIRMATION, state=(True, []))


def test_a_dirty_working_tree_is_refused(tmp_path):
    with pytest.raises(td.RunRefusedError, match="uncommitted changes"):
        td.check_run_allowed(tmp_path, *td.CONFIRMATION, state=(True, []), dirty=True)


def test_the_run_writes_the_ledger_row_before_any_model_is_scored_and_keeps_a_run_record(tmp_path):
    bars = synthetic(n_stocks=td.EXPECTED_STOCKS)
    ledger = _ledger(tmp_path)
    seen = {}

    def scores_fn(insts):
        seen["ledger_before_scoring"] = td.LEDGER_MARKER.format(
            first=td.CONFIRMATION[0], last=td.CONFIRMATION[1]
        ) in ledger.read_text(encoding="utf-8")

        def model_scores(fold):
            return {
                s: {d: float(i) for d in df["day"] if fold.start <= d <= fold.end}
                for i, (s, df) in enumerate(bars.items())
            }

        return model_scores

    nifty = next(iter(bars.values()))[["day", "open", "high", "low", "close"]].copy()
    md, js = td.run(
        None,
        first_start=td.CONFIRMATION[0],
        last_end=td.CONFIRMATION[1],
        out_dir=tmp_path / "out",
        ledger_path=ledger,
        state=(True, []),
        collect_fn=lambda: (_inst(bars), bars, nifty),
        scores_fn=scores_fn,
        commit_fn=lambda: "abc123",
        today=date(2026, 11, 6),
        eval_kw={"random_draws": 2, "account_draws": 2},
    )
    assert seen["ledger_before_scoring"] is True
    record = __import__("json").loads(js.read_text(encoding="utf-8"))["manifest"]
    assert (
        record["Code commit"] == "abc123"
        and "never activated" in record["Folds"]
        and "sha256" in record["Universe"]
    )
    assert md.name in ledger.read_text(encoding="utf-8") and md.exists()
    with pytest.raises(td.RunRefusedError, match="already exists"):
        td.run(
            None,
            first_start=td.CONFIRMATION[0],
            last_end=td.CONFIRMATION[1],
            out_dir=tmp_path / "out",
            ledger_path=ledger,
            state=(True, []),
            collect_fn=lambda: (_inst(bars), bars, nifty),
            scores_fn=scores_fn,
        )


def test_a_universe_that_is_not_the_frozen_forty_nine_is_refused_before_anything_is_written(tmp_path):
    bars = synthetic(n_stocks=48)
    ledger = _ledger(tmp_path)
    nifty = next(iter(bars.values()))[["day", "open", "high", "low", "close"]].copy()
    with pytest.raises(td.RunRefusedError, match="froze 49"):
        td.run(
            None,
            first_start=td.CONFIRMATION[0],
            last_end=td.CONFIRMATION[1],
            out_dir=tmp_path / "out",
            ledger_path=ledger,
            state=(True, []),
            collect_fn=lambda: (_inst(bars), bars, nifty),
            scores_fn=lambda insts: None,
        )
    assert "td-protocol-v1 history gate" not in ledger.read_text(encoding="utf-8")
    assert not (tmp_path / "out").exists()


def test_fold_models_train_on_an_explicit_stock_list_and_are_never_activated(monkeypatch):
    seen = {}
    monkeypatch.setattr("swing_trade_ml.ml.train.train_model", lambda db, **kw: seen.update(kw) or "model")
    assert td._train(None, date(2023, 6, 30), ["B", "A"]) == "model"
    assert (
        seen["symbols"] == ["B", "A"]
        and seen["auto_activate"] is False
        and seen["cutoff"] == date(2023, 6, 30)
    )


# ---------------------------------------------------------------- label, limits and the controlled technical rerun

GOOD_NOTE = (
    "Kind: execution_failure\n"
    "Cause: the laptop ran out of disk space while writing a model file in fold 7.\n"
    "Result read: none\n"
    "Same code and rules: yes\n"
)


class BoomError(RuntimeError):
    pass


def _env(tmp_path, n=td.EXPECTED_STOCKS):
    bars = synthetic(n_stocks=n)
    nifty = next(iter(bars.values()))[["day", "open", "high", "low", "close"]].copy()
    ledger = _ledger(tmp_path)

    def good_scores(insts):
        def model_scores(fold):
            return {
                s: {d: float(i) for d in df["day"] if fold.start <= d <= fold.end}
                for i, (s, df) in enumerate(bars.items())
            }

        return model_scores

    def bad_scores(insts):
        def model_scores(fold):
            raise BoomError("disk full")

        return model_scores

    def go(scores_fn, **kw):
        return td.run(
            None,
            first_start=td.CONFIRMATION[0],
            last_end=td.CONFIRMATION[1],
            out_dir=tmp_path / "out",
            ledger_path=ledger,
            state=(True, []),
            collect_fn=lambda: (_inst(bars), bars, nifty),
            scores_fn=scores_fn,
            commit_fn=lambda: "abc123",
            today=date(2026, 11, 6),
            eval_kw={"random_draws": 2, "account_draws": 2},
            **kw,
        )

    def note(name="incident_001.md", text=GOOD_NOTE):
        d = tmp_path / "out" / td.INCIDENT_DIR
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")

    return go, good_scores, bad_scores, ledger, note


def test_the_result_carries_the_survivor_bias_label_and_every_limit(tmp_path):
    go, good, _bad, _ledger_path, _note = _env(tmp_path)
    md, js = go(good)
    text = md.read_text(encoding="utf-8")
    assert "SURVIVOR-BIASED UNIVERSE" in text and "Limits of this test" in text
    assert "No liquidity or limit checks" in text and "never proof" in text
    data = __import__("json").loads(js.read_text(encoding="utf-8"))
    assert data["label"].startswith("HISTORICAL GATE") and len(data["limitations"]) == len(td.LIMITATIONS)


def test_a_crash_leaves_a_ledger_row_but_no_report_and_a_plain_rerun_is_refused(tmp_path):
    go, good, bad, ledger, _note = _env(tmp_path)
    with pytest.raises(BoomError):
        go(bad)
    assert td.LEDGER_MARKER.format(first=td.CONFIRMATION[0], last=td.CONFIRMATION[1]) in ledger.read_text(
        encoding="utf-8"
    )
    assert not list((tmp_path / "out").glob("ten_day_*")) if (tmp_path / "out").exists() else True
    with pytest.raises(td.RunRefusedError, match="--technical-rerun"):
        go(good)


def test_a_technical_rerun_needs_an_incident_note(tmp_path):
    go, good, bad, _ledger_path, _note = _env(tmp_path)
    with pytest.raises(BoomError):
        go(bad)
    with pytest.raises(td.RunRefusedError, match="need 1 incident note"):
        go(good, technical_rerun=True)


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        (GOOD_NOTE.replace("execution_failure", "result_was_bad"), "Kind"),
        (GOOD_NOTE.replace("Result read: none", "Result read: yes"), "Result read: none"),
        (GOOD_NOTE.replace("Same code and rules: yes", "Same code and rules: no"), "Same code and rules"),
        (
            GOOD_NOTE.replace(
                "the laptop ran out of disk space while writing a model file in fold 7.", "oops"
            ),
            "Cause",
        ),
    ],
)
def test_an_incident_note_must_say_what_failed_and_that_no_result_was_read(tmp_path, text, needle):
    go, good, bad, _ledger_path, note = _env(tmp_path)
    with pytest.raises(BoomError):
        go(bad)
    note(text=text)
    with pytest.raises(td.RunRefusedError, match=needle):
        go(good, technical_rerun=True)


def test_a_valid_technical_rerun_is_allowed_once_logged_and_then_a_finished_report_blocks_any_more(tmp_path):
    go, good, bad, ledger, note = _env(tmp_path)
    with pytest.raises(BoomError):
        go(bad)
    note()
    md, js = go(good, technical_rerun=True)
    text = ledger.read_text(encoding="utf-8")
    assert td.RERUN_MARKER.format(n=1, first=td.CONFIRMATION[0], last=td.CONFIRMATION[1]) in text
    assert "incident_001.md" in text and md.exists() and js.exists()
    with pytest.raises(td.RunRefusedError, match="already exists"):
        go(good, technical_rerun=True)  # the valid evaluation is now spent: no tuning, no repeat


def test_technical_reruns_are_capped_at_two(tmp_path):
    go, good, bad, _ledger_path, note = _env(tmp_path)
    with pytest.raises(BoomError):
        go(bad)
    note("incident_001.md")
    with pytest.raises(BoomError):
        go(bad, technical_rerun=True)
    note("incident_002.md")
    with pytest.raises(BoomError):
        go(bad, technical_rerun=True)
    note("incident_003.md")
    with pytest.raises(td.RunRefusedError, match="2 technical reruns are already used"):
        go(good, technical_rerun=True)


def test_a_rerun_flag_with_no_earlier_attempt_is_refused(tmp_path):
    go, good, _bad, _ledger_path, _note = _env(tmp_path)
    with pytest.raises(td.RunRefusedError, match="no earlier attempt"):
        go(good, technical_rerun=True)


def test_the_report_is_written_whole_or_not_at_all_and_nothing_is_printed_before_it(tmp_path, capsys):
    go, good, _bad, _ledger_path, _note = _env(tmp_path)
    go(good)
    assert capsys.readouterr().out == ""
    assert not list((tmp_path / "out").glob("*.tmp"))
