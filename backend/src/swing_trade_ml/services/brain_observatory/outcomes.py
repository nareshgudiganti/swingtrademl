"""Finished brain-idea results: THE one read-only function for them (spec addendum 13; evidence plan A3).

Two kinds of figure, never mixed:
- stored M09 grades (a record: gross, entry at the decision day's close), and
- figures computed now from stored prices (next-day open, half out, costs) set against the matched
  baselines of `evidence-defs-v1` (`baselines.trade_level`).
The category (practice / backtest / paper) is required and never mixed. Missing data is 'not available'
with the reason, never zero. Everything here is "Observed, not proof".
"""

from __future__ import annotations

from datetime import date, timedelta

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.brain_observatory import baselines, defs, queries
from swing_trade_ml.services.brain_observatory.redact import redact_text
from swing_trade_ml.services.brain_observatory.schedule import day_window, run_day

CATEGORIES = ("practice", "backtest", "paper")
LABEL = defs.OBSERVED_NOT_PROOF
BOOK = "paper"  # the only book whose brain runs count as practice or backtest evidence
PRACTICE_STAGE = "shadow"
BARS_BEFORE_DAYS = defs.MOMENTUM_BARS * 2 + 10  # at least 20 trading bars before the first day
BARS_AFTER_DAYS = 60  # ideas from the last session need about 15 more sessions
FORWARD_INSUFFICIENT = "Insufficient evidence"
SOURCES = {
    "stored_grade": (
        "M09 grade stored on each idea (brain/modules/m09_learn/outcomes.py): entry at the decision day's "
        "close, +8% target / -4% stop within 15 trading days, a day touching both counts as the stop. "
        "Gross: no costs, no slippage, no half-out."
    ),
    "net_after_costs": (
        "Computed now from stored daily prices (walk_forward.outcomes_for -> replay_scoring.strict_score), "
        "evidence-defs-v1: next-day open entry, +8% / -4%, half out at +5%, 15 trading days, slippage and "
        "charges from services/costs.py. Not a stored record."
    ),
    "every_stock": (
        "evidence-defs-v1: every stock the brain looked at on the days it picked, same rule and costs. "
        "Computed now."
    ),
    "random_5": (
        f"evidence-defs-v1: {defs.TOP_N} random stocks a day from that pool, {defs.TRADE_RANDOM_DRAWS} "
        f"draws (seed {defs.RANDOM_SEED}); the average of the draws and where the middle 90% sits. "
        "Computed now."
    ),
    "momentum_5": (
        f"evidence-defs-v1: the {defs.TOP_N} stocks with the highest {defs.MOMENTUM_BARS}-day return at "
        "the decision close, chosen from the stocks the brain looked at that day; same rule and costs. "
        "Computed now."
    ),
    "nifty_matched": (
        "evidence-defs-v1: NIFTY 50 bought at the open after each idea's decision and sold at the close "
        "of that idea's own exit day, per idea, with the same slippage and charges. A comparison only, "
        "not an index strategy anyone could run. Computed now."
    ),
    "cash": "Cash: 0%.",
    "edge": (
        "evidence-defs-v1: the average daily gap between the brain's picks and every stock, with a "
        f"block-bootstrap lower bound once there are {defs.MIN_CONFIDENCE_DAYS} trading days with ideas. "
        "Computed now."
    ),
    "costs": (
        f"services/costs.py: slippage {settings.PAPER_SLIPPAGE_BPS} bps per side, brokerage "
        f"Rs {settings.PAPER_BROKERAGE_PER_ORDER} per order, statutory charges per side, a flat depository "
        "fee on sells. Not yet checked against real Zerodha contract notes (tracker task bx5)."
    ),
}
NOTE = (
    f"{LABEL}. Stored grades are gross (no costs). Every other figure is computed now from stored prices, "
    f"under {defs.EVIDENCE_DEFS_VERSION}, and is not a stored record."
)


# --- stored grades ----------------------------------------------------------------------------------


def stored_grades(rows) -> dict:
    """Stored M09 grades. Rows are (outcome, return, ...); only the first two items are read."""
    graded = [(r[0], r[1]) for r in rows if r[0] and r[0] != "noscore"]
    base = {"source": SOURCES["stored_grade"], "gross": True}
    if not graded:
        return {
            **base,
            "available": False,
            "why": "No finished, graded ideas in these days.",
            "count": 0,
            "by_outcome": {},
            "avg_gross_return": None,
        }
    by: dict[str, int] = {}
    for outcome, _ in graded:
        by[outcome] = by.get(outcome, 0) + 1
    returns = [r for _, r in graded if r is not None]
    return {
        **base,
        "available": True,
        "count": len(graded),
        "by_outcome": by,
        "avg_gross_return": sum(returns) / len(returns) if returns else None,
    }


