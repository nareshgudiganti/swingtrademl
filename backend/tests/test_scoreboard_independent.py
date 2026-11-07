# ruff: noqa: E501, N806, N812 (long test sentences; short P / R aliases as in the h05 modules)
"""Independent check of the scoreboard maths. PURE: no database, no network, no .env.

Every "reference" function below is plain Python written from the DEFINITIONS in the signed protocols
(td-protocol-v1 sections 5-6, h05-protocol-v1 U1-U4, evidence-defs-v1, the 15-day scoreboard and
docs/brain/COSTS-CHECK-2026-10.md), NOT copied from the production functions. The production functions are
then run on the same hand-built inputs and must agree.

Coverage map (measure -> production function -> test):
  ranking quality   scoreboard.rank_days/group_stats, selection_lab.daily_ic/top5_measures, h05_rules.rank_group
  benchmark excess  scoreboard.daily_gap, walk_forward.daily_edge, h05_report._daily_edge/group_series,
                    phase_b.random5_trade, h05_rules.random_k_distribution, horizon_report.window_return
  net after costs   replay_scoring.strict_score (15D), ten_day.score_trade (10D), h05_rules.simulate_trade (5D)
  consistency       phase_b.consistency, walk_forward verdict share, selection_lab.r3 (no month rule exists)
  drawdown          lanes.pick_drawdown, portfolio_sim.max_drawdown, phase_b.nifty_buy_and_hold
  not measured      forward_view / _h05_row / summarise_group / nifty_summary / history_for on empty data
Read the findings in docs/brain/scoreboard-independent-check.md.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from swing_trade_ml.api.v1.endpoints import lanes as lane_api
from swing_trade_ml.brain import scoreboard as sb
from swing_trade_ml.brain import selection_lab as sl
from swing_trade_ml.brain import ten_day as td
from swing_trade_ml.brain import walk_forward as wf
from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_report as H
from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes import h05_verdict as V
from swing_trade_ml.brain.replay_scoring import CostStress, strict_score
from swing_trade_ml.core.config import settings
from swing_trade_ml.shadow_lanes import horizon_report as hr

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "docs" / "brain" / "evidence"

# Costs as written in docs/brain/COSTS-CHECK-2026-10.md (basis points of turnover). The 5 bps slippage is the
# settled 15D/10D value; h05 pins its own per-group slippage in the protocol.
SLIP = 5.0 / 1e4
BUY_BPS, SELL_BPS, DP = 11.9 / 1e4, 10.4 / 1e4, 15.93

needs_default_costs = pytest.mark.skipif(
    (
        settings.PAPER_SLIPPAGE_BPS,
        settings.PAPER_TAX_BPS_BUY,
        settings.PAPER_TAX_BPS_SELL,
        settings.PAPER_DP_CHARGE_PER_SELL,
    )
    != (5.0, 11.9, 10.4, 15.93),
    reason="a local setting overrides the pinned paper costs",
)


def approx(x, tol=1e-9):
    return pytest.approx(x, abs=tol)


def bars_df(rows):
    d0 = date(2024, 1, 1)
    return pd.DataFrame(
        [
            {"day": d0 + timedelta(days=i), "open": o, "high": h, "low": lo, "close": c}
            for i, (o, h, lo, c) in enumerate(rows)
        ]
    )


# =====================================================================================================
# (3) NET AFTER COSTS - reference trade simulator from the definition
# =====================================================================================================


def ref_trade(rows, *, horizon, target, stop, half_out, position=40_000.0, extra_slip=0.0, charges_x=1.0):
    """rows: (o,h,l,c) from the entry day. Returns (status, net_return|None, bars_held|None).
    Buy fill = open * (1+5bps) * (1+extra). Shares = position / fill (fractional). Levels from the fill.
    Stop is checked before anything else on a bar; a gap through a level fills at the open. Sells get
    price * (1-5bps) * (1-extra) and pay 10.4 bps of turnover + a flat 15.93 per sell; a half-out is a second sell."""
    if not rows:
        return "open", None, None
    fill = rows[0][0] * (1 + SLIP) * (1 + extra_slip)
    qty = position / fill
    cash_in = fill * qty + charges_x * (fill * qty * BUY_BPS)
    stop_px, tgt_px = fill * (1 - stop), fill * (1 + target)
    half_px = None if half_out is None else fill * (1 + half_out)

    def sell(px, q):
        gross = px * (1 - SLIP) * (1 - extra_slip) * q
        return gross - charges_x * (gross * SELL_BPS + DP)

    held, out, half_done = qty, 0.0, False
    for i, (o, h, lo, _c) in enumerate(rows[:horizon], start=1):
        if lo <= stop_px:
            out += sell(o if o <= stop_px else stop_px, held)
            return "stop", out / cash_in - 1, i
        if half_px is not None and not half_done and h >= half_px:
            out += sell(o if o >= half_px else half_px, qty / 2)
            held, half_done = qty / 2, True
        if h >= tgt_px:
            out += sell(o if o >= tgt_px else tgt_px, held)
            return "target", out / cash_in - 1, i
    if len(rows) < horizon:
        return "open", None, None
    out += sell(rows[horizon - 1][3], held)
    return "timeout", out / cash_in - 1, horizon


FLAT = (100.0, 100.3, 99.8, 100.0)

# name -> rows (entry day first). Each case isolates one rule.
TRADE_CASES = {
    "target_day3": [FLAT, FLAT, (100, 109, 99.9, 108)] + [FLAT] * 12,
    "stop_day2": [FLAT, (100, 100.2, 95.0, 96)] + [FLAT] * 13,
    "gap_down_through_stop": [FLAT, (90.0, 91, 89, 90)] + [FLAT] * 13,
    "gap_up_through_target": [FLAT, (115.0, 116, 114, 115)] + [FLAT] * 13,
    "both_levels_same_bar_is_stop": [FLAT, (100, 112, 90, 100)] + [FLAT] * 13,
    "timeout_flat": [FLAT] * 15,
    "half_out_then_target": [FLAT, (100, 105.6, 99.9, 105), (105, 109, 104, 108)] + [FLAT] * 12,
    "half_out_then_stop": [FLAT, (100, 105.6, 99.9, 105), (100, 100, 94, 95)] + [FLAT] * 12,
    "half_out_then_timeout": [FLAT, (100, 105.6, 99.9, 105)] + [(101, 102, 100.5, 101)] * 13,
    "unfinished_only_10_bars": [FLAT] * 10,
    "unfinished_target_not_hit_yet": [FLAT] * 3,
    "zero_volume_flat_bars_no_trade": [(100.0, 100.0, 100.0, 100.0)] * 15,  # volume is not an input at all
    "single_entry_bar": [FLAT],
}


@needs_default_costs
@pytest.mark.parametrize("name", sorted(TRADE_CASES))
@pytest.mark.parametrize(
    "stress", [CostStress(), CostStress(extra_slip=0.0005), CostStress(charges_x=2.0, extra_slip=0.003)]
)
def test_15_day_strict_score_matches_reference(name, stress):
    rows = TRADE_CASES[name]
    got = strict_score(bars_df(rows), stress=stress)
    status, net, held = ref_trade(
        rows,
        horizon=15,
        target=0.08,
        stop=0.04,
        half_out=0.05,
        extra_slip=stress.extra_slip,
        charges_x=stress.charges_x,
    )
    assert got.status == status
    if net is None:
        assert got.net_return is None and got.days is None  # an unfinished trade has NO number
    else:
        assert got.net_return == approx(net)
        assert got.days == held


@needs_default_costs
@pytest.mark.parametrize("name", sorted(TRADE_CASES))
def test_10_day_score_trade_matches_reference(name):
    rows = TRADE_CASES[name]
    got = td.score_trade(bars_df(rows))
    status, net, held = ref_trade(rows, horizon=10, target=0.06, stop=0.035, half_out=None, extra_slip=0.0005)
    assert got.status == status
    if net is None:
        assert got.net_return is None
    else:
        assert got.net_return == approx(net)
        assert got.days == held


@needs_default_costs
def test_known_answer_flat_timeout_costs_by_hand():
    """Flat price 100 all 15 days: only costs remain. Computed by hand, no code shared with production.
    fill=100.05 ; buy cost = 40000*11.9bps ; sell price = 100*(1-5bps)=99.95 ; sell cost = 10.4bps*gross + 15.93."""
    fill = 100.0 * 1.0005
    qty = 40_000.0 / fill
    cash_in = 40_000.0 * (1 + 11.9e-4)
    gross = 99.95 * qty
    cash_out = gross - gross * 10.4e-4 - 15.93
    expected = cash_out / cash_in - 1
    got = strict_score(bars_df([(100, 100, 100, 100)] * 15))
    assert got.status == "timeout"
    assert got.net_return == approx(expected)
    assert -0.0037 < got.net_return < -0.0035  # COSTS-CHECK / scoreboard audit: "round trip about 0.36%"


@needs_default_costs
def test_trade_exit_mirror_agrees_with_score_trade_on_exit_day_and_reason():
    for name, rows in TRADE_CASES.items():
        df = bars_df(rows)
        ex = td.trade_exit(df)
        out = td.score_trade(df)
        if out.status == "open":
            assert ex is None, name
        else:
            assert ex is not None, name
            assert ex[2] == out.status, name
            assert ex[0] == out.exit_day, name


# ---- h05 5-day shadow trade (own rule: +2% / -4% / 5 sessions, whole shares, group slippage, charges per protocol)

H05_SESSIONS = [date(2026, 10, 5) + timedelta(days=i) for i in range(0, 14)]
H05_SESSIONS = [d for d in H05_SESSIONS if d.weekday() < 5]


def ref_h05(bars_by_session, signal_close, group, stress=False):
    """Independent re-derivation of the h05 shadow trade from the protocol text. bars: list of (o,h,l,c) for sessions 1..5."""
    slip = (P.SLIPPAGE_BPS[group] + (P.STRESS["extra_slip_bps"] if stress else 0)) / 1e4
    times = P.STRESS["charges_x"] if stress else 1.0
    if not bars_by_session:
        return "pending", None
    if bars_by_session[0] is None:
        return "unresolved", None
    fill = bars_by_session[0][0] * (1 + slip)
    qty = math.floor(100_000.0 / fill)
    stop_px, tgt_px = fill * 0.96, fill * 1.02
    exit_px = None
    for _k, bar in enumerate(bars_by_session[:5], start=1):
        if bar is None:
            return "unresolved", None
        o, h, lo, _c = bar
        if lo <= stop_px:
            exit_px, why = (o if o <= stop_px else stop_px), "stop"
            break
        if h >= tgt_px:
            exit_px, why = (o if o >= tgt_px else tgt_px), "target"
            break
    if exit_px is None:
        if len(bars_by_session) < 5:
            return "pending", None
        exit_px, why = bars_by_session[4][3], "expiry"
    xfill = exit_px * (1 - slip)
    buy_cost = times * (qty * fill * 11.9 / 1e4)
    sell_cost = times * (qty * xfill * 10.4 / 1e4 + 15.93)
    return why, (qty * xfill - sell_cost - (qty * fill + buy_cost)) / (qty * fill + buy_cost)


H05_CASES = {
    "target": [(100, 100.5, 99.5, 100), (100, 103.0, 99.9, 102)],
    "stop": [(100, 100.5, 99.5, 100), (100, 100, 94, 95)],
    "both_same_candle": [(100, 110, 90, 100)],
    "gap_through_target": [(100, 100.5, 99.5, 100), (105, 106, 104, 105)],
    "expiry": [(100, 101, 99.5, 100)] * 5,
    "pending_short_window": [(100, 101, 99.5, 100)] * 3,
    "missing_candle_mid_window": [(100, 101, 99.5, 100), None, (100, 101, 99.5, 100)],
}


@pytest.mark.parametrize("group", ["large", "mid", "small"])
@pytest.mark.parametrize("stress", [False, True])
@pytest.mark.parametrize("name", sorted(H05_CASES))
def test_h05_simulate_trade_matches_reference(name, group, stress):
    sess = H05_SESSIONS
    signal = sess[1]
    window = sess[2:7]
    given = H05_CASES[name]
    bars = {d: b for d, b in zip(window, given, strict=False) if b is not None}
    use_sessions = sess[:2] + window[: len(given)] if name == "pending_short_window" else sess
    got = R.simulate_trade(bars, use_sessions, signal, 100.0, group, stress=stress)
    padded = list(given)
    want_status, want_net = ref_h05(padded, 100.0, group, stress)
    assert got.status == want_status
    if want_net is None:
        assert got.net_return is None
    else:
        assert got.net_return == approx(want_net)


# =====================================================================================================
# (1) RANKING QUALITY
# =====================================================================================================


def synthetic_stock_days(seed=3, n_days=30, n_stocks=25):
    rng = random.Random(seed)
    base = date(2025, 3, 3)
    rows = []
    for d in range(n_days):
        day = base + timedelta(days=d)
        stocks = n_stocks
        if d == 4:
            stocks = 19  # one short of the 20 needed: must be dropped
        if d == 5:
            stocks = 20  # exactly 20: must be kept
        for s in range(stocks):
            score = round(rng.random(), 1)  # lots of exact ties
            kind = rng.random()
            if kind < 0.08:
                status, ret = "open", None
            elif kind < 0.12:
                status, ret = "no_entry", None
            else:
                status = rng.choice(["target", "stop", "timeout"])
                ret = rng.uniform(-0.05, 0.08)
            rows.append(
                {
                    "day": day,
                    "symbol": f"S{s:02d}",
                    "score": score,
                    "status": status,
                    "ret": ret,
                    "fold": "f" + str(d // 10),
                }
            )
    return rows


def ref_scoreboard(rows, min_stocks=20):
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r)
    dropped = sum(1 for v in by_day.values() if len(v) < min_stocks)
    groups = {"top5": (1, 5), "r06_10": (6, 10), "r11_15": (11, 15), "r16_20": (16, 20)}
    pooled = {k: [] for k in [*groups, "all"]}
    gaps = {k: [] for k in groups}
    for day in sorted(by_day):
        v = by_day[day]
        if len(v) < min_stocks:
            continue
        order = sorted(v, key=lambda r: (-r["score"], r["symbol"]))
        done_all = [r["ret"] for r in order if r["status"] in ("target", "stop", "timeout")]
        pooled["all"] += done_all
        for k, (lo, hi) in groups.items():
            g = [r["ret"] for r in order[lo - 1 : hi] if r["status"] in ("target", "stop", "timeout")]
            pooled[k] += g
            if g:
                gaps[k].append(sum(g) / len(g) - sum(done_all) / len(done_all))
    return dropped, pooled, gaps


def test_scoreboard_groups_gaps_ties_short_days_and_unfinished_match_reference():
    rows = synthetic_stock_days()
    res = sb.scoreboard(sb.frame(rows))
    dropped, pooled, gaps = ref_scoreboard(rows)
    assert res["days_dropped_too_few_stocks"] == dropped == 1
    assert res["days_ranked"] == 29
    by = {g["group"]: g for g in res["groups"]}
    for k in ("top5", "r06_10", "r11_15", "r16_20", "all"):
        assert by[k]["completed"] == len(pooled[k])
        assert by[k]["avg_net"] == approx(sum(pooled[k]) / len(pooled[k]))
    for k, g in gaps.items():
        assert by[k]["gap_days"] == len(g)
        assert by[k]["avg_gap_vs_all"] == approx(sum(g) / len(g))
    # open / same-day ideas are counted apart and are never inside an average
    allg = by["all"]
    assert allg["signals"] == allg["completed"] + allg["open"] + allg["same_day"]
    assert allg["open"] > 0 and allg["same_day"] > 0
    assert allg["target"] + allg["stop"] + allg["time_limit"] == allg["completed"]


def test_scoreboard_rank_is_repeatable_on_ties_by_symbol():
    rows = [
        {
            "day": date(2025, 1, 1),
            "symbol": f"S{i:02d}",
            "score": 0.5,
            "status": "target",
            "ret": 0.01 * i,
            "fold": "f",
        }
        for i in range(25)
    ]
    ranked, _ = sb.rank_days(sb.frame(rows))
    assert list(ranked["symbol"][:5]) == ["S00", "S01", "S02", "S03", "S04"]
    assert list(ranked["rank"][:3]) == [1, 2, 3]


def test_scoreboard_thin_flag_matches_100_idea_minimum():
    rows = synthetic_stock_days(n_days=3)  # a handful of ideas only
    res = sb.scoreboard(sb.frame(rows))
    assert all(g["thin"] for g in res["groups"][:4]) and sb.MIN_COMPLETED == 100


def test_scoreboard_negative_baseline_gap_is_a_difference_not_a_ratio():
    # every stock loses; the top 5 loses less: gap must be POSITIVE while avg_net stays NEGATIVE
    rows = []
    for i in range(25):
        rows.append(
            {
                "day": date(2025, 1, 1),
                "symbol": f"S{i:02d}",
                "score": 1 - i / 100,
                "status": "stop",
                "ret": -0.04 + (0.02 if i < 5 else 0),
                "fold": "f",
            }
        )
    res = sb.scoreboard(sb.frame(rows))
    top = res["groups"][0]
    assert top["avg_net"] == approx(-0.02) and top["avg_gap_vs_all"] > 0
    assert top["avg_gap_vs_all"] == approx(-0.02 - (-0.02 * 5 / 25 - 0.04 * 20 / 25))


def spearman_ref(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    a, b = ranks(xs), ranks(ys)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den


def test_daily_ic_matches_reference_with_ties_missing_returns_short_and_constant_days():
    rng = random.Random(11)
    days = [date(2025, 5, 1) + timedelta(days=i) for i in range(6)]
    scores, returns = {}, {}
    expect = {}
    for di, d in enumerate(days):
        n = {0: 30, 1: 9, 2: 30, 3: 30, 4: 12, 5: 30}[di]
        xs, ys = [], []
        for i in range(n):
            sym = f"S{i:02d}"
            sc = round(rng.random(), 1) if di != 2 else 0.7  # day 2: every score equal
            ret = (
                rng.uniform(-0.1, 0.1) if di != 3 or i % 3 else None
            )  # day 3: a third of the returns missing
            scores.setdefault(sym, {})[d] = sc
            returns[(sym, d)] = ret
            if ret is not None:
                xs.append(sc)
                ys.append(ret)
        if len(xs) >= 10 and len(set(xs)) > 1 and len(set(ys)) > 1:
            expect[d] = spearman_ref(xs, ys)
    got = sl.daily_ic(scores, returns)
    assert set(got) == set(expect)
    assert days[1] not in got  # 9 stocks: below the 10-stock minimum
    assert days[2] not in got  # all scores equal: undefined, left out (never 0)
    for d in expect:
        assert got[d] == approx(expect[d], 1e-9)


def test_top5_measures_match_reference_and_skip_days_below_ten_stocks():
    rng = random.Random(5)
    days = [date(2025, 6, 2) + timedelta(days=i) for i in range(4)]
    scores, returns = {}, {}
    ref_excess, ref_mean_excess, ref_hits, ref_spread = [], [], [], []
    for di, d in enumerate(days):
        n = 8 if di == 1 else 23
        rows = []
        for i in range(n):
            sym = f"S{i:02d}"
            sc, ret = round(rng.random(), 1), rng.uniform(-0.1, 0.1)
            scores.setdefault(sym, {})[d] = sc
            returns[(sym, d)] = ret
            rows.append((sym, sc, ret))
        if n < 10:
            continue
        rows.sort(key=lambda r: (-r[1], r[0]))
        rets = sorted(r[2] for r in rows)
        top = [r[2] for r in rows[:5]]
        median = (rets[(n - 1) // 2] + rets[n // 2]) / 2
        ref_excess.append(sum(top) / 5 - median)
        ref_mean_excess.append(sum(top) / 5 - sum(rets) / n)
        pos = 0.7 * (n - 1)  # 70th percentile, linear interpolation
        lo = math.floor(pos)
        cut = rets[lo] + (rets[min(lo + 1, n - 1)] - rets[lo]) * (pos - lo)
        ref_hits.append(sum(1 for x in top if x >= cut) / 5)
        k = max(1, round(0.2 * n))
        ref_spread.append(sum(r[2] for r in rows[:k]) / k - sum(r[2] for r in rows[-k:]) / k)
    got = sl.top5_measures(scores, returns)
    assert got["days"] == len(ref_excess) == 3
    assert got["excess"] == approx(sum(ref_excess) / 3)
    assert got["excess_vs_mean"] == approx(sum(ref_mean_excess) / 3)
    assert got["hit_share"] == approx(sum(ref_hits) / 3)
    assert got["spread"] == approx(sum(ref_spread) / 3)


def test_h05_rank_and_top_pick_shortfall_and_ties():
    ranked = R.rank_group([("B", 0.5), ("A", 0.5), ("C", 0.9)])
    assert [r[0] for r in ranked] == ["C", "A", "B"]
    chosen, short = R.select_top(ranked)  # only 3 stocks scored: top-5 cannot be filled
    assert chosen == ["C", "A", "B"] and short == 2


# =====================================================================================================
# (2) BENCHMARK EXCESS: every stock, random-5, NIFTY 50
# =====================================================================================================


def h05row(
    day, sym, score, *, selected=False, net=None, status="target", blocked=False, scored=True, label=None
):
    return {
        "signal_day": day,
        "symbol": sym,
        "group": "large",
        "status": "scored" if scored else "not_scored",
        "not_scored_reason": None if scored else "no_features",
        "score": score,
        "score_production_path": None,
        "selected": selected,
        "repeat_blocked": blocked,
        "trained_on_symbol": True,
        "label_status": "evaluated" if label is not None else "pending",
        "label_hit": label,
        "trade_status": status if net is not None or status in ("pending", "unresolved") else "pending",
        "net_return": net,
        "trade_status_stress": status,
        "net_return_stress": net,
        "ambiguous": False,
        "gap_fill": False,
        "trade_flags": [],
    }


def make_h05_rows():
    """Day A: 12 stocks, 5 picks, a negative baseline and picks that beat it. Day B: only 3 picks (shortfall),
    day C: 9 eligible (below U2 minimum 10 -> not evidence). Day D: picks still pending (no finished pick)."""
    rows, d0 = [], date(2026, 11, 2)
    A, B, C, D = d0, d0 + timedelta(1), d0 + timedelta(2), d0 + timedelta(3)
    for i in range(12):
        rows.append(h05row(A, f"S{i:02d}", 1 - i / 100, selected=i < 5, net=-0.03 + (0.02 if i < 5 else 0)))
    for i in range(12):
        rows.append(h05row(B, f"S{i:02d}", 1 - i / 100, selected=i < 3, net=0.01 * (1 if i < 3 else -1)))
    for i in range(9):
        rows.append(h05row(C, f"S{i:02d}", 1 - i / 100, selected=i < 5, net=0.05))
    for i in range(12):
        rows.append(
            h05row(
                D, f"S{i:02d}", 1 - i / 100, selected=i < 5, net=None if i < 5 else -0.01, status="pending"
            )
        )
    return rows, (A, B, C, D)


def test_h05_group_series_matches_reference_negative_baseline_short_day_unmatured_and_u2_minimum():
    rows, (A, B, C, D) = make_h05_rows()
    s = H.group_series(rows)
    # reference: eligible day = >=10 scored stocks; pool = finished stocks that day (picks included); picks = counted + finished
    edges, picks_net = [], []
    for day in (A, B, C, D):
        day_rows = [r for r in rows if r["signal_day"] == day]
        if len(day_rows) < P.RUN_VALUES["min_evidence_per_group"]["min_eligible_per_day"]:
            continue
        pool = [r["net_return"] for r in day_rows if r["net_return"] is not None]
        mine = [
            r["net_return"]
            for r in day_rows
            if r["selected"] and not r["repeat_blocked"] and r["net_return"] is not None
        ]
        if mine and pool:
            edges.append(sum(mine) / len(mine) - sum(pool) / len(pool))
            picks_net.append(sum(mine) / len(mine))
    assert len(edges) == 2  # A and B only: C is below the per-day minimum, D has no finished pick
    assert s["trade_edge"] == [approx(e) for e in edges]
    assert s["picks_daily_net"] == [approx(x) for x in picks_net]
    # day A: baseline is NEGATIVE (-2.83%); picks lose 1% -> edge is POSITIVE while the picks' own result is NEGATIVE
    assert s["trade_edge"][0] > 0 > s["picks_daily_net"][0]


def test_h05_economic_verdict_cannot_pass_by_beating_a_losing_baseline():
    n = 20
    edge = [0.02 + 0.001 * (i % 3) for i in range(n)]  # picks beat the baseline every day
    net = [-0.01 - 0.001 * (i % 3) for i in range(n)]  # ... and lose money every day
    dec = V.run_decision(edge, edge, net, 0.0, min_days=10)
    assert dec["selection"]["verdict"] == V.PASS
    assert dec["economic"]["verdict"] == V.FAIL


def test_h05_verdict_needs_the_protocol_minimum_days_and_shortfall_limit():
    need = P.RUN_VALUES["min_evidence_per_group"]
    short = [0.01] * (need["matured_signal_days"] - 1)
    dec = V.run_decision(short, short, short, 0.0)
    assert dec["selection"]["verdict"] == V.INCONCLUSIVE and "needed" in dec["why"]
    full = [0.01 + 0.0005 * (i % 4) for i in range(need["matured_signal_days"])]
    assert V.run_decision(full, full, full, need["max_shortfall_day_share"] + 0.01)["why"].startswith(
        "the top 5 was short"
    )


def test_walk_forward_daily_edge_matches_reference():
    d0 = date(2025, 1, 1)
    out = {}
    from swing_trade_ml.brain.replay_scoring import StrictOutcome

    def o(r):
        return StrictOutcome(
            "timeout" if r is not None else "open", r, 15 if r is not None else None, False, False, None
        )

    picks = {d0: ["A", "B", "C"], d0 + timedelta(1): ["A", "B"], d0 + timedelta(2): ["A"]}
    everyone = {d0: ["A", "B", "C", "D"], d0 + timedelta(1): ["A", "B", "D"], d0 + timedelta(2): ["A", "D"]}
    vals = {
        ("A", d0): 0.02,
        ("B", d0): 0.0,
        ("C", d0): -0.02,
        ("D", d0): -0.06,
        ("A", d0 + timedelta(1)): 0.03,
        ("B", d0 + timedelta(1)): None,
        ("D", d0 + timedelta(1)): -0.01,
        ("A", d0 + timedelta(2)): None,
        ("D", d0 + timedelta(2)): -0.02,
    }
    for k, v in vals.items():
        out[k] = o(v)
    got = wf.daily_edge(picks, everyone, out)
    # day0: mean(.02,0,-.02)=0 minus mean(.02,0,-.02,-.06)=-.015 -> .015 ; day1: A=.03 vs mean(.03,-.01)=.01 -> .02 ; day2: picks unfinished -> skipped
    assert got == [approx(0.015), approx(0.02)]


def test_random_5_distribution_centres_on_the_exact_expectation_and_handles_pools_smaller_than_5():
    pools = [[0.04, -0.02, 0.01, 0.0, -0.05, 0.03, 0.02], [0.01, 0.02, 0.03], [-0.01] * 8, []]
    exact_num = sum(min(5, len(p)) * (sum(p) / len(p)) for p in pools if p)
    exact_den = sum(min(5, len(p)) for p in pools if p)
    dist = R.random_k_distribution(pools, draws=4000)
    mean = sum(dist) / len(dist)
    assert mean == pytest.approx(exact_num / exact_den, abs=2e-4)
    assert dist == sorted(dist)


def test_phase_b_random5_trade_centres_on_the_exact_expectation_and_reports_share_beaten():
    from swing_trade_ml.brain import phase_b as pb
    from swing_trade_ml.brain.replay_scoring import StrictOutcome

    d0 = date(2025, 1, 1)
    outcomes, everyone = {}, {}
    pools = {d0: [0.04, -0.02, 0.01, 0.0, -0.05, 0.03, 0.02], d0 + timedelta(1): [0.01, 0.02, 0.03]}
    for d, vals in pools.items():
        everyone[d] = [f"S{i}" for i in range(len(vals))]
        for i, v in enumerate(vals):
            outcomes[(f"S{i}", d)] = StrictOutcome("timeout", v, 15, False, False, None)
    res = pb.random5_trade(sorted(pools), everyone, outcomes, candidate_avg=0.5, draws=3000)
    num = sum(min(5, len(p)) * sum(p) / len(p) for p in pools.values())
    den = sum(min(5, len(p)) for p in pools.values())
    assert res["avg_net_mean"] == pytest.approx(num / den, abs=3e-4)
    assert res["share_beaten"] == 1.0  # a candidate average of +50% beats every draw
    assert res["draws"] == 3000


def test_nifty_window_return_and_summary():
    bars = {date(2026, 1, 5): (100.0, 101.0), date(2026, 1, 12): (103.0, 110.0)}
    assert hr.window_return(bars, date(2026, 1, 5), date(2026, 1, 12)) == approx(
        110 / 100 - 1
    )  # exit CLOSE / entry OPEN
    assert (
        hr.window_return(bars, date(2026, 1, 5), date(2026, 1, 13)) is None
    )  # exit bar missing: not guessed
    assert hr.window_return(bars, None, date(2026, 1, 12)) is None
    s = hr.nifty_summary(
        [(date(2026, 1, 5), date(2026, 1, 12)), (date(2026, 1, 5), date(2026, 1, 99 % 28 + 1))], bars
    )
    assert s["available"] and s["windows"] == 1 and s["mean_return"] == approx(0.10)
    assert hr.next_session(sorted(bars), date(2026, 1, 5)) == date(2026, 1, 12)


def test_horizon_report_never_subtracts_nifty_so_nifty_excess_is_not_available():
    """DOCUMENTED GAP (not a defect of a formula): the report carries NIFTY's own return but no 'edge vs NIFTY' field."""
    nifty = hr.nifty_summary([], {})
    assert set(nifty) == {"available", "mean_return", "windows", "note"}


