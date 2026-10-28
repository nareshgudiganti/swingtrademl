"""What changed since yesterday (ux11): today's live nightly brain ideas next to the previous
trading day's live nightly ideas, stock by stock.

Read only. It never runs the brain, never writes a row and never changes a word, a threshold
or an order. Only live nightly runs that finished count — the same rule as
strategies/brain.py::todays_run — so replays, "why" runs, intraday runs, failed runs and
superseded runs are never compared.

Display-only by design: the score comes back as a place in the day's ranking (1st, 2nd, ...),
never as the raw number, because the raw model score is a ranking and not a chance. Outcomes
(profit, hit or miss) are never included: brain-trial results are sealed.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.services import public_verdict

IST = ZoneInfo("Asia/Kolkata")

NOT_NIGHTLY = "This run is not a finished nightly run, so it is not compared with another day."
NO_RUN = "The brain has not finished a nightly run yet, so there is nothing to compare."
NO_PREVIOUS = "There is no earlier nightly run to compare with yet."


def ist_day(when: datetime) -> date:
    return when.astimezone(IST).date()


def _live_nightly():
    """Finished live nightly runs only (as strategies/brain.py::todays_run counts them)."""
    return select(BrainRun).where(
        BrainRun.kind == "nightly",
        BrainRun.live.is_(True),
        BrainRun.status == "done",
    )


def is_live_nightly(run: BrainRun) -> bool:
    return run.kind == "nightly" and bool(run.live) and run.status == "done"


def latest_live_nightly(db: Session, book: str) -> BrainRun | None:
    return db.execute(
        _live_nightly().where(BrainRun.book == book).order_by(BrainRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()


def previous_live_nightly(db: Session, run: BrainRun) -> BrainRun | None:
    """The newest finished live nightly run of the same book made on an earlier IST day."""
    day_start = datetime.combine(ist_day(run.as_of), time(0, 0), tzinfo=IST)
    return db.execute(
        _live_nightly()
        .where(BrainRun.book == run.book, BrainRun.as_of < day_start)
        .order_by(BrainRun.as_of.desc(), BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _ranks(ideas: list[BrainDecision]) -> dict[str, tuple[int, int, str | None]]:
    """symbol -> (place, out of, score kind). Ranked only among ideas whose score is the same
    kind, so a raw model score is never ranked against a calibrated one."""
    groups: dict[str | None, list[float]] = {}
    for d in ideas:
        if d.confidence is not None:
            groups.setdefault(d.score_source, []).append(d.confidence)
    out: dict[str, tuple[int, int, str | None]] = {}
    for d in ideas:
        if d.confidence is None:
            continue
        scores = groups[d.score_source]
        place = 1 + sum(1 for s in scores if s > d.confidence)
        out[d.symbol] = (place, len(scores), d.score_source)
    return out


def _by_symbol(db: Session, run: BrainRun) -> tuple[dict[str, BrainDecision], set[str]]:
    ideas: dict[str, BrainDecision] = {}
    held: set[str] = set()
    for d in db.execute(select(BrainDecision).where(BrainDecision.run_id == run.id)).scalars():
        if d.kind == "idea":
            ideas[d.symbol] = d
        else:
            held.add(d.symbol)
    return ideas, held


def _side(
    d: BrainDecision,
    rank: tuple[int, int, str | None] | None,
    *,
    db: Session | None = None,
    run: BrainRun | None = None,
    owner: bool = True,
) -> dict:
    """What the page needs to explain one day's decision — and nothing about results.

    For a non-owner the words are the stock-level verdict and the account's own room text is left out
    (services/public_verdict.py), the same as on the run and stock endpoints."""
    side = {
        "word": d.overruled_word or d.word,
        "brain_word": d.word,
        "overruled_word": d.overruled_word,
        "overrule_reason": d.overrule_reason,
        "reasons": list(d.reasons or []),
        "downgraded_from": d.downgraded_from,
        "downgrade_reason": d.downgrade_reason,
        "rank": rank[0] if rank else None,
        "rank_of": rank[1] if rank else None,
        "score_kind": rank[2] if rank else None,
    }
    if owner:
        return side
    public = public_verdict.public_fields(
        kind=d.kind,
        word=d.word,
        downgraded_from=d.downgraded_from,
        downgrade_reason=d.downgrade_reason,
        reasons=d.reasons or [],
        overruled_word=d.overruled_word,
        banner_mode=run.banner_mode if run is not None else None,
        trend=public_verdict.trend_lookup(db, run, d.symbol) if db is not None else None,
    )
    side.update(public)
    side["brain_word"] = public["word"]
    side["word"] = d.overruled_word or public["word"]
    side["overrule_reason"] = None
    return side


def _run_ref(run: BrainRun) -> dict:
    return {
        "run_id": run.id,
        "as_of": run.as_of,
        "day": ist_day(run.as_of).isoformat(),
        "banner_mode": run.banner_mode,
    }


def changes(db: Session, run_id: str | None = None, book: str = "paper", owner: bool = True) -> dict:
    """Today's ideas next to the previous trading day's, for the run the page is showing
    (`run_id`) or else the newest live nightly run of `book`."""
    if run_id is not None:
        run = db.get(BrainRun, run_id)
        if run is None:
            return {"comparable": False, "note": NO_RUN, "current": None, "previous": None, "ideas": []}
        if not is_live_nightly(run):
            return {
                "comparable": False,
                "note": NOT_NIGHTLY,
                "current": _run_ref(run),
                "previous": None,
                "ideas": [],
            }
    else:
        run = latest_live_nightly(db, book)
        if run is None:
            return {"comparable": False, "note": NO_RUN, "current": None, "previous": None, "ideas": []}

    prev = previous_live_nightly(db, run)
    if prev is None:
        return {
            "comparable": False,
            "note": NO_PREVIOUS,
            "current": _run_ref(run),
            "previous": None,
            "ideas": [],
        }

    now_ideas, now_held = _by_symbol(db, run)
    before_ideas, _ = _by_symbol(db, prev)
    now_rank, before_rank = _ranks(list(now_ideas.values())), _ranks(list(before_ideas.values()))
    rows = []
    for symbol in sorted(set(now_ideas) | set(before_ideas)):
        now, before = now_ideas.get(symbol), before_ideas.get(symbol)
        rows.append(
            {
                "symbol": symbol,
                "now": _side(now, now_rank.get(symbol), db=db, run=run, owner=owner)
                if now is not None
                else None,
                "before": _side(before, before_rank.get(symbol), db=db, run=prev, owner=owner)
                if before is not None
                else None,
                # Gone from today's ideas because the book now holds it, not because it was dropped.
                "held_now": owner and now is None and symbol in now_held,
            }
        )
    return {
        "comparable": True,
        "note": None,
        "current": _run_ref(run),
        "previous": _run_ref(prev),
        "ideas": rows,
    }