# --- stage rule -------------------------------------------------------------------------------------


def stage_on_day(history: list[tuple], day: date) -> str:
    """M18 stage at the end of that IST day: the latest change before it, or `shadow` when none (fail
    closed, as services/brain_golive/stage.current_stage)."""
    _, end = day_window(day)
    stage = PRACTICE_STAGE
    for changed_at, s in history:  # history is ordered by time
        if changed_at < end:
            stage = s
    return stage


# --- loading and computing --------------------------------------------------------------------------


def _journal(
    db, start: date, end: date, *, live: bool, book: str, stage_filter: str | None, with_journal: bool = True
):
    """Sessions, bounded bars and the trial journal's own journal + gate. Returns (journal, ctx, error);
    ctx carries what the baselines need. Fixed number of statements, however long the range. The journal
    (and its gate) is the slow part, so `build`, which only needs the loaded data, skips it."""
    from swing_trade_ml.brain.trial_journal import build_journal, gate

    ctx: dict = {"sessions": [], "bars": {}, "index_bars": None, "excluded_days": None}
    try:
        sessions = queries.nightly_sessions(db, start, end, live=live, book=book)
        ctx["excluded_days"] = 0
        if stage_filter is not None:
            history = queries.stage_history(db)
            kept = [s for s in sessions if stage_on_day(history, s.day) == stage_filter]
            ctx["excluded_days"], sessions = len(sessions) - len(kept), kept
        ctx["sessions"] = sessions
        symbols = sorted({i.symbol for s in sessions for i in s.ideas})
        lo, hi = start - timedelta(days=BARS_BEFORE_DAYS), end + timedelta(days=BARS_AFTER_DAYS)
        bars = queries.daily_bars(db, symbols, lo, hi)
        index = settings.BENCHMARK_INDEX_SYMBOL
        index_bars = queries.daily_bars(db, [index], lo, hi).get(index)
        ctx["bars"], ctx["index_bars"] = bars, index_bars
        if not with_journal:
            return {}, ctx, None
        journal = build_journal(sessions, bars, {}, index_bars=index_bars)
        journal["gate"] = gate(journal)
        return journal, ctx, None
    except Exception as exc:  # noqa: BLE001 — shown to the owner as 'not available', never hidden
        return None, ctx, redact_text(f"{type(exc).__name__}: {exc}")


def _picks(sessions) -> tuple[dict, dict]:
    """The brain's TRADE ideas per day (the candidate) and every stock it looked at (the pool)."""
    candidate = {s.day: sorted(i.symbol for i in s.ideas if i.word == "TRADE") for s in sessions}
    pool = {s.day: sorted({i.symbol for i in s.ideas}) for s in sessions}
    return candidate, pool


def _unavailable(why: str, source: str) -> dict:
    return {"available": False, "why": why, "source": source}


def _unavailable_all(why: str) -> dict:
    out: dict = {
        "defs": defs.EVIDENCE_DEFS_VERSION,
        "label": LABEL,
        "costs": SOURCES["costs"],
        "cash": {"available": True, "avg_net": 0.0, "source": SOURCES["cash"]},
        "edge": _unavailable(why, SOURCES["edge"]),
    }
    for key in ("candidate", "every_stock", "random_5", "momentum_5", "nifty_matched"):
        out[key] = _unavailable(why, SOURCES["net_after_costs" if key == "candidate" else key])
    return out


def _summary_row(row: dict, source: str, none_why: str) -> dict:
    if row.get("finished") and row.get("avg_net") is not None:
        return {"available": True, "source": source, **row}
    detail = []
    if row.get("open"):
        detail.append(f"{row['open']} still open")
    if row.get("no_data"):
        detail.append(f"{row['no_data']} with no price data")
    suffix = f" ({', '.join(detail)})" if detail else ""
    return {**row, **_unavailable(f"{none_why}{suffix}", source)}


