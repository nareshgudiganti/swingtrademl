# ruff: noqa: E501 (long explanatory lines)
"""Shared shadow lanes (10-day large, 15-day large, 15-day mid): owner-only, read-only.

GET only. It reads `lane_picks` / `lane_outcomes`, the model registry and stored report files, and writes
nothing. Every return, hit rate, excess, drawdown and uncertainty value is a FRACTION (0.012 means 1.2%);
mean_ic and lower_bound are raw correlations. A pick here is a test record, never a trade or advice; a review never promotes anything."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession, require_owner
from swing_trade_ml.core.config import REPO_ROOT
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.services.model_registry import role_of
from swing_trade_ml.shadow_lanes import lane_job
from swing_trade_ml.shadow_lanes.lane_service import SLOTS

router = APIRouter(prefix="/research/lanes", tags=["lanes"], dependencies=[Depends(require_owner)])

NOTE = (
    "Test picks only. Not trades and not advice. Each lane is judged on its own, against all eligible "
    "stocks of the same size group. A review never promotes a model."
)
MID_WARNING = "Limited experiment: about 14 mid-cap stocks. Sample-size limits are large; not a basis for trading approval."
SMALL_SAMPLE = "Fewer than 60 completed picks: too early to judge."
REVIEW_AFTER = 60
BOOTSTRAP_MIN = 30
DRAWDOWN_NOTE = "Drawdown is pick-level (largest fall of the running sum of completed picks' net returns). It is NOT a portfolio drawdown."
EVIDENCE = REPO_ROOT / "docs" / "brain" / "evidence"


# ------------------------------------------------------------------ pure helpers


def pick_drawdown(nets_in_order: list[float]) -> float | None:
    """Largest fall of the running sum, as a negative number (0.0 if it never falls)."""
    if not nets_in_order:
        return None
    run = peak = 0.0
    worst = 0.0
    for n in nets_in_order:
        run += n
        peak = max(peak, run)
        worst = min(worst, run - peak)
    return worst


def bootstrap_interval(
    by_day: list[list[float]], horizon: int, draws: int = 1000
) -> tuple[float, float] | None:
    """5th-95th percentile of the mean net return, resampling moving blocks of `horizon` signal days (seed 7)."""
    n_picks = sum(len(d) for d in by_day)
    if n_picks < BOOTSTRAP_MIN or not by_day:
        return None
    rng = np.random.default_rng(7)
    n_days = len(by_day)
    block = max(1, min(horizon, n_days))
    n_blocks = math.ceil(n_days / block)
    starts_max = n_days - block
    means = []
    for _ in range(draws):
        vals: list[float] = []
        for s in rng.integers(0, starts_max + 1, size=n_blocks):
            for day in by_day[int(s) : int(s) + block]:
                vals.extend(day)
        if vals:
            means.append(sum(vals) / len(vals))
    if not means:
        return None
    return float(np.percentile(means, 5)), float(np.percentile(means, 95))


def lane_status(sessions: int, completed: int) -> str:
    if sessions == 0:
        return "history_only"
    if sessions < REVIEW_AFTER:
        return "forward_watching"
    return "review_due" if completed >= REVIEW_AFTER else "inconclusive"


# ------------------------------------------------------------------ history (stored reports, read only)


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) else None


def _get(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _empty_history(note: str | None = None) -> dict:
    return {
        "available": False,
        "label": None,
        "ranking": {"mean_ic": None, "lower_bound": None, "days": None},
        "after_cost": {"mean_net_return": None, "trades": None},
        "benchmark_excess": None,
        "drawdown": None,
        "note": note,
    }


def history_for(slot_key: str, root: Path = EVIDENCE) -> dict:
    out = _empty_history()
    if slot_key == "10d-large":
        files = sorted((root / "td_v1").glob("ten_day_*.json")) if (root / "td_v1").is_dir() else []
        rep = _load(files[-1]) if files else None
        if rep is None:
            return out
        model_avg = _num(_get(rep, "pooled", "model", "avg_net"))
        every = _num(_get(rep, "pooled", "every_stock", "avg_net"))
        out.update(
            available=True,
            label=rep.get("label") if isinstance(rep.get("label"), str) else None,
            after_cost={"mean_net_return": model_avg, "trades": _get(rep, "pooled", "model", "ideas")},
            benchmark_excess=(model_avg - every) if model_avg is not None and every is not None else None,
            drawdown=_num(_get(rep, "benchmarks", "accounts", "best_5", "max_drawdown")),
            note=_get(rep, "verdict", "economic", "word")
            if isinstance(_get(rep, "verdict", "economic", "word"), str)
            else None,
        )
        return out
    mid = slot_key.endswith("midcap")
    base = root / "sl_v1"
    if not base.is_dir():
        return out
    dirs = [d for d in sorted(base.iterdir()) if d.is_dir() and (d / "metrics.json").is_file()]
    dirs = [d for d in dirs if bool(re.search(r"(M|mid)(?![a-z])", d.name)) == mid]
    rep = _load(dirs[-1] / "metrics.json") if dirs else None
    if rep is None:
        return out
    out.update(
        available=True,
        label=f"15-day ranking test ({dirs[-1].name})",
        ranking={
            "mean_ic": _num(_get(rep, "r1", "mean_ic")),
            "lower_bound": _num(_get(rep, "r1", "lower_bound")),
            "days": _get(rep, "r1", "days") if isinstance(_get(rep, "r1", "days"), int) else None,
        },
    )
    return out


# ------------------------------------------------------------------ views


def _rows(db, slot_key: str):
    return db.execute(
        select(LanePick, LaneOutcome)
        .outerjoin(LaneOutcome, LaneOutcome.pick_id == LanePick.id)
        .where(LanePick.slot_key == slot_key)
        .order_by(LanePick.signal_day, LanePick.rank)
    ).all()


def forward_view(rows: list, horizon: int, cap_group: str) -> tuple[dict, int, int]:
    picks = len(rows)
    done = [(p, o) for p, o in rows if o is not None and o.net_return is not None]
    open_n = sum(1 for _, o in rows if o is None)
    nets = [o.net_return for _, o in done]
    excess = [o.excess_return for _, o in done if o.excess_return is not None]
    sessions = len({p.signal_day for p, _ in rows})
    by_day: dict[date, list[float]] = {}
    for p, o in done:
        by_day.setdefault(p.signal_day, []).append(o.net_return)
    interval = bootstrap_interval([by_day[d] for d in sorted(by_day)], horizon)
    warnings = []
    if cap_group == "mid":
        warnings.append(MID_WARNING)
    if len(done) < REVIEW_AFTER:
        warnings.append(SMALL_SAMPLE)
    view = {
        "picks": picks,
        "completed": len(done),
        "open": open_n,
        "hit_rate": (sum(1 for n in nets if n > 0) / len(nets)) if nets else None,
        "mean_net_return": (sum(nets) / len(nets)) if nets else None,
        "benchmark_excess": (sum(excess) / len(excess)) if excess else None,
        "drawdown": pick_drawdown(
            [o.net_return for p, o in sorted(done, key=lambda po: (po[0].signal_day, po[0].rank))]
        ),
        "uncertainty": {"low": interval[0], "high": interval[1]} if interval else {"low": None, "high": None},
        "sample_warning": " ".join(warnings) or None,
        "review": {
            "due_after_sessions": REVIEW_AFTER,
            "sessions_done": sessions,
            "state": "due" if sessions >= REVIEW_AFTER else "not_due",
        },
    }
    return view, sessions, len(done)


def build_lanes(db) -> dict[str, Any]:
    lanes = []
    for slot_key, (horizon, group) in SLOTS.items():
        rows = _rows(db, slot_key)
        forward, sessions, completed = forward_view(rows, horizon, group)
        model = db.get(MLModel, rows[-1][0].model_id) if rows else None
        if model is None:
            model = lane_job.lane_model_for(db, slot_key)
        history = history_for(slot_key)
        lanes.append(
            {
                "slot_key": slot_key,
                "horizon_days": horizon,
                "cap_group": group,
                "model": (
                    {"id": model.id, "name": model.name, "version": model.version, "role": role_of(model)}
                    if model
                    else None
                ),
                "status": lane_status(sessions, completed),
                "started_on": rows[0][0].signal_day.isoformat() if rows else None,
                "sessions_recorded": sessions,
                "history": history,
                "forward": forward,
            }
        )
    return {"note": NOTE + " " + DRAWDOWN_NOTE, "lanes": lanes}


@router.get("")
def lanes(db: DbSession) -> dict[str, Any]:
    return build_lanes(db)


@router.get("/{slot_key}/picks")
def lane_picks(
    slot_key: str, db: DbSession, limit: int = Query(default=100, ge=1, le=1000)
) -> list[dict[str, Any]]:
    if slot_key not in SLOTS:
        raise HTTPException(status_code=404, detail="unknown lane")
    rows = db.execute(
        select(LanePick, LaneOutcome)
        .outerjoin(LaneOutcome, LaneOutcome.pick_id == LanePick.id)
        .where(LanePick.slot_key == slot_key)
        .order_by(LanePick.signal_day.desc(), LanePick.cap_group, LanePick.rank)
        .limit(limit)
    ).all()
    return [
        {
            "signal_day": p.signal_day.isoformat(),
            "symbol": p.symbol,
            "cap_group": p.cap_group,
            "rank": p.rank,
            "score": p.score,
            "model_version": p.model_version,
            "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
            "status": o.status if o is not None else "open",
            "net_return": o.net_return if o is not None else None,
            "excess_return": o.excess_return if o is not None else None,
        }
        for p, o in rows
    ]
