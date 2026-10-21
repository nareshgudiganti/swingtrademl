# backend/src/swing_trade_ml/brain/pit_replay.py
"""Point-in-time portfolio replay and same-rules comparison (ps12, read-only evidence tool).

A normal replay asks the brain about a past day, but its risk gate (M07) and the account-reading modules
(M03, M14, M15, M08's holding reviews) only know today's account, so no replayed idea is ever approved.
Here the brain sees a **simulated account as it stood at that day's close**:

- one account (`portfolio_sim.Book`) starts with `CAPITAL` in cash on the first replayed day;
- each day the brain is run after the close, reading that account through a `PointInTimeReader` (a
  `DatedReader` bounded by the day, like every replay) and judging its ideas with a point-in-time risk
  gate: M07's own candidates, market-mode policy and batch allocator, with the account and the entry
  check taken from the simulated account instead of the live database;
- the TRADE words become buys at the **next trading day's open** (slipped fill, charges), and the same
  account rules as `portfolio_sim.simulate` run them: +8% / -4%, half out at +5%, 15 trading days, the
  capital ladder's limits, the 25% sector cap / one stock per sector, the 15% drawdown halt, at most 5 new
  buys a day (2 when the banner is DEFENSIVE, none on NO NEW TRADES).

Nothing live changes: no frozen file is edited (the point-in-time pieces are new classes passed in through
the registry and the reader), nothing is written to the database and nothing counts toward the 30-idea
gate. The live risk gate and the live reader behave exactly as before.

Same-rules comparison on identical days, capital, exits, costs and limits:

- brain: the whole brain, on the point-in-time account.
- rules_only: the whole brain, but the model's opinion is replaced by one flat score at the buy level for
  every stock with a price, so only the brain's rules, modifiers and risk gate decide. (With no model
  opinion at all the brain can never say TRADE, `opinions.py`, so that variant would be cash.)
- model_only: the as-of model alone: every stock scoring at or above the buy level, best first; only the
  account rules apply (no banner, no brain rules).
- random: as many random stocks a day as the brain bought, from the same stock list, with the brain's
  banner; `DRAWS` seeded accounts.
- nifty: the whole capital in NIFTY 50 at the first fill day's open, sold at the last day's close.
- cash: 0%.

All local data is development data (EXPOSURE-LEDGER.md): these are diagnostics, not proof.

Run (backend/): python -m swing_trade_ml.brain.pit_replay --from 2026-07-13 --to 2026-08-14
    --asof-model swing_classifier_asof_20260710
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.brain import constitution
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.fallbacks import FALLBACKS
from swing_trade_ml.brain.market_mode import effective_mode
from swing_trade_ml.brain.module import REGISTRY, STEPS_FOR, ModuleRegistry, resolve_mode
from swing_trade_ml.brain.modules.m07_risk.allocator import Account, Candidate, CheckResult, Policy, allocate
from swing_trade_ml.brain.modules.m07_risk.module import (
    DEFENSIVE_MAX_NEW,
    DEFENSIVE_SIZE_FACTOR,
    RiskGate,
    candidates_from,
)
from swing_trade_ml.brain.portfolio_sim import Book, Pick, PortfolioResult, random_picks
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.replay_scoring import HORIZON_BARS
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.services.limits import limits_for

log = get_logger(__name__)

PROTOCOL_ID = "ps12-pit-replay-v1"
CAPITAL = 979_792.0  # the paper trial's clean starting balance (2026-09-28)
SETTLE_BARS = HORIZON_BARS  # trading days the account keeps running after the last decision, no new buys
DRAWS = 200  # random accounts (evidence-defs-v1: 200 seeded runs)
SEED = 12
NO_ROOM_LIMIT = 1e15  # the market-conditions ceiling is not simulated (as in portfolio_sim)
BRAIN_VARIANTS = ("brain", "rules_only")
VARIANTS = ("brain", "rules_only", "model_only", "random", "nifty", "cash")
FLAT_LABEL = "rules-only replay: the same flat score for every stock"

# The replay account's refusal reasons, in the words of v1's check_entry rule codes.
_RULES = {
    "already_held": ("ALREADY_OPEN", "Already held in the replay account."),
    "no_free_slot": ("POSITION_LIMIT", "Every position slot of the replay account is in use."),
    "no_price": ("NO_PRICE", "No price for this stock."),
    "sector_cap": ("SECTOR_CAP", "The replay account already holds a stock in this sector."),
    "too_small_or_no_cash": (
        "MIN_POSITION",
        "The replay account's cash, sector room or size limits leave less than the minimum position.",
    ),
}


# --- the simulated account, as the brain reads it ---------------------------------------------------


class SimAccount:
    """The replay account at the last stepped day's close, in the shapes the brain reads."""

    def __init__(self, book: Book, buckets: Callable[[str], str | None]) -> None:
        self.book = book
        self.bucket_of = buckets

    @property
    def as_of(self) -> date | None:
        return self.book.last_day

    def holdings(self) -> tuple[c.Holding, ...]:
        return tuple(
            c.Holding(
                symbol=p.symbol,
                qty=int(p.qty),
                avg_price=float(p.fill),
                stop=float(p.stop_px),
                target=float(p.target_px),
                scaled_out=p.half_done,
                opened_on=p.entry_day,
            )
            for p in sorted(self.book.open_, key=lambda p: p.symbol)
        )

    def numbers(self) -> dict:
        """What `DatedReader.portfolio_numbers` gives a live run: value, cash, drawdown, free slots."""
        b = self.book
        limits = limits_for(b.equity)
        return {
            "value": b.equity,
            "cash": b.cash,
            "drawdown_pct": b.drawdown(),
            "free_slots": max(0, limits.max_positions - len(b.open_)),
        }

    def risk_account(self) -> Account:
        """M07's account (allocator.Account), from the replay account instead of the database."""
        b = self.book
        limits = limits_for(b.equity)
        exposure: dict[str, float] = {}
        for p in b.open_:
            bucket = self.bucket_of(p.symbol)
            if bucket is not None:
                exposure[bucket] = exposure.get(bucket, 0.0) + p.qty * p.last_close
        return Account(
            portfolio_value=b.equity,
            cash=b.cash,
            free_slots=max(0, limits.max_positions - len(b.open_)),
            min_position_inr=limits.min_position_inr,
            sector_rule=limits.sector_rule,
            sector_cap_pct=limits.sector_cap_pct,
            sector_exposure=exposure,
            deploy_room=NO_ROOM_LIMIT,
        )

    def check(self, cand: Candidate, cash_left: float) -> CheckResult:
        """The entry check M07 asks for each candidate (v1's check_entry live): the replay account's own
        buy rules (`Book.refusal`) at the day's close, plus the 15% drawdown halt. Sized as a NORMAL day;
        the allocator halves it on a DEFENSIVE day, as it does live."""
        b = self.book
        if b.halted_now():
            return CheckResult(
                allowed=False,
                rule="DRAWDOWN",
                reason=f"The replay account is {b.drawdown():.0%} below its peak, past the 15% safety limit.",
            )
        limits = limits_for(b.equity)
        why, qty, _fill = b.refusal(cand.symbol, cand.bucket, cand.price, "NORMAL", limits, cash=cash_left)
        if why is not None:
            rule, reason = _RULES[why]
            return CheckResult(allowed=False, rule=rule, reason=reason)
        return CheckResult(
            allowed=True, qty=qty, reason="Sized by the replay account's rules", amount_inr=qty * cand.price
        )