def computed_figures(ctx: dict, error: str | None) -> dict:
    """evidence-defs-v1 trade-level figures for the loaded sessions. Never zero for missing data."""
    if error is not None:
        return _unavailable_all(f"The figures could not be computed: {error}")
    sessions = ctx["sessions"]
    if not sessions:
        return _unavailable_all("No brain runs of this category in these days.")
    candidate, pool = _picks(sessions)
    if not any(candidate.values()):
        return _unavailable_all("The brain made no TRADE ideas in these days.")
    try:
        t = baselines.trade_level(candidate, pool, ctx["bars"], ctx["index_bars"])
    except Exception as exc:  # noqa: BLE001
        return _unavailable_all(
            f"The figures could not be computed: {redact_text(f'{type(exc).__name__}: {exc}')}"
        )
    none_yet = "No finished ideas yet in these days"
    out = _unavailable_all("")
    out["candidate"] = _summary_row(t["candidate"], SOURCES["net_after_costs"], none_yet)
    out["every_stock"] = _summary_row(t["every_stock"], SOURCES["every_stock"], none_yet)
    out["momentum_5"] = _summary_row(t["momentum_5"], SOURCES["momentum_5"], none_yet)
    r = t["random_5"]
    out["random_5"] = (
        {"available": True, "source": SOURCES["random_5"], **r}
        if r["draws"] and r["avg_net_mean"] is not None
        else {**r, **_unavailable(none_yet, SOURCES["random_5"])}
    )
    n = t["nifty_matched"]
    if ctx["index_bars"] is None or ctx["index_bars"].empty:
        out["nifty_matched"] = {
            **n,
            **_unavailable("No NIFTY 50 prices are stored for these days.", SOURCES["nifty_matched"]),
        }
    else:
        out["nifty_matched"] = _summary_row(n, SOURCES["nifty_matched"], none_yet)
    e = t["edge"]
    out["edge"] = (
        {"available": True, "source": SOURCES["edge"], **e}
        if e["days"]
        else {
            **e,
            **_unavailable(
                "No day has both finished brain ideas and finished every-stock ideas.", SOURCES["edge"]
            ),
        }
    )
    out["coverage"] = t["coverage"]
    return out


# --- forward gate -----------------------------------------------------------------------------------


def forward_word(gate_row: dict) -> str:
    """Never 'Proven': the forward gate (layer-2 draft 5a) is adopted for now, not a frozen protocol."""
    if gate_row["word"] == "too early":
        return FORWARD_INSUFFICIENT
    return f"Forward gate (not frozen): {gate_row['word']}"


def official_forward_gate(db, today: date) -> dict:
    """The forward gate (layer-2 draft 5a) over the established trial cohort only: TRIAL_START to today,
    the same cohort as brain/trial_journal.journal_for (live nightly runs, book = TRADING_MODE, the latest
    run per IST day) and the same gate. Never uses the page's date range."""
    from swing_trade_ml.brain.trial_journal import TRIAL_START

    out = {
        "cohort_from": TRIAL_START.isoformat(),
        "cohort_to": today.isoformat(),
        "cohort": "live nightly brain runs, book = TRADING_MODE, from TRIAL_START (brain/trial_journal.py)",
        "label": LABEL,
    }
    journal, _ctx, error = _journal(
        db, TRIAL_START, today, live=True, book=settings.TRADING_MODE, stage_filter=None
    )
    if journal is None:
        return {
            "word": FORWARD_INSUFFICIENT,
            "why": f"The figures could not be computed: {error}",
            "available": False,
            **out,
            "gate": None,
        }
    gate_row = journal["gate"]
    if gate_row["word"] == "too early":
        why = "Fewer than 15 sessions or 30 finished TRADE ideas."
    else:
        why = (
            "The forward gate (layer-2 draft 5a) is adopted for now but is not a frozen protocol, "
            "so it can never show Proven."
        )
    return {"word": forward_word(gate_row), "why": why, "available": True, **out, "gate": gate_row}


# --- the one function -------------------------------------------------------------------------------


def build(db, start: date, end: date, category: str) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    if category == "paper":
        return {
            "category": "paper",
            "available": False,
            "label": LABEL,
            "why": "v1 paper trades are not brain decisions; they are not shown in Phase 1A and are never "
            "added to brain results.",
        }
    live = category == "practice"
    stage_filter = PRACTICE_STAGE if live else None
    history = queries.stage_history(db) if live else []
    rows = [
        r
        for r in queries.stored_grade_rows(db, start, end, live)
        if r[3] == BOOK and (stage_filter is None or stage_on_day(history, run_day(r[2])) == stage_filter)
    ]
    _, ctx, error = _journal(
        db, start, end, live=live, book=BOOK, stage_filter=stage_filter, with_journal=False
    )
    return {
        "category": category,
        "available": True,
        "label": LABEL,
        "note": NOTE,
        "stored_grades": stored_grades(rows),
        "computed": computed_figures(ctx, error),
        "excluded": {
            "other_stage_days": ctx["excluded_days"],
            "other_book_runs": queries.other_book_runs(db, start, end, live=live, book=BOOK),
        },
    }