# =====================================================================================================
# (4) CONSISTENCY
# =====================================================================================================


def test_phase_b_consistency_matches_reference():
    from swing_trade_ml.brain import phase_b as pb

    trades = [("A", 0.30), ("B", 0.02), ("C", 0.02), ("D", 0.02), ("E", -0.01)] + [("F", 0.001)] * 15
    got = pb.consistency(trades)
    rs = sorted((r for _, r in trades), reverse=True)
    drop = math.ceil(0.05 * len(rs))
    assert got["dropped_best"] == drop == 1
    assert got["profitable_without_best_5pct"] == (sum(rs[drop:]) > 0)
    total = sum(rs)
    assert got["largest_stock_share"] == approx(0.30 / total)
    assert pb.consistency([])["label"] == pb.INCONCLUSIVE


def test_fold_share_rule_needs_enough_folds_and_the_share_is_not_a_pass_when_unknown():
    folds = [{"days": 12, "ideas": 25, "mean_ic": 0.02 if i < 7 else -0.01} for i in range(11)]
    assert (
        sl.r3(folds)["state"] == "insufficient" and sl.r3(folds)["passes"] is False
    )  # 11 < 12 eligible folds
    folds = [{"days": 12, "ideas": 25, "mean_ic": 0.02 if i < 8 else -0.01} for i in range(13)]
    r = sl.r3(folds)
    assert r["eligible"] == 13 and r["positive"] == 8 and r["share"] == approx(8 / 13) and r["passes"]