class PointInTimeReader(DatedReader):
    """A replay reader (live=False, every read bounded by as_of) whose account answers come from the
    simulated account. `flat_score` replaces the model's score for the rules-only variant."""

    def __init__(self, db, as_of, account: SimAccount, *, asof_model=None, flat_score: float | None = None):
        super().__init__(db, as_of=as_of, live=False, asof_model=asof_model)
        self.pit = account
        self.flat_score = flat_score

    def portfolio_numbers(self, book: str) -> dict | None:
        return self.pit.numbers()

    def holdings(self, book: str) -> tuple[c.Holding, ...]:
        return self.pit.holdings()

    def system_state(self) -> c.SystemState:
        # The owner's pause switch is "now" data; the replay account has its own drawdown halt.
        return c.SystemState()

    def model_probability(self, symbol: str):
        if self.flat_score is None:
            return super().model_probability(symbol)
        if self.last_close(symbol) is None:
            return None
        return self.flat_score, self.flat_score, FLAT_LABEL


class PointInTimeRiskGate(RiskGate):
    """M07 with the account and the entry check taken from the replay account. Same manifest (mandatory,
    id M07), same candidates, market-mode policy and allocator. Without a replay account (any live run,
    any ordinary replay) it is exactly M07. Never registered globally: only `pit_registry` uses it."""

    def run(self, view) -> c.Contribution:
        pit = getattr(view.reader, "pit", None)
        if view.request.live or pit is None:
            return super().run(view)
        candidates, refusals = candidates_from(view)
        policy = Policy(
            mode=effective_mode(view.market, view.situations)[0],
            defensive_size_factor=DEFENSIVE_SIZE_FACTOR,
            defensive_max_new=DEFENSIVE_MAX_NEW,
            pairs=frozenset(
                frozenset((a, b))
                for a, b, _ in (view.portfolio.correlated if view.portfolio is not None else ())
            ),
        )
        from swing_trade_ml.services import risk

        verdicts = allocate(candidates, pit.risk_account(), pit.check, policy, risk.buy_cost)
        return c.Contribution(verdicts=tuple(refusals + verdicts))


