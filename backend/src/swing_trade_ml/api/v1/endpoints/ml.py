"""Model training, registry management, and predictions."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import IO, Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Integer, cast, func, select

from swing_trade_ml.api.deps import DbSession, Principal, require_owner
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.release_switches import promotion_refusal
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.ml import calibration as calibration_service
from swing_trade_ml.ml import predict as predict_service
from swing_trade_ml.ml import promotion
from swing_trade_ml.ml import train as train_service
from swing_trade_ml.ml.backup import registered_artifacts
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.schemas import (
    CalibrationReport,
    MessageResponse,
    MLModelDetail,
    MLModelOut,
    PredictionOut,
    PredictionRunOut,
    TrainRequest,
)

router = APIRouter(prefix="/ml", tags=["ml"])
log = get_logger(__name__)


@router.get("/models", response_model=list[MLModelOut])
def list_models(db: DbSession, name: str | None = None) -> list[MLModel]:
    stmt = select(MLModel).order_by(MLModel.created_at.desc())
    if name:
        stmt = stmt.where(MLModel.name == name)
    return list(db.execute(stmt).scalars().all())


def _zip_entry_name(model: MLModel, suffix: str) -> str:
    """A flat, server-independent name: never the artifact's real path."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{model.name}_{model.version}")
    return f"models/{safe}{suffix}"


def _build_backup_zip(db: DbSession) -> IO[bytes]:
    """Spool every registered artifact plus manifest.json into a temp file.

    Each artifact is streamed through the zip in chunks (hashing as it goes),
    so memory stays flat however large the models are; the spool rolls over to
    disk past 8 MB. A missing file is listed in the manifest, not an error —
    it is the finding the backup exists to surface.
    """
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115
    entries: list[dict] = []
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as archive:
        for model, source in registered_artifacts(db):
            produced = model.trained_at or model.created_at
            entry = {
                "model": model.name,
                "version": model.version,
                "status": model.status,
                "produced_at": produced.isoformat() if produced else None,
                "file": None,
                "size": None,
                "sha256": None,
                "missing": source is None,
            }
            if source is not None:
                name = _zip_entry_name(model, source.suffix)
                digest = hashlib.sha256()
                size = 0
                try:
                    with source.open("rb") as src, archive.open(name, "w", force_zip64=True) as out:
                        while chunk := src.read(1024 * 1024):
                            digest.update(chunk)
                            size += len(chunk)
                            out.write(chunk)
                    entry.update(file=name, size=size, sha256=digest.hexdigest())
                except OSError:
                    # Vanished or unreadable mid-copy: report it, keep going.
                    entry["missing"] = True
            entries.append(entry)
        manifest = {"generated_at": datetime.now(UTC).isoformat(), "artifacts": entries}
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    spool.seek(0)
    return spool


@router.get("/backup/models.zip")
def download_model_backup(db: DbSession) -> StreamingResponse:
    """Read-only zip of every registered model artifact (archived versions
    included) with a manifest of sizes and sha256 digests, for an off-server
    copy. Paths in the response are zip-relative only."""
    spool = _build_backup_zip(db)

    def _stream() -> Iterator[bytes]:
        try:
            while chunk := spool.read(1024 * 1024):
                yield chunk
        finally:
            spool.close()

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return StreamingResponse(
        _stream(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="stml-models-{stamp}.zip"'},
    )


@router.get("/models/active", response_model=MLModelDetail)
def active_model(db: DbSession, name: str | None = None) -> MLModel:
    model = get_active_model(db, name)
    if model is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No active model. Train one with POST /ml/train, then activate it.",
        )
    return model


