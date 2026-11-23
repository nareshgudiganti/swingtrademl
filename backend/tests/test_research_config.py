# ruff: noqa: E501 (long lines in test code)
"""Versioned horizon research rules (#387): immutable, selected by version, 10D and 15D research-only. Pure."""

from __future__ import annotations

import dataclasses

import pytest

from swing_trade_ml.brain.horizons import DEFAULT_POLICIES
from swing_trade_ml.core import research_config as rc


def test_the_active_version_is_a_named_version_not_a_toggle():
    assert rc.ACTIVE_VERSION in rc.VERSIONS
    assert rc.active() is rc.get_version(rc.ACTIVE_VERSION)


def test_five_day_rule_and_research_only_flags():
    five = rc.rule_for(5)
    assert (five.target_pct, five.stop_pct, five.max_sessions) == (0.02, 0.04, 5)
    assert five.research_only is False
    assert rc.is_research_only(10) and rc.is_research_only(15)
    assert not rc.is_research_only(5)


# An in-place edit of any rule changes this value. A change must be a NEW version, approved by the owner.
HZ_RULES_V1_SHA256 = "3dab34cd06b5756b633c957d61e71af8e64f8b7e055fa49375b570fd79d8eee6"


def test_version_one_is_pinned_by_value():
    assert rc.get_version("hz-rules-v1").sha256 == HZ_RULES_V1_SHA256


def test_the_version_table_is_read_only():
    with pytest.raises(TypeError):
        rc.VERSIONS["hz-rules-v2"] = rc.HZ_RULES_V1  # type: ignore[index]
    with pytest.raises(TypeError):
        del rc.VERSIONS["hz-rules-v1"]  # type: ignore[attr-defined]


def test_a_version_cannot_be_edited():
    rule = rc.rule_for(10)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.research_only = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rc.active().version = "x"  # type: ignore[misc]
    assert isinstance(rc.active().rules, tuple)


def test_the_fingerprint_is_stable_and_changes_with_any_rule():
    v1 = rc.HZ_RULES_V1
    assert v1.sha256 == rc.get_version("hz-rules-v1").sha256
    changed = rc.ResearchConfigVersion(
        "hz-rules-v1", tuple(dataclasses.replace(r, stop_pct=r.stop_pct + 0.01) for r in v1.rules)
    )
    assert changed.sha256 != v1.sha256
    flipped = rc.ResearchConfigVersion(
        "hz-rules-v1", tuple(dataclasses.replace(r, research_only=False) for r in v1.rules)
    )
    assert flipped.sha256 != v1.sha256


def test_unknown_version_or_horizon_is_an_error_never_a_guess():
    with pytest.raises(rc.ResearchConfigError):
        rc.get_version("hz-rules-v9")
    with pytest.raises(rc.ResearchConfigError):
        rc.rule_for(7)


def test_the_workflow_policies_match_the_config():
    for h in (5, 10, 15):
        rule, policy = rc.rule_for(h), DEFAULT_POLICIES[h]
        assert (rule.target_pct, rule.stop_pct, rule.half_out_pct, rule.max_sessions) == (
            policy.target_pct,
            policy.stop_pct,
            policy.half_out_pct,
            policy.max_sessions,
        )


def test_the_module_imports_nothing_from_the_app():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(rc.__file__).read_text(encoding="utf8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith("swing_trade_ml") for m in imported)
