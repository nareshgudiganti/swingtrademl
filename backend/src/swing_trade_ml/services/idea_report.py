"""Portfolio-page report: every brain idea that reached a word (WATCH, TRADE, ...), how long ago, with what
score, and what happened since.

Read-only and display-only. It reads the brain's stored decisions (brain_decisions + brain_runs) and writes
nothing; no new table. The logic is pure (`build_rows`, `summarise`, `apply_filters`) so it is tested without
a database; `load_observations` is the one DB read.

One row = one "entry": the first session in an unbroken stretch where a stock carried the same word. Cyient
shown as WATCH on 7, 8, 9 and 10 Nov is ONE row dated 7 Nov (still WATCH, 3 days done), not four. If the
word changes or the stock drops out of the list, a later return to a word starts a new row.

The trial seal (services/trial_seal.py) applies: for entries on or after the seal date, no return, outcome,
best/worst move or hit rate is returned. A sealed row shows only calendar facts (entry day, days done, days
left, scores). Its status stays "tracking" until the horizon has passed, so "finished early" cannot leak a
target or stop hit. Filters on results (outcome) never match sealed rows.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from swing_trade_ml.core.market_session import is_trading_day
from swing_trade_ml.services import trial_seal

IST = ZoneInfo("Asia/Kolkata")

WORDS = ("TRADE", "WATCH", "WAIT", "AVOID")
OUTCOMES = ("target", "stop", "timeout", "open")
# (label, low, high) on the 0-100 score; high is exclusive except the last band.
SCORE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("90+", 90, 101),
    ("80-90", 80, 90),
    ("70-80", 70, 80),
    ("60-70", 60, 70),
    ("below 60", 0, 60),
)
MAX_DAYS = 400


@dataclass(frozen=True)
class Obs:
    """One stock's decision in one nightly session."""

    symbol: str
    day: date  # the session's IST day
    word: str
    score: int | None  # 0-100, only when the stored confidence is a real score
    horizon_days: int
    regime: str | None  # the run's banner: NORMAL / DEFENSIVE / NO_NEW_TRADES
    outcome: str | None  # stored grade: target / stop / timeout
    outcome_return: float | None
    max_up: float | None
    max_down: float | None
    resolved_on: date | None


def band_of(score: int | None) -> str | None:
    if score is None:
        return None
    for label, lo, hi in SCORE_BANDS:
        if lo <= score < hi:
            return label
    return None


def trading_days_between(start: date, end: date) -> int:
    """Trading days after `start`, up to and including `end`."""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


def build_rows(obs: Iterable[Obs], sessions: Sequence[date]) -> list[dict]:
    """Entries (see module doc), newest first. `sessions` = every session day in the range, ascending."""
    if not sessions:
        return []
    last_day = sessions[-1]
    by_symbol: dict[str, dict[date, Obs]] = {}
    for o in obs:
        by_symbol.setdefault(o.symbol, {})[o.day] = o
    rows: list[dict] = []
    for days in by_symbol.values():
        latest = days[max(days)]
        prev_word: str | None = None
        entry: Obs | None = None
        streak_end: date | None = None
        entries: list[tuple[Obs, date]] = []
        for day in sessions:
            o = days.get(day)
            if o is None:
                prev_word = None
                continue
            if o.word != prev_word:
                if entry is not None and streak_end is not None:
                    entries.append((entry, streak_end))
                entry = o
            streak_end = day
            prev_word = o.word
        if entry is not None and streak_end is not None:
            entries.append((entry, streak_end))
        for first, end in entries:
            rows.append(_row(first, end, latest, last_day))
    rows.sort(key=lambda r: (r["entry_day"], r["symbol"]), reverse=True)
    return rows


