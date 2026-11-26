# ruff: noqa: E501 (long plain-English test text)
"""#259: the steps for adding a model or a data connector, walked in tests on the test database.

Verification only: no behaviour changes, nothing is activated, no connector is added to the real list. Every model row, file,
slot and feed below is private to the test (a temporary model folder, rolled-back rows, monkeypatched lists).
Findings and the how-to checklist: docs/verification/259-add-model-connector.md.

Existing coverage cited, not repeated: test_model_artifact_safety.py (version allocation, file checks), test_model_promotion_switch.py
(promotion switch), test_model_role.py and test_lane_slots.py (roles and slots), test_horizon_guard.py (mixed horizons),
test_research_config.py (pinned rules), test_module_registry*.py (module contract), test_brain_m01_quality.py (feed lines).
"""

from __future__ import annotations

from datetime import date

import pytest

from swing_trade_ml.core import research_config
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.core.modules import (
    CoreModuleError,
    DependencyError,
    Module,
    ModuleState,
    ModuleSwitches,
    RegistryError,
    validate,
)
from swing_trade_ml.db.models.feeds import DailyDelivery
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml import registry
from swing_trade_ml.ml.features import FEATURE_COLUMNS
from swing_trade_ml.services import lane_slots, model_registry

_tokens = iter(range(995_100, 995_900))
GAP = {"strict": True, "raises": AssertionError}
API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}


@pytest.fixture()
def model_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    return tmp_path


def publish(db, name, *, features=None, horizon=15, status=ModelStatus.TRAINED, **kw) -> MLModel:
    """Step 1 of adding a model, the way the trainers do it: next version, file published once, row with its hash."""
    features = list(FEATURE_COLUMNS[:5]) if features is None else features
    version = registry.next_version(db, name)
    path = registry.save_artifact(name, version, {"estimator": None, "feature_names": features})
    row = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=status,
        artifact_path=path,
        feature_names=features,
        prediction_horizon_days=horizon,
        metrics={"artifact_sha256": registry.artifact_sha256(path)},
        **kw,
    )
    db.add(row)
    db.flush()
    return row


# ====================================================================== adding a model


def test_step_1_registering_a_model_stores_its_version_horizon_features_and_file_and_it_loads_cleanly(db_session, model_dir):
    row = publish(db_session, "m259_new", horizon=5)
    assert (row.version, row.prediction_horizon_days, row.feature_names) == ("v1", 5, list(FEATURE_COLUMNS[:5]))
    assert registry.load_model_artifact(row)["feature_names"] == row.feature_names
    assert publish(db_session, "m259_new", horizon=5).version == "v2"  # the next version is never reused


def test_step_2_registering_activates_and_promotes_nothing(db_session, model_dir):
    incumbent = publish(db_session, "m259_live", status=ModelStatus.ACTIVE)
    new = publish(db_session, "m259_live")
    db_session.refresh(incumbent)
    assert new.status == ModelStatus.TRAINED and new.activated_at is None
    assert incumbent.status == ModelStatus.ACTIVE
    assert registry.get_active_model(db_session, "m259_live").id == incumbent.id  # scoring still uses the old one


def test_step_2b_a_registered_model_is_unassigned_to_any_research_slot_until_its_name_and_horizon_are_known(db_session, model_dir):
    assert model_registry.slot_for("m259_anything", 5) is None  # a name is never guessed into a cap group
    assert model_registry.slot_for("swing_classifier", 7) is None  # an unknown horizon is never guessed
    assert model_registry.slot_for("swing_classifier", 15) == "15d-large"
    assert model_registry.role_of(publish(db_session, "m259_roleless"))["role"] == "unmarked"  # never "final" by itself


