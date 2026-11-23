# ruff: noqa: E501  (long plain-English docstrings)
"""The trade rule the simulation obeys (#321), as a versioned setting that comes from ONE place:
`core/research_config.py` (version hz-rules-v1), the same rules the horizon records are stamped with.

OWNER DECISION: the default is the existing approved 5D paper rule (+2% / -4%, no half-out, sold at the close of
session 5; the entry day is session 1, as in the h05 lane). 10D (+6% / -3.5% / 10 sessions) and 15D (+8% / -4%, half
out at +5%, 15 sessions) are RESEARCH CONFIGURATIONS only: a rule built for them says `research_only`, every ledger
record repeats it, and nothing here invents or loosens a limit. The numbers are never copied into this package: they
are read from the research config at import time, and a test pins them against the lane protocol and the replay
constants so a drift shows up as a failure.

Every rule has a version string (`hz-rules-v1:5D`); every ledger record carries it, and a comparison refuses to mix two.
Each rule is refused if looser than its definition. The drawdown halt is `settings.MAX_PORTFOLIO_DRAWDOWN_PCT`, never
above the settled 15%; the stop-loss cooldown is `settings.STOP_LOSS_COOLDOWN_DAYS`, never below the settled 5. Sector
cap, position count and size, cash floor and minimum position come from `services/limits.limits_for(equity)`; sizing
from `brain/portfolio_sim.entry_budget` (1% risk at the stop). Read-only reuse: none of those is changed.
"""

from __future__ import annotations

from dataclasses import dataclass

from swing_trade_ml.core import research_config

SETTLED_DRAWDOWN_HALT = 0.15
SETTLED_MAX_NEW_PER_DAY = 5  # the owner's "top 5 a day"
SETTLED_RISK_PER_TRADE = 0.01
SETTLED_STOP_COOLDOWN_DAYS = 5  # services/risk.py: no re-buy within this many calendar days of a stop-out
SETTLED_DEFENSIVE_MAX_NEW = 2  # the same as brain/portfolio_sim.DEFENSIVE_MAX_NEW (M07)

# Market modes the brain publishes (CLAUDE.md principle 6). In DEFENSIVE a buy is half size and at most 2 a day;
# in NO_NEW_TRADES nothing is bought. A mode the ledger does not know is treated as NO_NEW_TRADES.
MODE_NORMAL = "NORMAL"
MODE_DEFENSIVE = "DEFENSIVE"
MODE_NO_NEW_TRADES = "NO_NEW_TRADES"
MODES = (MODE_NORMAL, MODE_DEFENSIVE, MODE_NO_NEW_TRADES)

# The app's entry rules (services/risk.py check_entry) that the ledger does NOT model, whatever inputs it is given.
# Every ledger lists them (PortfolioLedger.not_applied), so nothing claims "the app's rules were applied" falsely.
ALWAYS_NOT_APPLIED: tuple[str, ...] = (
    "regime deployable ceiling (services/deployable.py: how much of the account the market regime allows invested)",
    "the brain's one reserved slot (services/risk.py market_room)",
    "the per-strategy share of position slots (services/risk.py)",
)
# Modelled only when the caller supplies the input; each one missing is listed in PortfolioLedger.not_applied.
OPTIONAL_INPUTS: dict[str, str] = {
    "market_modes": "market mode per session (every session is then treated as NORMAL, looser than the app)",
    "liquidity": "liquidity limit (needs average daily traded value per stock, point in time)",
    "cap_tiers": "cap tier and small-company budget (needs each stock's tier)",
    "avoid": "exchange avoid list (needs the restriction, results and corporate-action feeds as inputs)",
}

_CONFIG = research_config.active()


def version_name(horizon: int) -> str:
    """The rule version of one horizon under the active research config, e.g. "hz-rules-v1:5D"."""
    return f"{_CONFIG.version}:{horizon}D"


RULE_5D = version_name(5)
RULE_10D = version_name(10)
RULE_15D = version_name(15)

# The definition each version may never be looser than: (target, stop, half-out or None, maximum sessions, label,
# research_only). Built from the research config: nothing here is a copy of a number.
DEFINITIONS: dict[str, tuple[float, float, float | None, int, str, bool]] = {
    version_name(rule.horizon): (
        rule.target_pct,
        rule.stop_pct,
        rule.half_out_pct,
        rule.max_sessions,
        f"{rule.horizon}D",
        rule.research_only,
    )
    for rule in _CONFIG.rules
}
DEFAULT_RULE = RULE_5D  # the existing approved 5D paper rule

# Kept for code that spoke of "the settled rules" (the 15-day plan).
SETTLED_STOP = DEFINITIONS[RULE_15D][1]
SETTLED_TARGET = DEFINITIONS[RULE_15D][0]
SETTLED_HALF_OUT = DEFINITIONS[RULE_15D][2]
SETTLED_HORIZON_SESSIONS = DEFINITIONS[RULE_15D][3]


class RuleLoosened(ValueError):  # noqa: N818 - reads as the refusal it is
    """A rule was handed in looser than its definition."""


class MixedRuleVersions(ValueError):  # noqa: N818 - reads as the refusal it is
    """Results made under different trade rules were put into one comparison."""


