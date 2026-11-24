# ruff: noqa: E501  (long plain-English docstrings)
"""The module registry (#291): which parts of the platform exist, whether each is on, and what it depends on.

A MODULE is a named part of the product with its routes, its scheduled jobs and its dependencies. This file is the one
place that says what modules exist. It holds the CONTRACT and the declarations; it changes nothing by itself.

The contract (each point has a test, tests/test_module_registry.py):

- CORE modules (sign-in, the risk limits and safety switches, orders and the paper-mode guards, health) are always on.
  Asking to switch one off is refused, and the refusal is recorded. A core module never depends on an optional one.
- An OPTIONAL module is on by default (every module declared today is exactly as available as before). Switching one
  off makes its routes answer "switched off" (`require_module`) and lists the scheduled jobs to leave out
  (`jobs_to_skip`). It never deletes, moves or rewrites data, and it touches nothing outside the module.
- Dependencies are honoured: a module cannot be switched on while something it depends on is off, and a module cannot
  be switched off while another module that depends on it is on (switch the dependent off first). Nothing cascades
  silently.
- Every request to change a switch is audited: who, when, which module, from what to what, why, and whether it was
  allowed or refused. A change is applied only after its audit record is written.
- A retired module can never be switched on again.

What is enforced, and where (`ENFORCEMENT`, repeated on every audit event): routes are refused by `require_module`
on every router of a declared optional module; scheduled jobs are removed by `apply_to_scheduler` when the scheduler
starts, in the process that starts it. Both read the state of THIS process only.

Where the state lives: in the `module_switches` table, through a store (`services/module_state.DbStore`). Every
process (the API and the worker) keeps the state in memory, starting from the declared defaults, and refreshes it
from the table every few seconds; the worker also re-reads it before each scheduled job run. No row means the
declared default, so nothing changes behaviour until the owner switches a module off through the admin endpoint
(`PUT /admin/modules/{id}`), which is audited. If the table cannot be read, a process keeps the state it last knew.

Pure: this module imports nothing from the application, only FastAPI's error type, like `release_switches.py`; the
audit sink and the store are loaded when first used.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fastapi import HTTPException, Request, status

log = logging.getLogger(__name__)

STATE_CACHE_SECONDS = 5.0  # how long a process trusts its copy of the durable state


class ModuleState(StrEnum):
    """Where a module is in its life. Only ACTIVE and PARKED modules are on by default."""

    DEVELOPMENT = "development"
    ACTIVE = "active"
    PARKED = "parked"  # kept and reachable, not being worked on (Finance today)
    DEPRECATED = "deprecated"
    RETIRED = "retired"  # gone from the product; its data stays; it can never be switched on


class ModuleError(Exception):
    """A registry rule was broken (the message says which)."""


class CoreModuleError(ModuleError):
    """Someone asked to switch a core module off."""


class DependencyError(ModuleError):
    """A switch would leave a module on without something it depends on."""


class UnknownModuleError(ModuleError, KeyError):
    """No module has this id."""


@dataclass(frozen=True, slots=True)
class Module:
    id: str
    label: str  # plain English
    core: bool = False
    state: ModuleState = ModuleState.ACTIVE
    route_prefixes: tuple[str, ...] = ()  # API paths, without /api/v1
    jobs: tuple[str, ...] = ()  # scheduler job ids this module owns
    capabilities: tuple[str, ...] = ()  # capability ids (for the later entitlement work, #335)
    depends_on: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()  # the code that belongs to it
    # Paths under route_prefixes that are SAFETY and never switch off with the module (a guard lets them through).
    always_on: tuple[str, ...] = ()

    @property
    def default_enabled(self) -> bool:
        return self.state in (ModuleState.ACTIVE, ModuleState.PARKED)


# ---------------------------------------------------------------------------------------------- the declarations
# Only modules whose routes and jobs exist today are declared, and a test checks every prefix and job id against the
# real app. More modules are declared as they are brought under the registry (the table is the only thing to edit).
REGISTRY: tuple[Module, ...] = (
    # ---- core: always on
    Module("core.auth", "Sign-in and accounts", core=True, route_prefixes=("/auth",)),
    Module(
        "core.safety",
        "Risk limits and safety switches",
        core=True,
        route_prefixes=("/risk", "/safety"),
        packages=("swing_trade_ml.services.risk", "swing_trade_ml.services.limits"),
    ),
    Module("core.orders", "Orders and the paper-mode guards", core=True, route_prefixes=("/orders",)),
    Module("core.health", "Health and readiness", core=True, route_prefixes=("/health", "/ready")),
    # ---- optional: on by default
    Module(
        "finance",
        "Personal finance (parked)",
        state=ModuleState.PARKED,
        route_prefixes=("/finance",),
        packages=("swing_trade_ml.services.finance",),
    ),
    Module(
        "mutual_funds",
        "Mutual funds",
        route_prefixes=("/mutual-funds",),
        jobs=("sync_mutual_fund_navs",),
        packages=("swing_trade_ml.services.finance.mutual_funds",),
    ),
    Module(
        "brain",
        "TradeMind Brain views",
        route_prefixes=("/brain",),
        # Not switchable, on purpose: brain_intraday (the 15-minute holdings check: stop-proximity warnings) and
        # brain_run_queue (runs requests already accepted); the stage, rollback and approval routes (safety).
        jobs=("brain_nightly", "brain_learn", "brain_daily_check"),
        always_on=("/brain/stage", "/brain/approvals"),
        # A plan reaches the brain's consumer views only with the TradeMind feature (core/plans.py).
        capabilities=("trademind",),
        packages=("swing_trade_ml.brain",),
    ),
    Module(
        "research_lanes",
        "Research lanes (owner only)",
        route_prefixes=("/research/lanes", "/research/lane-picks", "/research/h05"),
        jobs=(
            "lane_shadow_daily",
            "h05_daily",
        ),  # the lanes' own daily jobs (shadow_lanes/lane_job.py, h05 lane)
        # The h05 lane's own package is deliberately not named here: nothing outside the lane may reference it
        # (tests/test_h05_service.py). The registry only needs its route prefix above.
        packages=("swing_trade_ml.shadow_lanes",),
    ),
)

# A switch that is not a plain on/off is not in this table; the release switches (core/release_switches.py) stay as they are.


class RegistryError(ModuleError):
    """The declarations themselves are wrong (a duplicate id, a missing dependency, a cycle)."""


def validate(registry: Iterable[Module]) -> None:
    """Refuse a registry that cannot be reasoned about: duplicate ids, a dependency that is not declared, a cycle, a
    core module that depends on an optional one, or a core module that is not ACTIVE."""
    modules = list(registry)
    by_id = {m.id: m for m in modules}
    if len(by_id) != len(modules):
        raise RegistryError("a module id is declared twice")
    for m in modules:
        if m.core and m.state is not ModuleState.ACTIVE:
            raise RegistryError(f"{m.id}: a core module must be ACTIVE")
        for dep in m.depends_on:
            if dep not in by_id:
                raise RegistryError(f"{m.id} depends on {dep!r}, which is not declared")
            if m.core and not by_id[dep].core:
                raise RegistryError(f"core module {m.id} cannot depend on the optional module {dep}")
    seen: set[str] = set()

    def walk(mid: str, path: tuple[str, ...]) -> None:
        if mid in path:
            raise RegistryError("dependency cycle: " + " -> ".join((*path, mid)))
        if mid in seen:
            return
        for dep in by_id[mid].depends_on:
            walk(dep, (*path, mid))
        seen.add(mid)

    for m in modules:
        walk(m.id, ())


AuditSink = Callable[[dict], None]

ENFORCEMENT = {
    "routes": "enforced: every router of an optional module answers 'switched off' while it is off (require_module)",
    "jobs": "enforced: a scheduled job of a switched-off module is left out at start and skipped at every run",
    "scope": "shared: the state is stored in the database; each process refreshes it every few seconds",
}


class StateStore(Protocol):
    """Where the on/off state lives. `read` returns module id -> enabled for every module that has a row."""

    def read(self) -> dict[str, bool]: ...

    def write(self, module_id: str, enabled: bool, by: str, reason: str) -> None: ...

    # Optional: `exclusive()`, a context manager that lets only one switch at a time decide and write.


def durable_audit(event: dict) -> None:
    """The default sink: one row in the app's own audit log (services/audit, as the admin console writes it)."""
    from swing_trade_ml.services import module_audit

    module_audit.write_durable(event)


