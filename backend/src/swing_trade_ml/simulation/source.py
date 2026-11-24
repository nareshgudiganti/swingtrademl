# ruff: noqa: E501  (long plain-English docstrings)
"""The source adapter: horizon records, keyed by the permanent stock identity, become the ledger's daily picks.

A horizon record (`services/horizon_records`, table `horizon_records`) is one workflow result for one stock (a
`security_id`), one market session and one horizon. This module reads those rows and hands the ledger, per session, the
picks a portfolio may buy the next morning. It reads only; it writes nothing and commits nothing.

Rules it keeps:
- a portfolio under rule hz-rules-v1:5D reads ONLY 5-session records. A 10D or 15D record never reaches it, and a
  research-only record is read only by a rule that is itself research-only (the ledger record then says so);
- the run NAMES its model(s) (`ModelRef`, optionally one version); there is no default. Records of any other model are
  ignored. If more than one record is left for a stock and session (two named models, or two versions of one), the run is
  refused with `AmbiguousRecordsError`: the simulation never takes the best of several models or spends a buy slot twice;
- the records read are the FIRST revision of each key, as originally recorded (a later re-run never changes what a past
  session's picks were, so nothing is looked up after the fact);
- only a TRADE record is a pick. WATCH and WAIT are not picks; a Brain-filtered portfolio sees them as held back, with the
  reason, and buys nothing. NO_DECISION is nothing at all. No pick is ever replaced by another;
- every pick carries its `security_id` and the `record_id` it came from, and so does every fill and block the ledger
  makes from it, so a result can be traced back to the stock and the record.

The ledger keys everything by `security_id`. The symbol on each pick is the stock's symbol on that session's date, asked
of `services/identity` and used for display only; `rekey_by_security` turns symbol-keyed price series into id-keyed ones
through the same service, and refuses a symbol it cannot resolve.

Momentum has no record source yet (it needs its own verified ranking inputs): its picks are passed in by the caller,
and are empty if not given. That is still synthetic.

Everything database-related is imported when called, so importing this module loads no database code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import Candidate, Decisions
from swing_trade_ml.simulation.rules import TradingRules

TRADE = "TRADE"
NOT_A_PICK = ("WATCH", "WAIT")


class HorizonSourceError(ValueError):
    """A record that must never reach this rule was found (another horizon, a research row, another config)."""


class ModelNotNamedError(HorizonSourceError):
    """The run did not name a model. There is no default: the model that decides the picks is always chosen."""


class AmbiguousRecordsError(HorizonSourceError):
    """More than one record is left for one stock and session after the named models were chosen. The simulation never
    picks between them silently (that would quietly take the best of N models and waste a buy slot on the second)."""


@dataclass(frozen=True, slots=True)
class ModelRef:
    """A model a run names: its name, and optionally one version of it (needed when two versions both write records)."""

    name: str
    version: str | None = None

    def matches(self, row: Any) -> bool:
        return row.model_name == self.name and (self.version is None or row.model_version == self.version)

    def __str__(self) -> str:
        return self.name if self.version is None else f"{self.name}:{self.version}"


def named_models(models: Sequence[ModelRef | str] | None) -> tuple[ModelRef, ...]:
    """The models a run names, as `ModelRef`s. None, an empty list or a blank name is refused: no default exists."""
    if not models:
        raise ModelNotNamedError(
            "the run must name the model(s) whose records decide the picks; there is no default"
        )
    out = tuple(m if isinstance(m, ModelRef) else ModelRef(str(m).strip()) for m in models)
    if any(not m.name.strip() for m in out):
        raise ModelNotNamedError("a model name must not be blank")
    return out


def horizon_of(rules: TradingRules) -> int:
    return int(rules.horizon_label.rstrip("D"))


def symbol_on(db: Any, security_id: int, on: date, exchange: str = "NSE") -> str | None:
    """The stock's symbol on `on`, asked of the identity service (a rename is followed). For DISPLAY only: no pick,
    price or position is ever matched by it."""
    from swing_trade_ml.services import identity

    ref = identity.get_ref(db, security_id, exchange=exchange, on_date=on)
    return ref.symbol if ref is not None else None


class UnknownStockError(ValueError):
    """A symbol could not be resolved to exactly one security on that date. Nothing is guessed."""


def security_ids_for(db: Any, symbols: Sequence[str], on: date, exchange: str = "NSE") -> dict[str, int]:
    """symbol -> `security_id` on `on`, resolved through the identity service. Raises `UnknownStockError` for any symbol the
    identity tables do not know (or know ambiguously): a price series for an unknown stock is never accepted."""
    from swing_trade_ml.services import identity

    out: dict[str, int] = {}
    for symbol in symbols:
        sid = identity.resolve(db, symbol=symbol, exchange=exchange, on_date=on)
        if sid is None:
            raise UnknownStockError(f"{symbol!r} is not a known stock on {on}")
        out[symbol] = sid
    return out


def rekey_by_security(
    db: Any, by_symbol: Mapping[str, Any], on: date, exchange: str = "NSE"
) -> dict[int, Any]:
    """A mapping keyed by symbol (prices, traded value, cap tiers) -> the same values keyed by `security_id`, the key
    the ledger uses. Two symbols that resolve to one security are refused rather than merged."""
    ids = security_ids_for(db, list(by_symbol), on, exchange)
    if len(set(ids.values())) != len(ids):
        raise UnknownStockError("two symbols resolve to the same security")
    return {ids[symbol]: value for symbol, value in by_symbol.items()}


def _security_ids(db: Any) -> list[int]:
    from swing_trade_ml.services.identity import universe

    return universe.all_security_ids(db)


def read_records(
    db: Any,
    rules: TradingRules,
    *,
    models: Sequence[ModelRef | str] | None,
    since: date | None = None,
    until: date | None = None,
) -> list[Any]:
    """The first revision of every record of this rule's horizon written by the NAMED model(s), oldest session first,
    read through the horizon records service (the one door to that table). `models` has no default: records of any
    other model are ignored, and if more than one record is left for a stock and session the run is refused
    (`AmbiguousRecordsError`), never resolved by picking one. Raises if any row kept could not belong to this rule: that
    would be a mix of horizons, a research row for a product rule, or another research config."""
    from swing_trade_ml.services import horizon_records

    named = named_models(models)
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
    rows = [row for row in rows if any(m.matches(row) for m in named)]
    rows.sort(key=lambda r: (r.session_date, r.id))
    _refuse_ambiguity(db, rows, named)
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


def _refuse_ambiguity(db: Any, rows: Sequence[Any], named: Sequence[ModelRef]) -> None:
    by_key: dict[tuple[int, date], list[Any]] = {}
    for row in rows:
        by_key.setdefault((row.security_id, row.session_date), []).append(row)
    clashes = {key: group for key, group in by_key.items() if len(group) > 1}
    if not clashes:
        return
    (security_id, session), group = next(iter(sorted(clashes.items(), key=lambda kv: (kv[0][1], kv[0][0]))))
    symbol = symbol_on(db, security_id, session)  # for the message only
    who = f"security {security_id}" + (f" ({symbol})" if symbol else "")
    seen = ", ".join(f"record {r.id} from {r.model_name} {r.model_version or '(no version)'}" for r in group)
    raise AmbiguousRecordsError(
        f"{len(clashes)} stock-sessions have more than one record from the named models "
        f"({', '.join(str(m) for m in named)}); first: {who} on {session}: {seen}. "
        "The simulation never picks between records: name one model (or one version of it) per run."
    )


def bars_from_candles(
    db: Any, security_ids: Sequence[int], sessions: Sequence[str]
) -> dict[int, dict[str, Any]]:
    """security_id -> session (ISO date) -> `Bar`, from the stored daily candles. Each candle's instrument is matched to
    its security through the identity read API (`consumers.security_for_instrument`: token and symbol must agree),
    never by symbol alone. Candles are stamped IST midnight, so the session is the bar's date in IST. A session with no
    stored candle simply has no bar (the ledger then blocks the buy with `no_price` or marks the position stale):
    nothing is filled in or carried over. Reads only."""
    from datetime import timedelta

    from swing_trade_ml.simulation.ledger import Bar

    wanted = set(sessions)
    if not wanted or not security_ids:
        return {}
    first = date.fromisoformat(min(wanted)) - timedelta(days=1)
    last = date.fromisoformat(max(wanted)) + timedelta(days=2)
    out: dict[int, dict[str, Any]] = {}
    for security_id, day, candle in _candle_rows(db, security_ids, first, last):
        if day.isoformat() in wanted:
            out.setdefault(security_id, {})[day.isoformat()] = Bar(
                float(candle.open), float(candle.high), float(candle.low), float(candle.close)
            )
    return out


def _candle_rows(db: Any, security_ids: Sequence[int], first: date, last: date) -> Any:
    """(security_id, IST date, candle) for every stored daily candle of the given stocks from `first` up to (not
    including) `last`'s following midnight. Each candle's instrument is matched to its security through the identity
    read API; reads only."""
    from datetime import datetime

    from sqlalchemy import select

    from swing_trade_ml.core.market_session import IST
    from swing_trade_ml.db.models.market import Candle
    from swing_trade_ml.services.identity import consumers

    wanted_ids = set(security_ids)
    start = datetime.combine(first, datetime.min.time(), tzinfo=IST)
    end = datetime.combine(last, datetime.min.time(), tzinfo=IST)
    window = (Candle.interval == "day", Candle.ts >= start, Candle.ts < end)
    security_of: dict[int, int] = {}
    for instrument_id in db.scalars(select(Candle.instrument_id).where(*window).distinct()):
        security_id = consumers.security_for_instrument(db, instrument_id)
        if security_id in wanted_ids:
            security_of[instrument_id] = security_id
    if not security_of:
        return
    for candle in db.scalars(select(Candle).where(Candle.instrument_id.in_(set(security_of)), *window)):
        yield security_of[candle.instrument_id], candle.ts.astimezone(IST).date(), candle


def closes_from_candles(
    db: Any, security_ids: Sequence[int], first_session: str, last_session: str, *, lookback_days: int = 60
) -> dict[int, dict[date, float]]:
    """security_id -> IST date -> close, for the stored daily candles from `lookback_days` calendar days before
    `first_session` up to and including `last_session` (nothing later is ever read). History before the first session is
    what a trailing ranking needs. Reads only."""
    from datetime import timedelta

    first = date.fromisoformat(first_session) - timedelta(days=lookback_days)
    last = date.fromisoformat(last_session) + timedelta(days=1)  # the candle of `last_session` itself
    out: dict[int, dict[date, float]] = {}
    for security_id, day, candle in _candle_rows(db, security_ids, first, last):
        if day <= date.fromisoformat(last_session):
            out.setdefault(security_id, {})[day] = float(candle.close)
    return out


def records_by_id(db: Any, security_ids: Sequence[int]) -> dict[int, Any]:
    """record id -> the horizon record row, for the given stocks, every revision, read through the horizon records
    service. Used to trace a stored fill back to the record it was decided from."""
    from swing_trade_ml.services import horizon_records

    out: dict[int, Any] = {}
    for security_id in sorted(set(security_ids)):
        for row in horizon_records.records_for(db, security_id, view="all"):
            out[row.id] = row
    return out


def decisions_from_horizon_records(
    db: Any,
    rules: TradingRules,
    policy: Policy,
    *,
    models: Sequence[ModelRef | str] | None,
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
    for row in read_records(db, rules, models=models, since=since, until=until):
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
                security_id=row.security_id,
                symbol=symbol,
                score=float(row.score) if row.score is not None else 0.0,
                sector=(sectors or {}).get(row.security_id),
                block_reason=held_back,
                record_id=row.id,
            )
        )
    return out


def decisions_by_policy(
    db: Any,
    rules: TradingRules,
    *,
    models: Sequence[ModelRef | str] | None,
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
            db, rules, Policy.MODEL_ONLY, models=models, sectors=sectors, since=since, until=until
        ),
        Policy.BRAIN_FILTERED: decisions_from_horizon_records(
            db, rules, Policy.BRAIN_FILTERED, models=models, sectors=sectors, since=since, until=until
        ),
    }
