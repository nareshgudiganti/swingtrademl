# ruff: noqa: E501 (long explanatory lines)
"""Read-only overview of the 5-day and 15-day models for the admin screen (#385).

Shows, per model: who it is, its horizon, whether it is approved, what evidence is stored, when it last scored,
and whether the Brain used it or only a shadow lane did. Only SELECTs. A value that is not stored is the string
"not recorded"; a value that cannot be worked out is "unknown". Nothing is guessed and nothing is written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.lane_shadow import LanePick
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.workers import heartbeat, job_runs
from swing_trade_ml.workers.scheduler import list_jobs

NOT_RECORDED = "not recorded"
UNKNOWN = "unknown"
HORIZONS = (5, 15)

# The scheduled jobs that scan or score, and what each one does, in plain words.
JOBS: dict[str, str] = {
    "predict_watchlist": "Live scan: the active models score the watchlist",
    "brain_nightly": "Brain night run: decides ideas from the scores",
    "horizon5_nightly": "5-day recommendation records (Brain horizon workflow)",
    "h05_daily": "5-day evaluation lane (test only, no trades)",
    "lane_shadow_daily": "Shadow lanes: record the top picks and score them later (test only, no trades; off unless enabled)",
    "evaluate_predictions": "Marks past model scores right or wrong",
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


def _or(value: Any, missing: str = NOT_RECORDED) -> Any:
    return missing if value is None else value


def _jobs() -> dict[str, Any]:
    registered = {j["id"]: j for j in list_jobs() if j.get("id")}
    runs, runs_available = job_runs.read_runs()
    rows = []
    for job_id, about in JOBS.items():
        job = registered.get(job_id)
        run = runs.get(job_id, {})
        rows.append(
            {
                "id": job_id,
                "about": about,
                "scheduled": job is not None,
                "schedule": job_runs.describe_schedule(job["trigger"])
                if job and job.get("trigger")
                else None,
                "next_run": job.get("next_run") if job else None,
                "last_started_at": run.get("last_started_at"),
                "last_finished_at": run.get("last_finished_at"),
                "last_status": run.get("last_status"),
            }
        )
    return {"worker_alive": heartbeat.is_alive(), "runs_available": runs_available, "rows": rows}


def _brain_usage(last_horizon_rec: tuple | None, lane_pick_day: Any) -> dict[str, Any]:
    """Whether the Brain used this model. Only what the Brain's horizon records say; live Brain ideas store no
    model id, so a live Brain use cannot be shown from them (reported as such, never guessed)."""
    if last_horizon_rec is not None:
        session_date, research_only = last_horizon_rec
        if research_only:
            return {
                "state": "shadow_only",
                "label": "Shadow only: recorded for research, not used for Brain decisions",
                "last_session": session_date.isoformat(),
            }
        return {
            "state": "used",
            "label": "Used by the Brain horizon workflow",
            "last_session": session_date.isoformat(),
        }
    if lane_pick_day is not None:
        return {
            "state": "shadow_only",
            "label": "Shadow only: a test lane scored with it, the Brain did not",
            "last_session": lane_pick_day.isoformat(),
        }
    return {"state": UNKNOWN, "label": NOT_RECORDED, "last_session": None}


def _model_row(
    m: MLModel, last_pred: datetime | None, brain: dict[str, Any], lane_day: Any
) -> dict[str, Any]:
    from swing_trade_ml.services.model_registry import role_of

    role = role_of(m)
    approved = m.status == ModelStatus.ACTIVE
    return {
        "id": m.id,
        "name": m.name,
        "version": m.version,
        "algorithm": m.algorithm,
        "horizon_days": m.prediction_horizon_days,
        "label_kind": m.label_kind,
        "status": m.status,
        "approval": {
            "live_approved": approved,
            "label": "Approved: the live scan loads it"
            if approved
            else f"Not the live model (status {m.status})",
            "role": role["role"],
            "role_recorded": role["recorded"],
            "approved_at": _iso(m.activated_at) if approved else None,
            "approved_by": NOT_RECORDED,  # ml_models stores no approver
        },
        "evidence": {
            "trained_at": _or(_iso(m.trained_at)),
            "train_start": _or(_iso(m.train_start)),
            "train_end": _or(_iso(m.train_end)),
            "training_samples": _or(m.n_samples),
            "training_stocks": len(m.training_symbols or []) or NOT_RECORDED,
            "accuracy": _or(m.accuracy),
            "precision": _or(m.precision),
            "roc_auc": _or(m.roc_auc),
            "evaluation_report_link": NOT_RECORDED,
            "notes": _or(m.notes),
        },
        "last_scored_at": _or(_iso(last_pred), "never scored"),
        "last_shadow_lane_day": lane_day.isoformat() if lane_day else None,
        "brain_usage": brain,
    }


def build_overview(db: Session) -> dict[str, Any]:
    models = list(
        db.execute(
            select(MLModel)
            .where(
                MLModel.prediction_horizon_days.in_(HORIZONS),
                (MLModel.status == ModelStatus.ACTIVE) | (MLModel.model_role.in_(("final", "prod"))),
            )
            .order_by(MLModel.prediction_horizon_days, MLModel.name, MLModel.id)
            .limit(200)
        ).scalars()
    )
    ids = [m.id for m in models]
    last_pred: dict[int, datetime] = {}
    lane_day: dict[int, Any] = {}
    recs: dict[int, tuple] = {}
    if ids:
        last_pred = dict(
            db.execute(
                select(Prediction.model_id, func.max(Prediction.ts))
                .where(Prediction.model_id.in_(ids))
                .group_by(Prediction.model_id)
            ).all()
        )
        lane_day = dict(
            db.execute(
                select(LanePick.model_id, func.max(LanePick.signal_day))
                .where(LanePick.model_id.in_(ids))
                .group_by(LanePick.model_id)
            ).all()
        )
        for model_id, session_date, research_only in db.execute(
            select(HorizonRecordRow.model_id, HorizonRecordRow.session_date, HorizonRecordRow.research_only)
            .where(HorizonRecordRow.model_id.in_(ids))
            .order_by(HorizonRecordRow.session_date, HorizonRecordRow.id)
        ).all():
            recs[model_id] = (session_date, research_only)  # ascending, so the last one wins
    rows = [
        _model_row(
            m, last_pred.get(m.id), _brain_usage(recs.get(m.id), lane_day.get(m.id)), lane_day.get(m.id)
        )
        for m in models
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "horizons": {str(h): [r for r in rows if r["horizon_days"] == h] for h in HORIZONS},
        "jobs": _jobs(),
        "not_recorded": [
            "Who approved each model (ml_models stores no approver)",
            "A link to each model's evaluation report",
            "Which model scored a live Brain idea (live Brain ideas store no model id)",
        ],
    }
