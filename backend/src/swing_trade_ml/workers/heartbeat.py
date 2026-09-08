"""Cross-process liveness signal for the background scheduler.

The API and worker are separate processes (see docker-compose.yml), each with
its own in-memory APScheduler instance — the API's is deliberately disabled
(`ENABLE_SCHEDULER=false` there) so it never runs a second, duplicate copy of
the worker's jobs. That means checking the local `scheduler.running` flag from
the API process (which is what /status did) always reports False, forever,
regardless of whether the worker is actually healthy — it's asking the wrong
process's scheduler. This is a shared-volume heartbeat instead: the worker
touches it every tick, and any process (in practice the API, for /status) can
check how stale it is.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from swing_trade_ml.core.config import settings

_HEARTBEAT_PATH = Path(settings.MODEL_ARTIFACT_DIR) / ".scheduler_heartbeat"
# Same cross-process problem as the heartbeat file above, for the job list:
# /status runs in the API process, which never registers the worker's jobs
# on its own local APScheduler instance, so scheduler.get_jobs() there is
# always empty. The worker snapshots its real job list here on every
# heartbeat tick; the API reads it back instead of its own empty one.
_JOBS_PATH = Path(settings.MODEL_ARTIFACT_DIR) / ".scheduler_jobs.json"

# Generous relative to the ~60s write interval below — a couple of missed
# ticks (a slow job overrunning, a brief GC pause) should not flip the
# dashboard to "down" over something that isn't actually an outage.
STALE_AFTER_SECONDS = 180


def touch() -> None:
    _HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HEARTBEAT_PATH.write_text(str(time.time()))


def is_alive() -> bool:
    try:
        age = time.time() - float(_HEARTBEAT_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return False
    return age < STALE_AFTER_SECONDS


def write_jobs(jobs: list[dict[str, Any]]) -> None:
    _JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _JOBS_PATH.write_text(json.dumps(jobs))


def read_jobs() -> list[dict[str, Any]]:
    try:
        return json.loads(_JOBS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# Same cross-process problem again: job_signal_scan runs in the worker
# process and its ScanResult (instruments checked, signals produced, buys
# found) previously only ever reached a log line — invisible to anyone who
# isn't tailing container logs. Snapshotting it here, same pattern as the
# jobs list above, is what lets /status (running in the API process) answer
# "what did the last scan actually find" instead of just "when did it run."
_LAST_SCAN_PATH = Path(settings.MODEL_ARTIFACT_DIR) / ".last_scan.json"


def write_last_scan(data: dict[str, Any]) -> None:
    _LAST_SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LAST_SCAN_PATH.write_text(json.dumps(data))


def read_last_scan() -> dict[str, Any] | None:
    try:
        return json.loads(_LAST_SCAN_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
