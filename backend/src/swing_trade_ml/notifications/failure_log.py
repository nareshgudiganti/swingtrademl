"""A small record of urgent Telegram alerts that did not get through (#358).

Kept as a JSON file on the shared model volume, same pattern as workers/heartbeat.py: the worker
sends the alerts but the API serves the ops digest, and they are separate processes. No database
table, so no migration. The file holds only words and numbers (event name, HTTP status, short
reason, counts, times). Never the message text, the token or the chat id.

States:
- retrying  : first attempt failed for a temporary reason, retries are pending.
- gave_up   : retries used up. This is the warning the owner should see.
- permanent : refused for a reason retrying cannot fix (bad token, blocked chat). Shown at once.
A message that gets through on a retry removes its entry, so a recovery is silent.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from swing_trade_ml.core.config import settings

RETRYING = "retrying"
GAVE_UP = "gave_up"
PERMANENT = "permanent"
#: A failure stays visible for a day, then drops off so an old outage does not nag forever.
KEEP_FOR = timedelta(hours=24)
MAX_ENTRIES = 30

_lock = threading.Lock()


def _path() -> Path:
    return Path(settings.MODEL_ARTIFACT_DIR) / ".telegram_failures.json"


def _now() -> datetime:
    return datetime.now(UTC)


def _load() -> list[dict[str, Any]]:
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save(entries: list[dict[str, Any]]) -> None:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries[-MAX_ENTRIES:]))
    except OSError:
        pass  # a record that cannot be written must never break the alert path


def record(
    state: str,
    *,
    event: str,
    status: int | None,
    reason: str,
    attempts: int,
    entry_id: str | None = None,
) -> str:
    """Create or update one entry and return its id."""
    entry_id = entry_id or uuid.uuid4().hex[:12]
    now = _now().isoformat(timespec="seconds")
    with _lock:
        entries = _load()
        row = next((e for e in entries if e.get("id") == entry_id), None)
        if row is None:
            row = {"id": entry_id, "first_failed_at": now}
            entries.append(row)
        row.update(
            state=state,
            event=event,
            status=status,
            reason=reason[:160],
            attempts=attempts,
            last_attempt_at=now,
        )
        _save(entries)
    return entry_id


def clear(entry_id: str) -> None:
    with _lock:
        _save([e for e in _load() if e.get("id") != entry_id])


def recent(now: datetime | None = None) -> list[dict[str, Any]]:
    cutoff = (now or _now()) - KEEP_FOR
    out = []
    for e in _load():
        try:
            if datetime.fromisoformat(e["last_attempt_at"]) >= cutoff:
                out.append(e)
        except (KeyError, ValueError):
            continue
    return out


def needing_attention(now: datetime | None = None) -> list[dict[str, Any]]:
    """Entries the owner should see: gave up or permanent (still-retrying ones are not yet a problem)."""
    return [e for e in recent(now) if e.get("state") in (GAVE_UP, PERMANENT)]
