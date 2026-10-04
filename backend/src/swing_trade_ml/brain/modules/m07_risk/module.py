"""M07 · Risk and safety gate — the brain's one mandatory module.

For every stock the brain likes, ask version 1's own risk rules
(`risk.check_entry`: halt, cool-down, avoid lists, positions, drawdown,
sector, liquidity, market conditions, cash reserve, sizing) and let the batch
allocator make the approvals fit the account together. Without an allowed
verdict from here no stock can be a TRADE (constitution C1); if this module
fails, the whole run is NO NEW TRADES (C2).

Risk state is "now" data — cash, holdings, drawdown — so a replay of a past
date is never approved.
"""

from __future__ import annotations

from collections import defaultdict

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.market_mode import effective_mode
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m07_risk.allocator import Account, Candidate, CheckResult, Policy, allocate
from swing_trade_ml.brain.opinions import liked, pick_opinion, rank_strength
from swing_trade_ml.ml.sector_map import get_sector_bucket
from swing_trade_ml.services import deployable, risk
from swing_trade_ml.services.limits import limits_for
from swing_trade_ml.services.portfolio import portfolio_value_and_cash

STOP_PCT = 0.04  # the locked -4% stop sizes the position
DEFENSIVE_SIZE_FACTOR = 0.5
DEFENSIVE_MAX_NEW = 2


def candidates_from(view: ContextView) -> tuple[list[Candidate], list[c.RiskVerdict]]:
    """Liked stocks with a price, plus early refusals for liked stocks that
    cannot be sized (no price) or should not be trusted (stale data)."""
    by_symbol: dict[str, list[c.Opinion]] = defaultdict(list)
    for o in view.opinions:
        by_symbol[o.symbol].append(o)

    candidates: list[Candidate] = []
    refusals: list[c.RiskVerdict] = []
    for symbol in sorted(by_symbol):
        opinion = pick_opinion(by_symbol[symbol])
        if opinion is None or not liked(opinion):
            continue
        snap = view.snapshots.get(symbol)
        if snap is None or snap.close <= 0:
            refusals.append(
                c.RiskVerdict(
                    symbol=symbol,
                    allowed=False,
                    rule="NO_PRICE",
                    reason="No price for this stock, so it cannot be sized.",
                )
            )
            continue
        quality = view.quality.get(symbol)
        if quality is not None and not quality.fresh:
            detail = "; ".join(quality.issues) or f"quality score {quality.score:.2f}"
            refusals.append(
                c.RiskVerdict(
                    symbol=symbol,
                    allowed=False,
                    rule="DATA",
                    reason=f"Data is not reliable today ({detail}).",
                )
            )
            continue
        candidates.append(
            Candidate(
                symbol=symbol,
                price=snap.close,
                strength=rank_strength(by_symbol[symbol]),
                bucket=get_sector_bucket(symbol),
                instrument_id=view.reader.instrument_id(symbol),
            )
        )
    return candidates, refusals


def account_snapshot(db, book: str) -> Account:
    portfolio_value, cash = portfolio_value_and_cash(db, book)
    limits = limits_for(portfolio_value)
    holdings = risk.open_holdings(db, book)
    exposure: dict[str, float] = defaultdict(float)
    for h in holdings:
        bucket = get_sector_bucket(h.tradingsymbol)
        if bucket is not None:
            exposure[bucket] += h.value
    invested = sum(h.value for h in holdings)
    deploy_ceiling = deployable.current_deployable(db).fraction * portfolio_value
    return Account(
        portfolio_value=portfolio_value,
        cash=cash,
        free_slots=max(0, limits.max_positions - risk.open_position_count(db, book)),
        min_position_inr=limits.min_position_inr,
        sector_rule=limits.sector_rule,
        sector_cap_pct=limits.sector_cap_pct,
        sector_exposure=dict(exposure),
        deploy_room=deploy_ceiling - invested,
    )


def _v1_check(db, book: str, portfolio_value: float):
    def check(cand: Candidate, cash_left: float) -> CheckResult:
        if cand.instrument_id is None:
            return CheckResult(
                allowed=False, rule="NO_INSTRUMENT", reason="This stock is not in the instrument list."
            )
        d = risk.check_entry(
            db,
            book,
            cand.instrument_id,
            price=cand.price,
            stop_loss=round(cand.price * (1 - STOP_PCT), 2),
            portfolio_value=portfolio_value,
            available_cash=cash_left,
            strategy=None,
        )
        return CheckResult(
            allowed=d.allowed, qty=d.quantity, rule=d.rule, reason=d.reason, amount_inr=d.amount_inr
        )

    return check


@register_module
class RiskGate(BrainModule):
    manifest = Manifest(
        id="M07",
        name="Risk and safety gate",
        step=Step.RISK,
        kind="step",
        version="1.0.0",
        reads=(
            "Opinion@1",
            "Snapshot@1",
            "MarketState@1",
            "DataQuality@1",
            "Situation@1",
            "PortfolioState@1",
        ),
        writes=("RiskVerdict@1",),
        budget_s=20.0,
        mandatory=True,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        candidates, refusals = candidates_from(view)
        if not view.request.live:
            replay = [
                c.RiskVerdict(
                    symbol=cand.symbol,
                    allowed=False,
                    rule="REPLAY",
                    reason="Risk checks use today's account, so a replay of a past date "
                    "never approves a trade.",
                )
                for cand in candidates
            ]
            return c.Contribution(verdicts=tuple(refusals + replay))

        db = view.reader.db
        book = view.request.book
        account = account_snapshot(db, book)
        market = view.market
        policy = Policy(
            mode=effective_mode(market, view.situations)[0],
            defensive_size_factor=DEFENSIVE_SIZE_FACTOR,
            defensive_max_new=DEFENSIVE_MAX_NEW,
            pairs=frozenset(
                frozenset((a, b))
                for a, b, _ in (view.portfolio.correlated if view.portfolio is not None else ())
            ),
        )
        verdicts = allocate(
            candidates, account, _v1_check(db, book, account.portfolio_value), policy, risk.buy_cost
        )
        return c.Contribution(verdicts=tuple(refusals + verdicts))
