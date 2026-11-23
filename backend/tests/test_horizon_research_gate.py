# ruff: noqa: E501 (long lines in test code)
"""10D and 15D are research-only (#387): the gate, as tests. No database, no clock.

Research-only means: owner-only screens, no Brain decision input, off unless the owner configures a model, and the
rules come from one versioned config. These tests fail if a new importer or a new route would open a 10D or 15D
record to a customer screen or to a Brain decision.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import swing_trade_ml
from swing_trade_ml.core import research_config
from swing_trade_ml.services import lane_slots

SRC = Path(swing_trade_ml.__file__).parent
LANE_MODULES = ("swing_trade_ml.shadow_lanes", "swing_trade_ml.db.models.lane_shadow", "swing_trade_ml.services.lane_slots")
HORIZON_MODULES = (
    "swing_trade_ml.brain.horizons",
    "swing_trade_ml.brain.lanes",
    "swing_trade_ml.services.horizon_records",
    "swing_trade_ml.db.models.horizon",
)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _importers(prefixes: tuple[str, ...]) -> set[str]:
    return {
        _rel(p)
        for p in SRC.rglob("*.py")
        if any(m == pre or m.startswith(pre + ".") for m in _imports(p) for pre in prefixes)
    }


def test_five_day_slots_come_from_the_research_config():
    rule = research_config.rule_for(5)
    for key in ("5d-large-v1", "5d-midcap-v1"):
        slot = lane_slots.get(key)
        assert slot is not None and slot.horizon == 5
        assert (slot.target, slot.stop, slot.half_out) == (rule.target_pct, rule.stop_pct, rule.half_out_pct)
    assert not research_config.is_research_only(5)


def test_every_registered_10d_and_15d_slot_is_research_only():
    for slot in lane_slots.all_slots():
        rule = research_config.rule_for(slot.horizon)
        assert (slot.target, slot.stop, slot.half_out) == (rule.target_pct, rule.stop_pct, rule.half_out_pct)
        if slot.horizon in (10, 15):
            assert research_config.is_research_only(slot.horizon)


def test_no_slot_is_allowed_to_take_a_production_model():
    from swing_trade_ml.shadow_lanes import lane_job

    assert frozenset() == lane_job.PROD_ALLOWED_SLOTS


def test_no_brain_decision_path_reads_lane_or_horizon_records():
    """The Brain's decision modules, its run service, fallbacks, reader and the brain strategy import none of it."""
    decision = [
        *SRC.glob("brain/modules/**/*.py"),
        SRC / "brain/service.py",
        SRC / "brain/fallbacks.py",
        SRC / "brain/reader.py",
        SRC / "brain/runner.py",
        SRC / "brain/contracts.py",
        SRC / "strategies/brain.py",
    ]
    assert len(decision) > 20
    bad = {
        _rel(p): sorted(m for m in _imports(p) if any(m == x or m.startswith(x + ".") for x in (*LANE_MODULES, *HORIZON_MODULES)))
        for p in decision
        if p.exists()
    }
    assert {k: v for k, v in bad.items() if v} == {}


def test_only_known_owner_only_files_read_lane_records():
    allowed_api = {"api/v1/endpoints/lanes.py"}
    api_importers = {p for p in _importers(LANE_MODULES) if p.startswith("api/")}
    assert api_importers <= allowed_api, f"a new route file reads lane records: {sorted(api_importers - allowed_api)}"
    outside = {p for p in _importers(("swing_trade_ml.brain.horizons",)) if not p.startswith("brain/horizons/")}
    assert outside == set(), f"live code imports the horizon workflows: {sorted(outside)}"


@pytest.mark.parametrize("name", ["lanes", "lane_picks", "h05", "weekly_report"])
def test_the_lane_routers_are_owner_only(name):
    import importlib

    from swing_trade_ml.api.deps import require_owner

    router = importlib.import_module(f"swing_trade_ml.api.v1.endpoints.{name}").router
    assert require_owner in {d.dependency for d in router.dependencies}


def test_nothing_reads_horizon_records_yet_outside_its_own_service():
    """Records of all three horizons live in one table; the service is the only door, and nothing calls it yet.
    A new caller must be added here on purpose, and must use `product_records`, which leaves 10D and 15D out."""
    importers = _importers(("swing_trade_ml.services.horizon_records",))
    # research simulation reads 5D records through the service; it is admin-only and never a customer route
    allowed = {"simulation/source.py"}
    assert importers <= allowed, f"new readers of horizon records: {sorted(importers - allowed)}"
    table_importers = _importers(("swing_trade_ml.db.models.horizon",)) - {"services/horizon_records.py"}
    assert table_importers <= {"db/models/__init__.py"}, sorted(table_importers)


# Every module outside the lane and horizon packages that reads their records or tables, pinned. A new reader anywhere
# (api, services, brain, workers) fails here until it is added on purpose, with its owner-only proof below.
KNOWN_READERS = {
    "swing_trade_ml.shadow_lanes": {"api/v1/endpoints/lanes.py", "brain/prediction_reliability.py", "workers/scheduler.py"},
    "swing_trade_ml.db.models.lane_shadow": {"api/v1/endpoints/lanes.py", "brain/prediction_reliability.py", "db/models/__init__.py"},
    "swing_trade_ml.services.lane_slots": {"services/model_registry.py"},
    "swing_trade_ml.brain.lanes": {"api/v1/endpoints/h05.py", "brain/eligibility_report.py", "workers/scheduler.py"},
    "swing_trade_ml.db.models.lanes": {
        "api/v1/endpoints/lane_picks.py",
        "brain/eligibility_report.py",
        "brain/prediction_reliability.py",
        "db/models/__init__.py",
        "services/weekly_paper_report.py",
    },
}


@pytest.mark.parametrize("prefix", sorted(KNOWN_READERS))
def test_no_new_reader_of_lane_records_in_api_services_brain_or_workers(prefix):
    own = ("shadow_lanes/", "brain/lanes/", "brain/horizons/")
    found = {p for p in _importers((prefix,)) if not p.startswith(own)}
    assert found <= KNOWN_READERS[prefix], f"new reader of {prefix}: {sorted(found - KNOWN_READERS[prefix])}"


def test_the_readers_that_serve_a_route_are_owner_only():
    """The pinned readers that can reach a screen or a route: lanes, lane_picks, h05 (routers) and the weekly report."""
    from swing_trade_ml.api.deps import require_owner
    from swing_trade_ml.api.v1.endpoints import h05, lane_picks, lanes, weekly_report

    for module in (lanes, lane_picks, h05, weekly_report):
        assert require_owner in {d.dependency for d in module.router.dependencies}, module.__name__
    # the other pinned readers are reports and jobs that no route imports
    served = set(_importers(("swing_trade_ml.brain.prediction_reliability", "swing_trade_ml.brain.eligibility_report")))
    assert served == set(), sorted(served)