def test_scoreboard_fold_consistency_counts_only_folds_with_20_ideas():
    rows = synthetic_stock_days()
    ranked, _ = sb.rank_days(sb.frame(rows))
    res = sb._folds_top5_beat_all(ranked)
    done = ranked[ranked["status"].isin(sb.DONE)]
    total = won = 0
    for _, f in done.groupby("fold"):
        top = f[f["rank"] <= 5]
        if len(top) >= 20:
            total += 1
            won += top["ret"].mean() > f["ret"].mean()
    assert res == {"folds_with_enough_ideas": total, "top5_beat_all": int(won)}


def test_no_calendar_month_consistency_share_exists_anywhere():
    """td-protocol-v1 section 6 asks for 'share of eligible months beating every stock AND random-5 (>=60%, >=4 months)'.
    No code computes it. This test pins the GAP so that when it is built the test must be replaced by a real one."""
    src = ""
    for p in (REPO / "backend" / "src" / "swing_trade_ml").rglob("*.py"):
        src += p.read_text(encoding="utf-8", errors="ignore")
    for needle in ("eligible_months", "eligible month", "months_beating", "share_of_months"):
        assert needle not in src.lower(), needle


# =====================================================================================================
# (5) DRAWDOWN
# =====================================================================================================


def ref_worst_fall(values, start=0.0):
    peak, worst, cur = start, 0.0, start
    for v in values:
        cur += v
        peak = max(peak, cur)
        worst = min(worst, cur - peak)
    return worst


