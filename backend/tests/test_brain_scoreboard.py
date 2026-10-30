# ruff: noqa: E501 (long lines are test data)
"""S1 / S2 scoreboards (brain/scoreboard.py): ranks and groups, equal-amount percentage returns, open and
same-day ideas kept apart, the trial seal, the protected-sample refusal. No database needed."""

from __future__ import annotations

import json
from datetime import date

import pytest

from swing_trade_ml.brain import scoreboard as sb
from swing_trade_ml.services import trial_seal

DAY = date(2026, 3, 2)


def _day(
    day: date, n: int = 25, ret_of=lambda rank: 0.0, status_of=lambda rank: "timeout", fold="f1"
) -> list[dict]:
    """n stocks; stock k (0-based) has score 1 - k/100, so rank k+1."""
    return [
        {
            "day": day,
            "symbol": f"S{k:02d}",
            "score": 1 - k / 100,
            "status": status_of(k + 1),
            "ret": ret_of(k + 1),
            "fold": fold,
        }
        for k in range(n)
    ]


def test_ranks_follow_the_score_and_the_score_is_kept():
    rows = _day(DAY)
    df = sb.frame(list(reversed(rows)))  # input order must not matter
    ranked, dropped = sb.rank_days(df)
    assert dropped == 0
    assert list(ranked["symbol"][:3]) == ["S00", "S01", "S02"]
    assert list(ranked["rank"][:3]) == [1, 2, 3]
    assert list(ranked["score"][:3]) == [1.0, 0.99, 0.98]  # original scores, untouched


def test_equal_scores_are_ordered_by_symbol_so_ranks_repeat():
    rows = [
        {"day": DAY, "symbol": f"Z{k:02d}", "score": 0.5, "status": "timeout", "ret": 0.0, "fold": "f"}
        for k in range(25)
    ]
    a, _ = sb.rank_days(sb.frame(rows))
    b, _ = sb.rank_days(sb.frame(list(reversed(rows))))
    assert list(a["symbol"]) == list(b["symbol"]) == sorted(r["symbol"] for r in rows)


def test_a_day_with_too_few_scored_stocks_is_dropped_and_counted():
    df = sb.frame(_day(DAY, 25) + _day(date(2026, 3, 3), 12))
    ranked, dropped = sb.rank_days(df)
    assert dropped == 1
    assert set(ranked["day"]) == {DAY}


def test_the_five_groups_hold_the_right_ranks():
    res = sb.scoreboard(sb.frame(_day(DAY, 25)))
    by = {g["group"]: g for g in res["groups"]}
    assert [by[k]["signals"] for k in ("top5", "r06_10", "r11_15", "r16_20", "all")] == [5, 5, 5, 5, 25]
    assert [g["label"] for g in res["groups"]] == [
        "Top 5",
        "Ranks 6-10",
        "Ranks 11-15",
        "Ranks 16-20",
        "All eligible stocks",
    ]


def test_groups_are_compared_in_percent_so_size_does_not_decide():
    # every idea returns +2% regardless of rank: the 25-stock group and the 5-stock group must average the same
    res = sb.scoreboard(sb.frame(_day(DAY, 25, ret_of=lambda r: 0.02)))
    avgs = {g["group"]: g["avg_net"] for g in res["groups"]}
    assert all(v == pytest.approx(0.02) for v in avgs.values())
    assert all(g["avg_gap_vs_all"] in (0.0, pytest.approx(0.0)) for g in res["groups"])


def test_open_and_same_day_ideas_are_counted_but_never_averaged():
    rows = _day(
        DAY,
        25,
        ret_of=lambda r: 0.05 if r <= 3 else None,
        status_of=lambda r: (
            "target" if r <= 3 else ("open" if r == 4 else ("no_entry" if r == 5 else "stop"))
        ),
    )
    # ranks 6+ are 'stop' with no return: give them one so the averages are defined
    for r in rows:
        if r["status"] == "stop":
            r["ret"] = -0.04
    top = {g["group"]: g for g in sb.scoreboard(sb.frame(rows))["groups"]}["top5"]
    assert (top["signals"], top["completed"], top["open"], top["same_day"]) == (5, 3, 1, 1)
    assert top["target"] == 3 and top["stop"] == 0 and top["time_limit"] == 0
    assert top["avg_net"] == pytest.approx(0.05)  # only the 3 completed ideas


def test_outcome_counts_are_split_into_target_stop_and_time_limit():
    status = {1: "target", 2: "stop", 3: "timeout", 4: "timeout", 5: "target"}
    rows = _day(DAY, 25, ret_of=lambda r: 0.01, status_of=lambda r: status.get(r, "timeout"))
    top = {g["group"]: g for g in sb.scoreboard(sb.frame(rows))["groups"]}["top5"]
    assert (top["target"], top["stop"], top["time_limit"]) == (2, 1, 2)


