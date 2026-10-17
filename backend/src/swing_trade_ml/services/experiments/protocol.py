"""The frozen experiment protocol (owner-approved 17 Oct 2026, design rev 3, section 2 and 9).

Costs are copied from today's settings into the protocol, so a later change to the app's cost settings never
moves an experiment's results. A change to any value here is a new protocol code, never an edit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.experiments import ExperimentCohort, ExperimentProtocol

BPS = 10_000


@dataclass(frozen=True)
class Costs:
    brokerage_per_order: float
    tax_bps_buy: float
    tax_bps_sell: float
    dp_charge_per_sell: float


@dataclass(frozen=True)
class Protocol:
    code: str
    horizons: tuple[int, ...]
    notional_inr: float
    slippage_bps: float
    cutoff_ist: str
    entry_rule: str
    exit_rule: str
    dedupe_sessions: int
    big_gap: float
    costs: Costs
    benchmarks: tuple[str, ...]
    universe: str
    min_independent_samples: int
    earliest_verdict: str
    label: str


PROTOCOL_V1 = Protocol(
    code="horizon-v1",
    horizons=(5, 30),
    notional_inr=100_000,
    slippage_bps=10,
    cutoff_ist="09:00",
    entry_rule="open of session 1 (before 09:00 IST on a trading day: that session; otherwise the next)",
    exit_rule="time only: close of session N, the entry session counted as 1",
    dedupe_sessions=30,
    big_gap=0.30,
    costs=Costs(
        # Owner decision 17 Oct: Zerodha charges no brokerage on delivery trades. Taxes and the depository fee
        # still come from the app's paper cost settings.
        brokerage_per_order=0.0,
        tax_bps_buy=settings.PAPER_TAX_BPS_BUY,
        tax_bps_sell=settings.PAPER_TAX_BPS_SELL,
        dp_charge_per_sell=settings.PAPER_DP_CHARGE_PER_SELL,
    ),
    benchmarks=(settings.BENCHMARK_INDEX_SYMBOL, "equal_weight_universe", "same_stock_buy_hold"),
    universe="NSE equities with daily candles on both the entry and the exit session",
    min_independent_samples=30,
    earliest_verdict="2026-12-31",
    label="Research, owner-selected, unproven",
)

OWNER_COHORT = "Owner picks"


def frozen_charges(costs: Costs, turnover: float, side: str) -> float:
    """Brokerage plus taxes for one order, frozen rates (the formula of services/costs.compute_charges)."""
    sell = str(side).upper() == "SELL"
    rate = costs.tax_bps_sell if sell else costs.tax_bps_buy
    return costs.brokerage_per_order + turnover * (rate / BPS) + (costs.dp_charge_per_sell if sell else 0.0)


def ensure_owner_cohort(
    db: Session, protocol: Protocol = PROTOCOL_V1
) -> tuple[ExperimentProtocol, ExperimentCohort]:
    """The stored protocol row and the owner cohort, created once. A stored protocol row is never changed."""
    row = db.scalar(select(ExperimentProtocol).where(ExperimentProtocol.code == protocol.code))
    if row is None:
        row = ExperimentProtocol(code=protocol.code, params=asdict(protocol))
        db.add(row)
        db.flush()
    cohort = db.scalar(
        select(ExperimentCohort).where(
            ExperimentCohort.protocol_id == row.id,
            ExperimentCohort.source == "owner",
            ExperimentCohort.name == OWNER_COHORT,
        )
    )
    if cohort is None:
        cohort = ExperimentCohort(protocol_id=row.id, source="owner", name=OWNER_COHORT, status="active")
        db.add(cohort)
        db.flush()
    return row, cohort


def protocol_from_row(row: ExperimentProtocol) -> Protocol:
    """The protocol exactly as stored on first use. Scoring and pick rules always come from here, so a later
    change to the app's cost settings (or to PROTOCOL_V1 in code) never moves an existing experiment; a real
    change of rules needs a new protocol code."""
    p = dict(row.params)
    p["costs"] = Costs(**p["costs"])
    for key in ("horizons", "benchmarks"):
        p[key] = tuple(p[key])
    return Protocol(**p)
