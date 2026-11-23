# ruff: noqa: E501 (long explanatory lines)
"""Versioned research rules for each horizon (target, stop, window), and which horizons are research-only.

A version is immutable: its rules and its hash never change once written here. Changing a rule means adding a NEW
version and an owner-approved change of `ACTIVE_VERSION`; there is no switch, no environment value and no database
row that edits a version. Old records name the version they were made under, so they never move.

This holds research rules only. Trading limits, sizing, exits and the frozen trial protocols stay in code and tests
(see docs/architecture/TARGET-ARCHITECTURE-PROPOSAL.md section 7). Pure: imports nothing from the app.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


class ResearchConfigError(ValueError):
    """An unknown version or horizon was asked for; nothing is guessed."""


@dataclass(frozen=True, slots=True)
class HorizonRule:
    horizon: int  # exchange sessions
    target_pct: float
    stop_pct: float
    half_out_pct: float | None
    max_sessions: int
    # True = a lane may score and record it for the owner; no customer screen and no Brain decision may use it.
    research_only: bool


@dataclass(frozen=True, slots=True)
class ResearchConfigVersion:
    version: str
    rules: tuple[HorizonRule, ...]

    @property
    def sha256(self) -> str:
        """A fingerprint of the rules, stored beside the version name on every record made under it."""
        body = [
            [r.horizon, r.target_pct, r.stop_pct, r.half_out_pct, r.max_sessions, r.research_only]
            for r in sorted(self.rules, key=lambda r: r.horizon)
        ]
        return hashlib.sha256(json.dumps([self.version, body], separators=(",", ":")).encode()).hexdigest()

    def rule(self, horizon: int) -> HorizonRule:
        for r in self.rules:
            if r.horizon == horizon:
                return r
        raise ResearchConfigError(f"version {self.version!r} has no rule for a {horizon}-session horizon")

    @property
    def horizons(self) -> tuple[int, ...]:
        return tuple(sorted(r.horizon for r in self.rules))


# The values are copies of rules pinned elsewhere (h05 protocol for 5D, lane slots for 10D and 15D); a test checks it.
HZ_RULES_V1 = ResearchConfigVersion(
    "hz-rules-v1",
    (
        HorizonRule(5, target_pct=0.02, stop_pct=0.04, half_out_pct=None, max_sessions=5, research_only=False),
        HorizonRule(10, target_pct=0.06, stop_pct=0.035, half_out_pct=None, max_sessions=10, research_only=True),
        HorizonRule(15, target_pct=0.08, stop_pct=0.04, half_out_pct=0.05, max_sessions=15, research_only=True),
    ),
)

# Read-only: a version cannot be added, replaced or removed at run time. A new version is a code change.
VERSIONS: Mapping[str, ResearchConfigVersion] = MappingProxyType({HZ_RULES_V1.version: HZ_RULES_V1})

# Selected by version name in code, never by a toggle. A change needs a new version and the owner's approval.
ACTIVE_VERSION = HZ_RULES_V1.version


def get_version(version: str) -> ResearchConfigVersion:
    try:
        return VERSIONS[version]
    except KeyError:
        raise ResearchConfigError(f"unknown research config version {version!r}") from None


def active() -> ResearchConfigVersion:
    return get_version(ACTIVE_VERSION)


def rule_for(horizon: int, version: str | None = None) -> HorizonRule:
    return (get_version(version) if version else active()).rule(horizon)


def is_research_only(horizon: int, version: str | None = None) -> bool:
    """True when the horizon may not feed a customer screen or a Brain decision under this version."""
    return rule_for(horizon, version).research_only
