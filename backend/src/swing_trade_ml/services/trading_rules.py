"""The trading-rule numbers and the trading calendar the screens show, served from one place (#416).

The frontend displays these; it never owns them. Everything here is read from where the number already
lives: the versioned research rules (core/research_config.py), the brain's 15-day plan
(DEFAULT_POLICY in brain/modules/m08_decide/policy.py, not the v1 settings in core/config.py),
the trial's fixed numbers (brain/trial_constants.py) and the NSE holiday list (core/holidays.py).
Nothing here is a new rule, and nothing here changes a limit, a stop or an order.

Percentages are fractions (0.08 is +8%), exactly as stored. Pure apart from reading settings.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from swing_trade_ml.brain.modules.m08_decide.policy import DEFAULT_POLICY
from swing_trade_ml.brain.trial_constants import MIN_SESSIONS, TRIAL_START
from swing_trade_ml.core import research_config
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.holidays import NSE_HOLIDAYS


def trading_rules(as_of: date | None = None, *, include_research: bool = True) -> dict[str, Any]:
    """`as_of` is the last finished trading day (default: from the market clock). `include_research=False`
    leaves the research-only horizons (10 and 15 sessions) out: what everyone but the owner is served."""
    from swing_trade_ml.core import market_session

    day = as_of or market_session.session().last_closed_trading_day
    version = research_config.get_version(research_config.ACTIVE_VERSION)
    return {
        "research": {
            "version": version.version,
            "sha256": version.sha256,
            "horizons": [
                {
                    "horizon": r.horizon,
                    "target_pct": r.target_pct,
                    "stop_pct": r.stop_pct,
                    "half_out_pct": r.half_out_pct,
                    "max_sessions": r.max_sessions,
                    "research_only": r.research_only,
                }
                for r in sorted(version.rules, key=lambda r: r.horizon)
                if include_research or not r.research_only
            ],
        },
        # A risk limit, shown read-only: the drawdown from the account's peak that pauses new buys. Read from
        # the settings that enforce it (services/risk.py); nothing here can change it.
        "risk_limits": {"max_drawdown_pct": settings.MAX_PORTFOLIO_DRAWDOWN_PCT},
        # The brain's own plan, from the Brain's decision policy (m08_decide/policy.py DEFAULT_POLICY),
        # the same object that sets each stored target and stop. Not the v1 ml_swing settings,
        # which production overrides.
        "brain_plan": {
            "target_pct": DEFAULT_POLICY.target_pct,
            "stop_pct": DEFAULT_POLICY.stop_pct,
            "half_out_pct": DEFAULT_POLICY.first_target_pct,
            "max_sessions": DEFAULT_POLICY.horizon_days,
        },
        "trial": {
            "start": TRIAL_START.isoformat(),
            "min_sessions": MIN_SESSIONS,
            "sessions_so_far": trial_sessions_so_far(day),
        },
        "calendar": {"holidays": sorted(d.isoformat() for days in NSE_HOLIDAYS.values() for d in days)},
    }


def trial_sessions_so_far(as_of: date) -> int:
    """Trading sessions from the trial's first day up to and including `as_of` (the market calendar)."""
    from datetime import timedelta

    from swing_trade_ml.core import market_session

    n, d = 0, TRIAL_START
    while d <= as_of:
        if market_session.is_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n