def test_step_3_a_file_that_is_not_the_one_its_row_describes_is_refused(db_session, model_dir):
    row = publish(db_session, "m259_check")
    row.feature_names = [*row.feature_names, "extra_input"]  # the row says more inputs than the file has
    with pytest.raises(registry.ArtifactMismatchError, match="inputs differ"):
        registry.load_model_artifact(row)
    row.feature_names = list(FEATURE_COLUMNS[:5])
    row.version = "v9"
    with pytest.raises(registry.ArtifactMismatchError, match="belongs to"):
        registry.load_model_artifact(row)
    row.version = "v1"
    row.metrics = {"artifact_sha256": "0" * 64}
    with pytest.raises(registry.ArtifactMismatchError, match="hash"):
        registry.load_model_artifact(row)
    row.artifact_path = str(model_dir / "no_such_file.joblib")
    with pytest.raises(registry.ArtifactMismatchError, match="missing"):
        registry.load_model_artifact(row)


def test_step_3b_a_model_file_is_never_overwritten(db_session, model_dir):
    row = publish(db_session, "m259_once")
    with pytest.raises(FileExistsError):
        registry.save_artifact(row.name, row.version, {"estimator": None, "feature_names": []})


def test_step_4_activation_needs_a_trained_model_with_a_matching_file_and_leaves_the_incumbent_when_it_refuses(db_session, model_dir):
    incumbent = publish(db_session, "m259_act", status=ModelStatus.ACTIVE)
    failed = publish(db_session, "m259_act", status=ModelStatus.FAILED)
    with pytest.raises(ValueError, match="Cannot activate"):
        registry.activate_model(db_session, failed.id)
    broken = publish(db_session, "m259_act")
    broken.feature_names = ["different"]
    with pytest.raises(registry.ArtifactMismatchError):
        registry.activate_model(db_session, broken.id)
    db_session.refresh(incumbent)
    assert incumbent.status == ModelStatus.ACTIVE and broken.status == ModelStatus.TRAINED


def test_step_4b_activating_archives_only_the_same_names_incumbent(db_session, model_dir):
    mine, other = publish(db_session, "m259_mine", status=ModelStatus.ACTIVE), publish(db_session, "m259_other", status=ModelStatus.ACTIVE)
    new = publish(db_session, "m259_mine")
    registry.activate_model(db_session, new.id)
    db_session.refresh(mine)
    db_session.refresh(other)
    assert (new.status, mine.status, other.status) == (ModelStatus.ACTIVE, ModelStatus.ARCHIVED, ModelStatus.ACTIVE)


def test_step_5_promotion_through_the_api_is_refused_while_the_promotion_switch_is_off(client, db_session, model_dir):
    row = publish(db_session, "m259_api")
    response = client.post(f"{API}/ml/models/{row.id}/activate", headers=KEY)
    assert response.status_code == 403, response.text
    assert row.status == ModelStatus.TRAINED


# ----- research-only: slots and the pinned research rules


def test_step_6_the_pinned_research_rules_say_which_horizons_are_research_only():
    rules = {r.horizon: r.research_only for r in research_config.VERSIONS[research_config.ACTIVE_VERSION].rules}
    assert rules == {5: False, 10: True, 15: True}
    with pytest.raises(research_config.ResearchConfigError):
        research_config.rule_for(7)


def test_step_6b_adding_a_slot_is_validated_and_enables_nothing(monkeypatch):
    def slot(**kw):
        base = {"key": "10d-midcap", "horizon": 10, "tier": "midcap", "universe_group": "mid", "target": 0.06, "stop": 0.035, "half_out": None, "prefixes": ("t259_",), "protocol": "t-protocol", "dormant": True}
        return lane_slots.LaneSlot(**{**base, **kw})

    before = lane_slots.all_slots()
    for bad in (
        slot(horizon=7, key="7d-midcap"),  # unknown horizon
        slot(tier="micro", key="10d-micro"),  # unknown tier
        slot(key="10d-other"),  # key not built from horizon and tier
        slot(prefixes=("t259",)),  # no trailing underscore
        slot(prefixes=("td_h10_x_",)),  # overlaps an existing prefix
        slot(target=0.07),  # a different pinned rule for an existing horizon
        slot(key="10d-large"),  # already exists
    ):
        with pytest.raises(lane_slots.SlotConfigError):
            lane_slots.register(bad)
    assert lane_slots.all_slots() == before  # a refused entry changes nothing
    lane_slots.register(slot())
    try:
        assert lane_slots.get("10d-midcap").dormant is True
        assert model_registry.slot_for("t259_model", 10) == "10d-midcap"  # the registry now recognises the name...
        assert settings.LANE_SHADOW_ENABLED is False and settings.LANE_SHADOW_MODELS == ""  # ...but no lane runs
    finally:
        lane_slots.unregister("10d-midcap")
    assert model_registry.slot_for("t259_model", 10) is None