@pytest.mark.parametrize(
    "nets",
    [[0.01, -0.03, 0.02, -0.04, 0.05], [-0.02, -0.02], [0.01, 0.02], [0.0], [-0.05, 0.10, -0.01]],
)
def test_pick_drawdown_matches_reference_including_a_loss_before_any_gain(nets):
    assert lane_api.pick_drawdown(nets) == approx(ref_worst_fall(nets))
    assert lane_api.pick_drawdown([]) is None


def lane_row(day, rank, net, excess=None, base=None):
    pick = SimpleNamespace(signal_day=day, rank=rank, model_id=1)
    out = (
        None
        if net is None
        else SimpleNamespace(
            net_return=net, excess_return=excess, baseline_net_return=base, status="target", ambiguous=False
        )
    )
    return pick, out


def test_lane_forward_view_matches_reference_on_unordered_rows_and_unfinished_picks():
    d0 = date(2026, 1, 5)
    rows = [
        lane_row(d0 + timedelta(1), 2, -0.04, -0.03, -0.01),
        lane_row(d0, 1, 0.02, 0.01, 0.01),
        lane_row(d0 + timedelta(1), 1, 0.03, 0.02, 0.01),
        lane_row(d0, 2, None),  # unfinished: no outcome row
        lane_row(d0 + timedelta(2), 1, -0.05, 0.00, -0.05),
    ]
    view, sessions, completed = lane_api.forward_view(rows, 15, "large")
    ordered = [0.02, 0.03, -0.04, -0.05]  # signal_day, then rank
    assert (view["picks"], view["completed"], view["open"], sessions, completed) == (5, 4, 1, 3, 4)
    assert view["mean_net_return"] == approx(sum(ordered) / 4)
    assert view["hit_rate"] == approx(0.5)
    assert view["benchmark_excess"] == approx((0.01 + 0.02 - 0.03 + 0.0) / 4)
    assert view["drawdown"] == approx(ref_worst_fall(ordered))
    assert view["sample_warning"] and view["uncertainty"] == {
        "low": None,
        "high": None,
    }  # 4 < 30 picks: no range invented


