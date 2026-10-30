# backend/src/swing_trade_ml/brain/lanes/h05_power.py
# ruff: noqa: E501, N812 (short P / R / V import aliases and long report sentences, as in brain/five_day.py)
"""Reproducible support for the h05 run length and for the false-pass rate.

Question answered: if the three runs were run with RANDOM picks (no skill), how often would the frozen
decision procedure still say PASS - and how often would it say PASS for a pick set with a real edge?

It uses the EXACT procedure of the lane, not a re-implementation of it: `h05_verdict.run_decision` and
`combined_decision`, which call `h05_rules.block_range`. What it simulates around them:

  * outcomes: every eligible stock-day of the local history gets the REAL lane trade (`simulate_trade`: entry
    next open, +2% / -4% / 5 sessions, the frozen group slippage and costs) and the REAL endpoint label;
  * picks: random 5 per group per day (optionally 'sticky': a pick stays with probability s, as a smooth model
    score would keep it), with the lane's repeat blocking (a stock counts once per 5 sessions);
  * dependence across DATES: either real consecutive history windows ('history') or a stationary bootstrap of
    whole days in blocks of about `block_mean` sessions ('bootstrap'), so overlapping 5-day trades stay
    overlapping;
  * dependence across GROUPS: a day is one cross-section for all three groups, so a market-wide good or bad
    day hits all groups together and 'any group passes' is not a product of independent groups;
  * dependence across RUNS: the three runs are consecutive slices of ONE path, pooled in order;
  * missing days: each session is dropped with probability q for the whole lane (a job that did not run), never
    made up, and the run is not extended;
  * a day with fewer than 10 eligible stocks in a group is no evidence for that group.

Not simulated: a real model's picks (persistence is approximated by `stickiness`), the endpoint-label edge under
an alternative (it is left at zero, so power is conservative: the label veto can still bite), liquidity.
The history is the local candle database (about five years); only a handful of non-overlapping 180-session
windows exist in it, which is why 'bootstrap' is reported as well, and why both are estimates, not guarantees.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes import h05_verdict as V
from swing_trade_ml.db.models.market import Instrument

RESOLVED = ("target", "stop", "expiry")
EMPTY = (np.empty(0, dtype=np.int32), np.empty(0), np.empty(0))


@dataclass(frozen=True)
class Table:
    """Per market session and group: (stock ids, trade net returns, label hits with NaN where not evaluated)."""

    sessions: list[date]
    days: list[dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]]

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for d, day in zip(self.sessions, self.days, strict=True):
            h.update(str(d).encode())
            for g in P.GROUPS:
                ids, net, hit = day.get(g, EMPTY)
                h.update(g.encode() + ids.tobytes() + np.round(net, 10).tobytes() + np.nan_to_num(hit, nan=-1).tobytes())
        return h.hexdigest()


def table_from_rows(sessions: list[date], rows: list[tuple[int, str, int, float, float]]) -> Table:
    """rows: (session position, group, stock id, net return, label hit or NaN)."""
    by: dict[tuple[int, str], list] = defaultdict(list)
    for pos, group, sid, net, hit in rows:
        by[(pos, group)].append((sid, net, hit))
    days = []
    for pos in range(len(sessions)):
        day = {}
        for g in P.GROUPS:
            items = sorted(by.get((pos, g), []))
            if items:
                day[g] = (
                    np.array([i[0] for i in items], dtype=np.int32),
                    np.array([i[1] for i in items], dtype=float),
                    np.array([i[2] for i in items], dtype=float),
                )
        days.append(day)
    return Table(sessions, days)


def build_table(db: Session) -> Table:
    """The real lane outcome of every eligible stock-day in the local history (needs the database)."""
    from swing_trade_ml.brain.lanes.h05_models import build_universe
    from swing_trade_ml.brain.lanes.h05_service import _bars, market_sessions

    sessions = market_sessions(db)
    universe, _, _ = build_universe(db)
    rows: list[tuple[int, str, int, float, float]] = []
    pos_of = {d: i for i, d in enumerate(sessions)}
    for sid, (symbol, group) in enumerate(sorted(universe.items())):
        inst = db.scalar(select(Instrument).where(Instrument.exchange == "NSE", Instrument.tradingsymbol == symbol))
        if inst is None:
            continue
        bars = _bars(db, inst.id, date.min)
        closes = {d: b[3] for d, b in bars.items()}
        for k, day in enumerate(sorted(bars), start=1):
            if k < P.MIN_BARS or day not in pos_of:
                continue  # eligibility: enough history and a market session
            trade = R.simulate_trade(bars, sessions, day, bars[day][3], group)
            if trade.status not in RESOLVED or trade.net_return is None:
                continue
            label = R.endpoint_outcome(closes, sessions, day)
            hit = float(label.label) if label.status == "evaluated" else float("nan")
            rows.append((pos_of[day], group, sid, trade.net_return, hit))
    return table_from_rows(sessions, rows)


# ------------------------------------------------------------------ one simulated path


def _group_day_series(
    rng: np.random.Generator,
    day: tuple[np.ndarray, np.ndarray, np.ndarray],
    pos: int,
    last_counted: dict[int, int],
    prev: list[int],
    stickiness: float,
    delta: float,
):
    """Random (or sticky) top 5 for one group-day -> ((trade edge, label edge or None, picks' net) or None, picks)."""
    ids, net, hit = day
    if len(ids) < P.RUN_VALUES["min_evidence_per_group"]["min_eligible_per_day"]:
        return None, prev
    where = {int(s): j for j, s in enumerate(ids)}
    chosen: list[int] = []
    for s in prev:
        if s in where and s not in chosen and rng.random() < stickiness:
            chosen.append(s)
    rest = [int(s) for s in ids if int(s) not in chosen]
    need = P.TOP_K - len(chosen)
    if need > 0 and rest:
        chosen += [rest[i] for i in rng.choice(len(rest), size=min(need, len(rest)), replace=False)]
    counted = [s for s in chosen if not (s in last_counted and pos - last_counted[s] < P.TRADE_SESSIONS)]
    for s in counted:
        last_counted[s] = pos
    if not counted:
        return None, chosen
    cj = [where[s] for s in counted]
    picks_net = float(net[cj].mean()) + delta
    edge = picks_net - float(net.mean())
    evaluated = ~np.isnan(hit)
    pick_hits = hit[cj][~np.isnan(hit[cj])]
    label_edge = float(pick_hits.mean() - hit[evaluated].mean()) if pick_hits.size and evaluated.any() else None
    return (edge, label_edge, picks_net), chosen


def simulate_path(
    rng: np.random.Generator,
    table: Table,
    positions: list[int],
    run_length: int,
    delta: float,
    missing: float,
    stickiness: float,
    min_days: int | None = None,
) -> dict:
    """Three consecutive runs over `positions` (3 * run_length sessions). Returns every group's verdicts."""
    series = {g: [[] for _ in range(3)] for g in P.GROUPS}  # per group, per run: (edge, label edge, picks net) per day
    last: dict[str, dict[int, int]] = {g: {} for g in P.GROUPS}
    prev: dict[str, list[int]] = {g: [] for g in P.GROUPS}
    for i, tpos in enumerate(positions):
        if missing and rng.random() < missing:
            continue  # the lane recorded nothing this session; it is not made up
        run = min(i // run_length, 2)
        for g in P.GROUPS:
            day = table.days[tpos].get(g)
            if day is None:
                continue
            res, prev[g] = _group_day_series(rng, day, i, last[g], prev[g], stickiness, delta)
            if res is not None:
                series[g][run].append(res)
    out = {}
    for g in P.GROUPS:
        runs, pooled_edge, pooled_net = [], [], []
        for chunk in series[g]:
            edge = [c[0] for c in chunk]
            label = [c[1] for c in chunk if c[1] is not None]
            net = [c[2] for c in chunk]
            runs.append(V.run_decision(edge, label, net, 0.0, min_days=min_days))
            pooled_edge += edge
            pooled_net += net
        out[g] = {"runs": runs, "combined": V.combined_decision(runs, pooled_edge, pooled_net)}
    return out


def history_positions(rng: np.random.Generator, total: int, length: int) -> list[int]:
    """A real consecutive window of the history."""
    start = int(rng.integers(0, total - length + 1))
    return list(range(start, start + length))


def bootstrap_positions(rng: np.random.Generator, total: int, length: int, block_mean: int) -> list[int]:
    """Stationary bootstrap of whole days: blocks of about `block_mean` consecutive sessions, so overlapping
    5-day trades stay overlapping and every group keeps its own same-day cross-section."""
    out: list[int] = []
    pos = int(rng.integers(0, total))
    while len(out) < length:
        out.append(pos)
        pos = int(rng.integers(0, total)) if rng.random() < 1.0 / block_mean else (pos + 1) % total
    return out


# ------------------------------------------------------------------ many paths


def trim(table: Table) -> Table:
    """Only the sessions from the first to the last one that carry outcomes: the first 220 sessions of any
    history have no eligible stock, and the last 5 have no matured outcome yet."""
    live = [i for i, d in enumerate(table.days) if d]
    if not live:
        return Table([], [])
    return Table(table.sessions[live[0] : live[-1] + 1], table.days[live[0] : live[-1] + 1])


def usable_sessions(table: Table) -> int:
    return len(trim(table).sessions)


def run_grid_cell(
    table: Table,
    replicates: int,
    seed: int,
    mode: str,
    run_length: int = P.RUN_VALUES["run_length_sessions"],
    delta: float = 0.0,
    missing: float = 0.0,
    stickiness: float = 0.0,
    block_mean: int = 20,
) -> dict:
    """Rates over `replicates` simulated 3-run paths. Every rate has a Monte Carlo standard error."""
    rng = np.random.default_rng(seed)
    table = trim(table)
    total = len(table.sessions)
    length = 3 * run_length
    if total < length:
        raise ValueError(f"the history has {total} usable sessions; {length} are needed")
    base_days = P.RUN_VALUES["min_evidence_per_group"]["matured_signal_days"]
    min_days = round(base_days * run_length / P.RUN_VALUES["run_length_sessions"])
    counts: dict[str, int] = defaultdict(int)
    for _ in range(replicates):
        if mode == "history":
            positions = history_positions(rng, total, length)
        else:
            positions = bootstrap_positions(rng, total, length, block_mean)
        res = simulate_path(rng, table, positions, run_length, delta, missing, stickiness, min_days)
        any_sel = any_eco = any_either = any_both = False
        for g in P.GROUPS:
            c = res[g]["combined"]
            sel, eco = c["selection"]["verdict"], c["economic"]["verdict"]
            counts[f"{g}.combined_selection.{sel}"] += 1
            counts[f"{g}.combined_economic.{eco}"] += 1
            for r in res[g]["runs"]:
                counts[f"{g}.run_selection.{r['selection']['verdict']}"] += 1
                counts[f"{g}.run_economic.{r['economic']['verdict']}"] += 1
                counts[f"{g}.run_too_few_days"] += int(r.get("why") is not None)
            counts[f"{g}.both_pass"] += int(sel == V.PASS and eco == V.PASS)
            any_sel |= sel == V.PASS
            any_eco |= eco == V.PASS
            any_either |= V.PASS in (sel, eco)
            any_both |= sel == V.PASS and eco == V.PASS
        counts["any_group.combined_selection.PASS"] += int(any_sel)
        counts["any_group.combined_economic.PASS"] += int(any_eco)
        counts["any_group.either_PASS"] += int(any_either)
        counts["any_group.both_PASS"] += int(any_both)
    # per-run counters are shares of the 3 * replicates runs; everything else is a share of the replicates
    base = {k: replicates * (3 if ".run_" in k else 1) for k in counts}
    rates = {k: counts[k] / base[k] for k in sorted(counts)}
    se = {k: float(np.sqrt(p * (1 - p) / base[k])) for k, p in rates.items()}
    return {
        "setting": {
            "mode": mode,
            "run_length": run_length,
            "min_matured_days": min_days,
            "delta": delta,
            "missing": missing,
            "stickiness": stickiness,
            "block_mean": block_mean if mode == "bootstrap" else None,
            "replicates": replicates,
            "seed": seed,
        },
        "rates": rates,
        "monte_carlo_se": se,
    }


def history_summary(table: Table) -> dict:
    table = trim(table)
    usable = len(table.sessions)
    baseline = {}
    for g in P.GROUPS:
        vals = [d[g][1].mean() for d in table.days if g in d and len(d[g][1])]
        baseline[g] = {"mean_net_return_of_every_eligible_stock": float(np.mean(vals)), "days": len(vals)}
    return {
        "first_session": str(table.sessions[0]),
        "last_session_with_outcomes": str(table.sessions[-1]),
        "usable_sessions": usable,
        "non_overlapping_180_session_windows": usable // 180,
        "baseline_by_group": baseline,
        "table_sha256": table.fingerprint(),
    }


def full_report(table: Table, replicates: int, seed: int, quick: bool = False) -> dict:
    """The grid behind the protocol's run-length and false-pass statements."""
    started = time.time()
    cells: dict[str, dict] = {}
    for mode in ("history", "bootstrap"):
        for stick in (0.0, 0.8):
            for miss in (0.0, 0.2):
                cells[f"null/{mode}/stick{stick}/missing{miss}"] = run_grid_cell(
                    table, replicates, seed, mode=mode, stickiness=stick, missing=miss
                )
    for length in (60,) if quick else (30, 60, 90):
        for delta in (0.0, 0.005, 0.01, 0.015, 0.02):
            cells[f"power/L{length}/delta{delta}"] = run_grid_cell(
                table, replicates, seed, mode="bootstrap", run_length=length, delta=delta, stickiness=0.8, missing=0.1
            )
    return {"history": history_summary(table), "cells": cells, "seconds": round(time.time() - started)}


def _pct(x: float) -> str:
    return f"{x:.1%}"


def render_markdown(rep: dict) -> str:
    h = rep["history"]
    base = ", ".join(f"{g} {v['mean_net_return_of_every_eligible_stock']:.3%}" for g, v in h["baseline_by_group"].items())
    lines = [
        "# h05 run-length and false-pass support (reproducible)",
        "",
        f"History: {h['first_session']} to {h['last_session_with_outcomes']}, {h['usable_sessions']} sessions with outcomes "
        f"({h['non_overlapping_180_session_windows']} non-overlapping 180-session windows). Table sha256 `{h['table_sha256'][:16]}`.",
        "",
        f"Average net return of EVERY eligible stock under the lane's fixed rule and assumed costs: {base}.",
        "",
        "## Random picks (no skill): how often does the frozen procedure say PASS?",
        "",
        "| setting | selection PASS: large / mid / small / any group | economic PASS: large / mid / small / any group |",
        "|---|---|---|",
    ]
    for name, c in rep["cells"].items():
        if name.startswith("null/"):
            r = c["rates"]
            sel = " / ".join(_pct(r.get(f"{g}.combined_selection.PASS", 0)) for g in P.GROUPS)
            eco = " / ".join(_pct(r.get(f"{g}.combined_economic.PASS", 0)) for g in P.GROUPS)
            sel += f" / **{_pct(r.get('any_group.combined_selection.PASS', 0))}**"
            eco += f" / **{_pct(r.get('any_group.combined_economic.PASS', 0))}**"
            lines.append(f"| {name[5:]} | {sel} | {eco} |")
    lines += [
        "",
        "## A pick set with a real edge of `delta` per trade (bootstrap, sticky 0.8, 10% of sessions missed)",
        "",
        "| run length | delta | selection PASS large / mid / small | economic PASS large / mid / small |",
        "|---|---|---|---|",
    ]
    for name, c in rep["cells"].items():
        if name.startswith("power/"):
            s, r = c["setting"], c["rates"]
            sel = " / ".join(_pct(r.get(f"{g}.combined_selection.PASS", 0)) for g in P.GROUPS)
            eco = " / ".join(_pct(r.get(f"{g}.combined_economic.PASS", 0)) for g in P.GROUPS)
            lines.append(f"| {s['run_length']} | {s['delta']:.1%} | {sel} | {eco} |")
    return "\n".join(lines) + "\n"


def dump(rep: dict) -> str:
    return json.dumps(rep, indent=2, default=str, sort_keys=True)
