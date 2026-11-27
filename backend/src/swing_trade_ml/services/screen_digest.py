"""What changed since the last scan, for a saved screen (#310 slice A): Brain ideas only.

Compares the newest finished live nightly brain run with the previous trading day's (the same run rules as
services/brain_changes.py, so replays, "why" runs, intraday, failed and superseded runs never count) and lists
which stocks CAME IN to the screen and which DROPPED OUT, each with exactly one reason taken from a stored
field. Reasons, in this fixed order: data not fresh, the decision word changed, the pattern appeared or
disappeared, "Not recorded". (The rank and cap-tier reasons need #260 and are slice B.)

Read only: it writes nothing, never changes a word, order, size, stop or limit, and its decision query names
its columns, so a result column (outcome, outcome_return, max_up, max_down, resolved_on) is never selected:
brain-trial results stay sealed. Ranks are "place of N", never the raw score. For a non-owner only the public
verdict fields are used (services/public_verdict.py): no account-room text, no owner note. Stale or missing
data can only remove a stock from "came in"; it can never add one.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import brain_changes, public_verdict
from swing_trade_ml.services.saved_screens import normalise_spec

FOOTER = (
    "This is a ranking among the stocks the brain checked that night. It is not a chance of profit "
    "and not advice."
)
UNSUPPORTED_WINDOW = "There are no supported trading ideas for this time window yet, so nothing is compared."
NOT_FRESH = "Data not fresh, not compared."
DROPPED_NOT_FRESH = (
    "Data not fresh: the latest prices for this stock are missing or old, so it is not counted."
)
NOT_RECORDED = "Not recorded: nothing the brain stored explains this change."

#: A stock's newest daily bar may be this many calendar days older than the run (weekends and holidays).
STALE_AFTER_DAYS = 5
#: Stored text that sounds like a promise of gain is never repeated.
_BANNED = re.compile(r"profit|return|chance|gain|\bwill\b|likely|guarantee|certain|\bsure\b", re.I)
_LABEL = {"TRADE": "BUY"}  # on screen the word TRADE is called BUY

#: Only these columns are read: no result (outcome) column is ever selected.
_COLUMNS = (
    BrainDecision.symbol,
    BrainDecision.kind,
    BrainDecision.word,
    BrainDecision.confidence,
    BrainDecision.score_source,
    BrainDecision.reasons,
    BrainDecision.downgraded_from,
    BrainDecision.downgrade_reason,
    BrainDecision.overruled_word,
)
_CAP_RANK = {"large": 1, "midcap": 2, "smallcap": 3}


def _empty(note: str | None, current: dict | None = None) -> dict:
    return {
        "comparable": False,
        "note": note,
        "current": current,
        "previous": None,
        "came_in": [],
        "dropped_out": [],
        "not_compared": [],
        "footer": FOOTER,
    }


def _word(w: str) -> str:
    return _LABEL.get(w, w)


def _safe(text: str | None) -> str | None:
    """A stored sentence, only when it is short and makes no promise of gain."""
    t = " ".join((text or "").split())
    return t if t and len(t) <= 220 and not _BANNED.search(t) else None


def _ideas(db: Session, run: BrainRun) -> dict[str, Any]:
    rows = db.execute(select(*_COLUMNS).where(BrainDecision.run_id == run.id)).all()
    return {r.symbol: r for r in rows if r.kind == "idea"}


def _side(db: Session, run: BrainRun, d: Any, rank: tuple[int, int, str | None] | None, owner: bool) -> dict:
    word = d.overruled_word or d.word
    reasons = list(d.reasons or [])
    downgrade = d.downgrade_reason
    if not owner:
        pub = public_verdict.public_fields(
            kind=d.kind,
            word=d.word,
            downgraded_from=d.downgraded_from,
            downgrade_reason=d.downgrade_reason,
            reasons=reasons,
            overruled_word=d.overruled_word,
            banner_mode=run.banner_mode,
            trend=public_verdict.trend_lookup(db, run, d.symbol),
        )
        word = d.overruled_word or pub["word"]
        reasons, downgrade = pub["reasons"], pub["downgrade_reason"]
    stored = _safe(downgrade) or next((s for s in (_safe(r) for r in reasons) if s), None)
    return {
        "word": word,
        "rank": rank[0] if rank else None,
        "rank_of": rank[1] if rank else None,
        "_stored": stored,
    }


def _public(side: dict | None) -> dict | None:
    return None if side is None else {k: v for k, v in side.items() if not k.startswith("_")}


def _tiers(db: Session) -> dict[str, str]:
    """symbol -> company size, from the ml_swing strategies' model names (same rule as frontend cap.tsx)."""
    out: dict[str, str] = {}
    for params, symbols in db.execute(
        select(Strategy.params, Strategy.symbols).where(Strategy.strategy_type == "ml_swing")
    ):
        name = (params or {}).get("model_name")
        if not isinstance(name, str) or not name:
            continue
        if name.endswith("_smallcap"):
            tier = "smallcap"
        elif name.endswith("_midcap"):
            tier = "midcap"
        elif name == "swing_classifier":
            tier = "large"
        else:
            continue
        for s in symbols or []:
            key = str(s).upper()
            if key not in out or _CAP_RANK[tier] > _CAP_RANK[out[key]]:
                out[key] = tier
    return out


