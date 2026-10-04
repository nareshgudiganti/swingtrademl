"""The brain wired to the database: module switches, running, storing, reading
back. The API, the CLI and the scheduled jobs all go through here."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

import swing_trade_ml.brain.modules  # noqa: F401 — registers installed modules
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.module import REGISTRY, STEPS, STEPS_FOR, Mode, ModuleRegistry, resolve_mode
from swing_trade_ml.brain.reader import IST, DatedReader
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainDecision, BrainModuleSetting, BrainRun, FeatureSnapshot

log = get_logger(__name__)


class UnknownModuleError(LookupError):
    pass


class UnknownDecisionError(LookupError):
    pass


class OverruleRefusedError(ValueError):
    pass


class ModeRefusedError(ValueError):
    pass


# --- switches ----------------------------------------------------------------


def load_modes(db: Session) -> dict[str, Mode]:
    rows = db.execute(select(BrainModuleSetting)).scalars()
    return {r.module_id: Mode(r.mode) for r in rows}


def set_mode(
    db: Session,
    module_id: str,
    mode: Mode | str,
    *,
    by: str,
    note: str | None = None,
    known_ids: set[str] | None = None,
    mandatory_ids: set[str] | None = None,
) -> BrainModuleSetting:
    mode = Mode(mode)
    module_id = module_id.upper()
    known = known_ids if known_ids is not None else {cls.manifest.id for cls in REGISTRY.all()}
    mandatory = (
        mandatory_ids
        if mandatory_ids is not None
        else {cls.manifest.id for cls in REGISTRY.all() if cls.manifest.mandatory}
    )
    if module_id not in known:
        raise UnknownModuleError(f"No module {module_id} is installed.")
    if module_id in mandatory and mode is not Mode.ON:
        raise ModeRefusedError(f"{module_id} is the safety gate and cannot be switched to {mode.value}.")
    row = db.get(BrainModuleSetting, module_id) or BrainModuleSetting(module_id=module_id)
    row.mode, row.changed_by, row.note = mode.value, by, note
    db.add(row)
    db.commit()
    return row


# --- running ---------------------------------------------------------------


def run_brain(
    db: Session,
    *,
    kind: str = "nightly",
    as_of: datetime | None = None,
    symbols: list[str] | None = None,
    book: str = "paper",
    registry: ModuleRegistry = REGISTRY,
) -> tuple[BrainContext, str]:
    """Run and store. `as_of` in the past makes it a replay: no live-only inputs."""
    if kind not in STEPS_FOR:
        raise ValueError(f"kind must be one of {sorted(STEPS_FOR)}")
    now = datetime.now(UTC)
    live = as_of is None
    if as_of is not None and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=ZoneInfo("Asia/Kolkata"))  # the owner's clock
    as_of = as_of or now
    reader = DatedReader(db, as_of=as_of, live=live)
    if kind == "intraday":
        universe: tuple[str, ...] = ()  # holdings only
    else:
        universe = tuple(s.upper() for s in symbols) if symbols else reader.universe()

    run_id = f"{kind}-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    request = c.RunRequest(run_id=run_id, kind=kind, as_of=as_of, universe=universe, book=book, live=live)
    modes = load_modes(db)
    started = time.perf_counter()
    try:
        # A savepoint around the run: if the database fails mid-run (Postgres
        # then refuses every further statement in the transaction), rolling
        # back to it leaves the session usable to record the failure below.
        with db.begin_nested():
            ctx = execute(request, reader, registry, modes)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        with db.begin_nested():
            _store(db, ctx, registry, modes, elapsed_ms)
        db.commit()
    except Exception as exc:
        # Modules cannot break a run, but the database, the reader or the
        # storing can. Keep the failure so the console and health see it.
        _record_failure(db, request, exc, int((time.perf_counter() - started) * 1000))
        raise
    if kind == "nightly" and live:
        _sync_episodes(db, reader, registry, modes)
    log.info(
        "brain.run.done",
        run_id=run_id,
        kind=kind,
        decisions=len(ctx.decisions),
        banner=ctx.banner.mode.value,
        ms=elapsed_ms,
    )
    return ctx, run_id


def _sync_episodes(db: Session, reader: DatedReader, registry: ModuleRegistry, modes: dict) -> None:
    """After a live nightly run, refresh what the brain remembers: market
    episodes (M04, when on) and the experience table (M05, unless off).
    Replays and why-runs never write them; a failure here never fails the run."""
    from swing_trade_ml.brain.modules.m04_situations import store as episodes
    from swing_trade_ml.brain.modules.m05_memory import store as memory
    from swing_trade_ml.brain.modules.m09_learn import scoring as learning

    # (module, modes it runs in, store, function) — looked up at call time.
    jobs = (
        ("M04", (Mode.ON,), episodes, "sync_from_reader"),
        ("M05", (Mode.ON, Mode.SHADOW), memory, "rebuild_from_reader"),
        ("M09", (Mode.ON,), learning, "score_pending_from_reader"),
    )
    for module_id, wanted, store, name in jobs:
        cls = registry.get(module_id)
        if cls is None or resolve_mode(cls.manifest, modes.get(module_id)) not in wanted:
            continue
        job = getattr(store, name)
        try:
            with db.begin_nested():
                job(db, reader)
            db.commit()
        except Exception as exc:  # noqa: BLE001 — memory is a by-product, not the run
            log.warning("brain.afterrun.job_failed", module=module_id, error=str(exc))


def _record_failure(db: Session, request: c.RunRequest, exc: Exception, ms: int) -> None:
    try:
        db.add(
            BrainRun(
                id=request.run_id,
                kind=request.kind,
                as_of=request.as_of,
                book=request.book,
                live=request.live,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                ms=ms,
            )
        )
        db.commit()
    except Exception as record_exc:  # noqa: BLE001 — never hide the original error
        log.error("brain.run.failure_not_recorded", run_id=request.run_id, error=str(record_exc))
    log.error("brain.run.failed", run_id=request.run_id, kind=request.kind, error=str(exc))


def _jsonable(value):
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def _quality_summary(ctx: BrainContext) -> dict:
    overall = ctx.quality.get("*")
    return {
        "overall": None
        if overall is None
        else {
            "score": overall.score,
            "fresh": overall.fresh,
            "issues": list(overall.issues),
        },
        "stale": sorted(
            q.symbol
            for q in ctx.quality.values()
            if q.symbol not in ("*", settings.BENCHMARK_INDEX_SYMBOL) and not q.fresh
        ),
    }


def _context_summary(ctx: BrainContext) -> dict:
    from swing_trade_ml.brain.modules.m11_sector.ranking import plain_name

    sectors = sorted(ctx.sectors.values(), key=lambda s: s.rank)
    return {
        "sectors": [{**_jsonable(asdict(s)), "name": plain_name(s.sector)} for s in sectors],
        "situations": [_jsonable(asdict(s)) for s in ctx.situations],
        "portfolio": _portfolio_summary(ctx),
    }


def _portfolio_summary(ctx: BrainContext) -> dict:
    """M14's view of the book for the console: what is biggest, and which
    holdings move together."""
    p = ctx.portfolio
    if p is None:
        return {}
    held = set(ctx.held_symbols)
    return {
        "largest_position": list(p.largest_position) if p.largest_position else None,
        "top_sector": list(p.top_sector) if p.top_sector else None,
        "holdings_moving_together": [
            [a, b, round(r, 2)] for a, b, r in p.correlated if a in held and b in held
        ],
    }


def _store(db: Session, ctx: BrainContext, registry: ModuleRegistry, modes: dict, ms: int) -> None:
    req = ctx.request
    used_modes = {
        cls.manifest.id: resolve_mode(cls.manifest, modes.get(cls.manifest.id)).value
        for cls in registry.all()
    }
    db.add(
        BrainRun(
            id=req.run_id,
            kind=req.kind,
            as_of=req.as_of,
            book=req.book,
            live=req.live,
            ms=ms,
            status="done",
            banner_mode=ctx.banner.mode.value,
            banner_headline=ctx.banner.headline,
            modules=used_modes,
            trace=[_jsonable(asdict(e)) for e in ctx.trace],
            quality=_quality_summary(ctx),
            context=_context_summary(ctx),
        )
    )
    db.flush()
    carried = _todays_overrules(db, req) if req.live else {}
    for d in ctx.decisions.values():
        row = BrainDecision(
            run_id=req.run_id,
            symbol=d.symbol,
            kind=d.kind,
            word=d.word.value,
            entry_low=d.entry_low,
            entry_high=d.entry_high,
            target=d.target,
            stop=d.stop,
            qty=d.qty,
            horizon_days=d.horizon_days,
            confidence=d.confidence,
            score_source=d.confidence_source,
            evidence_text=d.evidence_text or None,
            reasons=list(d.reasons),
            downgraded_from=d.downgraded_from.value if d.downgraded_from else None,
            downgrade_reason=d.downgrade_reason,
        )
        _carry_overrule(row, carried.get((d.symbol, d.kind)))
        db.add(row)
    if req.kind == "nightly":
        _store_snapshots(db, ctx)
    if req.live and req.kind in ("nightly", "intraday") and ctx.tracks:
        from swing_trade_ml.brain.modules.m15_tracker.store import save_points

        opened = {h.symbol: h.opened_on for h in ctx.holdings if h.opened_on is not None}
        save_points(db, req.book, opened, list(ctx.tracks.values()), req.as_of.astimezone(IST).date())


def _todays_overrules(db: Session, req: c.RunRequest) -> dict[tuple[str, str], BrainDecision]:
    """The owner's overrules on earlier live runs of the same IST day and book,
    most careful per (symbol, kind). A rerun ("Run the brain now") becomes
    today's run for buying and approvals, so it must not drop them (C8)."""
    day = req.as_of.astimezone(IST).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST)
    rows = db.execute(
        select(BrainDecision)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.book == req.book,
            BrainRun.as_of >= start,
            BrainRun.as_of < start + timedelta(days=1),
            BrainRun.id != req.run_id,
            BrainDecision.overruled_word.is_not(None),
        )
    ).scalars()
    best: dict[tuple[str, str], BrainDecision] = {}
    for row in rows:
        key = (row.symbol, row.kind)
        held = best.get(key)
        if held is None or _caution(row.kind, row.overruled_word) < _caution(row.kind, held.overruled_word):
            best[key] = row
    return best


