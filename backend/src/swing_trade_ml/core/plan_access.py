"""What a caller may see under the Free / Pro plans (moved from api/deps.py, no behaviour change).

It lives in core so the services layer can name it without importing the api layer. `api.deps` re-exports it,
so every existing `from swing_trade_ml.api.deps import PlanAccess` keeps working and is the same class.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlanAccess:
    """What the caller may see. `unrestricted` callers see everything: the
    owner always, and a tester while plans are switched off. Members always get
    their plan's rules. The owner can still preview a plan
    (X-Preview-Plan) and then gets exactly what that plan's users get."""

    unrestricted: bool
    plan: str | None
    features: frozenset[str] = frozenset()
    limits: dict = field(default_factory=dict)
    previewing: bool = False

    def has(self, feature: str) -> bool:
        return self.unrestricted or feature in self.features

    @property
    def picks_per_day(self) -> int | None:
        return None if self.unrestricted else (self.limits.get("picks_per_day") or None)

    @property
    def history_days(self) -> int | None:
        return None if self.unrestricted else (self.limits.get("history_days") or None)

    @property
    def cap_tiers(self) -> set[str] | None:
        return None if self.unrestricted else set(self.limits.get("allowed_cap_tiers") or [])