def pit_registry(base: ModuleRegistry = REGISTRY) -> ModuleRegistry:
    """`base` with M07 swapped for the point-in-time risk gate (if M07 is in it at all)."""
    reg = ModuleRegistry()
    for cls in base.all():
        reg.register(PointInTimeRiskGate if cls.manifest.id == "M07" else cls)
    return reg


def execute_with_holdings(request: c.RunRequest, reader, registry: ModuleRegistry, modes) -> BrainContext:
    """`runner.execute`, except that the run starts with the reader's holdings. `BrainContext.start`
    reads holdings for live runs only, so a replay would otherwise never see the replay account's
    positions. The steps, fallbacks and constitution are the runner's own (tested to match it)."""
    from swing_trade_ml.brain.runner import _ms, _run_module

    ctx = BrainContext(request=request, reader=reader, holdings=tuple(reader.holdings(request.book)))
    for step in STEPS_FOR[request.kind]:
        used = False
        for cls in registry.for_step(step):
            used = _run_module(ctx, cls, resolve_mode(cls.manifest, modes.get(cls.manifest.id))) or used
        started = time.perf_counter()
        ctx.merge(FALLBACKS[step](ctx))
        if not used:
            ctx.trace.append(
                c.TraceEvent(
                    step=step.value,
                    module_id="fallback",
                    status="fallback",
                    reason="no module answered",
                    ms=_ms(started),
                )
            )
    constitution.enforce(ctx)
    return ctx


# --- one replayed day -------------------------------------------------------------------------------


@dataclass
class DayRecord:
    day: date
    banner: str
    picks: list[tuple[str, float]]  # TRADE words in the order the risk gate approved them, with a sort key
    ideas: list[tuple[str, str, str | None]]  # every idea: (symbol, final word, word it was lowered from)
    holding_words: dict[str, int] = field(default_factory=dict)
    seen: dict = field(default_factory=dict)  # the account the brain saw (for the no-look-ahead check)

    def to_json(self) -> dict:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> DayRecord:
        return cls(
            day=date.fromisoformat(d["day"]),
            banner=d["banner"],
            picks=[tuple(p) for p in d["picks"]],
            ideas=[tuple(i) for i in d["ideas"]],
            holding_words=d.get("holding_words", {}),
            seen=d.get("seen", {}),
        )