def _caution(kind: str, word: str) -> int:
    """The overrule endpoint's ordering: 0 = most careful."""
    vocabulary = c.IdeaWord if kind == "idea" else c.HoldingWord
    return c.rank(vocabulary(word))


def _carry_overrule(row: BrainDecision, earlier: BrainDecision | None) -> None:
    """Copy an earlier same-day overrule only when it is more careful than the
    new run's own word; a word already as careful stands on its own."""
    if earlier is None or _caution(row.kind, earlier.overruled_word) >= _caution(row.kind, row.word):
        return
    row.overruled_word = earlier.overruled_word
    row.overrule_reason = earlier.overrule_reason
    row.overruled_by = earlier.overruled_by
    row.overruled_at = earlier.overruled_at


def _store_snapshots(db: Session, ctx: BrainContext) -> None:
    """Upsert this night's feature snapshots (M02) — one per stock and day."""
    for snap in ctx.snapshots.values():
        if not snap.features:
            continue  # the price-only fallback: nothing worth keeping
        values = {
            "symbol": snap.symbol,
            "bar_date": date.fromisoformat(snap.as_of),
            "feature_set_version": snap.feature_set_version,
            "run_id": ctx.request.run_id,
            "close": snap.close,
            "atr_14": snap.atr_14,
            "adv_inr_20": snap.adv_inr_20,
            "features": dict(snap.features),
        }
        stmt = insert(FeatureSnapshot).values(**values)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol", "bar_date", "feature_set_version"],
                set_={k: stmt.excluded[k] for k in ("run_id", "close", "atr_14", "adv_inr_20", "features")},
            )
        )


