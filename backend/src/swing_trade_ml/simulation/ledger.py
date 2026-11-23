# ruff: noqa: E501  (long plain-English docstrings)
"""A pure daily ledger for one paper portfolio (#321): for every session it records the fills, the exits, the blocks
(each with its reason), the cash, the open positions and their marks, and the day's equity.

Inputs are plain values: the session list (ISO dates), a price series (open, high, low, close per stock per session)
and the picks each policy decided at the CLOSE of a session. The engine buys those picks at the NEXT session's open,
applies the app's trading rules (`simulation.rules.TradingRules`, never loosened), and walks every open position
through each day's bar in the same order the brain's own portfolio replay uses (`brain/portfolio_sim.py`): the stop
first, then the half-out (when the rule has one), then the target, then the exit at the close of the last session.

OWNER DECISION (zero-trade accounts): a portfolio that never trades is kept and reported like any other. The ledger
never forces a trade, never relaxes a rule and never substitutes a rejected pick for another. Every session of every
portfolio has a record: cash, positions (none is fine), the day's equity, and every blocked pick WITH its reason.

Which of the app's entry rules (services/risk.py `check_entry`) the ledger applies:
  APPLIED:      drawdown halt (15%), already held, stop-loss cooldown (calendar days, from the app's setting), position
                limit, share-price ceiling, one stock per sector (small rungs) and the sector cap, minimum position,
                1%-risk sizing (`brain/portfolio_sim.entry_budget`), the cash floor, costs and slippage;
  GIVEN INPUTS: market mode per session (NORMAL; DEFENSIVE = half size and at most 2 buys; NO_NEW_TRADES = none; an
                unknown mode counts as NO_NEW_TRADES), liquidity limit (average daily traded value), cap tier and the
                small-company budget, the exchange avoid list. Each is applied only when its input is supplied; one that
                is not supplied is listed in `PortfolioLedger.not_applied`, so nothing claims it was applied;
  NOT APPLIED:  the regime deployable ceiling, the brain's reserved slot and the per-strategy slot share
                (`rules.ALWAYS_NOT_APPLIED`), whatever the inputs.
Where an input is supplied but has no value for a stock (an unknown tier, no traded value), the pick is BLOCKED with
the reason, never allowed: bad data never makes a decision more aggressive.

Properties the tests pin:
- no look-ahead: the record of a session depends only on bars up to and including that session, and a pick decided at
  the close of session s is never bought before the open of session s+1;
- cash never goes negative: every buy is checked, with its charges, against the cash left after the buys before it;
- repeatable: the same inputs give the same ledger, to the last digit; there is no clock and no randomness;
- two portfolios may hold the same stock (each account is its own world).

Nothing here touches a database, places an order or reads the clock. Persisting the ledger needs a table (owner
approval, later). A stock is a plain symbol string until the identity interface (services/identity) is wired in.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from swing_trade_ml.simulation.cohorts import PortfolioSpec
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.rules import (
    ALWAYS_NOT_APPLIED,
    MODE_DEFENSIVE,
    MODE_NO_NEW_TRADES,
    MODE_NORMAL,
    MODES,
    OPTIONAL_INPUTS,
    TradingRules,
    require_one_version,
)

CASH_TOLERANCE = 1e-6  # float noise only; a real overspend is far larger


class LedgerInvariantError(AssertionError):
    """The engine broke one of its own promises (negative cash, a sold position still open). Never expected."""


class LedgerInputError(ValueError):
    """The inputs cannot be run (for example a session label that is not an ISO date)."""


@dataclass(frozen=True, slots=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class Candidate:
    """A pick decided at the close of a session. `block_reason` is set by the policy when it holds the pick back
    (for example a Brain safety check); the ledger records it as a block and buys nothing."""

    symbol: str
    score: float
    sector: str | None = None  # an unmapped stock counts as its own sector
    block_reason: str | None = None
    security_id: int | None = None  # the permanent stock id (services/identity), when the pick came from one
    record_id: int | None = None  # the horizon record the pick was read from


Bars = Mapping[str, Mapping[str, Bar]]  # symbol -> session -> bar
Decisions = Mapping[str, Sequence[Candidate]]  # session -> picks decided at that session's close
MarketModes = Mapping[str, str]  # session -> the mode decided at that session's close (governs the next open)
Liquidity = Mapping[str, Mapping[str, float]]  # symbol -> session -> average daily traded value (rupees)
CapTiers = Mapping[str, str]  # symbol -> "large" | "midcap" | "smallcap"
Avoid = Mapping[str, Mapping[str, str]]  # session -> {symbol: reason to stay out}


@dataclass(frozen=True, slots=True)
class FillRecord:
    symbol: str
    qty: int
    price: float  # per share, slippage included
    charges: float
    cost: float  # cash out: price * qty + charges
    security_id: int | None = None
    record_id: int | None = None


@dataclass(frozen=True, slots=True)
class ExitRecord:
    symbol: str
    qty: int
    price: float  # the level or open the shares were sold at, before slippage
    reason: str  # stop | half_out | target | horizon
    proceeds: float  # cash in, after slippage and charges
    stale: bool = (
        False  # sold at the last known close because the stock had no bar for its whole holding window
    )


@dataclass(frozen=True, slots=True)
class BlockRecord:
    symbol: str
    reason: str
    security_id: int | None = None
    record_id: int | None = None


@dataclass(frozen=True, slots=True)
class PositionMark:
    symbol: str
    qty: int
    mark: float  # last close
    value: float
    half_done: bool
    stale: bool  # no bar today: marked at the last close, nothing evaluated


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session: str
    fills: tuple[FillRecord, ...]
    exits: tuple[ExitRecord, ...]
    blocks: tuple[BlockRecord, ...]
    cash: float
    positions: tuple[PositionMark, ...]
    equity: float
    halted: bool  # the drawdown halt was on when today's buys were considered
    rule_version: str = ""  # the trade rule this record was made under (rules.TradingRules.version)
    market_mode: str = ""  # the mode that governed today's buys ("" when no market modes were supplied)
    research_only: bool = False  # made under a research configuration (10D, 15D): never a product result


@dataclass(frozen=True, slots=True)
class PortfolioLedger:
    spec: PortfolioSpec
    records: tuple[SessionRecord, ...] = field(default_factory=tuple)
    rule_version: str = (
        ""  # also set when the portfolio made no records, so a ledger always says which rule it ran
    )
    not_applied: tuple[str, ...] = ()  # the app rules this run did not apply (see the module docstring)
    research_only: bool = False

    @property
    def final_equity(self) -> float:
        return self.records[-1].equity if self.records else float(self.spec.balance_inr)

    @property
    def final_cash(self) -> float:
        return self.records[-1].cash if self.records else float(self.spec.balance_inr)

    @property
    def fill_count(self) -> int:
        return sum(len(r.fills) for r in self.records)

    @property
    def exit_count(self) -> int:
        return sum(len(r.exits) for r in self.records)

    @property
    def block_count(self) -> int:
        return sum(len(r.blocks) for r in self.records)


@dataclass(slots=True)
class _Position:
    symbol: str
    key: str  # sector bucket
    tier: str | None
    qty: int
    entry_index: int
    stop_px: float
    half_px: float | None  # None under a rule with no half-out
    target_px: float
    last_close: float
    half_done: bool = False


def _sell(price: float, qty: int) -> float:
    """Cash received for selling `qty` shares at `price`, after slippage and charges (the same arithmetic as
    brain/replay_scoring._sell at normal cost)."""
    from swing_trade_ml.services.costs import apply_slippage, compute_charges

    gross = apply_slippage(price, "SELL") * qty
    brokerage, taxes = compute_charges(gross, "SELL")
    return gross - (brokerage + taxes)


def _equity(cash: float, positions: Mapping[str, _Position]) -> float:
    return cash + sum(p.qty * p.last_close for p in positions.values())


def _exposure(positions: Mapping[str, _Position]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in positions.values():
        out[p.key] = out.get(p.key, 0.0) + p.qty * p.last_close
    return out


def _calendar(sessions: Sequence[str]) -> list[date]:
    try:
        return [date.fromisoformat(s) for s in sessions]
    except ValueError as exc:
        raise LedgerInputError("sessions must be ISO dates (YYYY-MM-DD)") from exc


def not_applied_for(
    market_modes: object | None, liquidity: object | None, cap_tiers: object | None, avoid: object | None
) -> tuple[str, ...]:
    """The app rules a run did not apply: the ones never modelled, plus each optional input that was not supplied."""
    supplied = {"market_modes": market_modes, "liquidity": liquidity, "cap_tiers": cap_tiers, "avoid": avoid}
    missing = tuple(text for name, text in OPTIONAL_INPUTS.items() if supplied[name] is None)
    return (*ALWAYS_NOT_APPLIED, *missing)


def run_portfolio(
    spec: PortfolioSpec,
    sessions: Sequence[str],
    bars: Bars,
    decisions: Decisions,
    rules: TradingRules | None = None,
    *,
    market_modes: MarketModes | None = None,
    liquidity: Liquidity | None = None,
    cap_tiers: CapTiers | None = None,
    avoid: Avoid | None = None,
) -> PortfolioLedger:
    """Walk one portfolio from its start session to the last session and return its ledger.

    `sessions` are ISO dates in order. The portfolio starts `spec.start_offset` sessions into the list. Picks in
    `decisions[s]` were decided at the close of session s and are bought at the open of s+1, in the market mode in
    `market_modes[s]` (None = every session NORMAL, listed as not applied; a session missing from a given mapping
    counts as NO_NEW_TRADES). `liquidity[symbol][s]`, `cap_tiers[symbol]` and `avoid[s][symbol]` are point-in-time
    inputs as of the decision session."""
    from swing_trade_ml.brain.portfolio_sim import entry_budget
    from swing_trade_ml.services.costs import apply_slippage, compute_charges
    from swing_trade_ml.services.limits import SMALL, limits_for

    rules = rules or TradingRules.from_app()
    dates = _calendar(sessions)
    cash = float(spec.balance_inr)
    positions: dict[str, _Position] = {}
    last_stop: dict[str, date] = {}
    pending: Sequence[Candidate] = ()
    decided_on = ""
    equity = cash
    peak = cash
    records: list[SessionRecord] = []

    for index in range(spec.start_offset, len(sessions)):
        day = sessions[index]
        fills: list[FillRecord] = []
        exits: list[ExitRecord] = []
        blocks: list[BlockRecord] = []
        halted = peak > 0 and (peak - equity) / peak >= rules.drawdown_halt
        if market_modes is None:
            mode = MODE_NORMAL
        else:
            mode = market_modes.get(decided_on, MODE_NO_NEW_TRADES) if decided_on else MODE_NORMAL
            if mode not in MODES:
                mode = MODE_NO_NEW_TRADES  # a mode we do not know is the cautious one
        buys_allowed = {MODE_NORMAL: rules.max_new_per_day, MODE_DEFENSIVE: rules.defensive_max_new}.get(
            mode, 0
        )
        buys_allowed = min(buys_allowed, rules.max_new_per_day)

        def _blk(c: Candidate, why: str) -> BlockRecord:
            return BlockRecord(c.symbol, why, c.security_id, c.record_id)

        # 1. Buy yesterday's picks at today's open (best score first, then symbol, so the order is fixed).
        considered = 0
        for cand in sorted(pending, key=lambda c: (-c.score, c.symbol)):
            symbol = cand.symbol
            if cand.block_reason:
                blocks.append(_blk(cand, f"held_back: {cand.block_reason}"))
                continue
            if mode == MODE_NO_NEW_TRADES:
                blocks.append(_blk(cand, "no_new_trades"))
                continue
            if considered >= buys_allowed:
                blocks.append(
                    _blk(cand, "market_mode_limit" if mode == MODE_DEFENSIVE else "over_daily_limit")
                )
                continue
            considered += 1
            if halted:
                blocks.append(_blk(cand, "drawdown_halt"))
                continue
            if symbol in positions:
                blocks.append(_blk(cand, "already_held"))
                continue
            stopped_on = last_stop.get(symbol)
            if stopped_on is not None and (dates[index] - stopped_on).days <= rules.stop_cooldown_days:
                blocks.append(_blk(cand, "stop_cooldown"))
                continue
            if avoid is not None:
                why = avoid.get(decided_on, {}).get(symbol)
                if why:
                    blocks.append(_blk(cand, f"avoid: {why}"))
                    continue
            now_equity = _equity(cash, positions)
            limits = limits_for(now_equity)
            if len(positions) >= limits.max_positions:
                blocks.append(_blk(cand, "no_free_slot"))
                continue
            bar = bars.get(symbol, {}).get(day)
            if bar is None:
                blocks.append(_blk(cand, "no_price"))
                continue
            tier: str | None = None
            small_room = math.inf
            if cap_tiers is not None:
                tier = cap_tiers.get(symbol)
                if tier is None:
                    blocks.append(_blk(cand, "cap_tier_unknown"))
                    continue
                if tier not in limits.allowed_cap_tiers:
                    blocks.append(_blk(cand, "cap_tier"))
                    continue
                if tier == SMALL and limits.small_cap_budget_pct is not None:
                    small_used = sum(p.qty * p.last_close for p in positions.values() if p.tier == SMALL)
                    small_room = limits.small_cap_budget_pct * now_equity - small_used
                    if small_room < limits.min_position_inr:
                        blocks.append(_blk(cand, "cap_tier"))
                        continue
            if limits.max_share_price_inr is not None and float(bar.open) > limits.max_share_price_inr:
                blocks.append(_blk(cand, "price_above_ladder_limit"))
                continue
            key = cand.sector or symbol
            exposure = _exposure(positions)
            if limits.sector_rule == "one_per_sector" and key in exposure:
                blocks.append(_blk(cand, "sector_cap"))
                continue
            if limits.sector_cap_pct is not None:
                sector_room = limits.sector_cap_pct * now_equity - exposure.get(key, 0.0)
                if sector_room < limits.min_position_inr:
                    blocks.append(_blk(cand, "sector_cap"))
                    continue
            liquidity_room = math.inf
            if liquidity is not None and limits.max_adv_pct is not None:
                adv = liquidity.get(symbol, {}).get(decided_on)
                if adv is None:
                    blocks.append(_blk(cand, "liquidity_unknown"))
                    continue
                liquidity_room = limits.max_adv_pct * adv
                if liquidity_room < limits.min_position_inr:
                    blocks.append(_blk(cand, "liquidity"))
                    continue
            fill = apply_slippage(float(bar.open), "BUY")
            risk_budget = entry_budget(
                now_equity,
                math.inf,
                limits,
                mode,
                exposure.get(key, 0.0),
                stop=rules.stop,
                risk_per_trade_pct=rules.risk_per_trade_pct,
            )
            ceiling = min(risk_budget, small_room, liquidity_room)
            cash_room = cash - limits.cash_floor_inr
            budget = min(ceiling, cash_room)
            qty = math.floor(budget / fill) if fill > 0 and budget > 0 else 0
            if qty < 1 or qty * fill < limits.min_position_inr:
                # Cash is the reason only when the risk and ceiling limits alone would have allowed a minimum position.
                short_of_cash = ceiling >= limits.min_position_inr > cash_room
                blocks.append(_blk(cand, "insufficient_cash" if short_of_cash else "below_minimum_position"))
                continue
            brokerage, taxes = compute_charges(fill * qty, "BUY")
            cost = fill * qty + brokerage + taxes
            if cost > cash:
                blocks.append(_blk(cand, "insufficient_cash"))
                continue
            cash -= cost
            positions[symbol] = _Position(
                symbol=symbol,
                key=key,
                tier=tier,
                qty=qty,
                entry_index=index,
                stop_px=fill * (1 - rules.stop),
                half_px=None if rules.half_out is None else fill * (1 + rules.half_out),
                target_px=fill * (1 + rules.target),
                last_close=fill,
            )
            fills.append(
                FillRecord(symbol, qty, fill, brokerage + taxes, cost, cand.security_id, cand.record_id)
            )

        # 2. Walk every open position through today's bar: stop, then half-out, then target, then the horizon.
        stale: set[str] = set()
        for symbol in list(positions):
            pos = positions[symbol]
            bar = bars.get(symbol, {}).get(day)
            if bar is None:
                if index - pos.entry_index + 1 >= rules.horizon_sessions:
                    # Held its whole window without a bar today: sold at the last known close, flagged stale. No
                    # price is invented, and the position does not stay open forever at a stale mark.
                    got = _sell(pos.last_close, pos.qty)
                    cash += got
                    exits.append(ExitRecord(symbol, pos.qty, pos.last_close, "horizon", got, stale=True))
                    del positions[symbol]
                else:
                    stale.add(symbol)
                continue
            o, h, lo, c = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
            pos.last_close = c
            sold_out = False
            if lo <= pos.stop_px:  # a bar touching the stop and anything else counts as the stop
                price = o if o <= pos.stop_px else pos.stop_px
                got = _sell(price, pos.qty)
                cash += got
                exits.append(ExitRecord(symbol, pos.qty, price, "stop", got))
                last_stop[symbol] = dates[index]
                pos.qty, sold_out = 0, True
            else:
                if pos.half_px is not None and not pos.half_done and pos.qty >= 2 and h >= pos.half_px:
                    half = pos.qty // 2
                    price = o if o >= pos.half_px else pos.half_px
                    got = _sell(price, half)
                    cash += got
                    exits.append(ExitRecord(symbol, half, price, "half_out", got))
                    pos.qty -= half
                    pos.half_done = True
                if h >= pos.target_px:
                    price = o if o >= pos.target_px else pos.target_px
                    got = _sell(price, pos.qty)
                    cash += got
                    exits.append(ExitRecord(symbol, pos.qty, price, "target", got))
                    pos.qty, sold_out = 0, True
                elif index - pos.entry_index + 1 >= rules.horizon_sessions:
                    got = _sell(c, pos.qty)
                    cash += got
                    exits.append(ExitRecord(symbol, pos.qty, c, "horizon", got))
                    pos.qty, sold_out = 0, True
            if sold_out:
                del positions[symbol]

        # 3. Mark at the close and record the day.
        equity = _equity(cash, positions)
        peak = max(peak, equity)
        if cash < -CASH_TOLERANCE:
            raise LedgerInvariantError(f"{spec.persona_key} {day}: cash went negative ({cash})")
        marks = tuple(
            PositionMark(p.symbol, p.qty, p.last_close, p.qty * p.last_close, p.half_done, p.symbol in stale)
            for p in positions.values()
        )
        records.append(
            SessionRecord(
                session=day,
                fills=tuple(fills),
                exits=tuple(exits),
                blocks=tuple(blocks),
                cash=cash,
                positions=marks,
                equity=equity,
                halted=halted,
                rule_version=rules.version,
                market_mode="" if market_modes is None else mode,
                research_only=rules.research_only,
            )
        )
        pending = decisions.get(day, ())  # decided at today's close, bought at tomorrow's open
        decided_on = day

    return PortfolioLedger(
        spec=spec,
        records=tuple(records),
        rule_version=rules.version,
        not_applied=not_applied_for(market_modes, liquidity, cap_tiers, avoid),
        research_only=rules.research_only,
    )


def run_cohort(
    specs: Sequence[PortfolioSpec],
    sessions: Sequence[str],
    bars: Bars,
    decisions_by_policy: Mapping[Policy, Decisions],
    rules: TradingRules | None = None,
    **inputs: object,
) -> dict[str, PortfolioLedger]:
    """Run every portfolio on the same prices with the picks of its own policy. Portfolios never share state, so two
    of them may hold the same stock, and a policy with no picks simply makes no trades. `inputs` are the optional
    point-in-time inputs of `run_portfolio` (market_modes, liquidity, cap_tiers, avoid), the same for every portfolio."""
    rules = rules or TradingRules.from_app()
    return {
        spec.persona_key: run_portfolio(
            spec,
            sessions,
            bars,
            decisions_by_policy.get(spec.policy, {}),
            rules,
            **inputs,  # type: ignore[arg-type]
        )
        for spec in specs
    }


def ledgers_rule_version(ledgers: Mapping[str, PortfolioLedger]) -> str:
    """The one rule version of a set of ledgers. Results made under different rules are never mixed: two versions
    in one comparison raise `rules.MixedRuleVersions`. Both the ledger's own version and every record's are checked."""
    versions = {ledger.rule_version for ledger in ledgers.values()}
    versions |= {record.rule_version for ledger in ledgers.values() for record in ledger.records}
    return require_one_version(versions)


def compare_by_policy(ledgers: Mapping[str, PortfolioLedger]) -> dict[Policy, dict[str, float]]:
    """Mean return, trade counts and blocked picks per policy over the COMPARED portfolios (the validation one is left
    out). Zero-trade portfolios are included, at their own return of zero. Refuses to mix rule versions."""
    ledgers_rule_version(ledgers)
    out: dict[Policy, dict[str, float]] = {}
    for policy in Policy:
        chosen = [
            ledger
            for ledger in ledgers.values()
            if ledger.spec.counts_in_comparison and ledger.spec.policy is policy
        ]
        if not chosen:
            continue
        returns = [ledger.final_equity / ledger.spec.balance_inr - 1 for ledger in chosen]
        out[policy] = {
            "portfolios": len(chosen),
            "zero_trade_portfolios": sum(1 for ledger in chosen if ledger.fill_count == 0),
            "mean_return": sum(returns) / len(returns),
            "fills": sum(ledger.fill_count for ledger in chosen),
            "exits": sum(ledger.exit_count for ledger in chosen),
            "blocked": sum(ledger.block_count for ledger in chosen),
            "research_only": any(ledger.research_only for ledger in chosen),
        }
    return out
