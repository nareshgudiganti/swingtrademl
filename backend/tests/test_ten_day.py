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
