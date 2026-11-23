"""#321/#379 cohort matrix: 33 setups = 11 balances x 3 start offsets, each given to all three policies
with equal capital and offset; 99 compared portfolios plus 1 validation; idempotent seeding. Pure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from swing_trade_ml.simulation.cohorts import (
    BALANCES_INR,
    COMPARISON_COUNT,
    START_OFFSETS,
    CohortError,
    InMemoryDirectory,
    build_matrix,
    build_setups,
    comparison_specs,
    filter_specs,
    matched_groups,
    verify_matrix,
)
from swing_trade_ml.simulation.identity import VALIDATION_USES_SETUP, Policy


def test_there_are_11_balances_3_offsets_and_33_distinct_setups():
    assert len(BALANCES_INR) == 11 and BALANCES_INR[0] == 10_000 and BALANCES_INR[-1] == 10_000_000
    assert START_OFFSETS == (0, 2, 4)
    setups = build_setups()
    assert len(setups) == 33
    assert [s.key for s in setups] == [f"setup-{i:02d}" for i in range(1, 34)]
    assert len({(s.balance_inr, s.start_offset) for s in setups}) == 33
    assert {s.balance_inr for s in setups} == set(BALANCES_INR)
    assert {s.start_offset for s in setups} == set(START_OFFSETS)


def test_the_ladder_rungs_are_all_among_the_balances():
    for rung in (10_000, 100_000, 1_000_000, 2_500_000, 5_000_000, 10_000_000):
        assert rung in BALANCES_INR


def test_the_matrix_is_100_portfolios_99_compared_and_1_validation():
    specs = build_matrix()
    assert len(specs) == 100
    assert len(comparison_specs(specs)) == COMPARISON_COUNT == 99
    assert [s.persona_key for s in specs if not s.counts_in_comparison] == ["syn-100"]


def test_each_policy_holds_33_portfolios_and_each_setup_is_under_all_three():
    specs = build_matrix()
    compared = comparison_specs(specs)
    for policy in Policy:
        assert sum(1 for s in compared if s.policy is policy) == 33
    groups = matched_groups(specs)
    assert len(groups) == 33
    for key, by_policy in groups.items():
        assert set(by_policy) == set(Policy), key
        assert len({(s.balance_inr, s.start_offset) for s in by_policy.values()}) == 1, key


def test_capital_and_offset_come_from_the_setup_not_the_persona():
    setups = {s.key: s for s in build_setups()}
    for spec in build_matrix():
        assert (spec.balance_inr, spec.start_offset) == (
            setups[spec.setup_key].balance_inr,
            setups[spec.setup_key].start_offset,
        )


def test_the_validation_portfolio_uses_an_existing_setup_and_is_never_compared():
    specs = build_matrix()
    validation = next(s for s in specs if not s.counts_in_comparison)
    assert validation.policy is Policy.BRAIN_FILTERED and validation.setup_key == VALIDATION_USES_SETUP
    assert validation not in comparison_specs(specs)
    assert validation not in [s for g in matched_groups(specs).values() for s in g.values()]


def test_the_matrix_is_repeatable():
    assert build_matrix() == build_matrix()


def test_a_broken_matrix_is_refused():
    specs = list(build_matrix())
    with pytest.raises(CohortError):  # a policy moved to another setup's capital: the match is broken
        verify_matrix([replace(specs[0], balance_inr=specs[0].balance_inr + 1), *specs[1:]])
    with pytest.raises(CohortError):  # one portfolio missing
        verify_matrix(specs[:-1])
    with pytest.raises(CohortError):  # the validation portfolio counted as a comparison
        verify_matrix([*specs[:-1], replace(specs[-1], counts_in_comparison=True)])
    with pytest.raises(CohortError):  # two portfolios for one persona
        verify_matrix([*specs[:-1], replace(specs[-1], persona_key=specs[0].persona_key)])


def test_admin_filters_by_policy_setup_capital_and_offset_and_validation_is_its_own_category():
    specs = build_matrix()
    assert len(filter_specs(specs)) == 99
    assert len(filter_specs(specs, policy=Policy.MOMENTUM)) == 33
    assert len(filter_specs(specs, setup_key="setup-05")) == 3
    assert len(filter_specs(specs, balance_inr=10_000)) == 9  # 3 offsets x 3 policies
    assert len(filter_specs(specs, start_offset=2)) == 33
    assert len(filter_specs(specs, policy=Policy.MODEL_ONLY, balance_inr=1_000_000, start_offset=4)) == 1
    only_validation = filter_specs(specs, validation=True)
    assert [s.persona_key for s in only_validation] == ["syn-100"]
    assert all(s.counts_in_comparison for s in filter_specs(specs))


def test_seeding_is_idempotent_no_duplicate_account_and_no_cash_twice():
    specs = build_matrix()
    directory = InMemoryDirectory()
    assert directory.seed(specs) == (100, 0)
    cash_once = directory.total_cash()
    assert len(directory) == 100
    assert cash_once == sum(s.balance_inr for s in specs)
    assert directory.seed(specs) == (0, 100)  # a retry, a restart
    assert len(directory) == 100 and directory.total_cash() == cash_once
    assert directory.account("syn-001").cash_inr == 10_000
