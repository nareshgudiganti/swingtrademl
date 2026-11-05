# backend/src/swing_trade_ml/brain/lanes/h05_service.py
# ruff: noqa: E501, N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""The h05 lane: start a run, score a signal day, score finished outcomes. Evaluation only.

It reads candles and the three frozen production models, and writes only the h05_* tables. No broker, no
order, no portfolio slot, no brain table. Every writing function begins with `require_runnable()`, which
refuses unless the lane is enabled, the protocol is complete and the owner has accepted its hash.

One consistent failure rule (protocol RULES["lane_stop"]): if any frozen-model check fails for any group, the
WHOLE lane records nothing for that signal day, persists the reason as an event, and never substitutes
another model.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes.h05_features import score_training_basis
from swing_trade_ml.brain.lanes.h05_models import (
    VerifiedModel,
    assert_same_models,
    build_universe,
    verify_models,
)
from swing_trade_ml.brain.lanes.h05_parity import parity_report
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import last_closed_trading_day, next_trading_day
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml.market_context import load_index_candles
from swing_trade_ml.ml.predict import predict_instrument

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
RUN_NUMBERS = (1, 2, 3)


def entry_open_time(signal_day: date) -> datetime:
    """The moment the simulated entry fills: the open of the first trading day after the signal."""
    d = next_trading_day(signal_day)
    return datetime(d.year, d.month, d.day, *P.ENTRY_OPEN_IST, tzinfo=IST)


def _ist_day(ts) -> date:
    return pd.Timestamp(ts).tz_convert(IST).date() if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).date()


def market_sessions(db: Session) -> list[date]:
    """Market sessions = the NIFTY 50 daily bars, as IST dates, ascending."""
    df = load_index_candles(db, "day")
    return sorted({_ist_day(t) for t in df["ts"]}) if not df.empty else []


def _bars(db: Session, instrument_id: int, since: date) -> dict[date, R.Bar]:
    rows = db.execute(
        select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close)
        .where(Candle.instrument_id == instrument_id, Candle.interval == "day")
        .order_by(Candle.ts.asc())
    ).all()
    return {
        _ist_day(r.ts): (float(r.open), float(r.high), float(r.low), float(r.close))
        for r in rows
        if _ist_day(r.ts) >= since
    }


def _sha(parts) -> str:
    return hashlib.sha256(repr(parts).encode()).hexdigest()


# ------------------------------------------------------------------ runs


def start_run(db: Session, run_no: int, start_day: date, end_day: date) -> H05Run:
    """Create run 1, 2 or 3. Runs 2 and 3 must see exactly the models and universe frozen at run 1."""
    P.require_runnable()
    if run_no not in RUN_NUMBERS:
        raise P.ProtocolError("run_no must be 1, 2 or 3")
    if end_day < start_day:
        raise P.ProtocolError("the run ends before it starts")
    if db.scalar(select(H05Run).where(H05Run.run_no == run_no)) is not None:
        raise P.ProtocolError(f"run {run_no} already exists; a run is never restarted")
    if run_no > 1:
        previous = db.scalar(select(H05Run).where(H05Run.run_no == run_no - 1))
        if previous is None or previous.status != "closed":
            raise P.ProtocolError(f"run {run_no - 1} must exist and be closed first")
        if start_day <= previous.end_day:
            raise P.ProtocolError("a run must start after the previous run ended")
    models = verify_models(db)
    universe, excluded, universe_hash = build_universe(db)
    frozen = {g: m.identity() for g, m in models.items()}
    first = db.scalar(select(H05Run).where(H05Run.run_no == 1))
    if first is not None:
        assert_same_models(first.models, models)
        if first.universe_hash != universe_hash:
            raise P.ProtocolError(
                "the stock universe changed since run 1; the draft protocol freezes it (U9)"
            )
    parity = parity_report(db, models)
    if not parity["ok"]:
        raise P.ProtocolError(
            "feature parity failed: a saved model does not reproduce its own scaler on its training data"
        )
    run = H05Run(
        run_no=run_no,
        protocol_code=P.PROTOCOL_CODE,
        protocol_hash=P.protocol_hash(),
        status="active",
        start_day=start_day,
        end_day=end_day,
        models=frozen,
        universe={"groups": universe, "excluded": excluded},
        universe_hash=universe_hash,
        parity=parity,
    )
    db.add(run)
    db.flush()
    return run