def _sector(symbol: str) -> str | None:
    from swing_trade_ml.ml.sector_map import get_sector_bucket, sector_display_name

    bucket = get_sector_bucket(symbol)
    return sector_display_name(bucket) if bucket else None


def _setups(db: Session, run: BrainRun, symbol: str, cache: dict) -> dict[str, str]:
    """label -> plain line for the patterns present on the stock's candles up to the run's own time."""
    key = (run.id, symbol)
    if key not in cache:
        try:
            from swing_trade_ml.brain.modules.m12_stock.setups import find_setups
            from swing_trade_ml.brain.reader import DatedReader

            bars = DatedReader(db, run.as_of, bool(run.live)).ohlcv(symbol, 300)
            cache[key] = {s.label: s.line for s in find_setups(bars)}
        except Exception:  # noqa: BLE001 - no evidence means "does not match", never a guess
            cache[key] = {}
    return cache[key]


def _fresh_symbols(db: Session, run: BrainRun, symbols: set[str]) -> set[str]:
    """Symbols whose newest daily bar (up to the run's time) is recent and that the run's own data check
    did not list as stale."""
    if not symbols:
        return set()
    stale = set((run.quality or {}).get("stale") or [])
    rows = db.execute(
        select(Instrument.tradingsymbol, func.max(Candle.ts))
        .join(Candle, Candle.instrument_id == Instrument.id)
        .where(Instrument.tradingsymbol.in_(symbols), Candle.interval == "day", Candle.ts <= run.as_of)
        .group_by(Instrument.tradingsymbol)
    ).all()
    today = brain_changes.ist_day(run.as_of)
    out = set()
    for symbol, ts in rows:
        if symbol in stale or ts is None:
            continue
        if (today - brain_changes.ist_day(ts)).days <= STALE_AFTER_DAYS:
            out.add(symbol)
    return out