def record_from(day: date, ctx: BrainContext, account: SimAccount) -> DayRecord:
    approved = [s for s, v in ctx.verdicts.items() if v.allowed]
    trades = {s for s, d in ctx.decisions.items() if d.kind == "idea" and d.word is c.IdeaWord.TRADE}
    order = [s for s in approved if s in trades] + sorted(trades - set(approved))
    n = len(order)
    return DayRecord(
        day=day,
        banner=ctx.banner.mode.value if ctx.banner else "NO_NEW_TRADES",
        picks=[(s, (n - i) / max(n, 1)) for i, s in enumerate(order)],
        ideas=[
            (d.symbol, d.word.value, d.downgraded_from.value if d.downgraded_from else None)
            for d in ctx.decisions.values()
            if d.kind == "idea"
        ],
        holding_words=dict(Counter(d.word.value for d in ctx.decisions.values() if d.kind == "holding")),
        seen={
            "as_of": account.as_of.isoformat() if account.as_of else None,
            **{k: round(v, 2) if isinstance(v, float) else v for k, v in account.numbers().items()},
            "held": [h.symbol for h in account.holdings()],
        },
    )


def run_brain_day(
    db: Session,
    day: date,
    account: SimAccount,
    *,
    registry: ModuleRegistry,
    modes: dict,
    asof_model,
    flat_score: float | None,
    release: bool = True,
) -> DayRecord:
    from swing_trade_ml.brain.replay_week import as_of_end_of_ist_day

    as_of = as_of_end_of_ist_day(day)
    reader = PointInTimeReader(db, as_of, account, asof_model=asof_model, flat_score=flat_score)
    request = c.RunRequest(
        run_id=f"pit-{day.isoformat()}", kind="nightly", as_of=as_of, universe=reader.universe(), live=False
    )
    savepoint = db.begin_nested()  # read-only: anything a module might have written is undone
    try:
        ctx = execute_with_holdings(request, reader, registry, modes)
    finally:
        savepoint.rollback()
        if release:
            db.rollback()  # never leave a transaction open between days (tests keep theirs)
    return record_from(day, ctx, account)


# --- a whole variant --------------------------------------------------------------------------------


def _load(path: Path | None) -> dict[date, DayRecord]:
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {date.fromisoformat(k): DayRecord.from_json(v) for k, v in raw.items()}


def _save(path: Path | None, records: dict[date, DayRecord]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({k.isoformat(): v.to_json() for k, v in sorted(records.items())}), encoding="utf-8"
    )
    tmp.replace(path)


def run_account(
    bars: dict[str, pd.DataFrame],
    sim_days: Sequence[date],
    decision_days: Sequence[date],
    decide: Callable[[date, SimAccount], DayRecord],
    *,
    capital: float = CAPITAL,
    buckets: Callable[[str], str | None],
    checkpoint: Path | None = None,
) -> tuple[PortfolioResult, dict[date, DayRecord]]:
    """Step one account through `sim_days`; after each decision day's close, ask `decide` (the brain on
    the account as it stands) and buy its picks at the next day's open. Each day's record is saved as
    soon as it exists; on a restart the account is rebuilt from the saved picks (it is deterministic)."""
    book = Book(bars, capital=capital)
    account = SimAccount(book, buckets)
    records = _load(checkpoint)
    wanted = set(decision_days)
    picks: list[Pick] = []
    mode = "NORMAL"
    for day in sim_days:
        book.step(day, picks, mode)
        if day not in wanted:
            picks, mode = [], "NORMAL"
            continue
        rec = records.get(day)
        if rec is None:
            rec = decide(day, account)
            records[day] = rec
            _save(checkpoint, records)
        picks = [Pick(day, s, score, buckets(s)) for s, score in rec.picks]
        mode = rec.banner
    return book.result(), records


