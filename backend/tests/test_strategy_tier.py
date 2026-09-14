"""Cap-tier convention shared by signals.py and the new strategies/performance
endpoint — see docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5a."""

from __future__ import annotations

from swing_trade_ml.strategies.tier import cap_tier


def test_default_model_name_is_large_cap():
    assert cap_tier("swing_classifier") == "large"


def test_midcap_model_name():
    assert cap_tier("swing_classifier_midcap") == "midcap"


def test_smallcap_model_name():
    assert cap_tier("swing_classifier_smallcap") == "smallcap"


def test_none_falls_back_to_large():
    assert cap_tier(None) == "large"
