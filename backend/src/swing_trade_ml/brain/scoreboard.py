# backend/src/swing_trade_ml/brain/scoreboard.py
# ruff: noqa: E501 (long lines are report sentences)
"""Honest scoreboards (read-only reports on DEVELOPMENT data; they decide nothing).

S1 - model quality. Every day, rank every eligible stock by the model's score and compare five groups:
Top 5, ranks 6-10, ranks 11-15, ranks 16-20, and ALL eligible stocks. Account limits play no part: this asks
only "is the score good?". Every idea in every group is scored the same way (the settled 15-day rule: enter
at the next open, +8% / -4%, half out at +5%, 15 trading days, costs and slippage). Each idea is one equal
amount, and the groups are compared on PERCENTAGE return after costs, so a group with more ideas is not
favoured. The score and the rank are kept exactly as they were at selection.

S2 - the brain's decisions, apart from model quality. Ideas the brain approved (word TRADE) against ideas it
wanted to trade but its checks blocked (downgraded from TRADE), with the stated reason, scored with the same
trade rule. DESCRIPTIVE ONLY: approved and blocked ideas are different stocks on different days, so this does
not by itself show that the brain improves returns.

Seal. Ideas of the live trial (decided on or after `trial_seal.SEALED_FROM`) show COUNTS ONLY: no result, no
average, no hit rate. Results are computed from unsealed days only, and no total that includes a sealed day's
result is ever returned, so nothing can be recovered by subtraction, filtering or export. The window refuses
the protected wf-protocol-v1 sample and any window that reaches the sealed days (S1).

Nothing here changes a threshold, a pass rule or the Phase B schedule (B1 stays score >= 0.80).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import pandas as pd

from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, STOP, TARGET
from swing_trade_ml.brain.walk_forward import BLOCK_DAYS, bootstrap_low, make_folds, outcomes_for
from swing_trade_ml.services import trial_seal

PROTECTED_START = date(2023, 7, 1)  # wf-protocol-v1 confirmation sample: pass/fail only, never diagnostics
PROTECTED_END = date(2025, 1, 31)
MIN_DAY_STOCKS = 20  # a day needs this many scored stocks to fill ranks 1-20
MIN_COMPLETED = 100  # fewer completed ideas than this is shown but flagged thin
GROUPS: tuple[tuple[str, str, int, int], ...] = (
    ("top5", "Top 5", 1, 5),
    ("r06_10", "Ranks 6-10", 6, 10),
    ("r11_15", "Ranks 11-15", 11, 15),
    ("r16_20", "Ranks 16-20", 16, 20),
)
DONE = ("target", "stop", "timeout")  # a completed 15-day result
COLUMNS = ["day", "symbol", "score", "status", "ret", "fold"]

# Audit items that decide how far these numbers can be trusted (docs/superpowers/specs/2026-10-26-data-audit-and-scoreboard-DRAFT.md).
# Each report prints this list; an item still "open" is flagged on every table that depends on it.
AUDIT_FLAGS: tuple[dict, ...] = (
    {
        "id": 8,
        "item": "signal timing and entry price",
        "state": "resolved by reading the code",
        "affects": "S1, S2",
    },
    {
        "id": 9,
        "item": "train/test overlap",
        "state": "resolved by reading the code and the fold cutoffs",
        "affects": "S1",
    },
    {
        "id": 10,
        "item": "which score is which (model version, run time, score type)",
        "state": "S2 prints score_source per idea; UI labelling still open",
        "affects": "S2",
    },
    {
        "id": 11,
        "item": "are the 129 reject stocks a clean test set",
        "state": "open - not used here",
        "affects": "none (not used)",
    },
    {
        "id": 12,
        "item": "survivorship, today's sector map, no corporate-action table",
        "state": "known limits",
        "affects": "S1, S2",
    },
)


# ----------------------------------------------------------------------------- S1: pure functions


def frame(rows: Sequence[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS)


def rank_days(df: pd.DataFrame, min_stocks: int = MIN_DAY_STOCKS) -> tuple[pd.DataFrame, int]:
    """Add `rank` (1 = highest score that day; equal scores are ordered by symbol so the rank is repeatable).
    The score is not changed. Days with fewer than `min_stocks` scored stocks cannot fill ranks 1-20 and are
    dropped; the number of dropped days is returned so the report can say so."""
    if df.empty:
        return df.assign(rank=pd.Series(dtype=int)), 0
    size = df.groupby("day")["symbol"].transform("size")
    dropped = int(df.loc[size < min_stocks, "day"].nunique())
    kept = df[size >= min_stocks].copy()
    kept = kept.sort_values(["day", "score", "symbol"], ascending=[True, False, True])
    kept["rank"] = kept.groupby("day").cumcount() + 1
    return kept.reset_index(drop=True), dropped


def _select(ranked: pd.DataFrame, lo: int | None, hi: int | None) -> pd.DataFrame:
    return ranked if lo is None else ranked[(ranked["rank"] >= lo) & (ranked["rank"] <= hi)]


def group_stats(g: pd.DataFrame) -> dict:
    """Counts and average net return of one group. Completed results only enter the average; open ideas and
    same-day observations (no entry bar yet) are counted apart and never mixed in."""
    done = g[g["status"].isin(DONE)]
    n = len(done)
    return {
        "signals": len(g),
        "completed": n,
        "open": int((g["status"] == "open").sum()),
        "same_day": int((g["status"] == "no_entry").sum()),
        "target": int((done["status"] == "target").sum()),
        "stop": int((done["status"] == "stop").sum()),
        "time_limit": int((done["status"] == "timeout").sum()),
        "avg_net": float(done["ret"].mean()) if n else None,
        "thin": n < MIN_COMPLETED,
    }


def daily_gap(ranked: pd.DataFrame, lo: int, hi: int) -> list[float]:
    """Per day (in day order): the group's average net return minus ALL eligible stocks' average, completed
    ideas only, both as percentages of the money put in (equal total capital per day)."""
    done = ranked[ranked["status"].isin(DONE)]
    out = []
    for _, d in done.groupby("day", sort=True):
        grp = d[(d["rank"] >= lo) & (d["rank"] <= hi)]
        if len(grp):
            out.append(float(grp["ret"].mean() - d["ret"].mean()))
    return out


def scoreboard(df: pd.DataFrame) -> dict:
    """S1 from scored stock-days. `df` columns: day, symbol, score, status, ret, fold."""
    ranked, dropped_days = rank_days(df)
    rows = []
    for key, label, lo, hi in GROUPS:
        st = group_stats(_select(ranked, lo, hi))
        gap = daily_gap(ranked, lo, hi)
        st.update(
            {
                "group": key,
                "label": label,
                "avg_gap_vs_all": float(sum(gap) / len(gap)) if gap else None,
                "gap_days": len(gap),
                "gap_lower_bound": bootstrap_low(gap, block=BLOCK_DAYS) if gap else None,
            }
        )
        rows.append(st)
    allg = group_stats(ranked)
    allg.update(
        {
            "group": "all",
            "label": "All eligible stocks",
            "avg_gap_vs_all": 0.0,
            "gap_days": None,
            "gap_lower_bound": None,
        }
    )
    rows.append(allg)
    return {
        "days_ranked": int(ranked["day"].nunique()) if len(ranked) else 0,
        "days_dropped_too_few_stocks": dropped_days,
        "groups": rows,
        "monotone_top_to_r16_20": _monotone(rows[:4]),
        "folds_top5_beat_all": _folds_top5_beat_all(ranked),
    }


def _monotone(rows: list[dict]) -> bool | None:
    v = [r["avg_net"] for r in rows]
    return None if any(x is None for x in v) else all(a >= b for a, b in pairwise(v))


def _folds_top5_beat_all(ranked: pd.DataFrame) -> dict:
    won = total = 0
    done = ranked[ranked["status"].isin(DONE)]
    for _, f in done.groupby("fold"):
        top, allr = f[f["rank"] <= 5], f
        if len(top) < 20:
            continue
        total += 1
        won += int(top["ret"].mean() > allr["ret"].mean())
    return {"folds_with_enough_ideas": total, "top5_beat_all": won}


# ----------------------------------------------------------------------------- S1: data


def check_window(first: date, last: date) -> None:
    if first <= PROTECTED_END and last >= PROTECTED_START:
        raise ValueError(
            f"Window {first} to {last} overlaps the protected confirmation sample "
            f"{PROTECTED_START} to {PROTECTED_END} (pass/fail only). Pick a window after {PROTECTED_END}."
        )
    if trial_seal.touches_seal(first, last):
        raise ValueError(
            f"Window {first} to {last} reaches the sealed trial days (from {trial_seal.SEALED_FROM}). "
            "Trial days show counts only; end the window before the seal."
        )


def collect_s1(
    db,
    first_start: date,
    last_end: date,
    *,
    test_days: int = 28,
    horizon: int = HORIZON_BARS,
    target: float = TARGET,
    stop: float = STOP,
    train_fn: Callable | None = None,
    score_fn: Callable | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Per fold a model trained only on outcomes known by its cutoff scores the fold's days (the wf-protocol-v1
    machinery, nothing tuned). Registers `wf_*` trial models locally, never activated."""
    from sqlalchemy import select

    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.walk_forward import _train
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.asof import asof_cutoff

    check_window(first_start, last_end)
    train_fn = train_fn or _train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn
    folds = make_folds(first_start, last_end, test_days)
    if not folds:
        raise ValueError("No test window fits between the start and end dates.")
    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    bars = {
        s: d
        for s, d in load_bars(
            db, [i.tradingsymbol for i in instruments], last_end + timedelta(days=60)
        ).items()
        if len(d)
    }
    rows: list[dict] = []
    cutoffs: dict[str, str | None] = {}
    for fold in folds:
        days = sorted({d for df in bars.values() for d in df["day"] if fold.start <= d <= fold.end})
        if not days:
            continue
        key = fold.start.isoformat()
        outcomes = outcomes_for(bars, days, horizon, target, stop)
        model = train_fn(db, fold.cutoff, horizon, target, stop)
        seen = asof_cutoff(model)
        cutoffs[key] = None if seen is None else seen.isoformat()
        for inst in instruments:
            for d, p in score_fn(db, inst, model, fold.cutoff).items():
                if not (fold.start <= d <= fold.end):
                    continue
                o = outcomes.get((inst.tradingsymbol, d))
                if o is None:
                    status, ret = "no_entry", None  # no bar after the decision day: a same-day observation
                else:
                    status, ret = o.status, o.net_return
                rows.append(
                    {
                        "day": d,
                        "symbol": inst.tradingsymbol,
                        "score": float(p),
                        "status": status,
                        "ret": ret,
                        "fold": key,
                    }
                )
    df = frame(rows)
    integrity = {
        "stocks_in_universe": len(bars),
        "duplicate_stock_days": int(df.duplicated(["symbol", "day"]).sum()) if len(df) else 0,
        "folds_whose_model_cutoff_is_missing_or_not_before_the_fold": [
            f.start.isoformat()
            for f in folds
            if cutoffs.get(f.start.isoformat()) is None or cutoffs[f.start.isoformat()] >= f.start.isoformat()
        ],
        "survivorship": "universe is today's watchlist: stocks dropped earlier are absent",
    }
    return df, {
        "first_start": first_start.isoformat(),
        "last_end": last_end.isoformat(),
        "folds": len(folds),
        "integrity": integrity,
    }


