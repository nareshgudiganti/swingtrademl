# ruff: noqa: E501  (long plain-English docstrings)
"""The cohort matrix of #321 and #379: 33 setups x 3 policies = 99 matched portfolios, plus 1 validation portfolio.

A SETUP is one starting balance and one start offset. There are 11 balances (the owner's capital ladder, Rs 10K to
Rs 1Cr) and 3 start offsets (0, 2 and 4 exchange sessions after the first day), so 33 setups. Every setup is given to
all three policies with identical capital and offset, so any difference between the three comes only from how each
picks its stocks. The validation portfolio is outside every comparison.

Assumption, flagged for the owner: #379 says "map setup keys to the #321 matrix" but not which key is which cell.
Here setup-NN (NN = 01..33) takes the cell NN - 1 counted across the offsets first: setup-01 is Rs 10K at offset 0,
setup-02 is Rs 10K at offset 2, setup-03 is Rs 10K at offset 4, setup-04 is Rs 25K at offset 0, and so on. Any other
mapping changes only this table, nothing else in the package.

Pure and in memory: no database, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from swing_trade_ml.simulation.identity import (
    COMPARED_COUNT,
    PERSONA_COUNT,
    Policy,
    SyntheticPersona,
    generate_roster,
)

# #321 section 3.2 (PROPOSED until the owner approves it): 11 starting balances, every ladder rung included.
BALANCES_INR: tuple[int, ...] = (
    10_000,
    25_000,
    50_000,
    100_000,
    250_000,
    500_000,
    1_000_000,
    2_500_000,
    5_000_000,
    7_500_000,
    10_000_000,
)
START_OFFSETS: tuple[int, ...] = (0, 2, 4)  # exchange sessions after the first start day
SETUP_COUNT = len(BALANCES_INR) * len(START_OFFSETS)  # 33
COMPARISON_COUNT = COMPARED_COUNT  # the default comparison states this number: 99


class CohortError(ValueError):
    """The matrix broke a promise of #321 or #379."""


@dataclass(frozen=True, slots=True)
class Setup:
    key: str  # "setup-01" .. "setup-33"
    balance_inr: int
    start_offset: int