def test_lane_excess_is_pooled_per_pick_while_h05_edge_is_per_day_these_differ():
    """FINDING: two different 'excess vs every stock' definitions share one UI label. With unequal picks per day the numbers differ."""
    d0 = date(2026, 1, 5)
    # day 1: 1 finished pick with excess +10%; day 2: 4 finished picks each with excess 0
    rows = [lane_row(d0, 1, 0.10, 0.10, 0.0)] + [
        lane_row(d0 + timedelta(1), r, 0.0, 0.0, 0.0) for r in (1, 2, 3, 4)
    ]
    view, *_ = lane_api.forward_view(rows, 15, "large")
    pooled = view["benchmark_excess"]
    per_day = (0.10 + 0.0) / 2
    assert pooled == approx(0.02) and per_day == approx(0.05) and pooled != per_day


# portfolio account drawdown: recompute from the daily equity curve the simulator itself returns
def test_portfolio_sim_max_drawdown_equals_worst_fall_of_its_own_equity_curve():
    from swing_trade_ml.brain.portfolio_sim import Pick, simulate

    d0 = date(2025, 1, 1)
    days = [d0 + timedelta(days=i) for i in range(30)]
    px = [100 + (i if i < 8 else 8 - 2.5 * (i - 8)) for i in range(30)]  # rises, then falls hard
    df = pd.DataFrame(
        {"day": days, "open": px, "high": [p + 0.5 for p in px], "low": [p - 0.5 for p in px], "close": px}
    )
    res = simulate([Pick(days[0], "AAA", 1.0)], {"AAA": df}, days, capital=1_000_000.0)
    peak, worst = 1_000_000.0, 0.0
    for _, eq in res.curve:
        peak = max(peak, eq)
        worst = max(worst, (peak - eq) / peak)
    assert res.max_drawdown == approx(worst)
    assert res.total_return == approx(res.curve[-1][1] / 1_000_000.0 - 1)


