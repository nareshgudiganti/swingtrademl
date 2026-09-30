"""What a brain module is: its manifest, its run() method, and the registry.

Same pattern as `strategies/base.py`: modules register themselves with a
decorator and stay pure — a module reads the context through a view limited
to the contracts it declared, and returns a Contribution. The runner, not the
module, decides whether that contribution is used, shadowed or discarded.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from swing_trade_ml.brain.context import ContextView
    from swing_trade_ml.brain.contracts import Contribution


class Step(StrEnum):
    PERCEIVE = "perceive"
    STATE = "state"
    RECOGNISE = "recognise"
    REMEMBER = "remember"
    REASON = "reason"
    RISK = "risk"
    DECIDE = "decide"
    LEARN = "learn"


STEPS: tuple[Step, ...] = tuple(Step)

# Which steps each kind of run goes through, in order. Intraday runs only
# re-check holdings, so they skip recognition, memory, reasoning and learning.
STEPS_FOR: dict[str, tuple[Step, ...]] = {
    "nightly": STEPS,
    "why": STEPS[:-1],
    "intraday": (Step.PERCEIVE, Step.STATE, Step.RISK, Step.DECIDE),
}


class Mode(StrEnum):
    ON = "on"  # output is used
    SHADOW = "shadow"  # runs; output recorded in the trace, not used
    OFF = "off"  # not run; the step's fallback applies


@dataclass(frozen=True, slots=True)
class Manifest:
    id: str  # "M03"
    name: str
    step: Step
    kind: str  # "step" owns the step's result; "plugin" adds to it
    version: str
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    budget_s: float = 10.0  # nightly budget; intraday gets a tenth
    mandatory: bool = False  # only the risk gate (M07)
    default_mode: Mode = Mode.SHADOW

    def budget(self, run_kind: str) -> float:
        return self.budget_s / 10 if run_kind == "intraday" else self.budget_s


@dataclass(frozen=True, slots=True)
class Health:
    status: str = "ready"  # ready | degraded | down
    reason: str = ""


class BrainModule(ABC):
    manifest: ClassVar[Manifest]

    @abstractmethod
    def run(self, view: ContextView) -> Contribution:
        """Read only what the manifest declares; return only what it declares."""

    def health(self, view: ContextView) -> Health:
        return Health()


def resolve_mode(manifest: Manifest, stored: Mode | str | None) -> Mode:
    """The mode a module actually runs in. The risk gate is never anything but
    ON, whatever was stored — switching it off is refused, not obeyed."""
    if manifest.mandatory:
        return Mode.ON
    if stored is None:
        return manifest.default_mode
    return Mode(stored)


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, type[BrainModule]] = {}

    def register(self, cls: type[BrainModule]) -> type[BrainModule]:
        m = cls.manifest
        if m.mandatory and m.step is not Step.RISK:
            raise ValueError(f"{m.id}: only a risk-step module can be mandatory")
        if m.id in self._modules and self._modules[m.id] is not cls:
            raise ValueError(f"module id {m.id} is already registered")
        self._modules[m.id] = cls
        return cls

    def all(self) -> list[type[BrainModule]]:
        return sorted(self._modules.values(), key=lambda c: c.manifest.id)

    def get(self, module_id: str) -> type[BrainModule] | None:
        return self._modules.get(module_id)

    def for_step(self, step: Step) -> list[type[BrainModule]]:
        """Step modules first, then plug-ins; ids break ties. The order is
        fixed so the same modules always merge in the same order."""
        mods = [c for c in self._modules.values() if c.manifest.step is step]
        return sorted(mods, key=lambda c: (c.manifest.kind == "plugin", c.manifest.id))


REGISTRY = ModuleRegistry()


def register_module(cls: type[BrainModule]) -> type[BrainModule]:
    return REGISTRY.register(cls)
