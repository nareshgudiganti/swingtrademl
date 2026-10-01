"""M02 · Perception.

Turns every stock's prices into the model's own features, from bars and
market context that end at the run's date. The service stores nightly
snapshots so any past day can be replayed exactly. Intraday runs skip this
step's work — their time budget is a tenth of the nightly one — and the
price-only fallback answers instead.
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m02_perception.snapshot import (
    ContextFrames,
    feature_set_version,
    snapshot_from,
)


@register_module
class Perception(BrainModule):
    manifest = Manifest(
        id="M02",
        name="Perception",
        step=Step.PERCEIVE,
        kind="step",
        version="1.0.0",
        reads=(),
        writes=("Snapshot@1",),
        budget_s=30.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        if view.request.kind == "intraday":
            return c.Contribution()
        reader = view.reader
        reader.refresh_context_if_stale()
        version = feature_set_version()
        snapshots = []
        for symbol in dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings))):
            bars = reader.ohlcv(symbol)
            if bars.empty:
                continue
            snap = snapshot_from(symbol, bars, ContextFrames(**reader.context_frames(symbol)), version)
            if snap is not None:
                snapshots.append(snap)
        return c.Contribution(snapshots=tuple(snapshots))
