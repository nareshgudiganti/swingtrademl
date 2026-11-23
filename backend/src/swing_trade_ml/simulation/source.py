# ruff: noqa: E501  (long plain-English docstrings)
"""The source adapter: horizon records, keyed by the permanent stock identity, become the ledger's daily picks.

A horizon record (`services/horizon_records`, table `horizon_records`) is one workflow result for one stock (a
`security_id`), one market session and one horizon. This module reads those rows and hands the ledger, per session, the
picks a portfolio may buy the next morning. It reads only; it writes nothing and commits nothing.

Rules it keeps:
- a portfolio under rule hz-rules-v1:5D reads ONLY 5-session records. A 10D or 15D record never reaches it, and a
  research-only record is read only by a rule that is itself research-only (the ledger record then says so);
- the records read are the FIRST revision of each key, as originally recorded (a later re-run never changes what a past
  session's picks were, so nothing is looked up after the fact);
- only a TRADE record is a pick. WATCH and WAIT are not picks; a Brain-filtered portfolio sees them as held back, with the
  reason, and buys nothing. NO_DECISION is nothing at all. No pick is ever replaced by another;
- every pick carries its `security_id` and the `record_id` it came from, and so does every fill and block the ledger
  makes from it, so a result can be traced back to the stock and the record.

The symbol a pick is traded under is the stock's symbol on that session's date, resolved through the identity tables
(`securities`, `security_symbols`), so a renamed stock still reaches its own prices.

Momentum has no record source yet (it needs its own verified ranking inputs): its picks are passed in by the caller,
and are empty if not given. That is still synthetic.

Everything database-related is imported when called, so importing this module loads no database code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import Candidate, Decisions
from swing_trade_ml.simulation.rules import TradingRules

TRADE = "TRADE"
NOT_A_PICK = ("WATCH", "WAIT")


class HorizonSourceError(ValueError):
    """A record that must never reach this rule was found (another horizon, a research row, another config)."""


def horizon_of(rules: TradingRules) -> int:
    return int(rules.horizon_label.rstrip("D"))


def symbol_on(db: Any, security_id: int, on: date, exchange: str = "NSE") -> str | None:
    """The stock's symbol on `on`, from the identity tables (a rename is followed), or None."""
    from sqlalchemy import select

    from swing_trade_ml.db.models.identity import SecuritySymbol

    return db.scalar(
        select(SecuritySymbol.symbol)
        .where(
            SecuritySymbol.security_id == security_id,
            SecuritySymbol.exchange == exchange,
            SecuritySymbol.valid_from <= on,
            (SecuritySymbol.valid_to.is_(None)) | (SecuritySymbol.valid_to >= on),
        )
        .order_by(SecuritySymbol.valid_from.desc())
        .limit(1)
    )


def _security_ids(db: Any) -> list[int]:
    from sqlalchemy import select

    from swing_trade_ml.db.models.identity import Security

    return list(db.scalars(select(Security.id).order_by(Security.id)))


def read_records(
    db: Any, rules: TradingRules, *, since: date | None = None, until: date | None = None
) -> list[Any]:
    """The first revision of every record of this rule's horizon, oldest session first, read through the horizon
    records service (the one door to that table). Raises if any row read could not belong to this rule: that would be
    a mix of horizons, a research row for a product rule, or another research config."""
    from swing_trade_ml.services import horizon_records

    horizon = horizon_of(rules)
    config_version = rules.version.split(":")[0]
    rows: list[Any] = []
    for security_id in _security_ids(db):
        rows.extend(
            horizon_records.records_for(
                db,
                security_id,
                view="first",
                horizon_days=horizon,
                since=since,
                until=until,
                product_only=not rules.research_only,
            )
        )
    rows.sort(key=lambda r: (r.session_date, r.id))
    for row in rows:
        if row.horizon_days != horizon:
            raise HorizonSourceError(
                f"record {row.id} is a {row.horizon_days}D record, this rule is {horizon}D"
            )
        if row.research_only and not rules.research_only:
            raise HorizonSourceError(f"record {row.id} is research-only and this rule is not")
        if row.research_config_version != config_version:
            raise HorizonSourceError(
                f"record {row.id} was made under {row.research_config_version}, this rule is {config_version}"
            )
    return rows


def decisions_from_horizon_records(
    db: Any,
    rules: TradingRules,
    policy: Policy,
    *,
    sectors: Mapping[int, str] | None = None,
    since: date | None = None,
    until: date | None = None,
) -> Decisions:
    """session (ISO date) -> the picks decided at that session's close, for one policy.

    MODEL_ONLY buys the TRADE records. BRAIN_FILTERED sees the same, plus the WATCH and WAIT ones as held back with
    the reason. MOMENTUM has no record source: use `decisions_by_policy` to pass its own picks."""
    if policy is Policy.MOMENTUM:
        return {}
    out: dict[str, list[Candidate]] = {}
    for row in read_records(db, rules, since=since, until=until):
        if row.decision != TRADE and not (policy is Policy.BRAIN_FILTERED and row.decision in NOT_A_PICK):
            continue
        symbol = symbol_on(db, row.security_id, row.session_date)
        if symbol is None:
            raise HorizonSourceError(
                f"record {row.id}: security {row.security_id} has no symbol on {row.session_date}"
            )
        held_back = None if row.decision == TRADE else f"brain check: {row.decision}"
        out.setdefault(row.session_date.isoformat(), []).append(
            Candidate(
                symbol=symbol,
                score=float(row.score) if row.score is not None else 0.0,
                sector=(sectors or {}).get(row.security_id),
                block_reason=held_back,
                security_id=row.security_id,
                record_id=row.id,
            )
        )
    return out


def decisions_by_policy(
    db: Any,
    rules: TradingRules,
    *,
    momentum: Decisions | None = None,
    sectors: Mapping[int, str] | None = None,
    sessions: Sequence[str] | None = None,
) -> dict[Policy, Decisions]:
    """The picks of all three policies for `run_cohort`. `momentum` is passed in (it has no record source yet)."""
    since = date.fromisoformat(sessions[0]) if sessions else None
    until = date.fromisoformat(sessions[-1]) if sessions else None
    return {
        Policy.MOMENTUM: dict(momentum or {}),
        Policy.MODEL_ONLY: decisions_from_horizon_records(
            db, rules, Policy.MODEL_ONLY, sectors=sectors, since=since, until=until
        ),
        Policy.BRAIN_FILTERED: decisions_from_horizon_records(
            db, rules, Policy.BRAIN_FILTERED, sectors=sectors, since=since, until=until
        ),
    }