def close_run(db: Session, run: H05Run) -> None:
    P.require_runnable()
    run.status = "closed"
    db.flush()


# ------------------------------------------------------------------ scoring a signal day


def _score_stock(db: Session, symbol: str, group: str, signal_day: date, model: VerifiedModel) -> dict:
    """One stock: a score, or NOT SCORED with the reason. Never another group's model, never a guess."""
    row = {"symbol": symbol, "group": group, "status": "not_scored", "not_scored_reason": None, "flags": []}
    inst = db.scalar(
        select(Instrument).where(Instrument.exchange == "NSE", Instrument.tradingsymbol == symbol)
    )
    if inst is None:
        return {**row, "not_scored_reason": "instrument_not_found"}
    row["instrument_id"] = inst.id
    if not inst.is_active:
        return {**row, "not_scored_reason": "instrument_inactive"}
    last_ts, n_bars = db.execute(
        select(func.max(Candle.ts), func.count()).where(
            Candle.instrument_id == inst.id, Candle.interval == "day"
        )
    ).one()
    if last_ts is None:
        return {**row, "not_scored_reason": "no_candles"}
    last_day = _ist_day(last_ts)
    if last_day < signal_day:
        return {**row, "not_scored_reason": "stale_data"}
    if last_day > signal_day:
        return {**row, "not_scored_reason": "signal_day_not_latest_candle"}
    if n_bars < P.MIN_BARS:
        return {**row, "not_scored_reason": "short_history"}
    primary = score_training_basis(db, inst, model.bundle)
    if primary is None:
        return {**row, "not_scored_reason": "invalid_features"}
    if not math.isfinite(primary.probability) or _ist_day(primary.ts) != signal_day:
        return {**row, "not_scored_reason": "invalid_score_or_date"}
    production = predict_instrument(db, inst, model.scorer)  # diagnostic only: today's serving path
    recent = db.execute(
        select(Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
        .where(Candle.instrument_id == inst.id, Candle.interval == "day")
        .order_by(Candle.ts.desc())
        .limit(20)
    ).all()
    return {
        **row,
        "status": "scored",
        "score": float(primary.probability),
        "score_production_path": float(production.probability) if production is not None else None,
        "signal_close": float(primary.price),
        "avg_volume_20": float(sum(r.volume for r in recent) / len(recent)) if recent else None,
        "bar": tuple(float(x) for x in recent[0]) if recent else None,
        "model_id": model.model_id,
        "model_version": model.version,
        "trained_on_symbol": symbol in model.training_symbols,
    }


def preview_day(
    db: Session, universe: dict, signal_day: date, models: dict[str, VerifiedModel]
) -> tuple[list[dict], dict[str, list[str]], dict]:
    """Read-only: score every stock of a universe for one signal day and pick the top 5 per group.

    Returns (rows, selected per group, summary per group). Writes nothing. Each stock is scored by the model of
    its OWN group; ranks are within a group and raw scores of different groups are never compared."""
    groups: dict[str, str] = universe["groups"]
    absent = sorted({g for g in groups.values() if g not in models})
    if absent:  # never fall back to another group's model
        raise P.ProtocolError(
            f"no frozen model for the {absent} group; refusing to use another group's model"
        )
    rows: list[dict] = [
        _score_stock(db, symbol, groups[symbol], signal_day, models[groups[symbol]])
        for symbol in sorted(groups)
    ]
    for symbol, why in sorted(universe["excluded"].items()):
        rows.append(
            {"symbol": symbol, "group": "-", "status": "not_scored", "not_scored_reason": why, "flags": []}
        )
    selected_today: dict[str, list[str]] = {}
    summary: dict = {}
    for group in P.GROUPS:
        members = [r for r in rows if r["group"] == group]
        ranked = R.rank_group([(r["symbol"], r["score"]) for r in members if r["status"] == "scored"])
        top, shortfall = R.select_top(ranked)
        rank_of = {sym: rk for sym, _, rk in ranked}
        for r in members:
            r["group_rank"] = rank_of.get(r["symbol"])
            r["selected"] = r["symbol"] in top
        selected_today[group] = top
        summary[group] = {
            "universe": len(members),
            "scored": len(ranked),
            "not_scored": len(members) - len(ranked),
            "not_scored_detail": {
                r["symbol"]: r["not_scored_reason"] for r in members if r["status"] != "scored"
            },
            "selected": top,
            "shortfall": shortfall,
        }
    return rows, selected_today, summary


def _provenance(db: Session, signal_day: date, sessions: list[date], rows: list[dict]) -> dict:
    """Where this signal day's market data came from. A fingerprint of ONE day's bars, not of the changing dataset."""
    stamp = datetime(signal_day.year, signal_day.month, signal_day.day, tzinfo=IST)
    watch_total = db.scalar(
        select(func.count())
        .select_from(Instrument)
        .where(Instrument.is_watchlisted.is_(True), Instrument.is_active.is_(True))
    )
    watch_with = db.scalar(
        select(func.count(func.distinct(Candle.instrument_id)))
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.is_watchlisted.is_(True), Candle.interval == "day", Candle.ts == stamp)
    )
    bars = sorted((r["symbol"], r["bar"]) for r in rows if r.get("bar"))
    return {
        "signal_day": str(signal_day),
        "nifty_last_session": str(sessions[-1]) if sessions else None,
        "nifty_sessions": len(sessions),
        "group_stocks": len(rows),
        "with_signal_bar": len(bars),
        "bars_sha256": _sha(bars),
        "watchlist_total": watch_total,
        "watchlist_with_signal_bar": watch_with,
    }