# ----------------------------------------------------------------------------- S2


_REASONS: tuple[tuple[str, str], ...] = (
    (r"risk checks use today's account", "risk check (replay used today's account - an artifact of replays)"),
    (r"risk check said no|risk check has not approved", "risk check said no"),
    (r"data is not reliable", "data not reliable"),
    (r"results on .* avoids new trades", "results-day rule"),
    (r"market is careful", "market careful and stock falling"),
)


def reason_bucket(text: str | None) -> str:
    t = (text or "").lower()
    for pattern, label in _REASONS:
        if re.search(pattern, t):
            return label
    return "other: " + (t[:60] or "no reason stored")


def classify_idea(word: str, downgraded_from: str | None) -> str | None:
    """approved = the brain's final word is TRADE; blocked = it wanted TRADE and a check changed it;
    None = not a trade intent (WATCH/WAIT/AVOID from the start)."""
    if word == "TRADE":
        return "approved"
    if downgraded_from == "TRADE":
        return "blocked"
    return None


def s2_report(ideas: Sequence[dict]) -> dict:
    """`ideas`: day, symbol, word, downgraded_from, downgrade_reason, score, score_source, status, ret.
    Results come from unsealed days only. Sealed days contribute counts and nothing else."""
    groups: dict[str, dict] = {
        "approved": {"counts": Counter(), "rows": []},
        "blocked": {"counts": Counter(), "rows": []},
    }
    sealed_counts = Counter()
    reasons = Counter()
    for i in ideas:
        kind = classify_idea(i["word"], i.get("downgraded_from"))
        if kind is None:
            continue
        reasons[(kind, reason_bucket(i.get("downgrade_reason")) if kind == "blocked" else "approved")] += 1
        if trial_seal.is_sealed_day(i["day"]):
            sealed_counts[kind] += 1  # a count and nothing else
            continue
        groups[kind]["rows"].append(i)
    out = {"descriptive_only": True, "note": DESCRIPTIVE_NOTE, "groups": {}}
    for kind, g in groups.items():
        df = (
            pd.DataFrame(g["rows"], columns=["day", "symbol", "score", "score_source", "status", "ret"])
            if g["rows"]
            else pd.DataFrame(columns=["day", "symbol", "score", "score_source", "status", "ret"])
        )
        st = group_stats(df) if len(df) else group_stats(pd.DataFrame(columns=["status", "ret"]))
        st["sources"] = dict(Counter(df["score_source"].fillna("none"))) if len(df) else {}
        out["groups"][kind] = st
    out["sealed_days_counts_only"] = {k: int(v) for k, v in sealed_counts.items()}
    out["reasons"] = [
        {"kind": k, "reason": r, "ideas": n} for (k, r), n in sorted(reasons.items(), key=lambda kv: -kv[1])
    ]
    return out


