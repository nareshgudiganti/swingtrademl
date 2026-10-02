"""M09 · Learning loop (the learn step).

Learning never happens inside a decision run — it only grades decisions
already made and proposes changes for the owner to accept (constitution C9).
The actual work (scoring, the report, proposals) runs after a live nightly
run (`service._sync_episodes`) and on the weekly job
(`m09_learn.learn.run_learning`); this step module itself contributes
nothing to the day's decisions.
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module


@register_module
class Learning(BrainModule):
    manifest = Manifest(
        id="M09",
        name="Learning loop",
        step=Step.LEARN,
        kind="step",
        version="1.0.0",
        reads=(),
        writes=(),
        budget_s=5.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        return c.Contribution()
