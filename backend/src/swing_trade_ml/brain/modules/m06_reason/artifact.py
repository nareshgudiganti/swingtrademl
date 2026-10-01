"""Saved combiners: `brain_meta_vN.joblib` plus a readable `brain_meta_vN.json`
report, in the same folder as the other model files. The newest version is
the one in use; older ones stay for rollback (delete or rename the newest).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from swing_trade_ml.core.config import settings

_NAME = re.compile(r"^brain_meta_v(\d+)\.joblib$")
_cache: dict[str, Any] = {}


def _folder() -> Path:
    return Path(settings.MODEL_ARTIFACT_DIR)


def _versions() -> list[tuple[int, Path]]:
    folder = _folder()
    if not folder.exists():
        return []
    found = [(int(m.group(1)), p) for p in folder.iterdir() if (m := _NAME.match(p.name))]
    return sorted(found)


def save(combiner: Any, report: dict, base_models: dict[str, str]) -> Path:
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    version = (_versions()[-1][0] if _versions() else 0) + 1
    path = folder / f"brain_meta_v{version}.joblib"
    payload = {
        "version": f"v{version}",
        "created_at": datetime.now(UTC).isoformat(),
        "combiner": combiner,
        "report": report,
        "base_models": base_models,
    }
    joblib.dump(payload, path)
    readable = {k: v for k, v in payload.items() if k != "combiner"}
    path.with_suffix(".json").write_text(json.dumps(readable, indent=2, default=str), encoding="utf-8")
    return path


def load_latest() -> dict | None:
    """The newest saved combiner, cached until its file changes."""
    versions = _versions()
    if not versions:
        return None
    path = versions[-1][1]
    key = f"{path}:{path.stat().st_mtime_ns}"
    if key not in _cache:
        _cache.clear()
        _cache[key] = joblib.load(path)
    return _cache[key]
