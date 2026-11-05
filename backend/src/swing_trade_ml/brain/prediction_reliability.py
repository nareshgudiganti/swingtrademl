"""Prediction Reliability: a read-only report of how far the model's predictions can be trusted.

Rules: docs/superpowers/specs/2026-11-05-prediction-reliability-rules.md. It measures evidence, never
guarantees accuracy or profit. Pure functions plus thin SELECT-only readers; no writes, no orders, no
thresholds changed. Horizons and models are separate series and are never pooled. Only completed outcomes
count. Days on or after the trial seal show counts only.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

# isort: off
from swing_trade_ml.services import trial_seal  # first: breaks an existing import cycle with trial_journal
from swing_trade_ml.brain.trial_journal import GATE_MIN_IDEAS, MIN_SESSIONS, SCORE_LINE, TOP_N
from swing_trade_ml.brain.walk_forward import bootstrap_low
from swing_trade_ml.ml.calibrated_model import reliability_table

# isort: on

IST = ZoneInfo("Asia/Kolkata")

INSUFFICIENT, HEALTHY, WATCH, FAIL = "INSUFFICIENT DATA", "HEALTHY", "WATCH", "FAIL"

SETS = ("top5", "trade", "over_80", "ranks_6_20", "baseline")
SET_NAMES = {
    "top5": "Top 5 by score",
    "trade": "TRADE decisions",
    "over_80": "Score 0.80 or more (top 5)",
    "ranks_6_20": "Ranks 6 to 20",
    "baseline": "Every eligible stock (baseline)",
}
DONE_STATUSES = ("target", "stop", "timeout", "expiry")
NOT_RECORDED = "not recorded for this source"


# The existing sample gates, reused and never changed here.
def _gates() -> dict[str, dict[str, int]]:
    from swing_trade_ml.brain.lanes.h05_protocol import RUN_VALUES
    from swing_trade_ml.shadow_lanes.lane_review import CHECKPOINTS

    h05_days = int(RUN_VALUES["min_evidence_per_group"]["matured_signal_days"])  # type: ignore[index]
    return {
        "brain": {"min_days": MIN_SESSIONS, "min_completed": GATE_MIN_IDEAS},
        "lane": {"min_days": CHECKPOINTS[0], "min_completed": CHECKPOINTS[0]},
        "h05": {"min_days": h05_days, "min_completed": h05_days},
    }


# PROPOSED health rules: the owner signs these before any real outcome is read.
HEALTH_RULES = {
    "brier_fail_margin": 0.02,  # Brier worse than the naive score by more than this -> FAIL
    "boot_low_healthy_above": 0.0,  # bootstrap lower bound of the daily net result must exceed this
    "psi_watch": 0.2,  # score drift at or above this -> WATCH
    "wilson_z": 1.96,
}


@dataclass(frozen=True, slots=True)
class Rec:
    """One prediction. `hit`/`ret` are None while the outcome is open (they never count then)."""

    day: date
    symbol: str
    score: float | None
    rank: int | None  # 1 = highest score that day among eligible stocks
    hit: int | None  # 1 target reached, 0 not; None = open
    ret: float | None  # net return after costs; None = open
    baseline_ret: float | None = None  # matched baseline for this record (lanes store it)
    trade: bool = False


# ----------------------------------------------------------------------------- pure measures


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def brier(probs: Sequence[float], hits: Sequence[int]) -> float | None:
    if len(probs) == 0:
        return None
    return float(np.mean((np.asarray(probs, float) - np.asarray(hits, float)) ** 2))


def effective_blocks(days: Sequence[date], horizon: int) -> int:
    """Independent picks: days at least one holding horizon apart (horizon trading days ~ 7/5 calendar)."""
    gap = timedelta(days=math.ceil(horizon * 7 / 5))
    kept: date | None = None
    n = 0
    for d in sorted(set(days)):
        if kept is None or d - kept >= gap:
            kept, n = d, n + 1
    return n


def psi_flag(reference: Sequence[float] | None, recent: Sequence[float] | None) -> dict:
    """Score drift. 'not measured' unless both samples are given and large enough."""
    if reference is None or recent is None:
        return {"measured": False, "text": "drift: not measured"}
    from swing_trade_ml.brain.modules.m09_learn.drift import psi

    v = psi(np.asarray(reference, float), np.asarray(recent, float))
    if v is None:
        return {"measured": False, "text": "drift: not measured (too few scores)"}
    return {"measured": True, "psi": v, "text": f"drift (PSI): {v:.2f}"}


def _mean(xs: Sequence[float]) -> float | None:
    return float(sum(xs) / len(xs)) if xs else None


def measure(recs: Sequence[Rec], horizon: int, baseline: Sequence[Rec] | None = None) -> dict:
    """Figures for one pick set (unsealed rows only). Open rows are counted apart and never averaged."""
    hit_done = [r for r in recs if r.hit is not None]
    pnl_done = [r for r in recs if r.ret is not None]
    n, k = len(hit_done), sum(r.hit for r in hit_done)  # type: ignore[misc]
    out: dict = {
        "picked": len(recs),
        "completed": n,
        "completed_pnl": len(pnl_done),
        "open": len(recs) - max(n, len(pnl_done)) if recs else 0,
        "days": len({r.day for r in recs}),
        "effective_blocks": effective_blocks([r.day for r in hit_done or pnl_done], horizon),
        "hit_rate": k / n if n else None,
        "hit_wilson": wilson(k, n, HEALTH_RULES["wilson_z"]),
    }
    scored = [r for r in hit_done if r.score is not None]
    if scored:
        probs = np.array([r.score for r in scored], float)
        ys = np.array([r.hit for r in scored], float)
        out["brier"] = brier(probs, ys)  # type: ignore[arg-type]
        out["brier_naive"] = None  # filled below once the baseline hit rate is known
        out["calibration"] = [b for b in reliability_table(ys, probs) if b["n"]]
    else:
        out["brier"] = out["brier_naive"] = None
        out["calibration"] = []
    by_day: dict[date, list[float]] = defaultdict(list)
    for r in pnl_done:
        by_day[r.day].append(r.ret)  # type: ignore[arg-type]
    daily = [sum(v) / len(v) for _, v in sorted(by_day.items())]
    out["avg_net"] = _mean([r.ret for r in pnl_done])  # type: ignore[misc]
    out["boot_low"] = bootstrap_low(daily) if daily else None
    # excess over the matched baseline
    if baseline is not None:
        bh = [r for r in baseline if r.hit is not None]
        out["baseline_hit_rate"] = sum(r.hit for r in bh) / len(bh) if bh else None  # type: ignore[misc]
        bday: dict[date, list[float]] = defaultdict(list)
        for r in baseline:
            if r.ret is not None:
                bday[r.day].append(r.ret)
        diffs = [_mean(by_day[d]) - _mean(bday[d]) for d in sorted(by_day) if d in bday]  # type: ignore[operator]
        out["avg_excess"] = _mean(diffs)
        out["baseline_avg_net"] = _mean([x for v in bday.values() for x in v])
    else:
        ex = [r.ret - r.baseline_ret for r in pnl_done if r.baseline_ret is not None]  # type: ignore[operator]
        out["baseline_hit_rate"] = None
        out["avg_excess"] = _mean(ex)
        out["baseline_avg_net"] = _mean([r.baseline_ret for r in pnl_done if r.baseline_ret is not None])  # type: ignore[misc]
    # Naive score: always say the baseline's hit rate (the pool's own when no baseline pool exists).
    if out["brier"] is not None:
        p0 = out["baseline_hit_rate"] if out["baseline_hit_rate"] is not None else out["hit_rate"]
        out["brier_naive"] = brier([p0] * len(scored), [r.hit for r in scored])  # type: ignore[misc]
    return out


def health(m: dict | None, gate: dict[str, int], *, sealed: bool = False, drift: dict | None = None) -> dict:
    """PROPOSED rules (docs, 'Health states'). Never HEALTHY from sealed data or below the sample gates."""
    if sealed or m is None:
        return {
            "state": INSUFFICIENT,
            "why": "evidence is sealed (counts only)" if sealed else "no completed picks",
        }
    if (
        m["days"] < gate["min_days"]
        or m["completed"] < gate["min_completed"]
        or m["completed_pnl"] < gate["min_completed"]
    ):
        return {
            "state": INSUFFICIENT,
            "why": f"needs {gate['min_days']} days and {gate['min_completed']} completed picks; "
            f"has {m['days']} days and {m['completed']} completed",
        }
    if m.get("avg_excess") is None:
        return {"state": INSUFFICIENT, "why": "no matched baseline"}
    rules = HEALTH_RULES
    lo, hi = m["hit_wilson"]
    bhr = m.get("baseline_hit_rate")
    brier_bad = m["brier"] is not None and m["brier"] > m["brier_naive"] + rules["brier_fail_margin"]
    if (
        (bhr is not None and hi < bhr)
        or (m["avg_net"] is not None and m["avg_net"] < 0 and m["avg_excess"] < 0)
        or brier_bad
    ):
        return {"state": FAIL, "why": "worse than its baseline or badly calibrated"}
    drifting = bool(drift and drift.get("measured") and drift["psi"] >= rules["psi_watch"])
    ok = (
        (bhr is None or lo > bhr)
        and m["avg_excess"] > 0
        and m["boot_low"] is not None
        and m["boot_low"] > rules["boot_low_healthy_above"]
        and (m["brier"] is None or m["brier"] <= m["brier_naive"])
    )
    if ok and not drifting:
        return {"state": HEALTHY, "why": "beats its baseline with a margin; calibrated"}
    return {"state": WATCH, "why": "drift" if drifting else "not clearly better than its baseline"}


def split_sets(recs: Sequence[Rec]) -> dict[str, list[Rec]]:
    return {
        "top5": [r for r in recs if r.rank is not None and r.rank <= TOP_N],
        "trade": [r for r in recs if r.trade],
        "over_80": [
            r for r in recs if r.rank is not None and r.rank <= TOP_N and (r.score or 0) >= SCORE_LINE
        ],
        "ranks_6_20": [r for r in recs if r.rank is not None and 6 <= r.rank <= 20],
        "baseline": list(recs),
    }


def report_series(
    key: dict, recs: Sequence[Rec], source: str, *, has_baseline_pool: bool, drift: dict | None = None
) -> dict:
    """One series (one source, horizon, model, group). The seal is applied here: sealed days give counts
    only, and results are computed from open days alone, so no total can include a sealed result."""
    gate = _gates()[source]
    horizon = key["horizon"]
    sealed_recs = [r for r in recs if trial_seal.is_sealed_day(r.day)]
    open_recs = [r for r in recs if not trial_seal.is_sealed_day(r.day)]
    sealed_by_set = {
        name: trial_seal.counts_only(
            {
                "picked": len(rs),
                "completed": sum(1 for r in rs if r.hit is not None or r.ret is not None),
                "open": sum(1 for r in rs if r.hit is None and r.ret is None),
                "avg_net": None,
                "hit_rate": None,
            }
        )
        for name, rs in split_sets(sealed_recs).items()
    }
    sets = split_sets(open_recs)
    out_sets: dict[str, dict | str] = {}
    healths: dict[str, dict] = {}
    for name in SETS:
        if name in ("ranks_6_20",) and not has_baseline_pool:
            out_sets[name] = NOT_RECORDED
            continue
        if name == "trade" and source != "brain":
            out_sets[name] = NOT_RECORDED
            continue
        base = sets["baseline"] if has_baseline_pool else None
        m = measure(sets[name], horizon, base if name != "baseline" else None)
        out_sets[name] = m
        if name in ("top5", "trade", "over_80"):
            healths[name] = health(
                m if m["picked"] else None,
                gate,
                sealed=bool(sealed_recs) and not open_recs,
                drift=drift,
            )
    return {
        "key": key,
        "sets": out_sets,
        "health": healths,
        "sealed_counts": sealed_by_set if sealed_recs else None,
        "sealed_note": trial_seal.SEALED_TEXT if sealed_recs else None,
        "drift": (drift or psi_flag(None, None))["text"],
    }


def build_report(series: Sequence[tuple[dict, Sequence[Rec], str, bool]]) -> dict:
    """series: (key, records, source, has_baseline_pool). Each series is reported on its own; there is no
    combined figure across horizons or models."""
    return {
        "disclaimer": "This measures evidence. It does not guarantee accuracy or profit.",
        "series": [report_series(k, r, s, has_baseline_pool=b) for k, r, s, b in series],
    }


# ----------------------------------------------------------------------------- readers (SELECT only)


def brain_series(db, start: date, end: date) -> list[tuple[dict, list[Rec], str, bool]]:
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, STOP, TARGET
    from swing_trade_ml.brain.trial_journal import load_sessions
    from swing_trade_ml.brain.walk_forward import outcomes_for

    sessions = load_sessions(db, start, end, live=True)
    if not sessions:
        return []
    syms = sorted({i.symbol for s in sessions for i in s.ideas})
    bars = load_bars(db, syms, end + timedelta(days=60))
    outs = outcomes_for(bars, [s.day for s in sessions], HORIZON_BARS, TARGET, STOP)
    recs: list[Rec] = []
    for s in sessions:
        ranked = sorted((i for i in s.ideas if i.score is not None), key=lambda i: (-i.score, i.symbol))
        rank = {i.symbol: n + 1 for n, i in enumerate(ranked)}
        for i in s.ideas:
            o = outs.get((i.symbol, s.day))
            done = o is not None and o.status in DONE_STATUSES and o.net_return is not None
            recs.append(
                Rec(
                    s.day,
                    i.symbol,
                    i.score,
                    rank.get(i.symbol),
                    (1 if o.status == "target" else 0) if done else None,
                    o.net_return if done else None,
                    None,
                    i.word == "TRADE",
                )
            )
    key = {
        "source": "brain",
        "horizon": HORIZON_BARS,
        "model": "brain nightly (version not recorded)",
        "group": "all",
    }
    return [(key, recs, "brain", True)]


def lane_series(db) -> list[tuple[dict, list[Rec], str, bool]]:
    from sqlalchemy import select

    from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick

    rows = db.execute(
        select(LanePick, LaneOutcome).outerjoin(LaneOutcome, LaneOutcome.pick_id == LanePick.id)
    ).all()
    groups: dict[tuple, list[Rec]] = defaultdict(list)
    for p, o in rows:
        done = o is not None and o.status in DONE_STATUSES and o.net_return is not None
        groups[(p.horizon_days, p.model_version, p.slot_key)].append(
            Rec(
                p.signal_day,
                p.symbol,
                p.score,
                p.rank,
                (1 if o.status == "target" else 0) if done else None,
                o.net_return if done else None,
                o.baseline_net_return if done else None,
            )
        )
    return [
        ({"source": "lane", "horizon": h, "model": v, "group": slot}, rs, "lane", False)
        for (h, v, slot), rs in sorted(groups.items())
    ]


def h05_series(db) -> list[tuple[dict, list[Rec], str, bool]]:
    from sqlalchemy import select

    from swing_trade_ml.db.models.lanes import H05Signal

    rows = db.execute(select(H05Signal).where(H05Signal.status == "scored")).scalars()
    groups: dict[tuple, list[Rec]] = defaultdict(list)
    for s in rows:
        groups[(s.model_version, s.group)].append(
            Rec(
                s.signal_day,
                s.symbol,
                s.score,
                s.group_rank,
                s.label_hit if s.label_status == "evaluated" else None,
                s.net_return if s.trade_status in DONE_STATUSES and s.net_return is not None else None,
            )
        )
    return [
        ({"source": "h05", "horizon": 5, "model": v or "unknown", "group": g}, rs, "h05", True)
        for (v, g), rs in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0])))
    ]


def collect(db, start: date, end: date) -> list[tuple[dict, list[Rec], str, bool]]:
    return brain_series(db, start, end) + lane_series(db) + h05_series(db)


# ----------------------------------------------------------------------------- text


def _pct(x: float | None, d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def plain_report(rep: dict) -> str:
    lines = ["# Prediction Reliability", "", rep["disclaimer"], ""]
    for s in rep["series"]:
        k = s["key"]
        lines += [f"## {k['source']} | {k['horizon']}-day | {k['model']} | {k['group']}", ""]
        for name in SETS:
            m = s["sets"][name]
            if isinstance(m, str):
                lines.append(f"- {SET_NAMES[name]}: {m}")
                continue
            h = s["health"].get(name)
            w = m["hit_wilson"]
            lines.append(
                f"- {SET_NAMES[name]}: picked {m['picked']}, completed {m['completed']}, open {m['open']}, "
                f"independent blocks {m['effective_blocks']}; hit {_pct(m['hit_rate'])}"
                + (f" (95% range {_pct(w[0])} to {_pct(w[1])})" if w else "")
                + f"; avg net {_pct(m['avg_net'], 2)}; vs baseline {_pct(m['avg_excess'], 2)}"
                + f"; bootstrap low {_pct(m['boot_low'], 2)}"
                + (
                    f"; Brier {m['brier']:.3f} (naive {m['brier_naive']:.3f})"
                    if m["brier"] is not None
                    else ""
                )
                + (f" -> {h['state']} ({h['why']})" if h else "")
            )
        if s["sealed_counts"]:
            c = s["sealed_counts"]["top5"]
            lines.append(
                f"- Sealed days: top 5 picked {c['picked']}, completed {c['completed']}, "
                f"open {c['open']}. {s['sealed_note']}"
            )
        lines += [f"- {s['drift']}", ""]
    return "\n".join(lines)


def write_report(text: str, directory: Path, today: date) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"prediction-reliability-{today.isoformat()}.md"
    with open(path, "x", encoding="utf-8") as f:  # 'x': refuses to overwrite
        f.write(text)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Prediction Reliability report (read-only)")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", default=None)
    p.add_argument("--out", default="docs/brain/evidence/reliability")
    a = p.parse_args(argv)
    today = datetime.now(IST).date()
    end = date.fromisoformat(a.end) if a.end else today
    with SessionLocal() as db:
        rep = build_report(collect(db, date.fromisoformat(a.start), end))
    text = plain_report(rep)
    print(text)
    try:
        print(f"Written: {write_report(text, Path(a.out), today)}")
    except FileExistsError:
        print("Report for today already exists; not overwritten.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