def test_a_group_that_really_does_better_shows_a_positive_gap():
    days = [date(2026, 3, 2 + i) for i in range(12)]
    rows = [r for d in days for r in _day(d, 25, ret_of=lambda r: 0.03 if r <= 5 else -0.01)]
    top = {g["group"]: g for g in sb.scoreboard(sb.frame(rows))["groups"]}["top5"]
    assert top["avg_gap_vs_all"] > 0
    assert top["avg_net"] == pytest.approx(0.03)


def test_a_thin_group_is_flagged():
    top = {g["group"]: g for g in sb.scoreboard(sb.frame(_day(DAY, 25)))["groups"]}["top5"]
    assert top["thin"] is True  # 5 completed ideas, well under 100


def test_the_window_refuses_the_protected_sample_and_the_sealed_days():
    with pytest.raises(ValueError, match="protected"):
        sb.check_window(date(2024, 1, 1), date(2024, 6, 1))
    with pytest.raises(ValueError, match="sealed"):
        sb.check_window(date(2026, 9, 1), trial_seal.SEALED_FROM)
    sb.check_window(date(2025, 2, 1), date(2026, 8, 15))  # the development window is fine


# ------------------------------------------------------------------------------------- S2


def _idea(
    day: date,
    word: str,
    down_from: str | None,
    reason: str | None,
    ret: float | None,
    status: str | None = "target",
    sym="AAA",
):
    return {
        "day": day,
        "symbol": sym,
        "word": word,
        "downgraded_from": down_from,
        "downgrade_reason": reason,
        "score": 0.7,
        "score_source": "model",
        "status": status,
        "ret": ret,
    }


def test_trade_intent_classification():
    assert sb.classify_idea("TRADE", None) == "approved"
    assert sb.classify_idea("WATCH", "TRADE") == "blocked"
    assert sb.classify_idea("WAIT", None) is None
    assert sb.classify_idea("AVOID", "WATCH") is None


def test_reasons_are_grouped_and_replay_artifacts_are_named():
    assert "artifact" in sb.reason_bucket(
        "Good idea, but the risk check said no: Risk checks use today's account"
    )
    assert sb.reason_bucket("The risk check has not approved this trade.") == "risk check said no"
    assert (
        sb.reason_bucket("Results on 23 Oct: the brain avoids new trades 5 trading days before results")
        == "results-day rule"
    )
    assert sb.reason_bucket(None).startswith("other")


def test_s2_scores_approved_and_blocked_apart_and_says_descriptive():
    d0 = date(2026, 8, 3)
    ideas = [
        _idea(d0, "TRADE", None, None, 0.08),
        _idea(d0, "TRADE", None, None, -0.04, "stop", "BBB"),
        _idea(d0, "WATCH", "TRADE", "The risk check has not approved this trade.", 0.02, "timeout", "CCC"),
        _idea(d0, "WAIT", None, None, 0.5, "target", "DDD"),  # not a trade intent: ignored
    ]
    r = sb.s2_report(ideas)
    assert r["descriptive_only"] is True and "not by itself show" in r["note"]
    assert r["groups"]["approved"]["completed"] == 2
    assert r["groups"]["approved"]["avg_net"] == pytest.approx(0.02)
    assert r["groups"]["blocked"]["completed"] == 1 and r["groups"]["blocked"]["avg_net"] == pytest.approx(
        0.02
    )
    assert r["groups"]["approved"]["sources"] == {"model": 2}


def test_s2_sealed_days_are_counts_only_nothing_leaks_by_total_or_filter():
    planted = 0.7316492
    sealed = trial_seal.SEALED_FROM
    ideas = [
        _idea(
            date(2026, 8, 3), "WATCH", "TRADE", "The risk check has not approved this trade.", 0.01, "timeout"
        ),
        _idea(sealed, "TRADE", None, None, planted, "target", "SEA"),
        _idea(sealed, "WATCH", "TRADE", "Good idea, but the risk check said no: x", planted, "target", "SEB"),
    ]
    r = sb.s2_report(ideas)
    assert r["sealed_days_counts_only"] == {"approved": 1, "blocked": 1}
    assert r["groups"]["approved"]["signals"] == 0 and r["groups"]["approved"]["avg_net"] is None
    assert r["groups"]["blocked"]["signals"] == 1  # the unsealed day only
    text = json.dumps(r, default=str) + sb.plain_report_s2(r, (date(2026, 7, 13), sealed))
    assert "0.7316" not in text and "73.16" not in text
    assert "Sealed trial days (counts only)" in text and "Descriptive only" in text


def test_audit_flags_name_every_open_dependency():
    assert {a["id"] for a in sb.AUDIT_FLAGS} >= {8, 9, 10, 11}
    s1 = sb.plain_report_s1(
        sb.scoreboard(sb.frame(_day(DAY, 25))),
        {
            "first_start": "2026-01-01",
            "last_end": "2026-02-01",
            "folds": 1,
            "integrity": {
                "stocks_in_universe": 25,
                "duplicate_stock_days": 0,
                "folds_whose_model_cutoff_is_missing_or_not_before_the_fold": [],
                "survivorship": "x",
            },
        },
    )
    assert "Audit items these numbers depend on" in s1 and "B1 stays score >= 0.80" in s1