def account_from_picks(
    picks: Sequence[Pick],
    bars: dict[str, pd.DataFrame],
    sim_days: Sequence[date],
    modes: dict[date, str] | None,
    capital: float = CAPITAL,
) -> PortfolioResult:
    """The same account for picks that do not depend on the account (model-only, random)."""
    from swing_trade_ml.brain.portfolio_sim import simulate

    used = {p.symbol for p in picks}
    return simulate(
        picks, {s: df for s, df in bars.items() if s in used}, list(sim_days), capital=capital, modes=modes
    )


def model_only_picks(
    scores: dict[str, dict[date, float]], decision_days: Sequence[date], level: float, buckets
) -> list[Pick]:
    """Every stock at or above the buy level, each decision day; the account takes the best 5."""
    return [
        Pick(d, s, sc[d], buckets(s))
        for d in decision_days
        for s, sc in sorted(scores.items())
        if d in sc and sc[d] >= level
    ]


def random_accounts(
    pool: dict[date, list[str]],
    per_day: dict[date, int],
    bars: dict[str, pd.DataFrame],
    sim_days: Sequence[date],
    modes: dict[date, str],
    buckets,
    *,
    draws: int = DRAWS,
    seed: int = SEED,
    capital: float = CAPITAL,
) -> list[PortfolioResult]:
    """`draws` accounts, each with the same number of random stocks a day as the brain bought (seed + n)."""
    table = {s: buckets(s) for syms in pool.values() for s in syms}
    return [
        account_from_picks(random_picks(pool, per_day, seed + n, table), bars, sim_days, modes, capital)
        for n in range(draws)
    ]


def row(res: PortfolioResult, records: dict[date, DayRecord] | None = None) -> dict:
    """The comparison numbers for one account."""
    closed = res.closed
    nets = [t.net_return for t in closed]
    banners = Counter(r.banner for r in (records or {}).values())
    return {
        "final_equity": round(res.end_equity, 2),
        "return": res.total_return,
        "max_drawdown": res.max_drawdown,
        "trades": len(closed),
        "still_open": res.still_open,
        "hit_rate_target_first": sum(t.status == "target" for t in closed) / len(closed) if closed else None,
        "avg_net_per_trade": sum(nets) / len(nets) if nets else None,
        "exits": dict(Counter(t.status for t in closed)),
        "halted_days": res.halted_days,
        "days_no_new_trades": banners.get("NO_NEW_TRADES", 0) if records is not None else None,
        "days_defensive": banners.get("DEFENSIVE", 0) if records is not None else None,
        "skipped": dict(res.skipped),
    }


def spread(values: list[float | None]) -> dict:
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return {"median": None, "p5": None, "p95": None}
    return {
        "median": statistics.median(xs),
        "p5": xs[int(0.05 * (len(xs) - 1))],
        "p95": xs[int(0.95 * (len(xs) - 1))],
    }


def random_row(results: list[PortfolioResult], records: dict[date, DayRecord]) -> dict:
    rows = [row(r) for r in results]
    banners = Counter(r.banner for r in records.values())
    out = {"draws": len(rows)}
    for key in (
        "final_equity",
        "return",
        "max_drawdown",
        "trades",
        "hit_rate_target_first",
        "avg_net_per_trade",
    ):
        out[key] = spread([r[key] for r in rows])
    out["days_no_new_trades"] = banners.get("NO_NEW_TRADES", 0)
    out["days_defensive"] = banners.get("DEFENSIVE", 0)
    return out


def nifty_row(
    index_bars: pd.DataFrame | None, sim_days: Sequence[date], capital: float = CAPITAL
) -> dict | None:
    """Whole capital in NIFTY 50 at the first fill day's open (the day after the first decision), sold at
    the last day's close, one round trip of the stock cost model (baselines.nifty_hold)."""
    from swing_trade_ml.services.brain_observatory.baselines import nifty_hold

    held = nifty_hold(index_bars, list(sim_days[1:]), capital)
    if held is None:
        return None
    return {
        "final_equity": round(capital * (1 + held["final_net_return"]), 2),
        "return": held["final_net_return"],
        "max_drawdown": held["max_drawdown"],
        "trades": 1,
    }


