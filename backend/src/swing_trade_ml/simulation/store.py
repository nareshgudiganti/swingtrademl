# ruff: noqa: E501  (long plain-English docstrings)
"""Persist a finished simulation run (#321, #379) into the `sim_*` tables, idempotently, and read it back.

`persist_run` takes the ledgers `ledger.run_cohort` made and writes them under one `run_key`. The promises:

- IDEMPOTENT: writing the same run again changes nothing and duplicates nothing (one run per `run_key`, one portfolio
  per persona, one row per portfolio-session, one fill per portfolio-session-stock). It reports how many rows were
  created and how many already existed.
- NEVER REWRITES: a replay whose values differ from what is stored (a different fill, cash, rule version, set of
  not-applied rules) raises `ReplayMismatchError` and writes nothing at all (the whole call is one savepoint). History is
  never edited to match a new run; start a new `run_key` instead.
- CASH CANNOT BE NEGATIVE: checked here and by the database. Float noise below zero (within the ledger's own
  tolerance) is stored as 0.0; anything larger refuses the write.
- ONE RULE VERSION PER RUN: ledgers of another rule version are refused (`rules.MixedRuleVersions`).
- THE VALIDATION PORTFOLIO is stored with `counts_in_comparison = false` and is left out of every figure
  `performance_by_policy` returns (the same promise as `ledger.compare_by_policy`).
- BLOCKED PICKS and NOT-APPLIED RULES are stored in full, with their reasons.
- TRACEABLE: every fill, exit and block carries `security_id`, policy and rule version, and either the
  `horizon_record_id` it was decided from (model-only and Brain-filtered: required, checked, and no rule reference
  allowed) or, for momentum, which has no record, the `rule_ref` (rule name and version) that made the pick (required).
  `trace_fills` joins them back to the stock and the record or rule.

Synthetic data only: nothing here has a user or account, sends a message or places an order. Importing this module loads
no database code; everything database-related is imported when a function is called. It does NOT commit: the caller
owns the transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import CASH_TOLERANCE, PortfolioLedger
from swing_trade_ml.simulation.rules import TradingRules, require_one_version

SCHEMA_VERSION = 1


class StoreError(ValueError):
    """The run cannot be stored as given (negative cash, two validation portfolios, a mixed rule version, ...)."""


class ReplayMismatchError(StoreError):
    """A row already stored under this key has different values. Nothing was written."""


@dataclass(slots=True)
class StoreResult:
    run_id: int
    created: dict[str, int] = field(default_factory=dict)
    existing: dict[str, int] = field(default_factory=dict)

    def _count(self, bucket: dict[str, int], table: str) -> None:
        bucket[table] = bucket.get(table, 0) + 1

    def made(self, table: str) -> None:
        self._count(self.created, table)

    def found(self, table: str) -> None:
        self._count(self.existing, table)

    @property
    def total_created(self) -> int:
        return sum(self.created.values())


def _clean_cash(value: float, where: str) -> float:
    if value >= 0:
        return float(value)
    if value >= -CASH_TOLERANCE:
        return 0.0  # float noise only
    raise StoreError(f"{where}: cash is negative ({value})")


def _validate(run_key: str, ledgers: Mapping[str, PortfolioLedger], rules: TradingRules) -> None:
    if not run_key or len(run_key) > 64:
        raise StoreError("run_key must be 1 to 64 characters")
    if not ledgers:
        raise StoreError("no ledgers to store")
    require_one_version({rules.version, *(ledger.rule_version for ledger in ledgers.values())})
    for key, ledger in ledgers.items():
        if key != ledger.spec.persona_key:
            raise StoreError(f"ledger key {key!r} is not its persona {ledger.spec.persona_key!r}")
        require_one_version({rules.version, *(record.rule_version for record in ledger.records)})
    if sum(1 for ledger in ledgers.values() if not ledger.spec.counts_in_comparison) > 1:
        raise StoreError("a run holds at most one validation portfolio")
    for ledger in ledgers.values():
        for record in ledger.records:
            _clean_cash(record.cash, f"{ledger.spec.persona_key} {record.session}")
            for item in (*record.fills, *record.exits, *record.blocks, *record.positions):
                if not isinstance(item.security_id, int) or isinstance(item.security_id, bool):
                    raise StoreError(f"{ledger.spec.persona_key} {record.session}: a row has no security_id")
            for item in (*record.fills, *record.exits, *record.blocks):
                where = f"{ledger.spec.persona_key} {record.session}: a {ledger.spec.policy.value} row for security {item.security_id}"
                if ledger.spec.policy is Policy.MOMENTUM:
                    # momentum has no horizon record: it is traced to the rule and version that made the pick
                    if not item.rule_ref or len(item.rule_ref) > 64:
                        raise StoreError(f"{where} has no rule reference, so it could not be traced")
                else:
                    if item.record_id is None:
                        raise StoreError(f"{where} has no horizon record, so it could not be traced")
                    if item.rule_ref is not None:
                        raise StoreError(
                            f"{where} carries a rule reference, which only momentum rows may have"
                        )


def _check_records(db: Any, ledgers: Mapping[str, PortfolioLedger], rules: TradingRules) -> None:
    """Every row that names a horizon record must name one that exists, belongs to the same stock and is of this rule's
    horizon and kind. Read through the horizon records service. Refuses the whole run, before anything is written."""
    from swing_trade_ml.simulation import source

    horizon = int(rules.horizon_label.rstrip("D"))
    config_version = rules.version.split(":")[0]
    items = [
        (ledger.spec.persona_key, record.session, item)
        for ledger in ledgers.values()
        for record in ledger.records
        for item in (*record.fills, *record.exits, *record.blocks)
        if item.record_id is not None
    ]
    records = source.records_by_id(db, [item.security_id for _, _, item in items])
    for who, session, item in items:
        row = records.get(item.record_id)
        problem = None
        if row is None:
            problem = "does not exist for this stock"
        elif row.security_id != item.security_id:
            problem = f"belongs to security {row.security_id}"
        elif row.horizon_days != horizon:
            problem = f"is a {row.horizon_days}D record, this run is {horizon}D"
        elif row.research_only != rules.research_only or row.research_config_version != config_version:
            problem = "was made under another research configuration"
        if problem:
            raise StoreError(
                f"{who} {session}: horizon record {item.record_id} for security {item.security_id} {problem}"
            )


def _same(stored: tuple, new: tuple, what: str) -> None:
    if stored != new:
        raise ReplayMismatchError(f"{what} is already stored with other values: stored {stored}, new {new}")


def universe_fingerprint(ids: Sequence[int] | None) -> tuple[str | None, str | None]:
    """(the sorted ids as JSON text, its sha256), or (None, None) when no universe is declared."""
    import hashlib
    import json

    if ids is None:
        return None, None
    text = json.dumps(sorted(int(i) for i in ids), separators=(",", ":"))
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def persist_run(
    db: Any,
    run_key: str,
    ledgers: Mapping[str, PortfolioLedger],
    rules: TradingRules,
    *,
    momentum_universe: Sequence[int] | None = None,
    momentum_not_ranked: Mapping[int, str] | None = None,
) -> StoreResult:
    """Write the run (and everything under it) that is not stored yet; check what is. See the module docstring.

    `momentum_universe` (the security ids Momentum ranks) is stored on the run row with its sha256 so the run can be
    reproduced; a replay under another universe is refused like any other difference. `momentum_not_ranked` names the
    declared stocks that were not ranked and why; each is stored once per run (`sim_not_ranked`), and a replay that gives
    another set is refused."""
    from sqlalchemy import select

    from swing_trade_ml.db.models.simulation import (
        SimBlock,
        SimDay,
        SimExit,
        SimFill,
        SimMark,
        SimNotApplied,
        SimPortfolio,
        SimRun,
    )

    _validate(run_key, ledgers, rules)
    _check_records(db, ledgers, rules)
    horizon = int(rules.horizon_label.rstrip("D"))
    config_version = rules.version.split(":")[0]
    dates = sorted({date.fromisoformat(r.session) for ledger in ledgers.values() for r in ledger.records})
    first, last = (dates[0], dates[-1]) if dates else (None, None)
    policy_of = {key: ledger.spec.policy.value for key, ledger in ledgers.items()}
    out = StoreResult(run_id=0)

    with db.begin_nested():
        run = db.scalar(select(SimRun).where(SimRun.run_key == run_key))
        universe_text, universe_sha = universe_fingerprint(momentum_universe)
        wanted = (SCHEMA_VERSION, rules.version, config_version, rules.research_only, horizon, universe_sha)
        if run is None:
            run = SimRun(
                run_key=run_key,
                schema_version=SCHEMA_VERSION,
                rule_version=rules.version,
                research_config_version=config_version,
                research_only=rules.research_only,
                horizon_days=horizon,
                momentum_universe=universe_text,
                momentum_universe_sha256=universe_sha,
                synthetic=True,
                first_session=first,
                last_session=last,
            )
            db.add(run)
            db.flush()
            out.made("sim_runs")
        else:
            _same(
                (
                    run.schema_version,
                    run.rule_version,
                    run.research_config_version,
                    run.research_only,
                    run.horizon_days,
                    run.momentum_universe_sha256,
                ),
                wanted,
                f"run {run_key!r}",
            )
            if first is not None and (run.first_session is None or first < run.first_session):
                raise ReplayMismatchError(
                    f"run {run_key!r} would start earlier than it did ({first} < {run.first_session})"
                )
            if last is not None and (run.last_session is None or last > run.last_session):
                run.last_session = last  # a replay that carries on past the stored end only extends it
            out.found("sim_runs")
        out.run_id = run.id
        if momentum_not_ranked is not None:
            _store_not_ranked(db, run, momentum_not_ranked, out)

        stored_portfolios = {
            p.persona_key: p for p in db.scalars(select(SimPortfolio).where(SimPortfolio.run_id == run.id))
        }
        for key, ledger in ledgers.items():
            spec = ledger.spec
            values = (
                spec.setup_key,
                spec.policy.value,
                int(spec.balance_inr),
                int(spec.start_offset),
                bool(spec.counts_in_comparison),
                ledger.rule_version,
                ledger.research_only,
            )
            portfolio = stored_portfolios.get(key)
            if portfolio is None:
                portfolio = SimPortfolio(
                    run_id=run.id,
                    persona_key=key,
                    setup_key=values[0],
                    policy=values[1],
                    balance_inr=values[2],
                    start_offset=values[3],
                    counts_in_comparison=values[4],
                    rule_version=values[5],
                    research_only=values[6],
                    synthetic=True,
                )
                db.add(portfolio)
                db.flush()
                out.made("sim_portfolios")
            else:
                _same(
                    (
                        portfolio.setup_key,
                        portfolio.policy,
                        portfolio.balance_inr,
                        portfolio.start_offset,
                        portfolio.counts_in_comparison,
                        portfolio.rule_version,
                        portfolio.research_only,
                    ),
                    values,
                    f"portfolio {key}",
                )
                out.found("sim_portfolios")
            _store_not_applied(db, portfolio, ledger, out, SimNotApplied)
            _store_records(
                db, portfolio, ledger, policy_of[key], out, (SimDay, SimFill, SimExit, SimBlock, SimMark)
            )
        db.flush()
    return out


def _store_not_ranked(db: Any, run: Any, not_ranked: Mapping[int, str], out: StoreResult) -> None:
    from sqlalchemy import select

    from swing_trade_ml.db.models.simulation import SimNotRanked

    for security_id, reason in not_ranked.items():
        if (
            not isinstance(security_id, int)
            or isinstance(security_id, bool)
            or not reason
            or len(reason) > 255
        ):
            raise StoreError(
                f"a not-ranked stock needs a security id and a reason (got {security_id!r}, {reason!r})"
            )
    stored = {
        r.security_id: r.reason for r in db.scalars(select(SimNotRanked).where(SimNotRanked.run_id == run.id))
    }
    if stored and stored != dict(not_ranked):
        raise ReplayMismatchError(
            f"run {run.run_key!r}: the declared stocks that were not ranked differ from those stored "
            f"(stored {sorted(stored)}, now {sorted(not_ranked)})"
        )
    for security_id, reason in sorted(not_ranked.items()):
        if security_id in stored:
            out.found("sim_not_ranked")
        else:
            db.add(SimNotRanked(run_id=run.id, security_id=security_id, reason=reason))
            out.made("sim_not_ranked")


def _store_not_applied(
    db: Any, portfolio: Any, ledger: PortfolioLedger, out: StoreResult, model: Any
) -> None:
    from sqlalchemy import select

    have = set(db.scalars(select(model.rule_text).where(model.portfolio_id == portfolio.id)))
    want = set(ledger.not_applied)
    if have and have != want:
        raise ReplayMismatchError(
            f"portfolio {ledger.spec.persona_key}: the not-applied rules differ from those stored"
        )
    for text_ in sorted(want - have):
        db.add(model(portfolio_id=portfolio.id, rule_text=text_))
        out.made("sim_not_applied")
    for _ in have & want:
        out.found("sim_not_applied")


def _store_records(
    db: Any, portfolio: Any, ledger: PortfolioLedger, policy: str, out: StoreResult, models: tuple
) -> None:
    from sqlalchemy import select

    day_m, fill_m, exit_m, block_m, mark_m = models
    pid = portfolio.id
    days = {r.session_date: r for r in db.scalars(select(day_m).where(day_m.portfolio_id == pid))}
    fills = {
        (r.session_date, r.security_id): r
        for r in db.scalars(select(fill_m).where(fill_m.portfolio_id == pid))
    }
    exits = {
        (r.session_date, r.security_id, r.reason): r
        for r in db.scalars(select(exit_m).where(exit_m.portfolio_id == pid))
    }
    blocks = {
        (r.session_date, r.seq): r for r in db.scalars(select(block_m).where(block_m.portfolio_id == pid))
    }
    marks = {
        (r.session_date, r.security_id): r
        for r in db.scalars(select(mark_m).where(mark_m.portfolio_id == pid))
    }
    who = ledger.spec.persona_key
    seen: dict[str, set] = {name: set() for name in ("days", "fills", "exits", "blocks", "marks")}

    for record in ledger.records:
        day = date.fromisoformat(record.session)
        cash = _clean_cash(record.cash, f"{who} {record.session}")
        new_day = (
            cash,
            float(record.equity),
            bool(record.halted),
            record.market_mode,
            record.rule_version,
            record.research_only,
        )
        seen["days"].add(day)
        row = days.get(day)
        if row is None:
            db.add(
                day_m(
                    portfolio_id=pid,
                    session_date=day,
                    cash=cash,
                    equity=float(record.equity),
                    halted=bool(record.halted),
                    market_mode=record.market_mode,
                    rule_version=record.rule_version,
                    research_only=record.research_only,
                )
            )
            out.made("sim_days")
        else:
            _same(
                (row.cash, row.equity, row.halted, row.market_mode, row.rule_version, row.research_only),
                new_day,
                f"{who} {day} day",
            )
            out.found("sim_days")

        for f in record.fills:
            new = (
                f.symbol,
                f.record_id,
                f.rule_ref,
                policy,
                record.rule_version,
                f.qty,
                f.price,
                f.charges,
                f.cost,
            )
            seen["fills"].add((day, f.security_id))
            row = fills.get((day, f.security_id))
            if row is None:
                db.add(
                    fill_m(
                        portfolio_id=pid,
                        session_date=day,
                        security_id=f.security_id,
                        symbol=f.symbol,
                        horizon_record_id=f.record_id,
                        rule_ref=f.rule_ref,
                        policy=policy,
                        rule_version=record.rule_version,
                        qty=f.qty,
                        price=f.price,
                        charges=f.charges,
                        cost=f.cost,
                    )
                )
                out.made("sim_fills")
            else:
                stored = (
                    row.symbol,
                    row.horizon_record_id,
                    row.rule_ref,
                    row.policy,
                    row.rule_version,
                    row.qty,
                    row.price,
                    row.charges,
                    row.cost,
                )
                _same(stored, new, f"{who} {day} fill of security {f.security_id}")
                out.found("sim_fills")

        for x in record.exits:
            new = (
                x.symbol,
                x.record_id,
                x.rule_ref,
                policy,
                record.rule_version,
                x.qty,
                x.price,
                x.proceeds,
                x.stale,
            )
            seen["exits"].add((day, x.security_id, x.reason))
            row = exits.get((day, x.security_id, x.reason))
            if row is None:
                db.add(
                    exit_m(
                        portfolio_id=pid,
                        session_date=day,
                        security_id=x.security_id,
                        symbol=x.symbol,
                        horizon_record_id=x.record_id,
                        rule_ref=x.rule_ref,
                        policy=policy,
                        rule_version=record.rule_version,
                        reason=x.reason,
                        qty=x.qty,
                        price=x.price,
                        proceeds=x.proceeds,
                        stale=x.stale,
                    )
                )
                out.made("sim_exits")
            else:
                stored = (
                    row.symbol,
                    row.horizon_record_id,
                    row.rule_ref,
                    row.policy,
                    row.rule_version,
                    row.qty,
                    row.price,
                    row.proceeds,
                    row.stale,
                )
                _same(stored, new, f"{who} {day} {x.reason} exit of security {x.security_id}")
                out.found("sim_exits")

        for seq, b in enumerate(record.blocks):
            new = (b.security_id, b.symbol, b.record_id, b.rule_ref, policy, record.rule_version, b.reason)
            seen["blocks"].add((day, seq))
            row = blocks.get((day, seq))
            if row is None:
                db.add(
                    block_m(
                        portfolio_id=pid,
                        session_date=day,
                        seq=seq,
                        security_id=b.security_id,
                        symbol=b.symbol,
                        horizon_record_id=b.record_id,
                        rule_ref=b.rule_ref,
                        policy=policy,
                        rule_version=record.rule_version,
                        reason=b.reason,
                    )
                )
                out.made("sim_blocks")
            else:
                stored = (
                    row.security_id,
                    row.symbol,
                    row.horizon_record_id,
                    row.rule_ref,
                    row.policy,
                    row.rule_version,
                    row.reason,
                )
                _same(stored, new, f"{who} {day} blocked pick #{seq}")
                out.found("sim_blocks")

        for m in record.positions:
            new = (m.symbol, m.qty, m.mark, m.value, m.half_done, m.stale)
            seen["marks"].add((day, m.security_id))
            row = marks.get((day, m.security_id))
            if row is None:
                db.add(
                    mark_m(
                        portfolio_id=pid,
                        session_date=day,
                        security_id=m.security_id,
                        symbol=m.symbol,
                        qty=m.qty,
                        mark=m.mark,
                        value=m.value,
                        half_done=m.half_done,
                        stale=m.stale,
                    )
                )
                out.made("sim_marks")
            else:
                _same(
                    (row.symbol, row.qty, row.mark, row.value, row.half_done, row.stale),
                    new,
                    f"{who} {day} position of security {m.security_id}",
                )
                out.found("sim_marks")

    for name, stored in (
        ("days", days),
        ("fills", fills),
        ("exits", exits),
        ("blocks", blocks),
        ("marks", marks),
    ):
        left_out = set(stored) - seen[name]
        if left_out:
            raise ReplayMismatchError(
                f"{who}: the replay leaves out {len(left_out)} stored {name} (first: {sorted(left_out)[0]}); "
                "a replay must contain everything already stored"
            )


# ------------------------------------------------------------------------------------------------ reading back


def performance_by_policy(db: Any, run_key: str) -> dict[str, dict[str, float]]:
    """Per policy: portfolios, zero-trade portfolios, mean return, over the COMPARED portfolios only. The validation
    portfolio is in no denominator. Zero-trade portfolios count, at their own return (zero if they never moved)."""
    from sqlalchemy import func, select

    from swing_trade_ml.db.models.simulation import SimDay, SimFill, SimPortfolio, SimRun

    run = db.scalar(select(SimRun).where(SimRun.run_key == run_key))
    if run is None:
        return {}
    portfolios = list(
        db.scalars(
            select(SimPortfolio).where(
                SimPortfolio.run_id == run.id, SimPortfolio.counts_in_comparison.is_(True)
            )
        )
    )
    out: dict[str, dict[str, float]] = {}
    for p in portfolios:
        last = db.scalar(
            select(SimDay.equity)
            .where(SimDay.portfolio_id == p.id)
            .order_by(SimDay.session_date.desc())
            .limit(1)
        )
        equity = float(last) if last is not None else float(p.balance_inr)
        fills = db.scalar(select(func.count()).select_from(SimFill).where(SimFill.portfolio_id == p.id)) or 0
        row = out.setdefault(p.policy, {"portfolios": 0, "zero_trade_portfolios": 0, "return_sum": 0.0})
        row["portfolios"] += 1
        row["zero_trade_portfolios"] += 1 if fills == 0 else 0
        row["return_sum"] += equity / p.balance_inr - 1
    for row in out.values():
        row["mean_return"] = row.pop("return_sum") / row["portfolios"]
    return out


@dataclass(frozen=True, slots=True)
class TraceRow:
    """One simulated fill traced back: stock -> horizon record -> policy and rule version -> the fill."""

    persona_key: str
    session_date: date
    security_id: int
    symbol: str
    horizon_record_id: int | None
    record_decision: str | None
    record_horizon_days: int | None
    record_session: date | None
    record_config_version: str | None
    record_security_id: int | None
    policy: str
    rule_version: str
    qty: int
    price: float
    rule_ref: str | None = None  # momentum fills trace to the rule and version instead of a horizon record


def trace_fills(db: Any, run_key: str) -> list[TraceRow]:
    """Every stored fill of the run joined back to its stock and horizon record (read through the horizon records
    service), in persona, session, stock order."""
    from sqlalchemy import select

    from swing_trade_ml.db.models.simulation import SimFill, SimPortfolio, SimRun
    from swing_trade_ml.simulation import source

    query = (
        select(SimPortfolio.persona_key, SimFill)
        .join(SimPortfolio, SimPortfolio.id == SimFill.portfolio_id)
        .join(SimRun, SimRun.id == SimPortfolio.run_id)
        .where(SimRun.run_key == run_key)
        .order_by(SimPortfolio.persona_key, SimFill.session_date, SimFill.security_id)
    )
    pairs = list(db.execute(query))
    records = source.records_by_id(
        db, [fill.security_id for _, fill in pairs if fill.horizon_record_id is not None]
    )
    rows = []
    for persona_key, fill in pairs:
        rec = records.get(fill.horizon_record_id) if fill.horizon_record_id is not None else None
        rows.append(
            TraceRow(
                persona_key=persona_key,
                session_date=fill.session_date,
                security_id=fill.security_id,
                symbol=fill.symbol,
                horizon_record_id=fill.horizon_record_id,
                record_decision=None if rec is None else rec.decision,
                record_horizon_days=None if rec is None else rec.horizon_days,
                record_session=None if rec is None else rec.session_date,
                record_config_version=None if rec is None else rec.research_config_version,
                record_security_id=None if rec is None else rec.security_id,
                policy=fill.policy,
                rule_version=fill.rule_version,
                qty=fill.qty,
                price=fill.price,
                rule_ref=fill.rule_ref,
            )
        )
    return rows