@router.get("/models/{model_id}", response_model=MLModelDetail)
def get_model(model_id: int, db: DbSession) -> MLModel:
    model = db.get(MLModel, model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    return model


@router.post("/train", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def train(payload: TrainRequest, background: BackgroundTasks) -> MessageResponse:
    """Train a new model version in the background.

    Backgrounded because a gradient-boosted fit over several years of pooled
    daily bars runs for minutes, well past an HTTP timeout. Poll GET /ml/models
    for the result.
    """
    if payload.auto_activate:
        # Switch message first; even with the switch on, activation needs the owner's approval of the
        # finished file (#328): train, review, then POST /ml/models/{id}/activate with the evidence.
        raise HTTPException(status.HTTP_403_FORBIDDEN, promotion_refusal() or AUTO_ACTIVATE_REFUSED)

    def _run() -> None:
        try:
            with session_scope() as db:
                train_service.train_model(
                    db,
                    name=payload.name,
                    algorithm=payload.algorithm,
                    symbols=payload.symbols,
                    interval=payload.interval,
                    horizon_days=payload.horizon_days,
                    target_return=payload.target_return,
                    stop_return=payload.stop_return,
                    test_size=payload.test_size,
                    hyperparameters=payload.hyperparameters,
                    auto_activate=payload.auto_activate,
                    walk_forward_folds=payload.walk_forward_folds or 0,
                    invoked_by="api",
                )
        except Exception as exc:  # noqa: BLE001 — surface via logs/Telegram, don't crash the worker
            log.error("ml.train.failed", error=str(exc))
            from swing_trade_ml.notifications import notifier

            notifier.send_sync(f"⚠️ <b>Training failed</b>\n\n<code>{exc}</code>", "error")

    background.add_task(_run)
    return MessageResponse(
        message=f"Training '{payload.name}' with {payload.algorithm}",
        detail="Poll GET /ml/models to see the new version once it completes.",
    )


AUTO_ACTIVATE_REFUSED = (
    "Activating straight after training is not allowed: train, review the result, record an owner "
    "approval with POST /ml/approvals, then POST /ml/models/{id}/activate with that approval id."
)


class EvidenceRef(BaseModel):
    """A repo file and its sha256 (checked on disk), or a PR number (recorded only)."""

    path: str | None = Field(default=None, max_length=300)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pr: int | None = Field(default=None, gt=0)

    def as_ref(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ApprovalRequest(BaseModel):
    """The designated owner's approval. The approver is the signed-in user, never the body."""

    kind: Literal["promote", "rollback", "brain_module_on", "strategy_model"]
    target: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=promotion.MIN_REASON_CHARS, max_length=promotion.MAX_TEXT_CHARS)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=promotion.MAX_EVIDENCE)
    protocol_verdict: str = Field(max_length=32)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_name: str | None = Field(default=None, max_length=128)


class UseApproval(BaseModel):
    approval_id: int


def _owner_or_403(principal: Principal):
    try:
        return promotion.signed_in_owner(principal)
    except promotion.PromotionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


@router.post("/approvals", status_code=status.HTTP_201_CREATED)
def record_approval(
    payload: ApprovalRequest, db: DbSession, principal: Annotated[Principal, Depends(require_owner)]
) -> dict:
    """Signed-in designated owner only: record an approval (#328). It changes nothing by itself; it is
    used once, within 7 days, by activate / rollback / the M06 switch / a strategy model change."""
    user = _owner_or_403(principal)
    try:
        row = promotion.record_approval(
            db,
            user,
            kind=payload.kind,
            target=payload.target,
            reason=payload.reason,
            evidence=[e.as_ref() for e in payload.evidence],
            protocol_verdict=payload.protocol_verdict,
            artifact_sha256=payload.artifact_sha256,
            model_name=payload.model_name,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return {"approval_id": row.id, "recorded_at": row.ts, "kind": payload.kind, "target": row.target_id}


def _gated(fn, db: DbSession, model_id: int, payload: UseApproval | None, principal: Principal) -> MLModel:
    if refusal := promotion_refusal():  # checked before the body, so "switched off" is always the answer
        raise HTTPException(status.HTTP_403_FORBIDDEN, refusal)
    _owner_or_403(principal)
    if payload is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, promotion.APPROVAL_REQUIRED)
    try:
        model = fn(db, model_id, payload.approval_id, invoked_by="api")
    except ValueError as exc:  # PromotionError, ArtifactMismatchError, wrong status: nothing changed
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    predict_service.clear_cache()
    return model


@router.post("/models/{model_id}/activate", response_model=MLModelOut)
def activate(
    model_id: int,
    db: DbSession,
    principal: Annotated[Principal, Depends(require_owner)],
    payload: Annotated[UseApproval | None, Body()] = None,
) -> MLModel:
    """Signed-in designated owner only: make a model ACTIVE through the promotion safeguard (#328), using
    a recorded approval; the previous active version is archived. Needs ALLOW_MODEL_PROMOTION."""
    return _gated(promotion.promote, db, model_id, payload, principal)


@router.post("/models/{model_id}/rollback", response_model=MLModelOut)
def rollback(
    model_id: int,
    db: DbSession,
    principal: Annotated[Principal, Depends(require_owner)],
    payload: Annotated[UseApproval | None, Body()] = None,
) -> MLModel:
    """Signed-in designated owner only: restore the model the last recorded promotion replaced."""
    return _gated(promotion.rollback, db, model_id, payload, principal)


@router.post("/predict", response_model=list[PredictionRunOut])
def run_predictions(
    db: DbSession,
    model_name: str | None = "swing_classifier",
    interval: str = "day",
    persist: bool = True,
) -> list[PredictionRunOut]:
    """Score the whole watchlist now, ranked by probability.

    Defaulting to "swing_classifier" here, not just in predict_watchlist()'s
    own signature, matters: a query param omitted by the caller arrives here
    as a literal None, which is then passed through explicitly — Python does
    not fall back to the callee's default in that case. Leaving this at None
    is exactly the Aug 12 incident recurring: a mid/small-cap promotion
    becomes "most recently activated" system-wide and silently shadows the
    large-cap watchlist's own model. Pass model_name=None explicitly in the
    request if that global-latest lookup is ever genuinely wanted.
    """
    results = predict_service.predict_watchlist(db, model_name, interval, persist)
    if not results:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No predictions produced — check that a model is active and candles are ingested.",
        )
    return [
        PredictionRunOut(
            symbol=r.symbol,
            instrument_id=r.instrument_id,
            probability=r.probability,
            predicted_class=r.predicted_class,
            price=r.price,
            ts=r.ts,
        )
        for r in results
    ]