DESCRIPTIVE_NOTE = (
    "Descriptive only. Approved and blocked ideas are different stocks on different days, so this comparison does "
    "not by itself show that the brain improves returns."
)


def collect_s2(db, first: date, last: date) -> list[dict]:
    """Stored brain ideas of the nightly runs whose IST day is in [first, last]: the newest finished run of each
    day, whole. Outcomes use the same strict trade rule as S1 on the stored prices. Sealed days carry no outcome."""
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.replay_scoring import after_day, strict_score
    from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

    ist = ZoneInfo("Asia/Kolkata")
    runs = db.execute(
        select(BrainRun.id, BrainRun.as_of, BrainRun.started_at, BrainRun.live).where(
            BrainRun.kind == "nightly", BrainRun.status == "done"
        )
    ).all()
    # One whole run per day (the newest): a run is one coherent set of decisions. Mixing the newest row of
    # each stock across several runs of the same day would mix different models and gates.
    chosen: dict[date, tuple] = {}
    for run_id, as_of, started, live in runs:
        day = as_of.astimezone(ist).date()
        if first <= day <= last and (day not in chosen or started > chosen[day][0]):
            chosen[day] = (started, live, run_id)
    by_run = {rid: (day, live) for day, (_, live, rid) in chosen.items()}
    newest: dict[tuple[date, str], tuple] = {}
    if by_run:
        for d in db.execute(
            select(BrainDecision).where(BrainDecision.run_id.in_(list(by_run)), BrainDecision.kind == "idea")
        ).scalars():
            day, live = by_run[d.run_id]
            newest[(day, d.symbol)] = (None, live, d, day, d.run_id)
    symbols = sorted({k[1] for k in newest})
    bars = load_bars(db, symbols, last + timedelta(days=60)) if symbols else {}
    ideas = []
    for (day, sym), (_, live, d, _, _run_id) in newest.items():
        status, ret = None, None
        if not trial_seal.is_sealed_day(day) and sym in bars:
            nxt = after_day(bars[sym], day)
            if len(nxt) == 0:
                status = "no_entry"
            else:
                o = strict_score(nxt)
                status, ret = o.status, o.net_return
        ideas.append(
            {
                "day": day,
                "symbol": sym,
                "word": d.word,
                "downgraded_from": d.downgraded_from,
                "downgrade_reason": d.downgrade_reason,
                "score": d.confidence,
                "score_source": d.score_source,
                "status": status,
                "ret": ret,
                "run_live": bool(live),
            }
        )
    return ideas


