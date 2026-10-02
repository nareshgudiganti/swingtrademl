"""Test doubles for brain tests: an in-memory reader and a module factory.

The runner only reaches data through a reader, so these let the runner,
fallbacks and constitution be tested without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, ModuleRegistry, Step

AS_OF = datetime(2026, 9, 29, 10, 20, tzinfo=UTC)


def rising_closes(n: int = 260, start: float = 100.0) -> pd.Series:
    return pd.Series(start * (1.001 ** np.arange(n)))


class FakeReader:
    """Answers the questions fallbacks ask, from fixed values."""

    def __init__(
        self,
        *,
        symbols=("ABC", "XYZ"),
        closes: dict[str, float] | None = None,
        probabilities: dict[str, float] | None = None,
        threshold: float = 0.6,
        index_closes: pd.Series | None = None,
        halted: bool = False,
        holdings: tuple[c.Holding, ...] = (),
    ) -> None:
        self.as_of = AS_OF
        self._symbols = tuple(symbols)
        self._closes = closes if closes is not None else dict.fromkeys(symbols, 100.0)
        self._probabilities = probabilities or {}
        self._threshold = threshold
        self._index = index_closes if index_closes is not None else rising_closes()
        self._halted = halted
        self._holdings = holdings

    def universe(self) -> tuple[str, ...]:
        return self._symbols

    def last_close(self, symbol: str) -> tuple[str, float] | None:
        close = self._closes.get(symbol)
        return None if close is None else ("2026-09-29", close)

    def index_closes(self) -> pd.Series:
        return self._index

    def system_state(self) -> c.SystemState:
        return c.SystemState(
            entries_halted=self._halted, halt_reason="Owner paused" if self._halted else None
        )

    def holdings(self, book: str) -> tuple[c.Holding, ...]:
        return self._holdings

    def sector_closes(self) -> dict[str, pd.Series]:
        return {}

    def event_rows(self, symbols) -> list:
        return []

    def restriction_rows(self, symbols) -> list:
        return []

    def ohlcv(self, symbol: str, n: int = 400) -> pd.DataFrame:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    def delivery_rows(self, symbols, days: int = 40) -> dict:
        return {}

    def deal_rows(self, symbols, days: int = 10) -> list:
        return []

    def model_probability(self, symbol: str) -> tuple[float, float, str] | None:
        p = self._probabilities.get(symbol)
        return None if p is None else (p, self._threshold, "swing_classifier v1")


def request(kind: str = "nightly", universe=("ABC", "XYZ"), live: bool = True) -> c.RunRequest:
    return c.RunRequest(run_id="test-run", kind=kind, as_of=AS_OF, universe=tuple(universe), live=live)


def make_module(
    module_id: str,
    step: Step,
    *,
    writes: tuple[str, ...] = (),
    reads: tuple[str, ...] = (),
    run=None,
    mandatory: bool = False,
    budget_s: float = 10.0,
    kind: str = "step",
) -> type[BrainModule]:
    """Build a module class whose run() is `run(view) -> Contribution`."""

    def _run(self, view):
        return run(view) if run else c.Contribution()

    manifest = Manifest(
        id=module_id,
        name=f"Test {module_id}",
        step=step,
        kind=kind,
        version="1.0.0",
        reads=reads,
        writes=writes,
        budget_s=budget_s,
        mandatory=mandatory,
        default_mode=Mode.ON,
    )
    return type(f"Fake{module_id}", (BrainModule,), {"manifest": manifest, "run": _run})


def allow_all_risk_gate(max_qty: int = 10) -> type[BrainModule]:
    """A stand-in for M07 that allows every symbol with an opinion."""

    def run(view):
        return c.Contribution(
            verdicts=tuple(
                c.RiskVerdict(symbol=o.symbol, allowed=True, max_qty=max_qty, reason="Within limits")
                for o in view.opinions
            )
        )

    return make_module(
        "M07", Step.RISK, reads=("Opinion@1",), writes=("RiskVerdict@1",), run=run, mandatory=True
    )


def fresh_quality() -> type[BrainModule]:
    """A stand-in for M01 that marks every symbol fresh."""

    def run(view):
        return c.Contribution(
            quality=tuple(c.DataQuality(symbol=s, score=1.0, fresh=True) for s in view.request.universe)
        )

    return make_module("M01", Step.PERCEIVE, writes=("DataQuality@1",), run=run)


def registry(*module_classes) -> ModuleRegistry:
    reg = ModuleRegistry()
    for cls in module_classes:
        reg.register(cls)
    return reg