# --- reading back ------------------------------------------------------------


def latest_run(db: Session, kind: str | None = None, include_replays: bool = False) -> BrainRun | None:
    """Newest finished run (failed runs have no decisions to show). Replays of
    past dates are skipped unless asked for: "latest" means today's thinking."""
    stmt = select(BrainRun).where(BrainRun.status == "done")
    if not include_replays:
        stmt = stmt.where(BrainRun.live.is_(True))
    if kind:
        stmt = stmt.where(BrainRun.kind == kind)
    return db.execute(stmt.order_by(BrainRun.started_at.desc()).limit(1)).scalar_one_or_none()


def decisions_for(db: Session, run_id: str) -> list[BrainDecision]:
    return list(
        db.execute(
            select(BrainDecision)
            .where(BrainDecision.run_id == run_id)
            .order_by(BrainDecision.kind, BrainDecision.symbol)
        ).scalars()
    )


def module_overview(db: Session, registry: ModuleRegistry = REGISTRY) -> list[dict]:
    modes = load_modes(db)
    return [
        {
            "id": m.id,
            "name": m.name,
            "step": m.step.value,
            "kind": m.kind,
            "version": m.version,
            "mode": resolve_mode(m, modes.get(m.id)).value,
            "mandatory": m.mandatory,
            "reads": list(m.reads),
            "writes": list(m.writes),
        }
        for m in (cls.manifest for cls in registry.all())
    ]


