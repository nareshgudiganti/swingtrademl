"""Admin > Jobs: every scheduled job, its schedule, last run and next run. Owner only, read only.

The job list (schedule, next run) comes from the worker's heartbeat snapshot; the last runs come from
Redis, written by the worker's listener (workers/job_runs.py). Nothing here can start or change a job.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from swing_trade_ml.api.deps import require_owner
from swing_trade_ml.workers import heartbeat, job_runs
from swing_trade_ml.workers.scheduler import list_jobs

router = APIRouter(prefix="/admin/jobs", tags=["admin-jobs"], dependencies=[Depends(require_owner)])

_RUN_FIELDS = (
    "last_started_at",
    "last_finished_at",
    "last_duration_s",
    "last_status",
    "last_error_kind",
    "running_since",
    "last_missed_at",
    "last_skipped_at",
)


@router.get("")
def scheduled_jobs() -> dict[str, Any]:
    registered = {j["id"]: j for j in list_jobs() if j.get("id")}
    runs, runs_available = job_runs.read_runs()
    rows = []
    for job_id in sorted(set(registered) | set(runs), key=job_runs.order_key):
        job = registered.get(job_id)
        run = runs.get(job_id, {})
        name, about = job_runs.label_for(job_id)
        trigger = job.get("trigger") if job else None
        rows.append(
            {
                "id": job_id,
                "name": name,
                "about": about,
                "registered": job is not None,
                "schedule": job_runs.describe_schedule(trigger) if trigger else None,
                "next_run": job.get("next_run") if job else None,
                **{f: run.get(f) for f in _RUN_FIELDS},
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "worker_alive": heartbeat.is_alive(),
        "runs_available": runs_available,
        "jobs": rows,
    }
