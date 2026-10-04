"""Runs the eight steps. A module can never break a run: if it is off, raises,
overruns its time budget, reads or writes a contract it did not declare, or
writes a verdict or decision it is not allowed to, its output is dropped and
the step's fallback answers instead. Every choice is written to the trace.

`execute` is pure over a reader, so it is tested without a database;
`service.run_brain` wires it to the real database and stores the result.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from swing_trade_ml.brain import constitution
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.fallbacks import FALLBACKS
from swing_trade_ml.brain.module import STEPS_FOR, Mode, ModuleRegistry, Step, resolve_mode


def _permission_error(manifest, out: c.Contribution) -> str | None:
    if out.verdicts and not manifest.mandatory:
        return "only the mandatory risk gate may write risk verdicts"
    if (out.decisions or out.banner is not None) and manifest.step is not Step.DECIDE:
        return "only decide-step modules may write decisions or the banner"
    return None


def _run_module(ctx: BrainContext, cls, mode: Mode) -> bool:
    """Run one module; merge its output if it is ON. True when it was used."""
    m = cls.manifest
    step = m.step.value

    def event(status: str, reason: str = "", ms: int = 0) -> None:
        ctx.trace.append(
            c.TraceEvent(step=step, module_id=m.id, status=status, reason=reason, ms=ms, version=m.version)
        )

    if mode is Mode.OFF:
        event("skipped", "switched off")
        return False

    started = time.perf_counter()
    try:
        out = cls().run(ctx.view_for(m))
        c.validate_contribution(out, m.writes)
    except c.ContractError as exc:
        event("fallback", f"bad output: {exc}", _ms(started))
        return False
    except Exception as exc:  # noqa: BLE001 — a module must never break the run
        event("fallback", f"error: {exc!r}", _ms(started))
        return False

    elapsed = time.perf_counter() - started
    budget = m.budget(ctx.request.kind)
    if elapsed > budget:
        event("fallback", f"too slow: {elapsed:.2f} s against a {budget:.2f} s budget", _ms(started))
        return False

    refused = _permission_error(m, out)
    if refused:
        event("rejected", refused, _ms(started))
        return False

    if mode is Mode.SHADOW:
        ctx.shadow[m.id] = out
        event("shadow", "recorded, not used", _ms(started))
        return False

    ctx.merge(out)
    if m.mandatory:
        ctx.risk_gate_ran = True
    event("used", "", _ms(started))
    return True


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def execute(
    request: c.RunRequest,
    reader,
    registry: ModuleRegistry,
    modes: Mapping[str, Mode | str],
    on_step: Callable[[int, int, str], None] | None = None,
) -> BrainContext:
    """`on_step(done, total, step)` is told after each step finishes, so a
    queued run can show "step 3 of 8" while it thinks; it never affects the run."""
    ctx = BrainContext.start(request, reader)
    steps = STEPS_FOR[request.kind]
    for n, step in enumerate(steps, start=1):
        used = False
        for cls in registry.for_step(step):
            mode = resolve_mode(cls.manifest, modes.get(cls.manifest.id))
            used = _run_module(ctx, cls, mode) or used
        # The fallback always runs after the modules. Merge never overwrites,
        # so it only fills what the modules left empty — a data-quality
        # module that writes no snapshots still gets fallback snapshots.
        started = time.perf_counter()
        ctx.merge(FALLBACKS[step](ctx))
        if not used:
            ctx.trace.append(
                c.TraceEvent(
                    step=step.value,
                    module_id="fallback",
                    status="fallback",
                    reason="no module answered",
                    ms=_ms(started),
                )
            )
        if on_step is not None:
            on_step(n, len(steps), step.value)
    constitution.enforce(ctx)
    return ctx