CASH_ROW = {"final_equity": CAPITAL, "return": 0.0, "max_drawdown": 0.0, "trades": 0}


def same_universe_pool(
    universes: dict[date, Sequence[str]], bars: dict[str, pd.DataFrame]
) -> dict[date, list[str]]:
    """Stocks of each day's list that have a bar that day (the stocks the brain could price)."""
    days_of = {s: set(df["day"]) for s, df in bars.items()}
    return {d: sorted(s for s in syms if d in days_of.get(s, ())) for d, syms in universes.items()}


# --- the whole comparison ---------------------------------------------------------------------------


def prepare(db: Session, decision_days: Sequence[date], upto: date):
    """Each decision day's stock list, every listed stock's bars (to `upto`), NIFTY's bars and the account's
    days: every trading day from the first decision day to the last, then `SETTLE_BARS` more."""
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.universe import brain_universe
    from swing_trade_ml.core.config import settings

    universes = {d: tuple(brain_universe(db, as_of=d)) for d in decision_days}
    symbols = sorted({s for u in universes.values() for s in u})
    bench = settings.BENCHMARK_INDEX_SYMBOL
    bars = {s: df for s, df in load_bars(db, [*symbols, bench], upto).items() if len(df)}
    index_bars = bars.pop(bench, None)
    sim_days = account_days({d for df in bars.values() for d in df["day"]}, decision_days)
    return universes, bars, index_bars, sim_days


def account_days(trading_days, decision_days: Sequence[date], settle: int = SETTLE_BARS) -> list[date]:
    days = sorted(trading_days)
    inside = [d for d in days if decision_days[0] <= d <= decision_days[-1]]
    missing = [d for d in decision_days if d not in set(inside)]
    if missing:
        raise ValueError(f"no price bars on decision days {missing}")
    return inside + [d for d in days if d > decision_days[-1]][:settle]


def run(
    db: Session,
    *,
    days: Sequence[date],
    asof_model,
    upto: date,
    out: Path,
    variants: Sequence[str] = VARIANTS,
    capital: float = CAPITAL,
    draws: int = DRAWS,
    seed: int = SEED,
    registry: ModuleRegistry = REGISTRY,
) -> dict:
    from sqlalchemy import select

    from swing_trade_ml.brain import queue as brain_queue
    from swing_trade_ml.brain import service
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml import asof
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    decision_days = list(days)
    universes, bars, index_bars, sim_days = prepare(db, decision_days, upto)
    symbols = sorted({s for u in universes.values() for s in u})
    modes = service.load_modes(db)
    level = float(settings.ML_MIN_CONFIDENCE)
    accounts: dict[str, dict] = {}
    records_of: dict[str, dict[date, DayRecord]] = {}

    for name in [v for v in BRAIN_VARIANTS if v in variants or (v == "brain" and "random" in variants)]:
        reg = pit_registry(registry)
        flat = level if name == "rules_only" else None

        def decide(day, account, reg=reg, flat=flat, name=name):
            log.info("pit_replay.day", variant=name, day=day.isoformat())
            return run_brain_day(
                db, day, account, registry=reg, modes=modes, asof_model=asof_model, flat_score=flat
            )

        with brain_queue.run_lock("nightly", "paper"):
            res, recs = run_account(
                bars,
                sim_days,
                decision_days,
                decide,
                capital=capital,
                buckets=get_sector_bucket,
                checkpoint=out / f"checkpoint_{name}.json",
            )
        records_of[name] = recs
        if name in variants:
            accounts[name] = row(res, recs)

    if "model_only" in variants:
        cutoff = asof.asof_cutoff(asof_model)
        insts = db.execute(select(Instrument).where(Instrument.tradingsymbol.in_(symbols))).scalars().all()
        scores = {}
        for inst in insts:
            series = asof.score_series(db, inst, asof_model, after=cutoff)
            scores[inst.tradingsymbol] = {
                d: p for d, p in series.items() if inst.tradingsymbol in universes.get(d, ())
            }
        picks = model_only_picks(scores, decision_days, level, get_sector_bucket)
        accounts["model_only"] = row(account_from_picks(picks, bars, sim_days, None, capital))
        accounts["model_only"]["ideas"] = len(picks)

    if "random" in variants:
        brain = records_of["brain"]
        per_day = {d: len(r.picks) for d, r in brain.items()}
        bmodes = {d: r.banner for d, r in brain.items()}
        pool = same_universe_pool(universes, bars)
        results = random_accounts(
            pool, per_day, bars, sim_days, bmodes, get_sector_bucket, draws=draws, seed=seed, capital=capital
        )
        accounts["random"] = random_row(results, brain)
        accounts["random"]["seeds"] = f"{seed}..{seed + draws - 1}"
    if "nifty" in variants:
        accounts["nifty"] = nifty_row(index_bars, sim_days, capital)
    if "cash" in variants:
        accounts["cash"] = {**CASH_ROW, "final_equity": capital}

    return {
        "protocol": PROTOCOL_ID,
        "decision_days": [d.isoformat() for d in decision_days],
        "account_days": [sim_days[0].isoformat(), sim_days[-1].isoformat(), len(sim_days)],
        "asof_model": getattr(asof_model, "name", None),
        "capital": capital,
        "buy_level": level,
        "slippage_bps": float(settings.PAPER_SLIPPAGE_BPS),
        "stocks": len(bars),
        "accounts": accounts,
        "brain_days": {
            n: [
                {
                    "day": d.isoformat(),
                    "banner": r.banner,
                    "trades": len(r.picks),
                    "holding_words": r.holding_words,
                }
                for d, r in sorted(recs.items())
            ]
            for n, recs in records_of.items()
        },
    }