def test_nifty_buy_and_hold_drawdown_matches_reference():
    from swing_trade_ml.brain import phase_b as pb

    closes = [100, 104, 110, 99, 95, 101, 90, 96]
    d0 = date(2025, 1, 1)
    ix = pd.DataFrame(
        {
            "day": [d0 + timedelta(i) for i in range(len(closes))],
            "open": [100.0, *closes[:-1]],
            "high": closes,
            "low": closes,
            "close": closes,
        }
    )
    got = pb.nifty_buy_and_hold(ix, list(ix["day"]))
    peak, worst = 1.0, 0.0
    for c in closes:
        v = c / 100.0
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak)
    assert got["max_drawdown"] == approx(worst) and worst == approx((110 - 90) / 110)
    assert pb.nifty_buy_and_hold(ix.iloc[0:0], [d0])["max_drawdown"] is None  # no data -> None, never 0


# =====================================================================================================
# (6) NOT MEASURED: missing / too-short data must say so, never 0
# =====================================================================================================


def test_lane_forward_view_with_no_rows_is_all_not_measured():
    view, sessions, completed = lane_api.forward_view([], 15, "large")
    for key in ("hit_rate", "mean_net_return", "benchmark_excess", "drawdown"):
        assert view[key] is None, key
    assert view["uncertainty"] == {"low": None, "high": None} and (sessions, completed) == (0, 0)
    assert "too early" in view["sample_warning"].lower()


