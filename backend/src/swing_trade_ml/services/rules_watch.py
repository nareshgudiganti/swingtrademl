"""Do the running risk settings still match the rules the owner agreed? (tracker rs2)

The agreed rules (settled 2026-09-14, CLAUDE.md "Risk rules") are written out once here, on purpose
apart from the code that applies them, and compared with the values the app really trades with: the
settings, the exit policy each active strategy resolves to, the stop and target each strategy type uses,
the brain's decision policy and the capital-ladder rungs. /risk/limits alone cannot answer this: it does
not hold the target, the stop or the horizon.

Read-only. Any difference is a failed check, so the 16:20 daily check messages it the same evening.
Changing a rule means changing it here too, with the owner's OK, which is the point.

Two horizons are agreed (owner, 2026-10-20): 15 trading days at +8% / -4% (the brain, the settled rule) and
5 days at +2% / -4% (the v1 bot and its models, a separate horizon tested on its own). The v1 settings may
use either one, but target and horizon must belong to the same one; the brain is always on 15 days.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings

AGREED = {
    "trading_mode": "paper",
    "allow_live_trading": False,
    "target_pct": 0.08,
    "stop_pct": 0.04,
    "first_target_pct": 0.05,
    "scale_out_fraction": 0.5,
    "horizon_trading_days": 15,
    "time_stop_calendar_days": 30,  # settled: agrees with the 15-trading-day horizon, never "fix" to 15
    "max_drawdown_pct": 0.15,
    "max_sector_pct": 0.25,
}
# Target and stop per agreed horizon (trading days). The 15-day row is AGREED above.
HORIZONS = {
    15: {"target_pct": AGREED["target_pct"], "stop_pct": AGREED["stop_pct"]},
    5: {"target_pct": 0.02, "stop_pct": 0.04},
}
# Strategies the owner accepted with their own levels: still shown in the check, never a failure.
# Owner 2026-10-22: sma_crossover_benchmark is a comparison strategy with textbook levels (-5% / +15%);
# changing it during the trial would change what the bot is compared against.
ACCEPTED_LEVELS = {
    "sma_crossover_benchmark": "it is not used to judge the brain (owner, 2026-10-22)",
}
NAME = "Risk rules"


def _pct(x: float) -> str:
    return f"{x * 100:g}%"


def _same(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) < 1e-9


def _settings_differences() -> list[str]:
    out = []
    if AGREED["trading_mode"] != settings.TRADING_MODE:
        out.append(f"trading mode is {settings.TRADING_MODE}, not paper")
    if settings.ALLOW_LIVE_TRADING:
        out.append("live trading is allowed (ALLOW_LIVE_TRADING)")
    pairs = (
        ("half-out point", settings.ML_FIRST_TARGET_PCT, "first_target_pct"),
        ("drawdown halt", settings.MAX_PORTFOLIO_DRAWDOWN_PCT, "max_drawdown_pct"),
    )
    for label, value, key in pairs:
        if not _same(value, AGREED[key]):
            out.append(f"{label} is {_pct(value)}, agreed {_pct(AGREED[key])}")
    days = settings.ML_PREDICTION_HORIZON_DAYS
    agreed = HORIZONS.get(days)
    if agreed is None:
        out.append(f"model horizon is {days} days, agreed 5 or 15")
        agreed = HORIZONS[15]
    for label, value, key in (
        ("target", settings.ML_TARGET_RETURN_PCT, "target_pct"),
        ("stop", settings.ML_STOP_RETURN_PCT, "stop_pct"),
    ):
        if not _same(value, agreed[key]):
            out.append(f"{label} is {_pct(value)}, agreed {_pct(agreed[key])} for {days} days")
    return out


def _brain_differences() -> list[str]:
    from swing_trade_ml.brain.modules.m08_decide import policy

    p = policy.DEFAULT_POLICY

    out = []
    for label, value, key in (
        ("target", p.target_pct, "target_pct"),
        ("stop", p.stop_pct, "stop_pct"),
        ("half-out point", p.first_target_pct, "first_target_pct"),
    ):
        if not _same(value, AGREED[key]):
            out.append(f"brain {label} is {_pct(value)}, agreed {_pct(AGREED[key])}")
    if p.horizon_days != AGREED["horizon_trading_days"]:
        out.append(f"brain horizon is {p.horizon_days} days, agreed 15")
    return out


def _ladder_differences() -> list[str]:
    from swing_trade_ml.services.limits import RUNGS

    out = []
    for r in RUNGS:
        if r.sector_rule == "pct_cap" and (
            r.sector_cap_pct is None or r.sector_cap_pct > AGREED["max_sector_pct"]
        ):
            cap = "none" if r.sector_cap_pct is None else _pct(r.sector_cap_pct)
            out.append(f"sector cap at the ₹{r.value:,.0f} rung is {cap}, agreed at most 25%")
    if RUNGS[0].sector_rule != "one_per_sector":
        out.append("the smallest account is no longer limited to one stock per sector")
    return out


def _levels_for(strategy: Any) -> tuple[float, float] | None:
    """The stop and target a strategy's BUY signals carry, as fractions; None for types that take theirs
    from elsewhere (the brain: its decision policy, checked separately)."""
    stype = strategy.strategy_type
    if stype == "ml_swing":
        return settings.ML_STOP_RETURN_PCT, settings.ML_TARGET_RETURN_PCT
    if stype == "sma_crossover":
        return (
            strategy.stop_loss_pct or settings.DEFAULT_STOP_LOSS_PCT,
            strategy.take_profit_pct or settings.DEFAULT_TAKE_PROFIT_PCT,
        )
    if stype == "brain":
        return None
    # Any other type: the strategy row's own levels when set, else the app-wide defaults it falls back on.
    return (
        strategy.stop_loss_pct or settings.DEFAULT_STOP_LOSS_PCT,
        strategy.take_profit_pct or settings.DEFAULT_TAKE_PROFIT_PCT,
    )


def _strategy_differences(db: Session, accepted: list[str] | None = None) -> list[str]:
    """Differences that fail the check. Stop / target differences of an ACCEPTED_LEVELS strategy go to
    `accepted` instead (shown, not failed); its other differences still fail."""
    from swing_trade_ml.db.models.trading import Strategy
    from swing_trade_ml.services.exit_policy import exit_policy_for_strategy

    out = []
    for s in db.execute(select(Strategy).where(Strategy.is_active.is_(True)).order_by(Strategy.id)).scalars():
        found = []
        levels = _levels_for(s)
        if levels is not None:
            stop, target = levels
            # ml_swing follows the v1 settings' horizon; any other type may sit on either agreed horizon.
            if s.strategy_type == "ml_swing":
                h = HORIZONS.get(settings.ML_PREDICTION_HORIZON_DAYS, HORIZONS[15])
            else:
                h = HORIZONS[5] if _same(target, HORIZONS[5]["target_pct"]) else HORIZONS[15]
            if not _same(stop, h["stop_pct"]):
                found.append(f"stop {_pct(stop)}")
            if not _same(target, h["target_pct"]):
                found.append(f"target {_pct(target)}")
        if found and s.name in ACCEPTED_LEVELS and accepted is not None:
            accepted.append(f"{s.name} uses its own rules ({', '.join(found)}); {ACCEPTED_LEVELS[s.name]}")
            found = []
        policy = exit_policy_for_strategy(s)
        if not _same(policy.scale_out_at_pct, AGREED["first_target_pct"]):
            at = "off" if policy.scale_out_at_pct is None else _pct(policy.scale_out_at_pct)
            found.append(f"half-out at {at}")
        if policy.scale_out_at_pct is not None and not _same(
            policy.scale_out_fraction, AGREED["scale_out_fraction"]
        ):
            found.append(f"sells {_pct(policy.scale_out_fraction)} at the first target")
        if policy.time_stop_days != AGREED["time_stop_calendar_days"]:
            found.append(f"time stop {policy.time_stop_days} days")
        if found:
            out.append(f"{s.name} uses " + ", ".join(found))
    return out


def check(db: Session) -> dict:
    """{name, ok, detail, level} like the weekly and daily health checks."""
    parts = (
        ("settings", _settings_differences),
        ("brain policy", _brain_differences),
        ("capital ladder", _ladder_differences),
        ("strategies", lambda: _strategy_differences(db, accepted)),
    )
    accepted: list[str] = []
    differences: list[str] = []
    for label, fn in parts:
        try:
            differences += fn()
        except Exception as exc:  # noqa: BLE001 - one bad read must not hide the rest
            differences.append(f"could not read the {label} ({exc.__class__.__name__})")
    if not differences:
        days = settings.ML_PREDICTION_HORIZON_DAYS
        v1 = HORIZONS[days]
        detail = (
            "Paper only; brain on 15 days at +8% / -4%; v1 bot on "
            f"{days} days at +{_pct(v1['target_pct'])} / -{_pct(v1['stop_pct'])}; "
            "half out at +5%, 30-day time stop, 15% halt, 25% sector cap."
        )
        if accepted:
            detail += " Accepted benchmark: " + "; ".join(accepted) + "."
        return {"name": NAME, "ok": True, "detail": detail, "level": "ok"}
    detail = "Differs from the agreed rules: " + "; ".join(differences) + "."
    if accepted:
        detail += " Accepted benchmark: " + "; ".join(accepted) + "."
    return {"name": NAME, "ok": False, "detail": detail, "level": "fail"}