# --- report -----------------------------------------------------------------------------------------


def _pct(x, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


def _inr(x) -> str:
    return "n/a" if x is None else f"₹{x:,.0f}"


def _fall(x) -> str:
    return "n/a" if x is None else ("0.0%" if x <= 0 else f"-{x * 100:.1f}%")


NAMES = {
    "brain": "Brain (full)",
    "rules_only": "Rules only (flat model score)",
    "model_only": "Model only (score ≥ buy level)",
    "random": "Random, same count a day",
    "nifty": "NIFTY 50 bought and held",
    "cash": "Cash",
}


def _random_line(r: dict) -> str:
    fe, rt, dd = r["final_equity"], r["return"], r["max_drawdown"]
    return (
        f"| {NAMES['random']} ({r['draws']} draws: median, 5th to 95th) | {_inr(fe['median'])} "
        f"| {_pct(rt['median'])} ({_pct(rt['p5'])} to {_pct(rt['p95'])}) "
        f"| {_fall(dd['median'])} ({_fall(dd['p5'])} to {_fall(dd['p95'])}) "
        f"| {r['trades']['median']} | {_pct(r['hit_rate_target_first']['median'], 0)} "
        f"| {_pct(r['avg_net_per_trade']['median'], 2)} "
        f"| {r['days_no_new_trades']} / {r['days_defensive']} |"
    )


def _line(key: str, r: dict) -> str:
    hit, avg = r.get("hit_rate_target_first"), r.get("avg_net_per_trade")
    nnt, dfn = r.get("days_no_new_trades"), r.get("days_defensive")
    return (
        f"| {NAMES[key]} | {_inr(r['final_equity'])} | {_pct(r['return'])} | {_fall(r['max_drawdown'])} "
        f"| {r['trades']} | {'-' if hit is None else _pct(hit, 0)} "
        f"| {'-' if avg is None else _pct(avg, 2)} | {'-' if nnt is None else f'{nnt} / {dfn}'} |"
    )


LIMITS = (
    "One 25-day window, one market. Few trades, so the numbers are noisy.",
    "The replay account does not apply: the owner's pause switch, the avoid list, the cool-down after a "
    "stop, the per-strategy slot share, the share-price cap, cap tiers, the liquidity ceiling and the "
    "market-conditions ceiling (same as portfolio_sim).",
    "Brain EXIT / REDUCE words on holdings are recorded but not acted on: every account exits by the same "
    "fixed rules.",
    "Fills are at the next open with fixed slippage; a gap past the entry zone is still bought.",
    "The stock list is each day's watchlist snapshot (survivor bias); sectors are today's map.",
)


def plain_report(result: dict) -> str:
    acc = result["accounts"]
    days = result["decision_days"]
    first, last, n = result["account_days"]
    lines = [
        "# Point-in-time portfolio replay: brain vs simpler choices on the same rules (ps12)",
        "",
        f"Protocol: `{result['protocol']}`. **Diagnostic on development data, not proof** "
        "(EXPOSURE-LEDGER.md).",
        f"{len(days)} decision days, {days[0]} to {days[-1]}; the account runs {n} trading days "
        f"({first} to {last}) so the last buys can finish.",
        f"Start money {_inr(result['capital'])}. Model `{result['asof_model']}` (trained before these days). "
        f"Buy level {result['buy_level']:.2f}; slippage {result['slippage_bps']:g} bps a side plus charges.",
        "",
        "| Strategy | Money at the end | Return | Worst fall from peak | Trades finished | Reached +8% first "
        "| Average per trade after costs | Days NO NEW TRADES / DEFENSIVE |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key in VARIANTS:
        if acc.get(key) is not None:
            lines.append(_random_line(acc[key]) if key == "random" else _line(key, acc[key]))
    lines += ["", "## Why picks were not bought", ""]
    for key in ("brain", "rules_only", "model_only"):
        if key in acc:
            lines.append(
                f"- {NAMES[key]}: {acc[key]['skipped'] or 'none skipped'}; still open at the end: "
                f"{acc[key]['still_open']}; exits {acc[key]['exits']}"
            )
    lines += [
        "",
        "## How to read it",
        "",
        "- Every account has the same start money, days, next-open fills, exits (+8% / -4%, half at +5%, "
        "15 days), costs and limits. Only the choice of stocks differs.",
        "- 'Random' bought as many stocks a day as the brain did, with the brain's market banner, so it "
        "shows what the brain's timing and caution are worth without its stock choice.",
        "- Development data: a better result here is not evidence that the brain is good; a worse one is a "
        "real warning.",
        "",
        "## Limits",
        "",
        *[f"- {t}" for t in LIMITS],
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.brain.replay_week import iter_ist_trading_days
    from swing_trade_ml.cli import _load_asof_model
    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Point-in-time portfolio replay and same-rules comparison (ps12)")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--asof-model", required=True)
    p.add_argument("--upto", default="2026-09-07", help="last day of prices (the account's settle days)")
    p.add_argument("--capital", type=float, default=CAPITAL)
    p.add_argument("--draws", type=int, default=DRAWS)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--variants", nargs="*", default=list(VARIANTS), choices=VARIANTS)
    p.add_argument("--out", default="../docs/brain/evidence/pit_replay")
    a = p.parse_args(argv)
    from swing_trade_ml.ml.asof import asof_cutoff

    days = list(iter_ist_trading_days(date.fromisoformat(a.start), date.fromisoformat(a.end)))
    out = Path(a.out)
    with SessionLocal() as db:
        model = _load_asof_model(db, a.asof_model)
        if model is None:
            p.error(f"no model named {a.asof_model}")
        cutoff = asof_cutoff(model)
        if cutoff is None or not days or days[0] <= cutoff:
            p.error(f"the days must start after the model's cutoff ({cutoff}), or it has seen them")
        result = run(
            db,
            days=days,
            asof_model=model,
            upto=date.fromisoformat(a.upto),
            out=out,
            variants=a.variants,
            capital=a.capital,
            draws=a.draws,
            seed=a.seed,
        )
    out.mkdir(parents=True, exist_ok=True)
    (out / "pit_replay.md").write_text(plain_report(result), encoding="utf-8")
    (out / "pit_replay.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")
    print(plain_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
