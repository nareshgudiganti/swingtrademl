# ruff: noqa: E501, N803, N806, N812 (long plain-English sentences; short P alias as in the h05 modules)
"""One forward-performance report over the 5-, 10- and 15-day tests, in one shape. Read-only.

5-day comes from the h05 tables, 10- and 15-day from `lane_picks` / `lane_outcomes`. It adds NO new thresholds and
NO new verdict logic: "enough days" and the wording of a reading are the existing ones (h05 protocol
`min_evidence_per_group.matured_signal_days`; lane review `CHECKPOINTS[0]` and `lane_review.reading`). A software
test passing is not a model validation, and a fold model of the 15-day lab is not a daily-inference model.

Returns are FRACTIONS (0.012 means 1.2%). The NIFTY 50 figure is a plain buy-and-hold over the same windows
(next session's open to the exit day's close), with no costs, so it is a yardstick and not a tradable result.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from statistics import fmean
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.services.model_registry import role_of

IST = "Asia/Kolkata"

NOTE = (
    "Test records only: not trades and not advice. Software tests passing does not prove a model works; only "
    "enough finished picks, judged against the same stocks' own average, can show that."
)
NIFTY_NOTE = (
    "NIFTY 50 comparison = buying the index at the next session's open and holding to the same exit day, no costs. "
    "A yardstick, not something the bot trades."
)
EXCESS_NOTE_5D = "5-day edge = the picks' average minus every eligible stock's average, per signal day (the 5-day test's own measure)."
EXCESS_NOTE_LANES = "10- and 15-day edge = each pick minus the average of every eligible stock of the same size group on the same day."

ROLE_LABELS = {
    "fold": "Evaluation fold model - not used for daily picks",
    "final": "Final model",
    "prod": "Existing production model (under test; not a frozen final model)",
    "unmarked": "Not marked (cannot be used for daily picks)",
}

# the order shown to the owner: (key, horizon, cap group, source, lane slot)
ROWS = (
    ("5d-large", 5, "large", "h05", None),
    ("5d-mid", 5, "mid", "h05", None),
    ("5d-small", 5, "small", "h05", None),
    ("10d-large", 10, "large", "lanes", "10d-large"),
    ("15d-large", 15, "large", "lanes", "15d-large"),
    ("15d-mid", 15, "mid", "lanes", "15d-midcap"),
)

#: the history test each lane slot is qualified by (names only; results live in the signed evidence files)
LANE_PROTOCOLS = {
    "10d-large": "td-protocol-v1",
    "15d-large": "sl-protocol-v1 (candidates S0, S1, S2)",
    "15d-midcap": "sl-protocol-v1 (candidates S0M, S1M, S2M)",
}
LAB_START_NOTE = "before 5 Dec 2026 (signed Amendment 2)"


# ------------------------------------------------------------------ pure helpers


def mean_or_none(values: list[float]) -> float | None:
    return fmean(values) if values else None


def window_return(
    bars: dict[date, tuple[float, float]], entry_day: date | None, exit_day: date | None
) -> float | None:
    """NIFTY buy-and-hold: close on the exit day over the open on the entry day, minus one. None if a bar is missing."""
    if entry_day is None or exit_day is None:
        return None
    entry, exit_ = bars.get(entry_day), bars.get(exit_day)
    if entry is None or exit_ is None or entry[0] <= 0:
        return None
    return exit_[1] / entry[0] - 1.0


def next_session(sessions: list[date], day: date) -> date | None:
    for s in sessions:
        if s > day:
            return s
    return None


def nifty_summary(
    windows: list[tuple[date | None, date | None]], bars: dict[date, tuple[float, float]]
) -> dict[str, Any]:
    rets = [r for r in (window_return(bars, e, x) for e, x in windows) if r is not None]
    if not bars:
        return {
            "available": False,
            "mean_return": None,
            "windows": 0,
            "note": "NIFTY 50 bars are not available here, so no index comparison is shown.",
        }
    if not rets:
        return {
            "available": True,
            "mean_return": None,
            "windows": 0,
            "note": "No finished window to compare yet.",
        }
    return {"available": True, "mean_return": fmean(rets), "windows": len(rets), "note": None}


def role_view(model: Any) -> dict[str, Any] | None:
    if model is None:
        return None
    r = role_of(model)
    return {
        "id": model.id,
        "name": model.name,
        "version": model.version,
        "role": r["role"],
        "role_recorded": r["recorded"],
        "role_label": ROLE_LABELS[r["role"]],
        "daily_picks_allowed": r["role"] == "final",
    }


# ------------------------------------------------------------------ database glue


def _ist_day(ts) -> date:
    t = pd.Timestamp(ts)
    return t.tz_convert(IST).date() if t.tzinfo else t.date()


def nifty_bars(db: Session) -> tuple[dict[date, tuple[float, float]], list[date]]:
    """{IST day: (open, close)} of the benchmark index, and its sessions ascending. Empty if absent."""
    rows = db.execute(
        select(Candle.ts, Candle.open, Candle.close)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL, Candle.interval == "day")
        .order_by(Candle.ts.asc())
    ).all()
    bars = {_ist_day(r.ts): (float(r.open), float(r.close)) for r in rows}
    return bars, sorted(bars)


def _lane_qualification(slot_key: str, model, history: dict) -> dict[str, Any]:
    protocol = LANE_PROTOCOLS[slot_key]
    qual = (
        (model.metrics or {}).get("qualification")
        if model is not None and isinstance(model.metrics, dict)
        else None
    )
    if model is not None and role_of(model)["role"] == "final" and isinstance(qual, dict):
        return {
            "state": "qualified",
            "protocol": protocol,
            "text": f"Qualified: frozen after a passed history test ({qual.get('candidate')}, frozen {qual.get('frozen_at')}).",
        }
    if history.get("available"):
        return {
            "state": "not_qualified",
            "protocol": protocol,
            "text": f"Not qualified yet: a history test is on file ({history.get('label')}), but no model has been frozen from it.",
        }
    when = f" It cannot start {LAB_START_NOTE}." if slot_key != "10d-large" else ""
    return {
        "state": "not_run",
        "protocol": protocol,
        "text": f"Not run: no history test is on file for this lane.{when}",
    }


def _lane_row(db: Session, key: str, horizon: int, group: str, slot: str, bars, sessions) -> dict[str, Any]:
    from swing_trade_ml.api.v1.endpoints import lanes as lane_api
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.shadow_lanes import lane_job, lane_review

    rows = lane_api._rows(db, slot)
    model = db.get(MLModel, rows[-1][0].model_id) if rows else lane_job.lane_model_for(db, slot)
    done = [(p, o) for p, o in rows if o is not None and o.net_return is not None]
    nets = [o.net_return for _, o in done]
    excess = [o.excess_return for _, o in done if o.excess_return is not None]
    matured_days = len({p.signal_day for p, _ in done})
    windows = [(next_session(sessions, p.signal_day), o.exit_day) for p, o in done]
    review = lane_review.build_review(db, slot, datetime.now(UTC).date())
    enough = matured_days >= lane_review.CHECKPOINTS[0] and len(done) >= lane_review.CHECKPOINTS[0]
    history = lane_api.history_for(slot)
    return {
        "key": key,
        "horizon_days": horizon,
        "cap_group": group,
        "source": "lanes",
        "model": role_view(model),
        "qualification": _lane_qualification(slot, model, history),
        "forward": {
            "matured_days": matured_days,
            "picks": len(rows),
            "finished": len(done),
            "net_per_trade": mean_or_none(nets),
            "edge_vs_every_stock": mean_or_none(excess),
            "hit_rate": (sum(1 for n in nets if n > 0) / len(nets)) if nets else None,
            "nifty": nifty_summary(windows, bars),
        },
        "verdict": {
            "state": "reading" if enough else "not_enough_days",
            "needed_days": lane_review.CHECKPOINTS[0],
            "text": review["reading"] if enough else "Not enough days to judge.",
            "rule": "lane review: first reading at 60 recorded sessions and 60 finished picks; descriptive only, never a promotion",
        },
    }


def _h05_rows(db: Session) -> tuple[dict[str, Any], dict[str, list[Any]], Any]:
    """(h05 report for the latest run, {group: counted pick rows}, protocol module)."""
    from swing_trade_ml.brain.lanes import h05_protocol as P
    from swing_trade_ml.brain.lanes import h05_report
    from swing_trade_ml.db.models.lanes import H05Run, H05Signal

    run = db.execute(select(H05Run).order_by(H05Run.run_no.desc()).limit(1)).scalars().first()
    if run is None:
        return {}, {}, P
    report = h05_report.build_report(db, run.run_no)
    picks: dict[str, list[Any]] = defaultdict(list)
    for s in db.execute(
        select(H05Signal).where(H05Signal.run_id == run.id, H05Signal.selected.is_(True))
    ).scalars():
        if not s.repeat_blocked:
            picks[s.group].append(s)
    return report, picks, P


def _h05_row(db: Session, key: str, horizon: int, group: str, report, picks, P, bars) -> dict[str, Any]:
    from swing_trade_ml.db.models.ml import MLModel

    run = report["runs"][0] if report.get("runs") else None
    expected = P.EXPECTED_MODELS[group]
    model = db.get(MLModel, expected["id"])
    earlier = P.EARLIER_EVIDENCE
    qualification = {
        "state": "not_qualified",
        "protocol": f"{earlier['protocol'].split(' ')[0]} (history), {P.PROTOCOL_CODE} (forward)",
        "text": f"Not qualified yet. Earlier history test: {earlier['result']}. The live 5-day test is the evidence being collected.",
    }
    needed = P.RUN_VALUES["min_evidence_per_group"]["matured_signal_days"]
    if run is None:
        return {
            "key": key,
            "horizon_days": horizon,
            "cap_group": group,
            "source": "h05",
            "model": role_view(model),
            "qualification": qualification,
            "forward": {
                "matured_days": 0,
                "picks": 0,
                "finished": 0,
                "net_per_trade": None,
                "edge_vs_every_stock": None,
                "hit_rate": None,
                "nifty": nifty_summary([], bars),
            },
            "verdict": {
                "state": "not_enough_days",
                "needed_days": needed,
                "text": "Not enough days to judge.",
                "rule": "h05 protocol",
            },
        }
    g = run["groups"][group]
    trade = g["shadow_trade"]["counted_picks"]
    edge = g["shadow_trade"]["daily_edge_vs_baseline"]
    windows = [
        (s.entry_day, s.exit_day)
        for s in picks.get(group, [])
        if s.trade_status in ("target", "stop", "expiry")
    ]
    matured_days = edge["days"]
    verdicts = (report.get("verdict") or {}) if report.get("protocol_accepted") else {}
    combined = (verdicts.get(group) or {}).get("combined") if isinstance(verdicts, dict) else None
    if matured_days < needed:
        verdict = {"state": "not_enough_days", "text": "Not enough days to judge."}
    elif combined is not None:
        verdict = {
            "state": "reading",
            "text": combined.get("reading") or "Verdict calculated from the frozen rule.",
        }
    else:
        verdict = {
            "state": "not_calculated",
            "text": report.get("verdict_note") or "No verdict is calculated yet.",
        }
    return {
        "key": key,
        "horizon_days": horizon,
        "cap_group": group,
        "source": "h05",
        "run_no": run["run_no"],
        "model": role_view(model),
        "qualification": qualification,
        "forward": {
            "matured_days": matured_days,
            "picks": g["counted_selections"],
            "finished": trade["finished"],
            "net_per_trade": trade["mean_net_return"],
            "edge_vs_every_stock": edge["mean"],
            "hit_rate": trade["win_rate"],
            "nifty": nifty_summary(windows, bars),
        },
        "verdict": {
            **verdict,
            "needed_days": needed,
            "rule": f"{P.PROTOCOL_CODE}: min_evidence_per_group.matured_signal_days",
        },
    }


def build(db: Session) -> dict[str, Any]:
    bars, sessions = nifty_bars(db)
    report, picks, P = _h05_rows(db)
    out = []
    for key, horizon, group, source, slot in ROWS:
        if source == "h05":
            out.append(_h05_row(db, key, horizon, group, report, picks, P, bars))
        else:
            out.append(_lane_row(db, key, horizon, group, slot, bars, sessions))
    return {
        "note": NOTE,
        "nifty_note": NIFTY_NOTE,
        "edge_notes": [EXCESS_NOTE_5D, EXCESS_NOTE_LANES],
        "fold_model_note": (
            "The 15-day lab trains one model per test fold (246 in all). Those fold models only measure ranking skill "
            "in the history test; they never make daily picks. A daily lane uses one frozen final model."
        ),
        "horizons": out,
    }