def step_overview(registry: ModuleRegistry = REGISTRY) -> list[dict]:
    """Each step and which installed modules fill it; an empty list means the
    step answers with its fallback."""
    return [
        {"step": step.value, "modules": [cls.manifest.id for cls in registry.for_step(step)]}
        for step in STEPS
    ]


def list_runs(db: Session, kind: str | None = None, limit: int = 20) -> list[BrainRun]:
    stmt = select(BrainRun)
    if kind:
        stmt = stmt.where(BrainRun.kind == kind)
    return list(db.execute(stmt.order_by(BrainRun.started_at.desc()).limit(limit)).scalars())


# --- owner actions ------------------------------------------------------------


def overrule(db: Session, decision_id: int, word: str, reason: str, by: str) -> BrainDecision:
    """Constitution C8: the owner may overrule any decision, but only toward
    caution. The brain's own word stays on the row next to the overrule."""
    d = db.get(BrainDecision, decision_id)
    if d is None:
        raise UnknownDecisionError(f"No decision {decision_id}.")
    vocabulary = c.IdeaWord if d.kind == "idea" else c.HoldingWord
    try:
        new_word = vocabulary(word.upper())
    except ValueError as exc:
        raise OverruleRefusedError(f"{word} is not a word for a {d.kind}.") from exc
    current = vocabulary(d.overruled_word or d.word)
    if c.rank(new_word) >= c.rank(current):
        raise OverruleRefusedError(
            f"An overrule can only be more careful than {current.value}; {new_word.value} is not."
        )
    d.overruled_word = new_word.value
    d.overrule_reason = reason.strip()
    d.overruled_by = by
    d.overruled_at = datetime.now(UTC)
    db.commit()
    return d


# --- health ------------------------------------------------------------------


def health(db: Session) -> dict:
    last = db.execute(select(BrainRun).order_by(BrainRun.started_at.desc()).limit(1)).scalar_one_or_none()
    last_ok_nightly = db.execute(
        select(BrainRun.started_at)
        .where(BrainRun.kind == "nightly", BrainRun.status == "done", BrainRun.live.is_(True))
        .order_by(BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    week_ago = datetime.now(UTC) - timedelta(days=7)
    failed = db.execute(
        select(func.count(BrainRun.id)).where(BrainRun.status == "failed", BrainRun.started_at >= week_ago)
    ).scalar_one()
    latest_done = latest_run(
        db, "nightly"
    )  # live nightly only: a replay or one-stock run says nothing about today
    overall = (latest_done.quality or {}).get("overall") if latest_done else None
    return {
        "last_run": None
        if last is None
        else {
            "run_id": last.id,
            "kind": last.kind,
            "started_at": last.started_at,
            "status": last.status,
            "ms": last.ms,
            "error": last.error,
        },
        "last_nightly_ok": last_ok_nightly,
        "failed_runs_7d": int(failed),
        "data": overall or {"score": None, "fresh": None, "issues": ["No data check has run yet."]},
        "stale_count": len((latest_done.quality or {}).get("stale", [])) if latest_done else 0,
    }