class DurableStore:
    """The default store: the `module_switches` table (services/module_state), loaded when first used."""

    def exclusive(self):
        from swing_trade_ml.services.module_state import DbStore

        return DbStore().exclusive()

    def read(self) -> dict[str, bool]:
        from swing_trade_ml.services.module_state import DbStore

        return DbStore().read()

    def write(self, module_id: str, enabled: bool, by: str, reason: str) -> None:
        from swing_trade_ml.services.module_state import DbStore

        DbStore().write(module_id, enabled, by, reason)


class ModuleSwitches:
    """The on/off state of a registry, with an audit trail. Defaults come from the declarations; with a store the
    state is shared through it (a short cache per process; `enabled(..., fresh=True)` always re-reads)."""

    def __init__(
        self,
        registry: Iterable[Module] = REGISTRY,
        audit: AuditSink | None = None,
        store: StateStore | None = None,
        cache_seconds: float = STATE_CACHE_SECONDS,
    ) -> None:
        self._modules = tuple(registry)
        validate(self._modules)
        self._by_id = {m.id: m for m in self._modules}
        self._on = {m.id: m.default_enabled for m in self._modules}
        self.events: list[dict] = []  # every request, in order (kept in memory as well as sent to `audit`)
        self._audit = audit
        self._store = store
        self._cache_seconds = cache_seconds
        self._loaded_at: float | None = None
        self._read_ok = False  # whether the stored state has been read successfully (the last time we tried)

    @property
    def state_unknown(self) -> bool:
        """True when a store is set but its state could not be read: the declared defaults are in use."""
        return self._store is not None and not self._read_ok

    def _refresh(self, force: bool = False) -> None:
        """Take the stored state for every optional module (no row = its default). A read that fails keeps what
        this process already knew (the declared default at first): a failure never switches anything."""
        if self._store is None:
            return
        now = time.monotonic()
        if not force and self._loaded_at is not None and now - self._loaded_at < self._cache_seconds:
            return
        try:
            rows = self._store.read()
        except Exception as exc:  # noqa: BLE001 - the app must keep answering when the table cannot be read
            log.error(
                "module_switches.read_failed (%s): the switch state is UNKNOWN; keeping the last known state "
                "(the declared defaults if none)",
                type(exc).__name__,
            )
            self._read_ok = False
            self._loaded_at = now
            return
        for m in self._modules:
            if not m.core and m.state is not ModuleState.RETIRED:
                self._on[m.id] = bool(rows[m.id]) if m.id in rows else m.default_enabled
        self._read_ok = True
        self._loaded_at = now

    # ---- reading
    def module(self, module_id: str) -> Module:
        try:
            return self._by_id[module_id]
        except KeyError:
            raise UnknownModuleError(module_id) from None

    def modules(self) -> tuple[Module, ...]:
        return self._modules

    def enabled(self, module_id: str, *, fresh: bool = False) -> bool:
        module = self.module(module_id)
        if module.core:
            return True
        self._refresh(force=fresh)
        return self._on[module_id]

    def dependents(self, module_id: str) -> tuple[str, ...]:
        """The modules that name this one in `depends_on`."""
        return tuple(m.id for m in self._modules if module_id in m.depends_on)

    def module_for_path(self, path: str) -> Module | None:
        """The module that owns an API path (the longest matching prefix), or None."""
        best: tuple[int, Module] | None = None
        for m in self._modules:
            for prefix in m.route_prefixes:
                if (path == prefix or path.startswith(prefix + "/")) and (
                    best is None or len(prefix) > best[0]
                ):
                    best = (len(prefix), m)
        return None if best is None else best[1]

    def jobs_to_skip(self) -> frozenset[str]:
        """Scheduler job ids that belong to a module that is off: leave them out (or remove them)."""
        return frozenset(job for m in self._modules if not self.enabled(m.id) for job in m.jobs)

    # ---- changing
    def _record(
        self, module_id: str, before: bool | None, after: bool, by: str, reason: str, outcome: str
    ) -> None:
        event = {
            "at": datetime.now(UTC).isoformat(),
            "module": module_id,
            "from": before,
            "to": after,
            "by": by,
            "reason": reason,
            "outcome": outcome,  # "applied" | "unchanged" | "refused: <why>"
            "scope": ENFORCEMENT["scope"],
        }
        if self._audit is not None:
            self._audit(event)  # a failing audit stops the change: nothing is switched without its record
        self.events.append(event)

    def set_enabled(self, module_id: str, on: bool, *, by: str, reason: str) -> bool:
        """Switch an OPTIONAL module on or off. Returns True when the state changed. Core modules, retired modules,
        and anything that would break a dependency are refused (and the refusal is recorded)."""
        if not by.strip() or not reason.strip():
            raise ModuleError("a change needs who made it and why")
        self.module(module_id)
        exclusive = getattr(self._store, "exclusive", None)
        with exclusive() if exclusive is not None else nullcontext():
            return self._set_enabled(module_id, on, by=by, reason=reason)

    def _set_enabled(self, module_id: str, on: bool, *, by: str, reason: str) -> bool:
        """The decision and the write, run while no other switch can (see `exclusive` on the store)."""
        module = self.module(module_id)
        self._refresh(force=True)  # decide from the shared state, not from a stale copy
        before = self._on[module_id] if not module.core else True
        refusal: ModuleError | None = None
        if module.core and not on:
            refusal = CoreModuleError(f"{module_id} is a core module and cannot be switched off")
        elif on and module.state is ModuleState.RETIRED:
            refusal = ModuleError(f"{module_id} is retired and cannot be switched on")
        elif on:
            off = [d for d in module.depends_on if not self.enabled(d)]
            if off:
                refusal = DependencyError(f"{module_id} needs {', '.join(off)} switched on first")
        elif not module.core:
            active = [d for d in self.dependents(module_id) if self.enabled(d)]
            if active:
                refusal = DependencyError(f"{', '.join(active)} depend on {module_id}: switch them off first")
        if refusal is not None:
            self._record(module_id, before, on, by, reason, f"refused: {refusal}")
            raise refusal
        if before == on:
            self._record(module_id, before, on, by, reason, "unchanged")
            return False
        self._record(module_id, before, on, by, reason, "applied")
        if self._store is not None:
            try:
                self._store.write(module_id, on, by, reason)
            except Exception as exc:
                # The request was audited as applied but could not be stored: say so, change nothing, tell the caller.
                with suppress(Exception):  # the failure itself is what the caller sees
                    self._record(
                        module_id, before, on, by, reason, f"failed: not stored ({type(exc).__name__})"
                    )
                raise
        self._on[module_id] = on
        if self._store is not None:
            self._loaded_at = time.monotonic()
        return True

    @contextmanager
    def switched_off(self, module_id: str, *, by: str = "test", reason: str = "test") -> Iterator[None]:
        """Tests: the module is off inside the block and back on afterwards (both changes audited)."""
        self.set_enabled(module_id, False, by=by, reason=reason)
        try:
            yield
        finally:
            self.set_enabled(module_id, True, by=by, reason=f"{reason} (restored)")