def digest(db: Session, spec: dict, *, user_id: int, owner: bool, book: str = "paper") -> dict:
    spec = normalise_spec(spec)
    if spec["horizon"] != "15d":
        return _empty(UNSUPPORTED_WINDOW)
    run = brain_changes.latest_live_nightly(db, book)
    if run is None:
        return _empty(brain_changes.NO_RUN)
    prev = brain_changes.previous_live_nightly(db, run)
    if prev is None:
        return _empty(brain_changes.NO_PREVIOUS, current=brain_changes._run_ref(run))

    now_ideas, before_ideas = _ideas(db, run), _ideas(db, prev)
    now_rank = brain_changes._ranks(list(now_ideas.values()))
    before_rank = brain_changes._ranks(list(before_ideas.values()))
    tiers = _tiers(db) if spec["cap_tiers"] else {}
    watch: set[str] = set()
    if spec["watch_only"]:
        watch = {
            s.upper()
            for s in db.execute(
                select(UserWatchlistItem.symbol).where(
                    UserWatchlistItem.user_id == user_id, UserWatchlistItem.removed_at.is_(None)
                )
            ).scalars()
        }
    query = spec["query"].upper()
    cache: dict = {}

    def base_ok(symbol: str, word: str) -> bool:
        if spec["word"] != "ALL" and word != spec["word"]:
            return False
        if query and query not in symbol.upper():
            return False
        if spec["sector"] and _sector(symbol) != spec["sector"]:
            return False
        if spec["cap_tiers"] and tiers.get(symbol.upper()) not in spec["cap_tiers"]:
            return False
        return not (spec["watch_only"] and symbol.upper() not in watch)

    def pattern_ok(r: BrainRun, symbol: str) -> bool:
        if not spec["patterns"]:
            return True
        found = _setups(db, r, symbol, cache)
        return any(p in found for p in spec["patterns"])

    # (symbol, now side, before side, now passes the plain filters, before passes them, now in, before in)
    candidates: list[tuple[str, dict | None, dict | None, bool, bool, bool, bool]] = []
    for symbol in sorted(set(now_ideas) | set(before_ideas)):
        n, b = now_ideas.get(symbol), before_ideas.get(symbol)
        ns = _side(db, run, n, now_rank.get(symbol), owner) if n is not None else None
        bs = _side(db, prev, b, before_rank.get(symbol), owner) if b is not None else None
        n_base = ns is not None and base_ok(symbol, ns["word"])
        b_base = bs is not None and base_ok(symbol, bs["word"])
        if not n_base and not b_base:
            continue
        n_in = n_base and pattern_ok(run, symbol)
        b_in = b_base and pattern_ok(prev, symbol)
        if n_in == b_in:  # unchanged membership is not listed
            continue
        candidates.append((symbol, ns, bs, n_base, b_base, n_in, b_in))

    fresh = _fresh_symbols(db, run, {c[0] for c in candidates})
    came_in: list[dict] = []
    dropped: list[dict] = []
    not_compared: list[dict] = []

    for symbol, ns, bs, _n_base, b_base, n_in, b_in in candidates:
        side = ns or bs or {}
        row = {
            "symbol": symbol,
            "now": _public(ns),
            "before": _public(bs),
            "rank": side.get("rank"),
            "rank_of": side.get("rank_of"),
        }
        if symbol not in fresh:
            if b_in and not n_in:
                dropped.append({**row, "reason_code": "data_not_fresh", "reason": DROPPED_NOT_FRESH})
            elif n_in and not b_in:
                not_compared.append({**row, "reason_code": "data_not_fresh", "reason": NOT_FRESH})
            continue
        if n_in == b_in:
            continue
        code, text = _reason(spec, symbol, ns, bs, b_base, n_in, run, db, cache)
        (came_in if n_in else dropped).append({**row, "reason_code": code, "reason": text})

    return {
        "comparable": True,
        "note": None,
        "current": brain_changes._run_ref(run),
        "previous": brain_changes._run_ref(prev),
        "came_in": came_in,
        "dropped_out": dropped,
        "not_compared": not_compared,
        "footer": FOOTER,
    }


def _reason(
    spec: dict,
    symbol: str,
    ns: dict | None,
    bs: dict | None,
    b_base: bool,
    came: bool,
    run: BrainRun,
    db: Session,
    cache: dict,
) -> tuple[str, str]:
    """The one reason: the first rule that matches, from stored fields only."""
    # (b) the decision word changed, when the word is part of the screen
    if spec["word"] != "ALL" and ns is not None and bs is not None and ns["word"] != bs["word"]:
        text = f"The brain moved it from {_word(bs['word'])} to {_word(ns['word'])}."
        stored = ns["_stored"] or bs["_stored"]
        return "word_changed", f"{text} Stored reason: {stored}" if stored else text
    # (c) the pattern appeared or disappeared (the stock must be in both runs, so it is a real change)
    if spec["patterns"] and ns is not None and bs is not None and b_base:
        if came:
            found = _setups(db, run, symbol, cache)
            line = next((found[p] for p in spec["patterns"] if p in found), None)
            if line:
                return "pattern_changed", f"Now matches your pattern filter. {line}"
        else:
            return (
                "pattern_changed",
                "No longer matches your pattern filter: the pattern is not present on the latest candles.",
            )
    return "not_recorded", NOT_RECORDED
