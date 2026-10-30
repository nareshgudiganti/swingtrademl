# backend/src/swing_trade_ml/brain/lanes/h05_verdict.py
# ruff: noqa: E501, N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""The frozen verdicts, calculated mechanically from matured outcomes. Pure: no database, no clock.

Two verdicts per cap group, never merged into one:

  SELECTION  - does the ranking pick better trades than the group's average eligible stock on the same days
               (same fills, exits and costs)? Daily edge = counted picks' average net return minus the
               average net return of every eligible stock. A negative baseline is the reference, so
               beating it is a selection result and NOTHING more.
  ECONOMIC   - do the picks make money after the assumed costs, whatever the baseline? Daily series = the
               counted picks' own average net return. A pick set that beats a losing baseline but loses
               money cannot pass this.

The rule is `h05_protocol.RUN_VALUES` (U1-U4). The report calls this ONLY after the owner has accepted the
protocol hash. INCONCLUSIVE is a normal outcome; 15 daily selections are never counted as 15 independent
observations (ranges come from a block bootstrap over signal days).
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R

PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"


def _range(values: Sequence[float]) -> tuple[float, float] | None:
    rule = P.RUN_VALUES["verdict_rule"]
    return R.block_range(values, block=rule["block_days"], level=rule["range_level"])


def _word(rng: tuple[float, float] | None) -> str:
    """PASS: the whole range is above zero. FAIL: the whole range is below zero. Anything else: INCONCLUSIVE."""
    if rng is None:
        return INCONCLUSIVE
    low, high = rng
    return FAIL if high < 0 else PASS if low > 0 else INCONCLUSIVE


def selection_verdict(trade_edge: Sequence[float], label_edge: Sequence[float]) -> dict:
    """Trade edge decides; the endpoint-label edge is a veto only (a label range wholly below zero blocks a PASS)."""
    trade_range, label_range = _range(trade_edge), _range(label_edge)
    word = _word(trade_range)
    vetoed = word == PASS and _word(label_range) == FAIL
    return {
        "verdict": INCONCLUSIVE if vetoed else word,
        "range": trade_range,
        "label_range": label_range,
        "label_veto": vetoed,
    }


def economic_verdict(picks_daily_net: Sequence[float]) -> dict:
    """Absolute: the picks' own daily average net return. No baseline is involved."""
    rng = _range(picks_daily_net)
    return {"verdict": _word(rng), "range": rng, "mean": mean(picks_daily_net)}


def run_decision(
    trade_edge: Sequence[float],
    label_edge: Sequence[float],
    picks_daily_net: Sequence[float],
    shortfall_day_share: float,
    min_days: int | None = None,
) -> dict:
    """One group, one run. Every series is one value per matured signal day, in day order.
    `min_days` exists only so h05_power can test other run lengths; the lane never passes it."""
    need = dict(P.RUN_VALUES["min_evidence_per_group"])
    if min_days is not None:
        need["matured_signal_days"] = min_days
    days = min(len(trade_edge), len(picks_daily_net))
    waiting = {"verdict": INCONCLUSIVE, "range": None}
    base = {"matured_days": days, "selection": waiting, "economic": waiting}
    if days < need["matured_signal_days"]:
        return {**base, "why": f"only {days} matured signal days; {need['matured_signal_days']} needed"}
    if shortfall_day_share > need["max_shortfall_day_share"]:
        return {**base, "why": f"the top 5 was short on {shortfall_day_share:.0%} of days"}
    return {
        **base,
        "selection": selection_verdict(trade_edge, label_edge),
        "economic": economic_verdict(picks_daily_net),
        "why": None,
    }


def _combine(words: Sequence[str], pooled: Sequence[float]) -> dict:
    """U4 for ONE verdict type of ONE group: at least 2 of 3 runs PASS, none FAIL, pooled range above zero."""
    rule = P.RUN_VALUES["combined_three_run_rule"]
    if len(words) < 3:
        return {"verdict": INCONCLUSIVE, "why": f"{len(words)} of 3 runs are final"}
    passing, failing = sum(w == PASS for w in words), sum(w == FAIL for w in words)
    pooled_range = _range(pooled)
    pooled_word = _word(pooled_range)
    if pooled_word == FAIL or failing >= 2:
        verdict = FAIL
    elif passing >= rule["min_runs_passing"] and failing == 0 and pooled_word == PASS:
        verdict = PASS
    else:
        verdict = INCONCLUSIVE
    return {
        "verdict": verdict,
        "runs_passing": passing,
        "runs_failing": failing,
        "pooled_range": pooled_range,
        "why": None,
    }


READING = {
    (PASS, PASS): "The ranking beat the group's average stock AND the picks made money after the assumed costs, in these hypothetical fixed-rule runs.",
    (PASS, INCONCLUSIVE): "The ranking beat the group's average stock, but making money after costs is not shown.",
    (PASS, FAIL): "The ranking beat the group's average stock, but the picks lost money after the assumed costs: relative skill, no economic result.",
    (INCONCLUSIVE, PASS): "Profitable under the stated assumptions; model advantage over the baseline was not established.",
    (FAIL, PASS): "Profitable under the stated assumptions; model advantage over the baseline was not established (the ranking was worse than the baseline).",
    (INCONCLUSIVE, INCONCLUSIVE): "Neither question is answered yet: INCONCLUSIVE.",
    (INCONCLUSIVE, FAIL): "The picks lost money after the assumed costs; the ranking is not shown to beat the average stock.",
    (FAIL, INCONCLUSIVE): "The ranking was worse than the average stock; making money is not shown.",
    (FAIL, FAIL): "The ranking was worse than the average stock and the picks lost money after the assumed costs.",
}


def reading(selection: str, economic: str) -> str:
    """One plain sentence for the pair. There is deliberately no single combined go / no-go word."""
    return READING[(selection, economic)]


def combined_decision(
    runs: Sequence[dict], pooled_trade_edge: Sequence[float], pooled_picks_daily_net: Sequence[float]
) -> dict:
    """One group across its three FINAL runs. Selection and economic are combined separately."""
    selection = _combine([r["selection"]["verdict"] for r in runs], pooled_trade_edge)
    economic = _combine([r["economic"]["verdict"] for r in runs], pooled_picks_daily_net)
    return {
        "selection": selection,
        "economic": economic,
        "reading": reading(selection["verdict"], economic["verdict"]),
    }


def mean(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None