def build_setups() -> tuple[Setup, ...]:
    """The 33 setups, in key order."""
    setups = []
    for index in range(SETUP_COUNT):
        balance = BALANCES_INR[index // len(START_OFFSETS)]
        offset = START_OFFSETS[index % len(START_OFFSETS)]
        setups.append(Setup(f"setup-{index + 1:02d}", balance, offset))
    return tuple(setups)


@dataclass(frozen=True, slots=True)
class PortfolioSpec:
    """One isolated paper portfolio: who owns it, which policy runs it, and the setup it started from."""

    persona_key: str
    policy: Policy
    setup_key: str
    balance_inr: int
    start_offset: int
    counts_in_comparison: bool  # False for the validation portfolio only


def build_matrix(roster: tuple[SyntheticPersona, ...] | None = None) -> tuple[PortfolioSpec, ...]:
    """The 100 portfolio specs, in roster order. Capital and offset come from the setup, never from the persona,
    so two policies on one setup cannot differ."""
    roster = roster if roster is not None else generate_roster()
    setups = {s.key: s for s in build_setups()}
    specs = []
    for persona in roster:
        setup = setups[persona.setup_key]
        specs.append(
            PortfolioSpec(
                persona_key=persona.key,
                policy=persona.policy,
                setup_key=setup.key,
                balance_inr=setup.balance_inr,
                start_offset=setup.start_offset,
                counts_in_comparison=persona.counts_in_comparison,
            )
        )
    verify_matrix(specs)
    return tuple(specs)


def comparison_specs(specs: Iterable[PortfolioSpec]) -> tuple[PortfolioSpec, ...]:
    """The 99 portfolios every default comparison uses: the validation portfolio is left out."""
    return tuple(s for s in specs if s.counts_in_comparison)


def matched_groups(specs: Iterable[PortfolioSpec]) -> dict[str, dict[Policy, PortfolioSpec]]:
    """setup key -> {policy: spec}, over the compared portfolios only."""
    groups: dict[str, dict[Policy, PortfolioSpec]] = {}
    for spec in comparison_specs(specs):
        groups.setdefault(spec.setup_key, {})[spec.policy] = spec
    return groups


def filter_specs(
    specs: Iterable[PortfolioSpec],
    *,
    policy: Policy | None = None,
    setup_key: str | None = None,
    balance_inr: int | None = None,
    start_offset: int | None = None,
    validation: bool = False,
) -> tuple[PortfolioSpec, ...]:
    """The admin filters of #379 acceptance 4. Validation is its own category: it is returned only when asked for
    (`validation=True`) and never mixed into the compared ones."""
    out = []
    for spec in specs:
        if spec.counts_in_comparison == validation:
            continue
        if policy is not None and spec.policy is not policy:
            continue
        if setup_key is not None and spec.setup_key != setup_key:
            continue
        if balance_inr is not None and spec.balance_inr != balance_inr:
            continue
        if start_offset is not None and spec.start_offset != start_offset:
            continue
        out.append(spec)
    return tuple(out)


def verify_matrix(specs: Iterable[PortfolioSpec]) -> None:
    """#379 acceptance 2 and 3: 33 portfolios per policy, 1 validation, every setup once under each policy with
    equal capital and offset."""
    specs = tuple(specs)
    if len(specs) != PERSONA_COUNT:
        raise CohortError(f"expected {PERSONA_COUNT} portfolios, found {len(specs)}")
    if len({s.persona_key for s in specs}) != len(specs):
        raise CohortError("a persona owns more than one portfolio")
    compared = comparison_specs(specs)
    if len(compared) != COMPARISON_COUNT or len(specs) - len(compared) != 1:
        raise CohortError("expected 99 compared portfolios and exactly 1 validation portfolio")
    per_policy = {p: sum(1 for s in compared if s.policy is p) for p in Policy}
    if set(per_policy.values()) != {SETUP_COUNT}:
        raise CohortError(f"each policy must hold {SETUP_COUNT} portfolios, found {per_policy}")
    groups = matched_groups(specs)
    if len(groups) != SETUP_COUNT:
        raise CohortError(f"expected {SETUP_COUNT} matched setups, found {len(groups)}")
    for key, by_policy in groups.items():
        if set(by_policy) != set(Policy):
            raise CohortError(f"{key}: every setup needs one portfolio under each policy")
        if len({(s.balance_inr, s.start_offset) for s in by_policy.values()}) != 1:
            raise CohortError(f"{key}: the three policies must start with equal capital and offset")


@dataclass(slots=True)
class PortfolioAccount:
    spec: PortfolioSpec
    cash_inr: float


class InMemoryDirectory:
    """The 100 isolated portfolio accounts, in memory. `seed` is idempotent: running it again (a retry, a restart)
    adds no account and credits no cash twice (#379 acceptance 1)."""

    def __init__(self) -> None:
        self._accounts: dict[str, PortfolioAccount] = {}

    def seed(self, specs: Iterable[PortfolioSpec]) -> tuple[int, int]:
        """Returns (created, already there). Opening cash is credited exactly once, when the account is created."""
        created = existing = 0
        for spec in specs:
            if spec.persona_key in self._accounts:
                existing += 1
                continue
            self._accounts[spec.persona_key] = PortfolioAccount(spec, float(spec.balance_inr))
            created += 1
        return created, existing

    def account(self, persona_key: str) -> PortfolioAccount:
        return self._accounts[persona_key]

    def __len__(self) -> int:
        return len(self._accounts)

    def total_cash(self) -> float:
        return sum(a.cash_inr for a in self._accounts.values())