# The one running instance every part of the app consults. Every request is written to the app's durable audit log,
# and the on/off state is shared through the database (`module_switches`).
switches = ModuleSwitches(audit=durable_audit, store=DurableStore())


def is_enabled(module_id: str) -> bool:
    return switches.enabled(module_id)


def require_module(module_id: str) -> Callable[[], None]:
    """Dependency for a router: while the module is off, every route of it answers 'switched off'. On (the
    default), it does nothing at all."""
    switches.module(module_id)  # an unknown id fails at start-up, not on the first request

    always_on = switches.module(module_id).always_on

    def _guard(request: Request) -> None:
        path = request.url.path.removeprefix("/api/v1")
        if any(path == p or path.startswith(p + "/") for p in always_on):
            return
        if not switches.enabled(module_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This part of the app is switched off.")

    _guard.module_id = module_id  # type: ignore[attr-defined]  # lets a test see which module guards a route
    return _guard


def apply_to_scheduler(scheduler: object, state: ModuleSwitches | None = None) -> list[str]:
    """Remove the scheduled jobs of every module that is off. A job that was never added is skipped. Returns the ids
    removed. With every module on (the default) this removes nothing."""
    chosen = state or switches
    removed: list[str] = []
    for job_id in sorted(chosen.jobs_to_skip()):
        if scheduler.get_job(job_id) is not None:  # type: ignore[attr-defined]
            scheduler.remove_job(job_id)  # type: ignore[attr-defined]
            removed.append(job_id)
    return removed


def guard_scheduler_jobs(scheduler: object, state: ModuleSwitches | None = None) -> list[str]:
    """Make every job a module owns re-read the shared state before each run and skip the run while the module is
    off (the job stays scheduled and nothing is deleted: switching the module back on resumes it at its next
    trigger). Returns the ids wrapped. Jobs that are not in a module are left alone."""
    chosen = state or switches
    wrapped: list[str] = []
    for module in chosen.modules():
        if module.core:
            continue
        for job_id in module.jobs:
            job = scheduler.get_job(job_id)  # type: ignore[attr-defined]
            if job is None or getattr(job.func, "_module_gated", None) == module.id:
                continue
            scheduler.modify_job(job_id, func=_gated(job.func, module.id, chosen))  # type: ignore[attr-defined]
            wrapped.append(job_id)
    return wrapped


def _gated(func: Callable, module_id: str, state: ModuleSwitches) -> Callable:
    @functools.wraps(func)
    def run(*args, **kwargs):
        if not state.enabled(module_id, fresh=True):
            log.info(
                "module_switches.job_skipped module=%s job=%s", module_id, getattr(func, "__name__", "?")
            )
            return None
        return func(*args, **kwargs)

    run._module_gated = module_id  # type: ignore[attr-defined]
    return run
