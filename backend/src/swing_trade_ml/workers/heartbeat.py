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

import time
from pathlib import Path

from swing_trade_ml.core.config import settings

_HEARTBEAT_PATH = Path(settings.MODEL_ARTIFACT_DIR) / ".scheduler_heartbeat"

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