def test_step_7_the_horizon_guard_refuses_a_mixed_or_unknown_horizon():
    from swing_trade_ml.brain.horizons.guard import check_score_for_horizon

    assert check_score_for_horizon("m", 5, 5).ok
    assert not check_score_for_horizon("m", 5, 15).ok and "No decision for this horizon" in check_score_for_horizon("m", 5, 15).reason
    assert not check_score_for_horizon("m", None, 5).ok


# ----- gaps: a step that lets something unsafe through


def _activation_refused(db, row) -> bool:
    try:
        registry.activate_model(db, row.id)
    except ValueError:
        return True
    return False


@pytest.mark.xfail(**GAP, reason="gap g1: activating a model does not check that its inputs exist in the live feature pipeline, so a model with an unknown input can become the active model")
def test_activation_refuses_a_model_whose_inputs_the_live_pipeline_does_not_produce(db_session, model_dir):
    row = publish(db_session, "m259_unknown_input", features=["not_a_real_feature_259"])
    assert _activation_refused(db_session, row), "activated although the live pipeline cannot produce its input"


@pytest.mark.xfail(**GAP, reason="gap g2: activation does not compare the model's horizon with the horizon of the name it replaces, so a 10-day model can replace the 15-day base model")
def test_activation_refuses_a_model_whose_horizon_differs_from_the_one_it_replaces(db_session, model_dir):
    publish(db_session, "m259_base", horizon=15, status=ModelStatus.ACTIVE)
    ten_day = publish(db_session, "m259_base", horizon=10)
    assert _activation_refused(db_session, ten_day), "a 10-day model replaced the 15-day base model"


@pytest.mark.xfail(**GAP, reason="gap g3: a model row registered without a horizon is stored as 15 days, not as unknown, so a 5-day model can pass as a 15-day one")
def test_a_model_registered_without_a_horizon_is_unknown_not_fifteen(db_session):
    row = MLModel(name="m259_nohorizon", version="v1", algorithm="lightgbm", status=ModelStatus.TRAINED)
    db_session.add(row)
    db_session.flush()
    assert row.prediction_horizon_days is None


# ====================================================================== adding a data connector


from brain_fakes import registry as brain_registry  # noqa: E402
from swing_trade_ml.brain import contracts as c  # noqa: E402
from swing_trade_ml.brain import reader as reader_module  # noqa: E402
from swing_trade_ml.brain.connectors import FeedSource, _latest  # noqa: E402
from swing_trade_ml.brain.modules.m01_quality.module import DataGateway  # noqa: E402
from swing_trade_ml.brain.reader import DatedReader  # noqa: E402
from swing_trade_ml.brain.runner import execute  # noqa: E402
from test_brain_m01_module import AS_OF, FRI, _add_bars  # noqa: E402


@pytest.fixture()
def world(db_session, monkeypatch):
    """The fresh-market setup of test_brain_m01_module.py: a benchmark with bars, entries switched on, room to deploy."""
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.safety import SystemState
    from swing_trade_ml.services import deployable

    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )
    if db_session.get(SystemState, 1) is None:
        db_session.add(SystemState(id=1, new_entries_enabled=True, exits_enabled=True))
    if not db_session.query(Instrument).filter_by(tradingsymbol=settings.BENCHMARK_INDEX_SYMBOL).count():
        _add_bars(db_session, settings.BENCHMARK_INDEX_SYMBOL, 995_000, FRI, n=260, close=25_000.0)
    db_session.commit()
    return db_session


def _quality_with_feed(db, monkeypatch, feed: FeedSource, symbol="CN259"):
    monkeypatch.setattr(reader_module, "FEEDS", (*reader_module.FEEDS, feed))
    _add_bars(db, symbol, next(_tokens), FRI)
    db.commit()
    req = c.RunRequest(run_id="t", kind="nightly", as_of=AS_OF, universe=(symbol,), live=True)
    return execute(req, DatedReader(db, as_of=AS_OF, live=True), brain_registry(DataGateway), {}).quality["*"]