def test_lane_forward_view_only_open_picks_is_not_measured():
    rows = [lane_row(date(2026, 1, 5), r, None) for r in (1, 2, 3)]
    view, *_ = lane_api.forward_view(rows, 15, "large")
    assert (
        view["mean_net_return"] is None
        and view["hit_rate"] is None
        and view["drawdown"] is None
        and view["open"] == 3
    )


def test_history_for_missing_files_is_unavailable_with_none_not_zero(tmp_path):
    for slot in ("10d-large", "15d-large", "15d-midcap"):
        h = lane_api.history_for(slot, root=tmp_path)
        assert h["available"] is False
        assert h["ranking"] == {"mean_ic": None, "lower_bound": None, "days": None}
        assert h["after_cost"] == {"mean_net_return": None, "trades": None}
        assert h["benchmark_excess"] is None and h["drawdown"] is None


def test_history_for_partial_report_leaves_unmeasured_fields_none(tmp_path):
    d = tmp_path / "td_v1"
    d.mkdir()
    (d / "ten_day_x.json").write_text(
        json.dumps({"pooled": {"model": {"avg_net": -0.01, "ideas": 100}}}), encoding="utf-8"
    )
    h = lane_api.history_for("10d-large", root=tmp_path)
    assert h["available"] and h["after_cost"]["mean_net_return"] == -0.01
    assert h["benchmark_excess"] is None  # every_stock missing -> no subtraction from nothing
    assert h["drawdown"] is None


def test_nifty_summary_states_when_there_are_no_bars_or_no_windows():
    a = hr.nifty_summary([(date(2026, 1, 5), date(2026, 1, 9))], {})
    assert a["available"] is False and a["mean_return"] is None and a["windows"] == 0
    b = hr.nifty_summary([], {date(2026, 1, 5): (1.0, 1.0)})
    assert b["available"] and b["mean_return"] is None and b["note"]


class _NoDb:
    def get(self, *_a, **_k):
        return None


def test_h05_row_with_no_run_is_not_measured_and_not_enough_days():
    row = hr._h05_row(_NoDb(), "5d-large", 5, "large", {}, {}, P, {})
    f = row["forward"]
    assert row["verdict"]["state"] == "not_enough_days"
    assert f["net_per_trade"] is None and f["edge_vs_every_stock"] is None and f["hit_rate"] is None
    assert f["matured_days"] == 0 and f["nifty"]["available"] is False


