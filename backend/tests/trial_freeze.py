"""Which files decide what the bot and the brain pick, size and exit. Shared by the freeze test and the
script that records an approved change (scripts/approve_trial_change.py)."""

from __future__ import annotations

import hashlib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
MANIFEST = Path(__file__).with_name("trial_freeze.json")

# Every file that changes which stocks are picked, how much is bought, or when a position exits.
FROZEN_DIRS = ("brain/modules", "strategies")
FROZEN_FILES = (
    "brain/constitution.py",
    "brain/context.py",
    "brain/contracts.py",
    "brain/fallbacks.py",
    "brain/market_mode.py",
    "brain/module.py",
    "brain/opinions.py",
    "brain/reader.py",
    "brain/runner.py",
    "brain/service.py",
    "brain/universe.py",
    "ml/calibrated_model.py",
    "ml/features.py",
    "ml/market_context.py",
    "ml/predict.py",
    "ml/real_question.py",
    "ml/sector_map.py",
    "services/avoid.py",
    "services/deployable.py",
    "services/engine.py",
    "services/exit_policy.py",
    "services/limits.py",
    "services/risk.py",
)


def frozen_paths() -> list[str]:
    paths = set(FROZEN_FILES)
    for d in FROZEN_DIRS:
        paths |= {p.relative_to(PACKAGE).as_posix() for p in (PACKAGE / d).rglob("*.py")}
    return sorted(paths)


def fingerprint(rel: str) -> str:
    """Line endings ignored, so a Windows checkout and Linux CI agree."""
    text = (PACKAGE / rel).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(text).hexdigest()[:16]