def test_a_new_feed_is_one_entry_and_the_quality_check_then_reports_it_when_it_is_empty_or_behind(world, monkeypatch):
    empty = _quality_with_feed(world, monkeypatch, FeedSource("licensed news", lambda db, upto: None))
    assert "The licensed news feed has no data yet." in empty.issues
    behind = _quality_with_feed(world, monkeypatch, FeedSource("licensed news", lambda db, upto: date(2026, 9, 16)), symbol="CN259B")
    assert any("licensed news feed is" in i and "behind" in i for i in behind.issues)


def test_a_late_new_feed_is_reported_but_does_not_stop_trading_so_a_connector_that_must_gate_needs_its_own_rule(world, monkeypatch):
    quality = _quality_with_feed(world, monkeypatch, FeedSource("licensed news", lambda db, upto: None))
    assert quality.fresh is True  # side feeds only add an issue line: gating is a decision the new connector must add


def test_a_feed_that_uses_the_shared_latest_helper_ignores_rows_dated_after_the_run(world, monkeypatch):
    world.add(DailyDelivery(symbol="CN259D", series="EQ", trade_date=FRI, delivery_pct=50.0))
    world.add(DailyDelivery(symbol="CN259D", series="EQ", trade_date=date(2026, 9, 29), delivery_pct=50.0))  # after the run
    world.flush()
    feed = FeedSource("deliveries test", _latest(DailyDelivery.trade_date))
    monkeypatch.setattr(reader_module, "FEEDS", (feed,))
    latest = DatedReader(world, as_of=AS_OF, live=True).feed_latest()
    assert latest == {"deliveries test": FRI}  # the Tuesday row after the run is not seen


@pytest.mark.xfail(**GAP, reason="gap g4: a connector that reports a day after the run date is treated as fresh and nothing is said; only connectors built with the shared helper are bounded by the run date")
def test_a_feed_that_claims_a_day_after_the_run_date_is_flagged(world, monkeypatch):
    quality = _quality_with_feed(world, monkeypatch, FeedSource("licensed news", lambda db, upto: date(2026, 10, 30)), symbol="CN259F")
    assert any("licensed news" in i for i in quality.issues), quality.issues


# ====================================================================== adding an optional module


def test_a_new_optional_module_is_one_declaration_and_the_registry_enforces_the_rules_for_it():
    registry_ = (
        Module("core.x", "Core", core=True, route_prefixes=("/x",)),
        Module("feed.news", "News feed", route_prefixes=("/news",), jobs=("news_pull",)),
        Module("feed.news_ui", "News screens", route_prefixes=("/news-ui",), depends_on=("feed.news",)),
    )
    switches = ModuleSwitches(registry_)
    assert switches.enabled("feed.news") and switches.enabled("feed.news_ui")  # on by default: adding one changes nothing
    with pytest.raises(DependencyError):
        switches.set_enabled("feed.news", False, by="owner", reason="t")  # a dependent is still on
    switches.set_enabled("feed.news_ui", False, by="owner", reason="t")
    switches.set_enabled("feed.news", False, by="owner", reason="t")
    assert switches.jobs_to_skip() == {"news_pull"} and switches.enabled("core.x")
    with pytest.raises(CoreModuleError):
        switches.set_enabled("core.x", False, by="owner", reason="t")
    assert any(e["module"] == "feed.news" and e["outcome"].startswith("refused") for e in switches.events)  # the refusal is recorded


def test_a_declaration_that_breaks_the_rules_is_refused_before_the_app_starts():
    with pytest.raises(RegistryError):  # a core module may not depend on an optional one
        validate((Module("a", "A"), Module("core.x", "Core", core=True, depends_on=("a",))))
    with pytest.raises(RegistryError):  # an unknown dependency
        validate((Module("a", "A", depends_on=("nope",)),))
    assert ModuleState.DEVELOPMENT.value == "development"  # a module under development is off until the owner says so
    assert Module("dev", "Dev", state=ModuleState.DEVELOPMENT).default_enabled is False
