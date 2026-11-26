# ruff: noqa: E501  (long plain-English docstrings)
"""Run the research simulation from STORED data and persist it (#321, #379): the one caller of the simulation store.

    python -m swing_trade_ml.simulation.runner --run-key 5d-2026-12 --from 2026-12-01 --to 2026-12-31 \
        --model NAME[@VERSION] --momentum-universe FILE_OR_SYMBOLS [--dry-run]

`run_and_persist` does, in order:
  1. picks the trade rule by version (default "hz-rules-v1/5D", the approved 5D paper rule; "/" and ":" both work).
     A research version (10D, 15D) is refused unless the caller says `allow_research=True`;
  2. reads the STORED horizon records of those sessions through `services/horizon_records` (the product reader for a
     product rule: a research-only record never reaches 5D), first revision only, via `source.py`. The run NAMES its
     model(s) (`models`, no default): records of other models are ignored, and if more than one record is left for a
     stock and session the run is refused (`source.AmbiguousRecordsError`), never resolved by picking one;
  3. reads the stored daily candles for exactly the stocks those records name (matched by `security_id` through the
     identity read API, not by symbol alone), unless prices are passed in;
  4. runs the 99 compared + 1 validation portfolios (`cohorts.build_matrix`) through the ledger;
  5. writes them with `store.persist_run`, which is idempotent: a second call adds nothing, and a call with more
     sessions adds only the new days. A call whose past differs from what is stored is refused, and nothing is written.

What it does NOT do: place orders, send a message, run on a schedule, touch a user or an account, or commit (the
caller owns the transaction; the command line commits, or rolls back with --dry-run). Momentum's 33 portfolios trade on
the app's existing momentum rule (`simulation/momentum.py`: the 5 strongest 20-bar risers at each close) over Momentum's
own DECLARED universe (`momentum_universe`, required, no default, stored on the run row), each pick carrying its rule
reference in place of a horizon record; picks can instead be passed in.

The command line is admin-only and refuses to run unless DATABASE_URL names a database ending in `_test`, or the
explicit flag --allow-non-test-database is given (to be passed by the owner, later). There is no job and no schedule.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from swing_trade_ml.simulation.cohorts import PortfolioSpec, build_matrix
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import Bar, Candidate, run_cohort
from swing_trade_ml.simulation.rules import DEFINITIONS, TradingRules
from swing_trade_ml.simulation.source import ModelRef, named_models

DEFAULT_RULE_VERSION = "hz-rules-v1/5D"


class RunnerError(ValueError):
    """The run cannot start as asked (unknown or research rule without permission, bad sessions, refused database)."""


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: int
    run_key: str
    rule_version: str
    first_session: str
    last_session: str
    session_count: int
    portfolios: int
    compared: int
    validation: int
    picks: dict[str, int]  # policy -> number of picks decided over the window
    fills: int
    blocks: int
    zero_trade_portfolios: int
    created: dict[str, int]
    existing: dict[str, int]
    models: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)
    momentum_declared: int = 0  # stocks the run declared for Momentum
    momentum_ranked: int = 0  # of those, the ones with stored prices that the rule ranked
    momentum_not_ranked: dict[int, str] = field(default_factory=dict)  # security id -> why it was not ranked

    @property
    def rows_created(self) -> int:
        return sum(self.created.values())

    def summary(self) -> str:
        made = ", ".join(f"{k}={v}" for k, v in sorted(self.created.items())) or "nothing new"
        lines = [
            f"run {self.run_key!r} ({self.rule_version}), {self.session_count} sessions {self.first_session} to {self.last_session}",
            f"models named: {', '.join(self.models)}",
            f"portfolios: {self.portfolios} ({self.compared} compared, {self.validation} validation); {self.zero_trade_portfolios} made no trade",
            f"momentum universe: {self.momentum_ranked} of {self.momentum_declared} declared stocks ranked",
            f"picks by policy: {self.picks}; fills: {self.fills}; blocked picks: {self.blocks}",
            f"rows created: {made}",
            *self.notes,
        ]
        return "\n".join(lines)


def declared_universe(ids: Sequence[int] | None) -> tuple[int, ...]:
    """The momentum universe as sorted, distinct permanent security ids. Missing, empty, repeated or non-integer ids are
    refused: the universe is part of the run spec and is never guessed."""
    if not ids:
        raise RunnerError("the run must declare Momentum's universe (security ids); there is no default")
    if any(not isinstance(i, int) or isinstance(i, bool) or i <= 0 for i in ids):
        raise RunnerError("the momentum universe must be positive integer security ids")
    if len(set(ids)) != len(ids):
        raise RunnerError("the momentum universe lists a stock twice")
    return tuple(sorted(ids))


def resolve_universe(db: Any, spec: str, on: date) -> tuple[int, ...]:
    """A universe given as a file (symbols separated by commas, spaces or lines; `#` starts a comment) or as a comma list
    of symbols, resolved to security ids on `on` through the identity service. An unknown or ambiguous symbol, or two
    symbols of one stock, refuses the run: nothing is guessed."""
    from pathlib import Path

    from swing_trade_ml.simulation import source

    path = Path(spec)
    text = path.read_text(encoding="utf-8") if path.is_file() else spec
    symbols = [
        token for line in text.splitlines() for token in line.split("#", 1)[0].replace(",", " ").split()
    ]
    if not symbols:
        raise RunnerError("the momentum universe names no symbol")
    if len({s.upper() for s in symbols}) != len(symbols):
        raise RunnerError("the momentum universe lists a symbol twice")
    try:
        resolved = source.security_ids_for(db, symbols, on)
    except source.UnknownStockError as exc:
        raise RunnerError(f"momentum universe refused: {exc}") from exc
    return declared_universe(list(resolved.values()))


def rules_for(rule_version: str, *, allow_research: bool = False) -> TradingRules:
    """The trade rule of a version such as "hz-rules-v1/5D" (or "hz-rules-v1:5D"). Unknown versions and research
    versions without permission are refused."""
    name = rule_version.strip().replace("/", ":")
    if name not in DEFINITIONS:
        raise RunnerError(f"unknown rule version {rule_version!r}; known: {', '.join(sorted(DEFINITIONS))}")
    rules = TradingRules.for_horizon(int(DEFINITIONS[name][4].rstrip("D")))
    if rules.research_only and not allow_research:
        raise RunnerError(f"{rules.version} is research-only; pass allow_research=True to run it on purpose")
    return rules


def _check_sessions(sessions: Sequence[str]) -> list[date]:
    from swing_trade_ml.core.market_session import is_trading_day

    if not sessions:
        raise RunnerError("no sessions given")
    try:
        days = [date.fromisoformat(s) for s in sessions]
    except ValueError as exc:
        raise RunnerError("sessions must be ISO dates (YYYY-MM-DD)") from exc
    if any(b <= a for a, b in pairwise(days)):
        raise RunnerError("sessions must be in strictly increasing order")
    if not all(is_trading_day(d) for d in days):
        raise RunnerError("every session must be an NSE trading day")
    return days


def trading_sessions(start: date, end: date) -> list[str]:
    """The NSE trading days from `start` to `end`, inclusive, as ISO dates."""
    from swing_trade_ml.core.market_session import is_trading_day

    out, day = [], start
    while day <= end:
        if is_trading_day(day):
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def run_and_persist(
    db: Any,
    *,
    run_key: str,
    sessions: Sequence[str],
    models: Sequence[ModelRef | str],
    momentum_universe: Sequence[int],
    rule_version: str = DEFAULT_RULE_VERSION,
    allow_research: bool = False,
    bars: Mapping[int, Mapping[str, Bar]] | None = None,
    momentum: Mapping[str, Sequence[Candidate]] | None = None,
    sectors: Mapping[int, str] | None = None,
    specs: Sequence[PortfolioSpec] | None = None,
) -> RunReport:
    """Read stored records (and candles), run the cohort, persist it. See the module docstring. Does not commit.

    Momentum's picks come from the app's existing momentum rule over stored closes (`simulation.momentum`), ranking
    `momentum_universe`: the stocks Momentum is declared to rank, as permanent security ids. It has no default (it is
    never "whatever the models scored"), it is stored on the run row, and a replay with another universe is refused. If
    `momentum` picks are passed in, they are used as they are and the universe is only recorded."""
    from swing_trade_ml.simulation import momentum as momentum_rule
    from swing_trade_ml.simulation import source, store

    _check_sessions(sessions)
    rules = rules_for(rule_version, allow_research=allow_research)
    specs = tuple(specs) if specs is not None else build_matrix()
    universe = declared_universe(momentum_universe)
    ranked_count, not_ranked = 0, {}
    if momentum is None:
        closes = source.closes_from_candles(db, universe, sessions[0], sessions[-1])
        last_day = date.fromisoformat(sessions[-1])
        symbols = {sid: source.symbol_on(db, sid, last_day) or "" for sid in closes}
        ranked_result = momentum_rule.momentum_result(closes, sessions, symbols=symbols, universe=universe)
        momentum, ranked_count, not_ranked = (
            ranked_result.decisions,
            len(ranked_result.ranked),
            dict(ranked_result.not_ranked),
        )
    else:
        # Picks passed in must carry a reference of their own. Only the momentum rule's own picks (made just above) may
        # carry the rule's reference, so a caller cannot dress a list up as the app's momentum rule.
        official = momentum_rule.rule_ref()
        for picks in momentum.values():
            for pick in picks:
                if not pick.rule_ref or not pick.rule_ref.strip() or pick.rule_ref == official:
                    raise RunnerError(
                        f"a pick passed in must carry its own rule reference, and not {official!r}, which only the "
                        "app's momentum rule may use"
                    )
    decisions = source.decisions_by_policy(
        db, rules, models=models, momentum=momentum, sectors=sectors, sessions=sessions
    )
    if bars is None:
        wanted = {
            c.security_id for by_session in decisions.values() for picks in by_session.values() for c in picks
        }
        bars = source.bars_from_candles(db, sorted(wanted), sessions)
    ledgers = run_cohort(specs, sessions, bars, decisions, rules)
    result = store.persist_run(
        db,
        run_key,
        ledgers,
        rules,
        momentum_universe=universe,
        momentum_not_ranked=not_ranked if ranked_count or not_ranked else None,
    )

    notes = []
    if ranked_count or not_ranked:
        reasons = ", ".join(sorted(set(not_ranked.values())))
        notes.append(
            f"momentum: {momentum_rule.rule_ref()} ranked {ranked_count} of {len(universe)} declared stocks "
            "(the app's existing momentum rule, closes up to each decision day only)"
            + (f"; {len(not_ranked)} not ranked: {reasons}" if not_ranked else "")
        )
    if not any(decisions[Policy.MOMENTUM].values()):
        notes.append(
            "momentum: the rule made no picks in these sessions (too little stored candle history, or no stocks); "
            "its portfolios are still stored"
        )
    if not decisions[Policy.MODEL_ONLY]:
        notes.append(f"no stored {rules.horizon_label} horizon records in these sessions: nothing was picked")
    return RunReport(
        run_id=result.run_id,
        run_key=run_key,
        rule_version=rules.version,
        first_session=sessions[0],
        last_session=sessions[-1],
        session_count=len(sessions),
        portfolios=len(ledgers),
        compared=sum(1 for s in specs if s.counts_in_comparison),
        validation=sum(1 for s in specs if not s.counts_in_comparison),
        picks={
            policy.value: sum(len(p) for p in by_session.values()) for policy, by_session in decisions.items()
        },
        fills=sum(ledger.fill_count for ledger in ledgers.values()),
        blocks=sum(ledger.block_count for ledger in ledgers.values()),
        zero_trade_portfolios=sum(1 for ledger in ledgers.values() if ledger.fill_count == 0),
        created=dict(result.created),
        existing=dict(result.existing),
        models=tuple(str(m) for m in named_models(models)),
        notes=tuple(notes),
        momentum_declared=len(universe),
        momentum_ranked=ranked_count,
        momentum_not_ranked=not_ranked,
    )


# ------------------------------------------------------------------------------------------- admin command line


def check_database(url: str | None, *, allow: bool = False) -> None:
    """Refuse a database whose name does not end in `_test`, unless the explicit allow flag is given."""
    from sqlalchemy.engine import make_url

    if allow:
        return
    try:
        name = make_url(url or "").database or ""
    except Exception as exc:  # a malformed URL is a refusal, whatever it raised
        raise RunnerError("DATABASE_URL could not be read; refusing to run") from exc
    if not name.endswith("_test"):
        raise RunnerError(
            f"refusing to run: the database name {name!r} does not end in '_test' "
            "(the owner can pass --allow-non-test-database later)"
        )
    # A *_test name on a remote host is not enough: use the repo's guard (local host, test database).
    from swing_trade_ml.core.db_guard import assert_local_test_database

    try:
        assert_local_test_database(url or "")
    except RuntimeError as exc:  # the guard's refusal; its message never echoes the URL
        raise RunnerError(f"refusing to run: {exc}") from None


def parse_model(text: str) -> ModelRef:
    """`NAME` or `NAME@VERSION` from the command line."""
    name, _, version = text.partition("@")
    if not name.strip():
        raise RunnerError("a model name must not be blank")
    return ModelRef(name.strip(), version.strip() or None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m swing_trade_ml.simulation.runner",
        description="Admin only: run the 99+1 research simulation from stored horizon records and store it.",
    )
    parser.add_argument("--run-key", required=True, help="the name of this run (up to 64 characters)")
    parser.add_argument(
        "--from", dest="start", required=True, type=date.fromisoformat, help="first session (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--to", dest="end", required=True, type=date.fromisoformat, help="last session (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--model",
        dest="models",
        action="append",
        required=True,
        help="a model whose records decide the picks, NAME or NAME@VERSION; repeat for several. There is no default",
    )
    parser.add_argument(
        "--momentum-universe",
        required=True,
        help="the stocks Momentum ranks: a file of symbols, or a comma list; resolved on the first session, an unknown "
        "symbol refuses the run. There is no default",
    )
    parser.add_argument(
        "--rule", default=DEFAULT_RULE_VERSION, help=f"rule version (default {DEFAULT_RULE_VERSION})"
    )
    parser.add_argument("--allow-research", action="store_true", help="allow a research-only rule (10D, 15D)")
    parser.add_argument(
        "--dry-run", action="store_true", help="run and report, then roll back: nothing is kept"
    )
    parser.add_argument(
        "--allow-non-test-database",
        action="store_true",
        help="run against a database that is not named *_test (owner only, later)",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, database_url: str | None = None) -> int:
    args = _parser().parse_args(argv)
    url = database_url or os.environ.get("DATABASE_URL")
    if url is None:
        from swing_trade_ml.core.config import settings

        url = settings.DATABASE_URL
    try:
        check_database(url, allow=args.allow_non_test_database)
        models = [parse_model(text) for text in args.models]
        if args.end < args.start:
            raise RunnerError("--to is before --from")
        sessions = trading_sessions(args.start, args.end)
        from swing_trade_ml.db.session import SessionLocal

        db = SessionLocal()
        try:
            universe = resolve_universe(
                db, args.momentum_universe, date.fromisoformat(sessions[0]) if sessions else args.start
            )
            report = run_and_persist(
                db,
                run_key=args.run_key,
                sessions=sessions,
                models=models,
                momentum_universe=universe,
                rule_version=args.rule,
                allow_research=args.allow_research,
            )
            if args.dry_run:
                db.rollback()
            else:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
    except (RunnerError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(report.summary())
    print("dry run: nothing was kept" if args.dry_run else "stored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
