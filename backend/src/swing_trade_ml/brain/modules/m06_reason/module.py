"""M06 · Reasoning (the calibrated combiner).

For each idea stock with today's features (M02), score the two base models
the saved combiner was trained on, add the market and stock context, and
turn it into ONE calibrated chance of reaching +8% before -4% within 15
trading days (`swingtrade brain meta-train` builds and proves the combiner).

The buy level is the break-even chance after costs plus a safety margin, so
"liked" means "pays after costs", not "scores high". Starts in trial
(SHADOW) mode: recorded, not used, until switched on.

No combiner saved, base model files missing, or features missing → no
opinion for that stock; the active model's fallback speaks instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m06_reason import artifact
from swing_trade_ml.brain.modules.m06_reason.dataset import CONTEXT_COLUMNS, score_bundle
from swing_trade_ml.brain.modules.m08_decide.money import cost_pct
from swing_trade_ml.brain.modules.m08_decide.policy import DEFAULT_POLICY, DecidePolicy

SAFETY_MARGIN = 0.05  # the chance must beat break-even by this much


def break_even(price: float, policy: DecidePolicy = DEFAULT_POLICY) -> float:
    """The chance at which a trade's expected result after costs is zero, priced
    on a typical position: p * reward - (1 - p) - cost/stop = 0."""
    qty = max(1, round(policy.cost_notional_inr / price))
    return (1 + cost_pct(price, qty) / policy.stop_pct) / (policy.reward_r + 1)


def _bucket_line(report: dict, p: float) -> str:
    """How honest the combiner was near this chance on unseen months."""
    chosen = report.get("candidates", {}).get(report.get("chosen"), {})
    for b in chosen.get("calibration", []):
        if b["low"] <= p < b["high"] or (p >= b["high"] == 1.0):
            return (
                f"On months no model had seen, when it said {b['low']:.0%} to {b['high']:.0%} "
                f"(average {b['mean_p']:.0%}), {b['actual']:.0%} of {b['n']} cases really did."
            )
    return ""


def _base(reader, label: str):
    name, _, version = label.rpartition(" ")
    loader = getattr(reader, "model_bundle", None)
    return loader(name, version) if loader and name else None


@register_module
class Reasoning(BrainModule):
    manifest = Manifest(
        id="M06",
        name="Reasoning (calibrated chance)",
        step=Step.REASON,
        kind="step",
        version="1.0.0",
        reads=("Snapshot@1",),
        writes=("Opinion@1",),
        budget_s=20.0,
        default_mode=Mode.SHADOW,
    )

    def run(self, view: ContextView) -> c.Contribution:
        saved = artifact.load_latest()
        if saved is None:
            return c.Contribution()
        bases = saved.get("base_models", {})
        barrier = _base(view.reader, bases.get("barrier", ""))
        swing = _base(view.reader, bases.get("swing", ""))
        if barrier is None or swing is None:
            return c.Contribution()

        report = saved.get("report", {})
        chosen = report.get("candidates", {}).get(report.get("chosen"), {})
        auc = chosen.get("auc") or 0.5
        confidence = float(np.clip((auc - 0.5) * 4, 0.0, 1.0))
        n_seen = report.get("n_test_rows", 0)
        held = {h.symbol for h in view.holdings}
        ideas = [s for s in view.request.universe if s not in held]

        opinions = []
        for symbol in ideas:
            snap = view.snapshots.get(symbol)
            if snap is None or not snap.features or snap.close <= 0:
                continue
            feats = dict(snap.features)
            p_barrier, p_swing = score_bundle(barrier, feats), score_bundle(swing, feats)
            if p_barrier is None or p_swing is None:
                continue
            row = {"p_barrier": p_barrier, "p_swing": p_swing}
            row.update({col: feats.get(col, np.nan) for col in CONTEXT_COLUMNS})
            p = float(np.clip(saved["combiner"].predict(pd.DataFrame([row]))[0], 0.0, 1.0))
            threshold = break_even(snap.close) + SAFETY_MARGIN
            evidence = " ".join(
                part
                for part in (
                    f"Calibrated on {n_seen} unseen stock-days ({saved.get('version', '?')}).",
                    _bucket_line(report, p),
                )
                if part
            )
            opinions.append(
                c.Opinion(
                    source="combined",
                    symbol=snap.symbol,
                    stance=float(np.clip((p - threshold) * 4, -1.0, 1.0)),
                    confidence=confidence,
                    reasons=(
                        f"Calibrated chance of +8% before -4%: {p:.0%} "
                        f"(needs {threshold:.0%} to pay after costs).",
                    ),
                    probability=p,
                    threshold=threshold,
                    calibrated=True,
                    evidence=evidence,
                )
            )
        return c.Contribution(opinions=tuple(opinions))
