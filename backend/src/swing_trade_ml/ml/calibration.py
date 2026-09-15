"""Calibration: does a 0.70 confidence actually win 70% of the time?

Every signal the product shows carries a model confidence, and until this
module nothing had ever checked that number against what happened next. The
report buckets scored rows by confidence and sets the observed win rate beside
the mean confidence of each bucket, so an over-confident model shows up as a
negative gap rather than as a feeling.

Two sources, one shape:

* **Signals** are already scored against a barrier (target, stop, or expiry)
  by `evaluate_pending_signals`, so the report reads `outcome` directly.
* **Predictions** are bucketed on `probability`, but the win is recomputed from
  `actual_return` against the owning model's target. `was_correct` is useless
  here: it records agreement between `predicted_class` and the outcome, so a
  probability-0.15 class-0 row that went nowhere counts as "correct" and would
  inflate every bucket it touched.

See the plan's Stage 1.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.models.trading import Signal

# Rows below 0.55 sit well under ML_MIN_CONFIDENCE and never become trades, so
# they say little about the confidence the user acts on. They are counted in
# `excluded_below_min` rather than silently dropped, so the totals reconcile.
MIN_CONFIDENCE = 0.55
BUCKET_EDGES: tuple[float, ...] = (0.55, 0.60, 0.70, 0.80, 1.00)
# Below this a bucket's hit rate swings too far on a single trade to act on.
MEANINGFUL_SAMPLE = 30
# A barrier target hit stores `actual_return` as (upper - entry) / entry, which
# equals the target only up to float rounding.
TARGET_TOLERANCE = 1e-9

TARGET_HIT = "TARGET_HIT"


@dataclass
class CalibrationBucket:
    lower: float
    upper: float
    n: int = 0
    wins: int = 0
    observed_rate: float | None = None
    mean_confidence: float | None = None
    calibration_gap: float | None = None
    mean_outcome_pct: float | None = None
    worst_outcome_pct: float | None = None
    meaningful: bool = False


@dataclass
class CalibrationReport:
    source: Literal["signals", "predictions"]
    mode: str | None = None
    strategy_id: int | None = None
    since: datetime | None = None
    model_id: int | None = None
    label_kind: str | None = None
    total_scored: int = 0
    excluded_below_min: int = 0
    brier_score: float | None = None
    buckets: list[CalibrationBucket] = field(default_factory=list)


def bucket_index(confidence: float) -> int | None:
    """Index into BUCKET_EDGES, or None when below the minimum.

    Lower-inclusive and upper-exclusive, except the top bucket which also takes
    1.0 — otherwise a certain-looking prediction would fall out of the report.
    """
    if confidence < BUCKET_EDGES[0]:
        return None
    last = len(BUCKET_EDGES) - 2
    for i in range(last):
        if confidence < BUCKET_EDGES[i + 1]:
            return i
    return last


def _build(
    report: CalibrationReport, rows: list[tuple[float, bool, float | None]]
) -> CalibrationReport:
    """rows: (confidence, won, outcome_pct)."""
    grouped: list[list[tuple[float, bool, float | None]]] = [
        [] for _ in range(len(BUCKET_EDGES) - 1)
    ]
    excluded = 0
    for row in rows:
        idx = bucket_index(row[0])
        if idx is None:
            excluded += 1
        else:
            grouped[idx].append(row)

    buckets: list[CalibrationBucket] = []
    included: list[tuple[float, bool, float | None]] = []
    for i, members in enumerate(grouped):
        bucket = CalibrationBucket(lower=BUCKET_EDGES[i], upper=BUCKET_EDGES[i + 1])
        bucket.n = len(members)
        bucket.meaningful = bucket.n >= MEANINGFUL_SAMPLE
        if members:
            bucket.wins = sum(1 for _, won, _ in members if won)
            bucket.observed_rate = bucket.wins / bucket.n
            bucket.mean_confidence = sum(c for c, _, _ in members) / bucket.n
            bucket.calibration_gap = bucket.observed_rate - bucket.mean_confidence
            outcomes = [o for _, _, o in members if o is not None]
            if outcomes:
                bucket.mean_outcome_pct = sum(outcomes) / len(outcomes)
                bucket.worst_outcome_pct = min(outcomes)
            included.extend(members)
        buckets.append(bucket)

    report.total_scored = len(rows)
    report.excluded_below_min = excluded
    report.buckets = buckets
    if included:
        report.brier_score = sum((c - float(won)) ** 2 for c, won, _ in included) / len(included)
    return report


def signal_calibration(
    db: Session,
    *,
    mode: str | None = "paper",
    strategy_id: int | None = None,
    since: datetime | None = None,
) -> CalibrationReport:
    """Calibration of scored signals. Only a target hit is a win: a stop is a
    loss, and so is an expiry, because the question the confidence answers is
    whether the target is reached before the stop within the horizon."""
    stmt = select(Signal.confidence, Signal.outcome, Signal.outcome_pct).where(
        Signal.confidence.isnot(None),
        Signal.outcome.isnot(None),
    )
    if mode is not None:
        stmt = stmt.where(Signal.mode == mode)
    if strategy_id is not None:
        stmt = stmt.where(Signal.strategy_id == strategy_id)
    if since is not None:
        stmt = stmt.where(Signal.generated_at >= since)

    rows = [
        (float(conf), outcome == TARGET_HIT, outcome_pct)
        for conf, outcome, outcome_pct in db.execute(stmt).all()
    ]
    report = CalibrationReport(source="signals", mode=mode, strategy_id=strategy_id, since=since)
    return _build(report, rows)


def prediction_calibration(
    db: Session,
    *,
    model_id: int | None = None,
    label_kind: str = "barrier",
) -> CalibrationReport:
    """Calibration of evaluated predictions for one label kind.

    Filtering on the row's `label_kind` keeps the endpoint era out of a barrier
    report: the two answer different questions, and averaging them would
    describe neither model.
    """
    stmt = (
        select(Prediction.probability, Prediction.actual_return, MLModel.target_return_pct)
        .join(MLModel, MLModel.id == Prediction.model_id)
        .where(
            Prediction.evaluated_at.isnot(None),
            Prediction.actual_return.isnot(None),
            Prediction.label_kind == label_kind,
        )
    )
    if model_id is not None:
        stmt = stmt.where(Prediction.model_id == model_id)

    # For a barrier row the evaluator stores exactly the target on a hit and
    # something below it otherwise (a stop, or a close that never touched the
    # upper barrier). For an endpoint row the rule was already >= target. One
    # comparison therefore serves both kinds.
    rows = [
        (float(prob), actual >= target - TARGET_TOLERANCE, actual)
        for prob, actual, target in db.execute(stmt).all()
    ]
    report = CalibrationReport(source="predictions", model_id=model_id, label_kind=label_kind)
    return _build(report, rows)
