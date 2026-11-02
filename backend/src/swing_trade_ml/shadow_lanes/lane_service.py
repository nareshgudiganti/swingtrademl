# ruff: noqa: E501 (long explanatory lines)
"""Shared daily shadow lanes (10-day large, 15-day large, 15-day mid): record the day's top 5, score matured picks.

Evaluation only. It reads candles and one registered model, and writes only `lane_picks` / `lane_outcomes`
(append-only in the database). It never changes `ml_models` (no activation, no status change), never places an
order and imports nothing from the brain modules, risk, execution, brokers, strategies or the h05 lane.

Rules are pinned here and nowhere else:
- 10D: next-session-open entry, +6% target, -3.5% stop, no half-out, 10 sessions, fills 0.05% worse.
- 15D: next-session-open entry, +8% target, -4% stop, half out at +5%, 15 sessions, fills 0.05% worse.
A bar that touches both levels is counted as the stop and flagged ambiguous.
The baseline of a pick is the mean net return of ALL eligible stocks of its cap group, entered the same day
under the same rule: the market-cap-appropriate benchmark.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import swing_trade_ml.brain.ten_day  # noqa: F401 - imported first: replay_scoring has an import cycle that only resolves from here
from swing_trade_ml.brain.replay_scoring import CostStress, StrictOutcome, strict_score
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import last_closed_trading_day, next_trading_day
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.services.costs import apply_slippage
from swing_trade_ml.services.model_registry import slot_for

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

TOP_N = 5
EXTRA_SLIP = 0.0005
STRESS = CostStress(extra_slip=EXTRA_SLIP)
GROSS = CostStress(charges_x=0.0, extra_slip=0.0)  # same rule, brokerage and taxes removed (slippage kept)

#: slot -> (horizon in sessions, cap group)
SLOTS: dict[str, tuple[int, str]] = {
    "10d-large": (10, "large"),
    "15d-large": (15, "large"),
    "15d-midcap": (15, "mid"),
}
#: horizon -> pinned trade rule
RULES: dict[int, dict] = {
    10: {"target": 0.06, "stop": 0.035, "half_out": None},
    15: {"target": 0.08, "stop": 0.04, "half_out": 0.05},
}


class LaneError(Exception):
    """A day cannot be recorded; nothing was written."""


# ------------------------------------------------------------------ pure helpers


def slot_parts(slot_key: str) -> tuple[int, str]:
    if slot_key not in SLOTS:
        raise LaneError(f"unknown lane slot {slot_key!r}")
    return SLOTS[slot_key]


def rank_top(scored: list[tuple[str, float]], n: int = TOP_N) -> list[tuple[str, float, int]]:
    """Top `n` by score descending, ties broken by symbol ascending. Non-finite scores are ignored."""
    ok = [(s, float(p)) for s, p in scored if p is not None and math.isfinite(p)]
    ok.sort(key=lambda sp: (-sp[1], sp[0]))
    return [(s, p, i + 1) for i, (s, p) in enumerate(ok[:n])]


def entry_open_time(signal_day: date) -> datetime:
    d = next_trading_day(signal_day)
    return datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)


def maturity_window(sessions: list[date], signal_day: date, horizon: int) -> list[date] | None:
    """The `horizon` sessions starting at the entry session (first session after the signal day), or None
    while they have not all happened yet."""
    after = [d for d in sessions if d > signal_day]
    return after[:horizon] if len(after) >= horizon else None


def exit_fill_before_slippage(status: str, fill: float, row: pd.Series, rule: dict) -> float | None:
    o = float(row["open"])
    if status == "stop":
        px = fill * (1 - rule["stop"])
        return o if o <= px else px
    if status == "target":
        px = fill * (1 + rule["target"])
        return o if o >= px else px
    if status == "timeout":
        return float(row["close"])
    return None


@dataclass(frozen=True)
class Scored:
    status: str  # target | stop | timeout | unresolved
    net: float | None
    gross: float | None
    entry_fill: float | None
    exit_day: date | None
    exit_fill: float | None
    sessions_held: int | None
    ambiguous: bool


def score_window(bars: pd.DataFrame, horizon: int) -> Scored:
    """Score one stock over its (already cut) window under the pinned rule. `bars`: day, open, high, low, close,
    first row = entry session. Fewer than `horizon` bars and no earlier exit -> unresolved."""
    rule = RULES[horizon]
    kw = {"horizon": horizon, "target": rule["target"], "stop": rule["stop"], "half_out": rule["half_out"]}
    out: StrictOutcome = strict_score(bars, stress=STRESS, **kw)
    if out.status == "open" or out.net_return is None:
        return Scored("unresolved", None, None, None, None, None, None, False)
    gross = strict_score(bars, stress=GROSS, **kw).net_return
    fill = apply_slippage(float(bars.iloc[0]["open"]), "BUY") * (1 + EXTRA_SLIP)
    row = bars[bars["day"] == out.exit_day].iloc[0]
    ambiguous = out.status == "stop" and float(row["high"]) >= fill * (1 + rule["target"])
    return Scored(
        out.status,
        out.net_return,
        gross,
        fill,
        out.exit_day,
        exit_fill_before_slippage(out.status, fill, row, rule),
        out.days,
        ambiguous,
    )


def group_baseline(nets: list[float | None]) -> float | None:
    vals = [n for n in nets if n is not None and math.isfinite(n)]
    return sum(vals) / len(vals) if vals else None


# ------------------------------------------------------------------ data access


def _ist_day(ts) -> date:
    t = pd.Timestamp(ts)
    return t.tz_convert(IST).date() if t.tzinfo else t.date()


def market_sessions(db: Session) -> list[date]:
    """Market sessions = the NIFTY 50 daily bars, as IST dates, ascending (read directly, not from a cache)."""
    rows = db.execute(
        select(Candle.ts)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL, Candle.interval == "day")
        .order_by(Candle.ts.asc())
    ).scalars()
    return sorted({_ist_day(t) for t in rows})


def _asof_scorer(db: Session, inst: Instrument, model: MLModel, signal_day: date) -> float | None:
    from swing_trade_ml.ml import asof

    return asof.score_series(db, inst, model, signal_day - timedelta(days=1)).get(signal_day)


Scorer = Callable[[Session, Instrument, MLModel, date], "float | None"]


def _instrument(db: Session, symbol: str) -> Instrument | None:
    return db.scalar(
        select(Instrument).where(Instrument.exchange == "NSE", Instrument.tradingsymbol == symbol)
    )


def _window_bars(db: Session, instrument_id: int, window: list[date]) -> pd.DataFrame:
    """Only the bars of the window sessions: nothing after maturity is ever read."""
    lo = datetime(window[0].year, window[0].month, window[0].day, tzinfo=UTC) - timedelta(days=1)
    hi = datetime(window[-1].year, window[-1].month, window[-1].day, tzinfo=UTC) + timedelta(days=2)
    rows = db.execute(
        select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close)
        .where(
            Candle.instrument_id == instrument_id, Candle.interval == "day", Candle.ts >= lo, Candle.ts < hi
        )
        .order_by(Candle.ts.asc())
    ).all()
    wanted = set(window)
    recs = [
        {
            "day": _ist_day(r.ts),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
        }
        for r in rows
        if _ist_day(r.ts) in wanted
    ]
    return pd.DataFrame(recs, columns=["day", "open", "high", "low", "close"])


# ------------------------------------------------------------------ recording


def record_day(
    db: Session,
    model: MLModel,
    slot_key: str,
    cap_groups: dict[str, list[str]],
    signal_day: date,
    now: datetime | None = None,
    *,
    scorer: Scorer | None = None,
    min_ready_share: float = 0.0,
    extra_flags: dict | None = None,
) -> dict:
    """Score the eligible stocks of each cap group with `model` and record the top 5 per group.

    `cap_groups`: {"large": [symbols], ...}; only the slot's own cap group is accepted. Idempotent: a model
    and signal day that already have picks are left exactly as they are. The `ml_models` row is never touched."""
    horizon, group = slot_parts(slot_key)
    if set(cap_groups) - {group}:
        raise LaneError(f"slot {slot_key} takes only the {group!r} cap group")
    if model.id is None or slot_for(model.name, model.prediction_horizon_days) != slot_key:
        raise LaneError(f"model {model.name!r} is not registered for slot {slot_key}")
    moment = now or datetime.now(UTC)
    if signal_day > last_closed_trading_day(moment):
        raise LaneError("the signal session has not closed yet")
    if moment >= entry_open_time(signal_day):
        raise LaneError(
            "the entry session has already opened: a selection is stored before its entry, never after"
        )
    if db.scalar(
        select(LanePick.id).where(LanePick.model_id == model.id, LanePick.signal_day == signal_day).limit(1)
    ):
        return {"recorded": 0, "skipped": True, "groups": {}}

    score_fn = scorer or _asof_scorer
    rule = RULES[horizon]
    entry_assumption = {
        "entry": "next_session_open",
        "slippage_bps_per_side": float(settings.PAPER_SLIPPAGE_BPS),
        "extra_slip_bps": EXTRA_SLIP * 10_000,
    }
    symbols = sorted({s.upper() for s in cap_groups.get(group, [])})
    scored: list[tuple[str, float]] = []
    for sym in symbols:
        inst = _instrument(db, sym)
        if inst is None or not inst.is_active:
            continue
        p = score_fn(
            db, inst, model, signal_day
        )  # None = under 220 bars, no candle that day, or unusable features
        if p is not None and math.isfinite(p):
            scored.append((sym, float(p)))
    if symbols and len(scored) / len(symbols) < min_ready_share:
        raise LaneError(
            f"only {len(scored)} of {len(symbols)} stocks are scoreable: the day's data is not ready"
        )
    top = rank_top(scored)
    flags = {"eligible_n": len(scored), "eligible_symbols": sorted(s for s, _ in scored), **(extra_flags or {})}
    if len(top) < TOP_N:
        flags["shortfall"] = TOP_N - len(top)
    try:
        with db.begin_nested():
            for sym, p, rk in top:
                db.add(
                    LanePick(
                        model_id=model.id,
                        slot_key=slot_key,
                        horizon_days=horizon,
                        cap_group=group,
                        signal_day=signal_day,
                        symbol=sym,
                        rank=rk,
                        score=p,
                        model_version=model.version,
                        recorded_at=moment,
                        entry_assumption=entry_assumption,
                        target_pct=rule["target"],
                        stop_pct=rule["stop"],
                        flags=flags,
                    )
                )
    except IntegrityError:
        return {"recorded": 0, "skipped": True, "groups": {}}
    return {
        "recorded": len(top),
        "skipped": False,
        "groups": {
            group: {"eligible": len(scored), "picked": len(top), "shortfall": flags.get("shortfall", 0)}
        },
    }


# ------------------------------------------------------------------ outcomes


def evaluate_matured(db: Session, as_of: date) -> dict:
    """Insert one outcome for every pick whose horizon has matured by `as_of`. Never edits an outcome."""
    sessions = [d for d in market_sessions(db) if d <= as_of]
    open_picks = (
        db.execute(
            select(LanePick)
            .outerjoin(LaneOutcome, LaneOutcome.pick_id == LanePick.id)
            .where(LaneOutcome.id.is_(None))
            .order_by(LanePick.signal_day, LanePick.model_id, LanePick.rank)
        )
        .scalars()
        .all()
    )
    groups: dict[tuple, list[LanePick]] = {}
    for p in open_picks:
        groups.setdefault((p.model_id, p.slot_key, p.signal_day, p.cap_group, p.horizon_days), []).append(p)
    written = 0
    for (_, _, signal_day, _, horizon), picks in groups.items():
        window = maturity_window(sessions, signal_day, horizon)
        if window is None:
            continue
        eligible = list((picks[0].flags or {}).get("eligible_symbols") or [])
        eligible = sorted(set(eligible) | {p.symbol for p in picks})
        results: dict[str, Scored] = {}
        for sym in eligible:
            inst = _instrument(db, sym)
            bars = _window_bars(db, inst.id, window) if inst is not None else pd.DataFrame()
            results[sym] = score_window(bars, horizon)
        baseline = group_baseline([r.net for r in results.values()])
        for p in picks:
            r = results[p.symbol]
            excess = r.net - baseline if r.net is not None and baseline is not None else None
            db.add(
                LaneOutcome(
                    pick_id=p.id,
                    matured_day=window[-1],
                    status=r.status,
                    entry_fill=r.entry_fill,
                    exit_day=r.exit_day,
                    exit_fill=r.exit_fill,
                    sessions_held=r.sessions_held,
                    gross_return=r.gross,
                    net_return=r.net,
                    baseline_net_return=baseline,
                    excess_return=excess,
                    ambiguous=r.ambiguous,
                )
            )
            written += 1
    db.flush()
    return {"outcomes": written}
