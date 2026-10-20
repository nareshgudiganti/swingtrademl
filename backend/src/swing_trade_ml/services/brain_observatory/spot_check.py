"""Monthly spot check: are the brain's stated reasons true? (ps9, 2026-10-20). Read-only.

Picks 20 decisions at random from the month's nightly runs (a fixed seed per month, so the same month
always gives the same 20) and recomputes, from the raw daily prices the run could see (on or before its
`as_of`), every reason that makes a claim about prices. Each check is written here from the plain rule,
not by calling the brain's own code, so a bug there shows as a mismatch instead of agreeing with itself.

Claims checked today:
- the trade plan: target and stop are +8% / -4% from that day's close, and the buy range holds the close;
- a breakout above / breakdown below the 20-day high / low on N x the usual volume;
- a pullback to the 20-day average in an up-trend;
- "X is N% above its 50-day average";
- "NIFTY's 50-day average is above / below its 200-day average".

Any other reason is counted as "not checkable from prices" (scores, similar cases, news...). This reads
decisions and prices only, never outcomes, so it does not spend any held-out period.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST

SAMPLE = 20
_RS = r"₹([\d,]+)"
PLAN = re.compile(rf"Plan: buy around {_RS} to {_RS}, target {_RS} \(\+(\d+)%\), stop {_RS} \(-(\d+)%\)")
BREAKOUT = re.compile(r"breakout above the 20-day high on ([\d.]+)x the usual volume")
BREAKDOWN = re.compile(r"closed below the 20-day low on ([\d.]+)x the usual volume")
PULLBACK = re.compile(r"pullback to the 20-day average in an up-trend")
STRETCH = re.compile(r"is (\d+)% above its 50-day average")
NIFTY_TREND = re.compile(r"NIFTY's 50-day average is (above|below) its 200-day average")


def _rupees(s: str) -> float:
    return float(s.replace(",", ""))


def _result(claim: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"claim": claim, "ok": ok, "detail": detail}


def _plan(m: re.Match, bars: pd.DataFrame, _index: pd.Series) -> dict:
    close = float(bars["close"].iloc[-1])
    lo, hi, target, up, stop, down = (
        _rupees(m[1]),
        _rupees(m[2]),
        _rupees(m[3]),
        int(m[4]),
        _rupees(m[5]),
        int(m[6]),
    )
    want_t, want_s = close * (1 + up / 100), close * (1 - down / 100)
    tol = 1.0 + 0.001 * close  # the text rounds to whole rupees
    problems = []
    if abs(target - want_t) > tol:
        problems.append(f"target ₹{target:,.0f} is not +{up}% of the close ₹{close:,.2f} (₹{want_t:,.2f})")
    if abs(stop - want_s) > tol:
        problems.append(f"stop ₹{stop:,.0f} is not -{down}% of the close ₹{close:,.2f} (₹{want_s:,.2f})")
    if not lo - 1 <= close <= hi + 1:
        problems.append(f"the close ₹{close:,.2f} is outside the buy range ₹{lo:,.0f} to ₹{hi:,.0f}")
    return _result("trade plan levels", not problems, "; ".join(problems) or f"close ₹{close:,.2f}")


def _volume_x(bars: pd.DataFrame) -> float | None:
    avg = float(bars["volume"].iloc[-21:-1].mean())
    return None if avg <= 0 else float(bars["volume"].iloc[-1]) / avg


def _breakout(m: re.Match, bars: pd.DataFrame, _index: pd.Series) -> dict:
    close, top, vx = float(bars["close"].iloc[-1]), float(bars["high"].iloc[-21:-1].max()), _volume_x(bars)
    stated = float(m[1])
    ok = close > top and vx is not None and abs(vx - stated) <= 0.051
    return _result(
        "breakout",
        ok,
        f"close {close:,.2f} vs 20-day high {top:,.2f}; volume {vx or 0:.2f}x (stated {stated}x)",
    )


def _breakdown(m: re.Match, bars: pd.DataFrame, _index: pd.Series) -> dict:
    close, bottom, vx = float(bars["close"].iloc[-1]), float(bars["low"].iloc[-21:-1].min()), _volume_x(bars)
    stated = float(m[1])
    ok = close < bottom and vx is not None and abs(vx - stated) <= 0.051
    return _result(
        "breakdown",
        ok,
        f"close {close:,.2f} vs 20-day low {bottom:,.2f}; volume {vx or 0:.2f}x (stated {stated}x)",
    )


def _pullback(_m: re.Match, bars: pd.DataFrame, _index: pd.Series) -> dict:
    close = bars["close"]
    sma20, sma50 = close.rolling(20).mean(), close.rolling(50).mean()
    up = sma20.iloc[-1] > sma50.iloc[-1] and sma50.iloc[-1] > sma50.iloc[-11]
    touched = bars["low"].iloc[-1] <= sma20.iloc[-1] * 1.01 and close.iloc[-1] >= sma20.iloc[-1] * 0.98
    return _result(
        "pullback in up-trend",
        bool(up and touched),
        f"up-trend {bool(up)}, touched the 20-day average {bool(touched)}",
    )


def _stretch(m: re.Match, bars: pd.DataFrame, _index: pd.Series) -> dict:
    close = bars["close"]
    ratio = float(close.iloc[-1] / close.rolling(50).mean().iloc[-1] - 1) * 100
    stated = int(m[1])
    return _result(
        "distance above the 50-day average", abs(ratio - stated) <= 0.51, f"{ratio:.1f}% (stated {stated}%)"
    )


def _nifty_trend(m: re.Match, _bars: pd.DataFrame, index: pd.Series) -> dict:
    if len(index) < 200:
        return _result("NIFTY trend", False, "not enough NIFTY history to recompute")
    above = index.rolling(50).mean().iloc[-1] > index.rolling(200).mean().iloc[-1]
    stated = m[1] == "above"
    return _result("NIFTY trend", above == stated, f"50-day {'above' if above else 'below'} 200-day")


CHECKS: tuple[tuple[re.Pattern, Callable[..., dict]], ...] = (
    (PLAN, _plan),
    (BREAKOUT, _breakout),
    (BREAKDOWN, _breakdown),
    (PULLBACK, _pullback),
    (STRETCH, _stretch),
    (NIFTY_TREND, _nifty_trend),
)


def check_decision(reasons: list[str], bars: pd.DataFrame, index: pd.Series) -> tuple[list[dict], int]:
    """(checked claims, number of reasons with no price claim) for one decision."""
    claims, other = [], 0
    for text in reasons:
        hits = [(m, fn) for pattern, fn in CHECKS for m in [pattern.search(text)] if m]
        if not hits:
            other += 1
            continue
        for m, fn in hits:
            if len(bars) < 60:
                claims.append(_result(fn.__name__.strip("_"), False, "fewer than 60 daily bars to recompute"))
            else:
                claims.append(fn(m, bars, index))
    return claims, other


# --- database ----------------------------------------------------------------------------------


def _bars_upto(db: Session, symbol: str, upto: datetime, n: int = 260) -> pd.DataFrame:
    from swing_trade_ml.db.models.market import Candle, Instrument

    rows = db.execute(
        select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol == symbol, Candle.interval == "day", Candle.ts <= upto)
        .order_by(Candle.ts.desc())
        .limit(n)
    ).all()
    df = pd.DataFrame(list(reversed(rows)), columns=["ts", "open", "high", "low", "close", "volume"])
    return df.astype(dict.fromkeys(("open", "high", "low", "close", "volume"), "float64")) if len(df) else df


def _index_upto(db: Session, upto: datetime) -> pd.Series:
    from swing_trade_ml.core.config import settings

    bars = _bars_upto(db, settings.BENCHMARK_INDEX_SYMBOL, upto, n=260)
    return bars["close"] if len(bars) else pd.Series(dtype=float)


def pick(db: Session, start: date, end: date, n: int = SAMPLE, seed: int | None = None) -> list:
    """`n` decisions from the live nightly runs of start..end, the same ones every time for one seed."""
    from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

    lo = datetime.combine(start, datetime.min.time(), tzinfo=IST)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=IST)
    rows = db.execute(
        select(BrainDecision, BrainRun.as_of)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.as_of >= lo,
            BrainRun.as_of < hi,
        )
        .order_by(BrainDecision.id)
    ).all()
    rng = random.Random(seed if seed is not None else int(start.strftime("%Y%m")))
    return rng.sample(rows, min(n, len(rows)))


def spot_check(db: Session, start: date, end: date, n: int = SAMPLE) -> dict[str, Any]:
    picked = pick(db, start, end, n)
    rows, index_cache = [], {}
    for d, as_of in picked:
        if as_of not in index_cache:
            index_cache[as_of] = _index_upto(db, as_of)
        texts = [*(d.reasons or []), *([d.evidence_text] if d.evidence_text else [])]
        claims, other = check_decision(texts, _bars_upto(db, d.symbol, as_of), index_cache[as_of])
        rows.append(
            {
                "decision_id": d.id,
                "run_id": d.run_id,
                "day": as_of.astimezone(IST).date().isoformat(),
                "symbol": d.symbol,
                "word": d.word,
                "claims": claims,
                "not_checkable": other,
            }
        )
    claims = [c for r in rows for c in r["claims"]]
    mismatches = [
        {"symbol": r["symbol"], "day": r["day"], "decision_id": r["decision_id"], **c}
        for r in rows
        for c in r["claims"]
        if not c["ok"]
    ]
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "decisions": len(rows),
        "claims_checked": len(claims),
        "claims_true": len(claims) - len(mismatches),
        "decisions_all_true": sum(1 for r in rows if all(c["ok"] for c in r["claims"])),
        "reasons_not_checkable": sum(r["not_checkable"] for r in rows),
        "mismatches": mismatches,
        "rows": rows,
    }