def score_day(db: Session, run: H05Run, signal_day: date, now: datetime | None = None) -> dict:
    """Score and RECORD one signal day for a run (every eligible stock, selected or not)."""
    P.require_runnable()
    if run.status != "active":
        raise P.ProtocolError("the run is closed")
    if not (run.start_day <= signal_day <= run.end_day):
        raise P.ProtocolError("the signal day is outside the run")
    moment = now or datetime.now(UTC)
    if signal_day > last_closed_trading_day(moment):
        raise P.ProtocolError("the signal session has not closed yet")
    sessions = market_sessions(db)
    if R.session_index(sessions, signal_day) is None:
        raise P.ProtocolError("the signal day is not a market session")
    if moment >= entry_open_time(signal_day):
        raise P.ProtocolError(
            "the entry session has already opened: a selection is stored before its simulated entry, never after"
        )
    if db.scalar(
        select(func.count())
        .select_from(H05Signal)
        .where(H05Signal.run_id == run.id, H05Signal.signal_day == signal_day)
    ):
        raise P.ProtocolError("this signal day is already recorded; a recorded day is never rewritten")
    try:
        models = verify_models(db)
        assert_same_models(run.models, models)
    except P.ProtocolError as exc:
        # The whole lane stops for this day, whichever group failed. The reason is persisted (the caller
        # commits) and the day stays unrecorded; the report lists it. No other model is ever used.
        db.add(
            H05Event(run_id=run.id, signal_day=signal_day, kind="lane_stopped_model_check", detail=str(exc))
        )
        db.flush()
        return {"stopped": True, "reason": str(exc)}

    scored_rows, selected_today, summary = preview_day(db, run.universe, signal_day, models)
    for group in P.GROUPS:
        s = summary[group]
        members = [r for r in scored_rows if r["group"] == group]
        db.add(
            H05GroupDay(
                run_id=run.id,
                signal_day=signal_day,
                group=group,
                universe_n=s["universe"],
                scored_n=s["scored"],
                not_scored_n=s["not_scored"],
                selected_n=len(s["selected"]),
                shortfall=s["shortfall"],
                provenance=_provenance(db, signal_day, sessions, members),
                recorded_at=moment,
            )
        )

    # repeats: against every earlier selection of this run plus today's
    earlier = db.execute(
        select(H05Signal.signal_day, H05Signal.symbol).where(
            H05Signal.run_id == run.id, H05Signal.selected.is_(True)
        )
    ).all()
    by_day: dict[date, list[str]] = {}
    for d, sym in earlier:
        by_day.setdefault(d, []).append(sym)
    by_day[signal_day] = [s for g in P.GROUPS for s in selected_today[g]]
    blocked = R.repeat_blocked(by_day, sessions)

    for r in scored_rows:
        db.add(
            H05Signal(
                run_id=run.id,
                signal_day=signal_day,
                symbol=r["symbol"],
                group=r["group"],
                instrument_id=r.get("instrument_id"),
                status=r["status"],
                not_scored_reason=r["not_scored_reason"],
                model_id=r.get("model_id"),
                model_version=r.get("model_version"),
                trained_on_symbol=r.get("trained_on_symbol"),
                score=r.get("score"),
                score_production_path=r.get("score_production_path"),
                group_rank=r.get("group_rank"),
                selected=bool(r.get("selected")),
                repeat_blocked=(signal_day, r["symbol"]) in blocked,
                signal_close=r.get("signal_close"),
                avg_volume_20=r.get("avg_volume_20"),
                flags=r["flags"],
                recorded_at=moment,
            )
        )
    db.flush()
    return summary


