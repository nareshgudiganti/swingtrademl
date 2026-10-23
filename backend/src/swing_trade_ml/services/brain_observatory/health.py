"""Module health for one stored brain run (spec 3.2; R1 independent flags, R2 corroboration, C4 history).

Pure functions over what the run stored: `brain_runs.modules` (every module installed when the run was
stored, with the mode it ran in; `{}` for failed or very old runs) and `brain_runs.trace` (one line per
module and step). The module -> step map comes from the current code's module list and is marked inferred
wherever it decides anything.
"""

from __future__ import annotations

from functools import lru_cache

from swing_trade_ml.brain.module import STEPS_FOR

EXECUTED = frozenset({"used", "shadow", "fallback", "rejected"})
VALID = frozenset({"used", "shadow"})
FAILED = frozenset({"fallback", "rejected"})
CONSISTENT = {
    "off": {"skipped"},
    "on": {"used", "fallback", "rejected"},
    "shadow": {"shadow", "fallback", "rejected"},
}
ALERTING_KINDS = frozenset(
    {"nightly", "intraday"}
)  # mirrors brain/alerts/service.py; a test keeps them equal
FLAGS = (
    "expected",
    "executed",
    "valid_output",
    "used",
    "shadow",
    "switched_off",
    "failed",
    "not_observed",
    "not_applicable",
    "not_installed_then",
    "unknown",
    "unknown_module",
    "duplicate",
    "conflicting",
)
CORROBORATION = ("corroborated", "single_source", "no_record", "not_installed", "conflicting")
M00_STATES = {
    "queued": ("not_started", "queued; not started yet"),
    "running": ("in_progress", "running now"),
    "failed": ("executed_failed", "started and failed; see the error"),
    "done": ("executed", "finished"),
    "superseded": ("executed", "finished; replaced by a later run of the same day"),
}


@lru_cache(maxsize=1)
def current_step_map() -> dict[str, str]:
    import swing_trade_ml.brain.modules  # noqa: F401 — registers the installed modules
    from swing_trade_ml.brain.module import REGISTRY

    return {cls.manifest.id: cls.manifest.step.value for cls in REGISTRY.all()}


def module_rows(kind: str, modules: dict | None, trace: list | None, step_map: dict[str, str]) -> list[dict]:
    modules = modules or {}
    installed_known = bool(modules)
    by_id: dict[str, list[dict]] = {}
    for item in trace or []:
        mid = item.get("module_id")
        if mid and mid != "fallback":
            by_id.setdefault(mid, []).append(item)
    steps_in_kind = {s.value for s in STEPS_FOR.get(kind, ())}
    rows = []
    for mid in sorted(set(step_map) | set(modules) | set(by_id)):
        lines = by_id.get(mid, [])
        mode = modules.get(mid)
        statuses = [item.get("status") for item in lines]
        seen = set(statuses)
        recorded_step = lines[0].get("step") if lines else None
        step = recorded_step or step_map.get(mid)
        inferred_step = recorded_step is None
        applicable = None if step is None else step in steps_in_kind
        conflicts = []
        if len(seen) > 1:
            conflicts.append(f"step log has different results for one module: {sorted(seen)}")
        if mode is not None and seen and not seen <= CONSISTENT.get(mode, set()):
            conflicts.append(f"mode '{mode}' but the step log says {sorted(seen)}")
        not_installed = installed_known and mid not in modules and not lines
        list_unknown = not installed_known and not lines
        off = "skipped" in seen or mode == "off"
        if conflicts:
            corroboration = "conflicting"
        elif not_installed:
            corroboration = "not_installed"
        elif mode is not None and lines:
            corroboration = "corroborated"
        elif mode is not None or lines:
            corroboration = "single_source"
        else:
            corroboration = "no_record"
        listed = installed_known and mid in modules
        flags = {
            "expected": bool(applicable) and listed and not off,
            "executed": bool(seen & EXECUTED),
            "valid_output": bool(seen & VALID),
            "used": "used" in seen,
            "shadow": "shadow" in seen,
            "switched_off": off,
            "failed": bool(seen & FAILED),
            "not_observed": bool(applicable) and listed and not lines and not off,
            "not_applicable": applicable is False,
            "not_installed_then": not_installed,
            "unknown": list_unknown,
            "unknown_module": mid not in step_map,
            "duplicate": len(lines) > 1 and len(seen) == 1,
            "conflicting": bool(conflicts),
        }
        rows.append(
            {
                "module_id": mid,
                "step": step,
                "step_source": None
                if step is None
                else ("current code (inferred)" if inferred_step else "step log"),
                "mode_recorded": mode,
                "statuses": statuses,
                "flags": flags,
                "inferred": dict.fromkeys(("expected", "not_observed", "not_applicable"), inferred_step),
                "corroboration": corroboration,
                "conflicts": conflicts,
                "failure_messages": [
                    item.get("reason", "") for item in lines if item.get("status") in FAILED
                ],
            }
        )
    return rows


def step_fallbacks(trace: list | None) -> list[dict]:
    return [
        {"step": item.get("step"), "reason": item.get("reason", "")}
        for item in trace or []
        if item.get("module_id") == "fallback"
    ]


def flag_counts(rows: list[dict]) -> dict:
    counts: dict = {flag: sum(1 for r in rows if r["flags"][flag]) for flag in FLAGS}
    counts["corroboration"] = {c: sum(1 for r in rows if r["corroboration"] == c) for c in CORROBORATION}
    counts["inferred_flags"] = ["expected", "not_observed", "not_applicable"]
    return counts


def headline(status: str, rows: list[dict], fallbacks: list[dict]) -> str:
    """The run's own status unless it finished; a finished run is 'completed' or 'degraded', or
    'completed_unchecked' when it stored no module list, so a missing module could not be noticed."""
    if status != "done":
        return status
    bad = any(r["flags"]["failed"] or r["flags"]["not_observed"] or r["flags"]["conflicting"] for r in rows)
    if bad or fallbacks:
        return "degraded"
    return "completed_unchecked" if any(r["flags"]["unknown"] for r in rows) else "completed"


def outside_rows(kind: str, live: bool, status: str, alerts_checked_at, alerts_sent: int) -> list[dict]:
    state, detail = M00_STATES.get(status, ("unknown", f"unrecognised run status '{status}'"))
    if status not in ("done", "superseded"):
        m16 = {"state": "not_applicable", "detail": "alerts are checked only after a finished run"}
    elif live and kind in ALERTING_KINDS:
        m16 = (
            {"state": "executed", "detail": f"alert check recorded; {alerts_sent} alerts sent"}
            if alerts_checked_at is not None
            else {"state": "unknown", "detail": "Not observed or send failed: no alert check was recorded"}
        )
    else:
        m16 = {"state": "not_applicable", "detail": "alerts run only after live nightly and intraday runs"}
    return [
        {"module_id": "M00", "state": state, "detail": detail},
        {"module_id": "M16", **m16},
        {
            "module_id": "M17",
            "state": "not_applicable",
            "detail": "the console is a screen, not a step of a run",
        },
        {
            "module_id": "M18",
            "state": "not_applicable",
            "detail": "go-live is not part of a single run; the day's stage is shown as day context",
        },
    ]
