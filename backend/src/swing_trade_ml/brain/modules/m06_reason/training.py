"""`swingtrade brain meta-train`: build the unseen-window dataset, compare the
candidates by walk-forward, fit the winner on the whole window and save it
with its report. Nothing is switched on: M06 starts in trial (shadow) mode.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m06_reason import artifact
from swing_trade_ml.brain.modules.m06_reason.dataset import build_dataset
from swing_trade_ml.brain.modules.m06_reason.trainer import Combiner, evaluate
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.registry import get_active_model


class TrainingError(RuntimeError):
    pass


def _watchlist(db: Session) -> list[str]:
    return list(
        db.execute(
            select(Instrument.tradingsymbol)
            .where(Instrument.is_watchlisted.is_(True), Instrument.is_active.is_(True))
            .order_by(Instrument.tradingsymbol)
        ).scalars()
    )


def train_and_save(
    db: Session,
    barrier_name: str = "swing_classifier_barrier",
    swing_name: str = "swing_classifier",
    symbols: list[str] | None = None,
) -> dict:
    barrier, swing = get_active_model(db, barrier_name), get_active_model(db, swing_name)
    for name, model in ((barrier_name, barrier), (swing_name, swing)):
        if model is None:
            raise TrainingError(f"There is no active model named {name!r}.")
    frame = build_dataset(db, barrier, swing, symbols or _watchlist(db))
    if frame.empty:
        raise TrainingError(
            "No unseen, labelled stock-days were found after the base models' training window."
        )
    report = evaluate(frame)
    if report["chosen"] is None:
        raise TrainingError(report["why"])
    combiner = Combiner.fit(frame, report["chosen"])
    report["n_rows"] = len(frame)
    report["n_symbols"] = int(frame["symbol"].nunique())
    path = artifact.save(
        combiner,
        report,
        base_models={
            "barrier": f"{barrier.name} {barrier.version}",
            "swing": f"{swing.name} {swing.version}",
        },
    )
    return {"path": path, "report": report}