# ----------------------------------------------------------------------------- report


def _pct(x: float | None, d: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def plain_report_s1(r: dict, meta: dict) -> str:
    lines = [
        "# S1 - is the score good? (development data, 15-day rule, not a pass or fail)",
        "",
        f"Test days {meta['first_start']} to {meta['last_end']}, {meta['folds']} folds. 15-day rule: enter at the next open, "
        "+8% / -4%, half out at +5%, 15 trading days, costs and slippage. Each idea is one equal amount; groups are "
        "compared on PERCENTAGE return after costs. Open ideas and same-day observations are counted but never averaged.",
        f"Days ranked: {r['days_ranked']} (dropped for too few scored stocks: {r['days_dropped_too_few_stocks']}).",
        "",
        "| Group | Signals | Completed | Target | Stop | Time limit | Open | Same day | Avg net per idea | Gap to all eligible (per day) | Lower bound |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for g in r["groups"]:
        lines.append(
            f"| {g['label']}{' (thin)' if g['thin'] else ''} | {g['signals']} | {g['completed']} | {g['target']} | {g['stop']} | "
            f"{g['time_limit']} | {g['open']} | {g['same_day']} | {_pct(g['avg_net'])} | {_pct(g['avg_gap_vs_all'])} | {_pct(g['gap_lower_bound'])} |"
        )
    f = r["folds_top5_beat_all"]
    lines += [
        "",
        f"Top 5 beat all eligible stocks in {f['top5_beat_all']} of {f['folds_with_enough_ideas']} folds (folds with at least 20 completed Top-5 ideas).",
        f"Average falls steadily from Top 5 down to ranks 16-20: {r['monotone_top_to_r16_20']}.",
        "Lower bound = 5th percentile of the average daily gap, 15-day blocks. Above zero means the gap is unlikely to be luck.",
        "",
        "## Integrity",
        f"- Stocks: {meta['integrity']['stocks_in_universe']}; duplicate stock-days: {meta['integrity']['duplicate_stock_days']}; "
        f"folds with a missing or late model cutoff: {meta['integrity']['folds_whose_model_cutoff_is_missing_or_not_before_the_fold'] or 'none'}.",
        f"- {meta['integrity']['survivorship']}.",
        "",
        "## Audit items these numbers depend on",
    ]
    lines += [f"- #{a['id']} {a['item']}: {a['state']} (affects {a['affects']})" for a in AUDIT_FLAGS]
    lines += [
        "",
        "Development-data diagnostics only. They change no threshold, pass rule or the Phase B schedule (B1 stays score >= 0.80).",
    ]
    return "\n".join(lines)


def plain_report_s2(r: dict, window: tuple[date, date]) -> str:
    lines = [
        "# S2 - brain decisions, apart from model quality",
        "",
        f"Stored brain ideas for {window[0]} to {window[1]}. {r['note']}",
        "Same trade assumptions as S1 (next open, +8% / -4%, half out at +5%, 15 days, costs). Days from "
        f"{trial_seal.SEALED_FROM} on are sealed: counts only, never a result.",
        "",
        "| Group | Signals | Completed | Target | Stop | Time limit | Open | Same day | Avg net per idea | Score source |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for kind in ("approved", "blocked"):
        g = r["groups"][kind]
        lines.append(
            f"| {kind.capitalize()}{' (thin)' if g['thin'] else ''} | {g['signals']} | {g['completed']} | {g['target']} | {g['stop']} | "
            f"{g['time_limit']} | {g['open']} | {g['same_day']} | {_pct(g['avg_net'])} | {g['sources'] or 'n/a'} |"
        )
    s = r["sealed_days_counts_only"]
    lines += [
        "",
        f"Sealed trial days (counts only): approved {s.get('approved', 0)}, blocked {s.get('blocked', 0)}.",
        "",
        "## Why ideas were blocked (all days, counts only)",
    ]
    lines += [f"- {x['kind']}: {x['reason']} - {x['ideas']}" for x in r["reasons"]]
    return "\n".join(lines)


def write(result: dict, name: str, text: str, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    md, js = directory / f"{name}.md", directory / f"{name}.json"
    md.write_text(text, encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.core.config import REPO_ROOT
    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="S1/S2 scoreboards (read-only, development data)")
    p.add_argument("report", choices=["s1", "s2"])
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    a = p.parse_args(argv)
    first, last = date.fromisoformat(a.start), date.fromisoformat(a.end)
    out = REPO_ROOT / "docs" / "brain" / "evidence" / "scoreboard"
    with SessionLocal() as db:
        if a.report == "s1":
            df, meta = collect_s1(db, first, last)
            res = scoreboard(df)
            md, _ = write(
                {"meta": meta, "result": res}, f"s1_{first}_{last}", plain_report_s1(res, meta), out
            )
        else:
            res = s2_report(collect_s2(db, first, last))
            md, _ = write(res, f"s2_{first}_{last}", plain_report_s2(res, (first, last)), out)
    print(md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