@dataclass(frozen=True, slots=True)
class TradingRules:
    target: float = DEFINITIONS[DEFAULT_RULE][0]
    stop: float = DEFINITIONS[DEFAULT_RULE][1]
    half_out: float | None = DEFINITIONS[DEFAULT_RULE][2]  # None = no half-out
    horizon_sessions: int = DEFINITIONS[DEFAULT_RULE][
        3
    ]  # the most sessions a position is held (the entry day is 1)
    drawdown_halt: float = SETTLED_DRAWDOWN_HALT
    max_new_per_day: int = SETTLED_MAX_NEW_PER_DAY
    risk_per_trade_pct: float = SETTLED_RISK_PER_TRADE
    stop_cooldown_days: int = SETTLED_STOP_COOLDOWN_DAYS
    defensive_max_new: int = SETTLED_DEFENSIVE_MAX_NEW
    version: str = DEFAULT_RULE
    horizon_label: str = DEFINITIONS[DEFAULT_RULE][4]

    def __post_init__(self) -> None:
        if self.version not in DEFINITIONS:
            raise RuleLoosened(f"unknown rule version {self.version!r}; known: {sorted(DEFINITIONS)}")
        target, stop, half_out, sessions, label, _ = DEFINITIONS[self.version]
        if self.horizon_label != label:
            raise RuleLoosened(f"{self.version} is the {label} rule, not {self.horizon_label}")
        if not 0 < self.stop <= stop:
            raise RuleLoosened(f"{self.version}: stop {self.stop} is looser than {stop}")
        if not 0 < self.target <= target:
            raise RuleLoosened(f"{self.version}: target {self.target} is above its definition {target}")
        if not 1 <= self.horizon_sessions <= sessions:
            raise RuleLoosened(f"{self.version}: {self.horizon_sessions} sessions is longer than {sessions}")
        if half_out is None:
            if self.half_out is not None:
                raise RuleLoosened(f"{self.version} has no half-out")
        else:
            if self.half_out is None or not 0 < self.half_out <= half_out:
                raise RuleLoosened(f"{self.version}: the half-out must exist and be at most {half_out}")
            if self.half_out >= self.target:
                raise RuleLoosened("the half-out level must sit below the target")
        if not 0 < self.drawdown_halt <= SETTLED_DRAWDOWN_HALT:
            raise RuleLoosened(
                f"drawdown halt {self.drawdown_halt} is looser than the settled {SETTLED_DRAWDOWN_HALT}"
            )
        if not 1 <= self.max_new_per_day <= SETTLED_MAX_NEW_PER_DAY:
            raise RuleLoosened(f"more than {SETTLED_MAX_NEW_PER_DAY} new buys a day")
        if not 0 < self.risk_per_trade_pct <= SETTLED_RISK_PER_TRADE:
            raise RuleLoosened("risk per trade is above the settled 1%")
        if self.stop_cooldown_days < SETTLED_STOP_COOLDOWN_DAYS:
            raise RuleLoosened(
                f"stop-loss cooldown {self.stop_cooldown_days} days is shorter than {SETTLED_STOP_COOLDOWN_DAYS}"
            )
        if not 0 <= self.defensive_max_new <= SETTLED_DEFENSIVE_MAX_NEW:
            raise RuleLoosened(f"more than {SETTLED_DEFENSIVE_MAX_NEW} new buys a day in a DEFENSIVE market")

    @property
    def research_only(self) -> bool:
        """True for a research configuration (10D, 15D): it may be run and recorded, never shown to a customer or
        used by a Brain decision."""
        return DEFINITIONS[self.version][5]

    @classmethod
    def for_horizon(cls, horizon: int) -> TradingRules:
        """The rule of one horizon, read from the research config. A local setting can only tighten it."""
        from swing_trade_ml.core.config import settings

        rule = _CONFIG.rule(horizon)  # an unknown horizon raises: nothing is guessed
        return cls(
            target=rule.target_pct,
            stop=rule.stop_pct,
            half_out=rule.half_out_pct,
            horizon_sessions=rule.max_sessions,
            drawdown_halt=min(float(settings.MAX_PORTFOLIO_DRAWDOWN_PCT), SETTLED_DRAWDOWN_HALT),
            stop_cooldown_days=max(int(settings.STOP_LOSS_COOLDOWN_DAYS), SETTLED_STOP_COOLDOWN_DAYS),
            version=version_name(horizon),
            horizon_label=f"{horizon}D",
        )

    @classmethod
    def plan_5d(cls) -> TradingRules:
        """The default: the existing approved 5D paper rule."""
        return cls.for_horizon(5)

    @classmethod
    def plan_10d(cls) -> TradingRules:
        """A research configuration only (research_only)."""
        return cls.for_horizon(10)

    @classmethod
    def plan_15d(cls) -> TradingRules:
        """A research configuration only (research_only): +8% / -4%, half out at +5%, 15 sessions."""
        return cls.for_horizon(15)

    @classmethod
    def from_app(cls) -> TradingRules:
        """The default rule: the existing approved 5D paper rule."""
        return cls.plan_5d()


def require_one_version(versions: set[str] | frozenset[str]) -> str:
    """The one rule version of a comparison, or MixedRuleVersions when there is more than one (or none)."""
    if len(versions) != 1:
        raise MixedRuleVersions(
            f"a comparison needs exactly one rule version, found {sorted(versions) or 'none'}"
        )
    return next(iter(versions))