def _row(first: Obs, streak_end: date, latest: Obs, last_day: date) -> dict:
    done = trading_days_between(first.day, last_day)
    sealed = trial_seal.is_sealed_day(first.day)
    horizon_over = done >= first.horizon_days
    graded = first.outcome is not None
    if graded and (horizon_over or not sealed):
        status = "finished"
    elif horizon_over:
        status = "due"  # horizon has passed, the nightly grading has not written the result yet
    else:
        status = "tracking"
    row = {
        "symbol": first.symbol,
        "word": first.word,
        "entry_day": first.day.isoformat(),
        "entry_score": first.score,
        "score_band": band_of(first.score),
        "latest_score": latest.score,
        "latest_word": latest.word,
        "still_this_word": streak_end == last_day and latest.word == first.word,
        "horizon_days": first.horizon_days,
        "days_done": min(done, first.horizon_days),
        "days_left": max(0, first.horizon_days - done),
        "regime": first.regime,
        "status": status,
        "sealed": sealed,
        "outcome": None,
        "return_pct": None,
        "best_pct": None,
        "worst_pct": None,
        "result_days": None,
    }
    if not sealed and graded:
        row.update(
            outcome=first.outcome,
            return_pct=None if first.outcome_return is None else round(first.outcome_return * 100, 2),
            best_pct=None if first.max_up is None else round(first.max_up * 100, 2),
            worst_pct=None if first.max_down is None else round(first.max_down * 100, 2),
            result_days=_result_days(first),
        )
    return row


def _result_days(first: Obs) -> int | None:
    if first.resolved_on is None:
        return None
    return trading_days_between(first.day, first.resolved_on)


def apply_filters(
    rows: Sequence[dict],
    *,
    words: Sequence[str] = (),
    bands: Sequence[str] = (),
    horizons: Sequence[int] = (),
    regimes: Sequence[str] = (),
    outcomes: Sequence[str] = (),
    current_only: bool = False,
    only_symbols: Collection[str] | None = None,
) -> list[dict]:
    """Every filter is "any of"; an empty one does not filter. Outcome filters never match a sealed row.

    `only_symbols` (None = every stock) keeps just those stocks: the ones we hold or have held and sold."""
    out = []
    for r in rows:
        if only_symbols is not None and r["symbol"].upper() not in only_symbols:
            continue
        if words and r["word"] not in words:
            continue
        if bands and r["score_band"] not in bands:
            continue
        if horizons and r["horizon_days"] not in horizons:
            continue
        if regimes and r["regime"] not in regimes:
            continue
        if current_only and not r["still_this_word"]:
            continue
        if outcomes:
            if r["sealed"]:
                continue
            kind = r["outcome"] if r["outcome"] is not None else "open"
            if kind not in outcomes:
                continue
        out.append(r)
    return out


def summarise(rows: Sequence[dict]) -> dict:
    """Counts always; results only over rows that are not sealed. Never a rate over sealed rows."""
    counts = Counter(r["status"] for r in rows)
    open_unsealed = [r for r in rows if not r["sealed"]]
    graded = [r for r in open_unsealed if r["outcome"] is not None]
    returns = [r["return_pct"] for r in graded if r["return_pct"] is not None]
    by_outcome = Counter(r["outcome"] for r in graded)
    return {
        "ideas": len(rows),
        "tracking": counts.get("tracking", 0),
        "due": counts.get("due", 0),
        "finished": counts.get("finished", 0),
        "still_this_word": sum(1 for r in rows if r["still_this_word"]),
        "sealed_ideas": sum(1 for r in rows if r["sealed"]),
        "results": {
            "ideas": len(graded),
            "target": by_outcome.get("target", 0),
            "stop": by_outcome.get("stop", 0),
            "timeout": by_outcome.get("timeout", 0),
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        },
    }


def _score_of(d) -> int | None:
    """A 0-100 score only when the stored confidence is a real score (not some other opinion's confidence)."""
    if not d.score_source or d.confidence is None:
        return None
    return round(d.confidence * 100)


def load_observations(db, start: date, end: date, book: str) -> tuple[list[Obs], list[date]]:
    """Idea decisions of live nightly runs in [start, end] (IST days); a later run of the same day wins."""
    from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

    lo = datetime.combine(start, time(0, 0), tzinfo=IST)
    hi = datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=IST)
    runs = db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.book == book,
            BrainRun.as_of >= lo,
            BrainRun.as_of < hi,
        )
        .order_by(BrainRun.started_at.asc())
    ).scalars()
    latest: dict[date, BrainRun] = {}
    for r in runs:
        latest[r.as_of.astimezone(IST).date()] = r
    obs: list[Obs] = []
    for day, run in sorted(latest.items()):
        decisions = db.execute(
            select(BrainDecision).where(BrainDecision.run_id == run.id, BrainDecision.kind == "idea")
        ).scalars()
        for d in decisions:
            obs.append(
                Obs(
                    symbol=d.symbol,
                    day=day,
                    word=d.overruled_word or d.word,
                    score=_score_of(d),
                    horizon_days=d.horizon_days,
                    regime=run.banner_mode,
                    outcome=d.outcome,
                    outcome_return=d.outcome_return,
                    max_up=d.max_up,
                    max_down=d.max_down,
                    resolved_on=d.resolved_on,
                )
            )
    return obs, sorted(latest)