@router.get("/score-trail/{symbol}", response_model=dict)
def stock_score_trail(
    db: DbSession, symbol: str, exchange: str = "NSE", limit: int = Query(30, le=120)
) -> dict:
    """Day-by-day strength score for any stock, held or not (oldest first).

    Days the model was not run are absent — never filled in from a neighbour.
    """
    from swing_trade_ml.services import score_history
    from swing_trade_ml.services.exit_policy import exit_confidence_for

    instrument = db.execute(
        select(Instrument).where(
            Instrument.tradingsymbol == symbol.upper(), Instrument.exchange == exchange
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown instrument {exchange}:{symbol.upper()}")
    trail = score_history.stock_trail(db, instrument.id, limit=limit)
    return {
        "symbol": instrument.tradingsymbol,
        "score_trail": trail,
        "score_band": trail[-1]["band"] if trail else None,
        "last_score": trail[-1]["score"] if trail else None,
        "exit_confidence": exit_confidence_for(None),
    }


@router.get("/predictions", response_model=list[PredictionOut])
def list_predictions(
    db: DbSession,
    model_id: int | None = None,
    evaluated_only: bool = False,
    limit: int = Query(100, le=1000),
) -> list[dict]:
    """Symbol-resolved so the dashboard can show "what we predicted and what
    actually happened" without a second lookup per row."""
    stmt = (
        select(Prediction, Instrument.tradingsymbol)
        .join(Instrument, Instrument.id == Prediction.instrument_id)
        .order_by(Prediction.ts.desc())
        .limit(limit)
    )
    if model_id:
        stmt = stmt.where(Prediction.model_id == model_id)
    if evaluated_only:
        stmt = stmt.where(Prediction.evaluated_at.isnot(None))

    rows = db.execute(stmt).all()
    return [
        {
            "id": pred.id,
            "model_id": pred.model_id,
            "instrument_id": pred.instrument_id,
            "symbol": symbol,
            "ts": pred.ts,
            "predicted_class": pred.predicted_class,
            "probability": pred.probability,
            "price_at_prediction": pred.price_at_prediction,
            "actual_return": pred.actual_return,
            "was_correct": pred.was_correct,
            "evaluated_at": pred.evaluated_at,
        }
        for pred, symbol in rows
    ]


@router.get("/predictions/accuracy", response_model=dict)
def prediction_accuracy(db: DbSession, model_id: int | None = None) -> dict:
    """Realised out-of-sample accuracy on predictions the bot actually made.

    This, not the training-time test split, is the number to judge the model on
    after six months of paper trading.

    `by_model` is the answer: one row per model with its name, version, horizon and label kind, because models
    of different horizons answer different questions. The top-level figures are every chosen model together
    (`overall_note` says so) and are kept only for older callers. With nothing evaluated, accuracy, average
    probability and average return are null ("not enough data"), never 0.0.
    """
    stmt = select(
        func.count(Prediction.id),
        # Postgres cannot SUM a boolean; cast to int so "how many were correct"
        # is one aggregate rather than a second round trip.
        func.sum(cast(Prediction.was_correct, Integer)),
        func.avg(Prediction.probability),
        func.avg(Prediction.actual_return),
    ).where(Prediction.evaluated_at.isnot(None))
    per_model = (
        select(
            MLModel.id,
            MLModel.name,
            MLModel.version,
            MLModel.prediction_horizon_days,
            MLModel.label_kind,
            func.count(Prediction.id),
            func.sum(cast(Prediction.was_correct, Integer)),
            func.avg(Prediction.probability),
            func.avg(Prediction.actual_return),
        )
        .join(MLModel, MLModel.id == Prediction.model_id)
        .where(Prediction.evaluated_at.isnot(None))
        .group_by(
            MLModel.id, MLModel.name, MLModel.version, MLModel.prediction_horizon_days, MLModel.label_kind
        )
        .order_by(MLModel.name, MLModel.version)
    )
    if model_id:
        stmt = stmt.where(Prediction.model_id == model_id)
        per_model = per_model.where(Prediction.model_id == model_id)

    total, correct, avg_prob, avg_return = db.execute(stmt).one()
    total = int(total or 0)
    correct = int(correct or 0)

    by_model = []
    for mid, name, version, horizon, kind, n, n_correct, m_prob, m_ret in db.execute(per_model).all():
        n, n_correct = int(n or 0), int(n_correct or 0)
        by_model.append(
            {
                "model_id": mid,
                "name": name,
                "version": version,
                "horizon_days": horizon,
                "label_kind": kind,
                "evaluated_predictions": n,
                "correct": n_correct,
                "accuracy": (n_correct / n) if n else None,
                "avg_probability": float(m_prob) if m_prob is not None else None,
                "avg_actual_return": float(m_ret) if m_ret is not None else None,
            }
        )

    return {
        "evaluated_predictions": total,
        "correct": correct,
        "accuracy": (correct / total) if total else None,
        "avg_probability": float(avg_prob) if avg_prob is not None else None,
        "avg_actual_return": float(avg_return) if avg_return is not None else None,
        "overall_note": (
            "The figures above are all models together, across horizons and label kinds. "
            "Judge a model by its own row in by_model."
        ),
        "by_model": by_model,
    }


@router.get("/predictions/accuracy/horizon", response_model=dict)
def prediction_accuracy_at_horizon(
    db: DbSession,
    horizon_days: int = Query(..., ge=1, le=60),
    target_return: float | None = None,
    model_id: int | None = None,
) -> dict:
    """"What if we judged this model on X days instead of the horizon it was
    trained for?" — entirely read-only, re-scores every prediction against
    an arbitrary horizon without touching the stored (permanent) evaluation.

    Answers "is the app guessing properly" for any X you want to test, using
    the same predictions already on record rather than requiring a retrain.
    """
    try:
        result = predict_service.accuracy_at_horizon(db, horizon_days, target_return, model_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return {
        "horizon_days": result.horizon_days,
        "target_return": result.target_return,
        "total_predictions": result.total_predictions,
        "evaluable": result.evaluable,
        "correct": result.correct,
        # Nothing old enough to check is "no answer", never 0.0 (#474).
        "accuracy": result.accuracy if result.evaluable else None,
        "avg_actual_return": result.avg_actual_return if result.evaluable else None,
    }


@router.post("/predictions/evaluate", response_model=MessageResponse)
def evaluate_predictions(db: DbSession) -> MessageResponse:
    """Backfill outcomes for predictions whose horizon has elapsed."""
    count = predict_service.evaluate_pending_predictions(db)
    return MessageResponse(message=f"Evaluated {count} predictions")


@router.get("/calibration", response_model=CalibrationReport)
def calibration(
    db: DbSession,
    source: Literal["signals", "predictions"] = "signals",
    mode: str | None = "paper",
    strategy_id: int | None = None,
    since: datetime | None = None,
    model_id: int | None = None,
    label_kind: str = "barrier",
) -> CalibrationReport:
    """Does a shown confidence of 0.70 actually hit its target 70% of the time?

    `mode`, `strategy_id` and `since` apply to signals; `model_id` and
    `label_kind` to predictions. Buckets under 30 samples are flagged not
    meaningful rather than hidden, so the report is honest from day one.
    """
    if source == "signals":
        report = calibration_service.signal_calibration(
            db, mode=mode, strategy_id=strategy_id, since=since
        )
    else:
        report = calibration_service.prediction_calibration(
            db, model_id=model_id, label_kind=label_kind
        )
    return CalibrationReport.model_validate(report)