# ------------------------------------------------------------------ scoring finished outcomes


def evaluate(db: Session, run: H05Run) -> dict:
    """Fill in the endpoint-label outcome and the shadow-trade outcome once the sessions have happened.

    The label uses the SIGNAL close and the close of session 5; the trade uses the entry fill. A final outcome
    is written once and never changed. Pending rows stay pending."""
    P.require_runnable()
    sessions = market_sessions(db)
    rows = (
        db.execute(
            select(H05Signal)
            .where(
                H05Signal.run_id == run.id,
                H05Signal.status == "scored",
                (H05Signal.label_status == "pending") | (H05Signal.trade_status == "pending"),
            )
            .order_by(H05Signal.instrument_id, H05Signal.signal_day)
        )
        .scalars()
        .all()
    )
    earliest: dict[int, date] = {}
    for r in rows:
        earliest[r.instrument_id] = min(r.signal_day, earliest.get(r.instrument_id, r.signal_day))
    cache: dict[int, dict[date, R.Bar]] = {}
    done = {"label": 0, "trade": 0}
    for s in rows:
        if s.instrument_id not in cache:
            cache[s.instrument_id] = _bars(db, s.instrument_id, earliest[s.instrument_id])
        bars = cache[s.instrument_id]
        window = R.sessions_after(sessions, s.signal_day, P.TRADE_SESSIONS)
        provenance = {
            "bars_through": str(max(bars)) if bars else None,
            "window_sessions": [str(d) for d in window],
            "window_bars_sha256": _sha([(str(d), bars.get(d)) for d in [s.signal_day, *window]]),
        }
        if s.label_status == "pending":
            o = R.endpoint_outcome({d: b[3] for d, b in bars.items()}, sessions, s.signal_day)
            if o.status != "pending":
                s.label_status, s.label_day5, s.label_close5, s.label_hit, s.label_note = (
                    o.status,
                    o.day5,
                    o.close5,
                    o.label,
                    o.note or None,
                )
                done["label"] += 1
        if s.trade_status == "pending":
            t = R.simulate_trade(bars, sessions, s.signal_day, s.signal_close, s.group)
            if t.status != "pending" and (s.recorded_at is None or s.recorded_at >= entry_open_time(s.signal_day)):
                t = R.TradeResult(
                    "unresolved", "recorded at or after the entry open: never simulated", flags=("recorded_late",)
                )
            if t.status != "pending":
                s.trade_status, s.trade_note, s.entry_day, s.entry_open, s.entry_fill = (
                    t.status,
                    t.note or None,
                    t.entry_day,
                    t.entry_open,
                    t.entry_fill,
                )
                s.exit_day, s.exit_price, s.exit_fill = t.exit_day, t.exit_price, t.exit_fill
                s.exit_reason = t.status if t.status in ("target", "stop", "expiry") else None
                s.sessions_held, s.gap_fill, s.ambiguous, s.costs_inr = (
                    t.sessions_held,
                    t.gap_fill,
                    t.ambiguous,
                    t.costs_inr,
                )
                s.net_return, s.trade_flags = t.net_return, list(t.flags)
                late = "recorded_late" in t.flags
                hard = (
                    t
                    if late
                    else R.simulate_trade(bars, sessions, s.signal_day, s.signal_close, s.group, stress=True)
                )
                s.trade_status_stress, s.net_return_stress = hard.status, hard.net_return
                done["trade"] += 1
        if s.label_status != "pending" or s.trade_status != "pending":
            s.outcome_provenance = provenance
            s.evaluated_at = datetime.now(UTC)
    db.flush()
    return done