def groww_user_ids(db, principal) -> list[int]:
    """Whose Groww Tracker counts as "ours": only owner accounts named in REAL_ACCOUNT_USERS.

    The tracker holds a person's own real shares, so it follows the same privacy rule as My Holdings.
    A signed-in account counts only if it may see the real account; the shared API key (the owner's
    scripts) counts every REAL_ACCOUNT_USERS owner. Anyone else gets an empty list.
    """
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.session import User

    if principal is None or not principal.can_see_real_account:
        return []
    if principal.user is not None:
        return [principal.user.id]
    allowed = {n.strip().lower() for n in settings.REAL_ACCOUNT_USERS.split(",") if n.strip()}
    if not allowed:
        return []
    rows = db.execute(select(User.id).where(User.role == "owner", func.lower(User.username).in_(allowed)))
    return [int(i) for i in rows.scalars()]


def held_or_sold_symbols(db, mode: str, groww_user_ids: Sequence[int] = ()) -> set[str]:
    """Upper-case symbols we hold or sold: every position in this trading mode (open or closed),
    plus, for the given users only, Groww Tracker stocks they hold (on the list with a buy price)
    or sold (Sold records)."""
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Position
    from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem, UserWatchlistSale

    rows = db.execute(
        select(Instrument.tradingsymbol)
        .join(Position, Position.instrument_id == Instrument.id)
        .where(Position.mode == mode)
        .distinct()
    ).scalars()
    out = {str(sym).upper() for sym in rows}
    if groww_user_ids:
        ids = list(groww_user_ids)
        held = db.execute(
            select(UserWatchlistItem.symbol).where(
                UserWatchlistItem.user_id.in_(ids),
                UserWatchlistItem.removed_at.is_(None),
                UserWatchlistItem.buy_price.is_not(None),
            )
        ).scalars()
        sold = db.execute(
            select(UserWatchlistSale.symbol).where(UserWatchlistSale.user_id.in_(ids))
        ).scalars()
        out |= {str(sym).upper() for sym in held} | {str(sym).upper() for sym in sold}
    return out


def build(
    db,
    start: date,
    end: date,
    book: str,
    *,
    words: Sequence[str] = (),
    bands: Sequence[str] = (),
    horizons: Sequence[int] = (),
    regimes: Sequence[str] = (),
    outcomes: Sequence[str] = (),
    current_only: bool = False,
    mine_only: bool = False,
    groww_users: Sequence[int] = (),
) -> dict:
    obs, sessions = load_observations(db, start, end, book)
    all_rows = build_rows(obs, sessions)
    rows = apply_filters(
        all_rows,
        words=words,
        bands=bands,
        horizons=horizons,
        regimes=regimes,
        outcomes=outcomes,
        current_only=current_only,
        only_symbols=held_or_sold_symbols(db, book, groww_users) if mine_only else None,
    )
    sealed_touched = any(r["sealed"] for r in all_rows)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "sessions": len(sessions),
        "last_session": sessions[-1].isoformat() if sessions else None,
        "mine_only": mine_only,
        "rows": rows,
        "summary": summarise(rows),
        "seal": {
            "active": trial_seal.active() and sealed_touched,
            "from": (trial_seal.sealed_from().isoformat() if trial_seal.sealed_from() else None),
            "text": trial_seal.SEALED_TEXT,
            "outcome_filter_hides_sealed": bool(outcomes) and sealed_touched,
        },
        "options": {
            "words": [w for w in WORDS if any(r["word"] == w for r in all_rows)],
            "bands": [b for b, _, _ in SCORE_BANDS],
            "horizons": sorted({r["horizon_days"] for r in all_rows}),
            "regimes": sorted({r["regime"] for r in all_rows if r["regime"]}),
            "outcomes": list(OUTCOMES),
        },
    }
