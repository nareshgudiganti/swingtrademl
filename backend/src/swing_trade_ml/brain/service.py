"""The brain wired to the database: module switches, running, storing, reading
back. The API, the CLI and the scheduled jobs all go through here."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import swing_trade_ml.brain.modules  # noqa: F401 — registers installed modules
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.module import REGISTRY, STEPS, STEPS_FOR, Mode, ModuleRegistry, resolve_mode
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainDecision, BrainModuleSetting, BrainRun

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
        ctx = execute(request, reader, registry, modes)
    except Exception as exc:
        # Modules cannot break a run, but the database or the reader can.
        # Keep the failure so the console and health can see it, then raise.
        if not db.is_active:  # only a failed flush leaves the session unusable
            db.rollback()
        db.add(
            BrainRun(
                id=run_id,
                kind=kind,
                as_of=as_of,
                book=book,
                live=live,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                ms=int((time.perf_counter() - started) * 1000),
            )
        )
        db.commit()
        log.error("brain.run.failed", run_id=run_id, kind=kind, error=str(exc))
        raise
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _store(db, ctx, registry, modes, elapsed_ms)
    log.info(
        "brain.run.done",
        run_id=run_id,
        kind=kind,
        decisions=len(ctx.decisions),
        banner=ctx.banner.mode.value,
        ms=elapsed_ms,
    )
    return ctx, run_id


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
        "stale": sorted(q.symbol for q in ctx.quality.values() if q.symbol != "*" and not q.fresh),
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
        )
    )
    db.flush()
    for d in ctx.decisions.values():
        db.add(
            BrainDecision(
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
                evidence_text=d.evidence_text or None,
                reasons=list(d.reasons),
                downgraded_from=d.downgraded_from.value if d.downgraded_from else None,
                downgrade_reason=d.downgrade_reason,
            )
        )
    db.commit()


# --- reading back ------------------------------------------------------------


def latest_run(db: Session, kind: str | None = None) -> BrainRun | None:
    """Newest finished run (failed runs have no decisions to show)."""
    stmt = select(BrainRun).where(BrainRun.status == "done")
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
        .where(BrainRun.kind == "nightly", BrainRun.status == "done")
        .order_by(BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    week_ago = datetime.now(UTC) - timedelta(days=7)
    failed = db.execute(
        select(func.count(BrainRun.id)).where(BrainRun.status == "failed", BrainRun.started_at >= week_ago)
    ).scalar_one()
    latest_done = latest_run(db)
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