def test_h05_row_below_the_minimum_days_gives_no_reading_even_if_the_numbers_look_good():
    rows, _ = make_h05_rows()
    g = H.summarise_group(rows)
    report = {
        "runs": [{"run_no": 1, "groups": {"large": g}}],
        "protocol_accepted": True,
        "verdict": {"large": {"combined": {"reading": "PASS words"}}},
    }
    row = hr._h05_row(_NoDb(), "5d-large", 5, "large", report, {}, P, {})
    assert row["forward"]["matured_days"] == 2 < P.RUN_VALUES["min_evidence_per_group"]["matured_signal_days"]
    assert row["verdict"]["state"] == "not_enough_days" and "PASS" not in row["verdict"]["text"]


def test_lane_h05_report_with_no_finished_picks_has_none_for_every_mean():
    rows = [
        h05row(date(2026, 11, 2), f"S{i:02d}", 1 - i / 100, selected=i < 5, net=None, status="pending")
        for i in range(12)
    ]
    g = H.summarise_group(rows)
    t = g["shadow_trade"]["counted_picks"]
    assert t["finished"] == 0 and t["mean_net_return"] is None and t["win_rate"] is None
    assert g["shadow_trade"]["daily_edge_vs_baseline"]["mean"] is None
    assert g["shadow_trade"]["daily_edge_vs_baseline"]["note"]  # says why there is no range


@pytest.mark.xfail(
    strict=True,
    reason="DEFECT: h05_rules.random_k_distribution returns 200 x 0.0 when there is no usable pool, so "
    "h05_report.summarise_group shows random_5 range [0.0, 0.0] (a real-looking zero) instead of None / 'Not measured'.",
)
def test_h05_random_five_range_with_no_data_is_none_not_zero():
    g = H.summarise_group([])
    assert g["shadow_trade"]["random_5_same_days_5th_to_95th_percentile"] is None


def test_r3_zero_eligible_folds_is_insufficient_never_a_pass():
    r = sl.r3([])
    assert r["state"] == "insufficient" and r["passes"] is False and r["eligible"] == 0
    # FINDING (not asserted as a defect): share is the number 0.0 here although it is undefined with no folds
    assert r["share"] == 0.0


def test_bootstrap_range_needs_enough_days_else_none():
    assert R.block_range([0.01] * 9, block=5) is None  # fewer than 2 blocks of days -> no range invented
    assert wf.bootstrap_low([0.01] * 19, block=10) is None
    assert sl.block_quantile([0.01] * 29, 0.0125, block=15) is None
    assert lane_api.bootstrap_interval([[0.01]] * 20, 15) is None  # < 30 picks


def test_selection_lab_ranking_verdict_is_insufficient_when_lower_bound_cannot_be_computed():
    ic = {date(2025, 1, 1) + timedelta(i): 0.1 for i in range(5)}
    r = sl.r1(ic)
    assert r["lower_bound"] is None and r["passes"] is False
    assert sl.r1({})["mean_ic"] is None


# =====================================================================================================
# REAL (committed) evidence files: read-only, internal consistency of what the UI would show
# =====================================================================================================

TD_FILE = EVIDENCE / "td_v1" / "ten_day_2023-07-01_2025-01-31.json"
S1_FILE = EVIDENCE / "scoreboard" / "s1_2025-02-01_2026-08-15.json"


@pytest.mark.skipif(not TD_FILE.exists(), reason="evidence file not in this checkout")
def test_real_10d_history_report_is_internally_consistent_with_what_history_for_shows():
    rep = json.loads(TD_FILE.read_text(encoding="utf-8"))
    pooled = rep["pooled"]
    # 5 ideas a day: ideas == 5 * days, and the per-idea mean equals the per-day mean
    assert pooled["model"]["ideas"] == 5 * pooled["model"]["days"]
    assert pooled["model"]["avg_net"] == approx(pooled["model"]["avg_net_by_day"], 1e-12)
    # the UI's 'excess over the group's own average stock' = model minus every stock = the pooled daily edge
    shown = lane_api.history_for("10d-large", root=EVIDENCE)
    assert shown["available"]
    assert shown["benchmark_excess"] == approx(pooled["model"]["avg_net"] - pooled["every_stock"]["avg_net"])
    assert shown["benchmark_excess"] == approx(pooled["model_edge_per_day"], 1e-9)
    nm = rep["benchmarks"]["nifty_matched"]
    assert nm["candidate_minus_nifty"] == approx(nm["candidate_avg_same_ideas"] - nm["avg_net"])
    # the model number and the random-5 range use the same unit (average per idea after costs)
    r5 = rep["benchmarks"]["random_5"]
    assert r5["p5"] <= r5["avg_net_mean"] <= r5["p95"]
    # the drawdown the page shows is the best-5 ACCOUNT replay, not a pick-level number
    assert shown["drawdown"] == rep["benchmarks"]["accounts"]["best_5"]["max_drawdown"]


@pytest.mark.skipif(not S1_FILE.exists(), reason="evidence file not in this checkout")
def test_real_s1_scoreboard_file_is_internally_consistent():
    res = json.loads(S1_FILE.read_text(encoding="utf-8"))["result"]
    by = {g["group"]: g for g in res["groups"]}
    for g in res["groups"]:
        assert g["target"] + g["stop"] + g["time_limit"] == g["completed"]
        assert g["signals"] == g["completed"] + g["open"] + g["same_day"]
    # top-5 minus all, pooled, should be close to the per-day mean gap (equal only when every day has equal size)
    assert by["top5"]["avg_net"] - by["all"]["avg_net"] == pytest.approx(
        by["top5"]["avg_gap_vs_all"], abs=2e-5
    )
    assert by["all"]["signals"] >= 5 * res["days_ranked"]
    assert res["monotone_top_to_r16_20"] == all(
        a["avg_net"] >= b["avg_net"] for a, b in zip(res["groups"][:3], res["groups"][1:4], strict=True)
    )
