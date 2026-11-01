# ruff: noqa: E501 (long test sentences)
"""Model registry, phase 1: strict mapping, honest status and usage, stored-only provenance, deterministic
priorities, owner-only access, a write that touches nothing else, and isolation from the brain and activation."""

from __future__ import annotations

import ast
import builtins
import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select, text

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.registry import ModelResearchSlot
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import model_registry as svc

PKG = Path(svc.__file__).resolve().parents[1]
MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261101_1200_model_research_slots.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("mrs_migration", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seed(db):
    for key, horizon, tier, status, priority in _migration().SEED:
        db.add(
            ModelResearchSlot(
                slot_key=key,
                horizon_days=horizon,
                cap_tier=tier,
                research_status=status,
                priority=priority,
                version=1,
            )
        )
    db.flush()


def model(db, name="swing_classifier", version="v1", horizon=5, status="ACTIVE", **kw):
    m = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=status,
        prediction_horizon_days=horizon,
        feature_names=kw.pop("feature_names", ["a", "b", "c"]),
        training_symbols=kw.pop("training_symbols", ["X", "Y"]),
        **kw,
    )
    db.add(m)
    db.flush()
    return m


def strategy(db, name, model_name=None, active=True, strategy_type="ml_swing"):
    params = {} if model_name is None else {"model_name": model_name}
    s = Strategy(name=name, strategy_type=strategy_type, params=params, is_active=active)
    db.add(s)
    db.flush()
    return s


def headers(db, role):
    u = User(
        username=f"reg-{role}",
        hashed_password="x",
        is_active=True,
        is_superuser=role == "owner",
        plan="pro",
        role=role,
    )
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


@pytest.fixture()
def reg(db_session):
    seed(db_session)
    return db_session


# --------------------------------------------------------------- 1. strict mapping


@pytest.mark.parametrize(
    ("name", "horizon", "slot"),
    [
        ("swing_classifier", 5, "5d-large"),
        ("swing_classifier_midcap", 5, "5d-midcap"),
        ("swing_classifier_smallcap", 15, "15d-smallcap"),
        ("swing_classifier", 10, "10d-large"),
    ],
)
def test_verified_names_map_to_their_slot(name, horizon, slot):
    assert svc.slot_for(name, horizon) == slot


@pytest.mark.parametrize(
    ("name", "horizon"),
    [
        ("wf_h15_20260101", 15),  # experimental
        ("swing_classifier_barrier", 15),  # looks like large, but not a verified name
        ("swing_classifier_midcap_barrier_cal", 15),
        ("swing_classifier_v2", 5),
        ("Swing_Classifier", 5),
        ("swing_classifier", 7),  # not one of the three horizons
        ("swing_classifier", None),
        (None, 5),
        ("", 5),
    ],
)
def test_unknown_or_experimental_names_stay_unassigned_never_guessed(name, horizon):
    assert svc.slot_for(name, horizon) is None


def test_the_list_puts_experiments_in_a_read_only_unassigned_section(reg):
    a = model(reg, "swing_classifier_midcap", "v2", horizon=5)
    b = model(reg, "wf_h15_20260101", "v1", horizon=15, status="TRAINED")
    out = svc.list_slots(reg)
    assert len(out["slots"]) == 9
    mid5 = next(s for s in out["slots"] if s["slot_key"] == "5d-midcap")
    assert [m["provenance"]["model_id"] for m in mid5["models"]] == [a.id]
    assert [m["provenance"]["model_id"] for m in out["unassigned"]] == [b.id]
    assert all(m["slot"] is None for m in out["unassigned"])


# --------------------------------------------------------------- 2. registry status vs strategy usage


def test_an_active_model_with_no_strategy_is_not_reported_as_used(reg):
    m = model(reg, status="ACTIVE")
    v = svc.model_view(m, svc.active_strategy_usage(reg))
    assert v["registry_status"] == "ACTIVE" and v["active_strategies"] == []
    assert "deployed" not in str(v).lower()  # no merged "Deployed / Not deployed" label


def test_usage_lists_only_active_ml_swing_strategies_naming_the_model(reg):
    m = model(reg, "swing_classifier_midcap", horizon=5)
    strategy(reg, "mid-live", "swing_classifier_midcap")
    strategy(reg, "mid-off", "swing_classifier_midcap", active=False)
    strategy(reg, "other-model", "swing_classifier_smallcap")
    strategy(reg, "sma", "swing_classifier_midcap", strategy_type="sma_crossover")
    v = svc.model_view(m, svc.active_strategy_usage(reg))
    assert [u["strategy"] for u in v["active_strategies"]] == ["mid-live"]


def test_an_older_version_of_the_same_name_is_not_credited_with_the_strategy(reg):
    new = model(reg, version="v2", status="ACTIVE")
    old = model(reg, version="v1", status="ARCHIVED")
    strategy(reg, "large-live", "swing_classifier")
    usage = svc.active_strategy_usage(reg)
    assert [u["strategy"] for u in svc.model_view(new, usage)["active_strategies"]] == ["large-live"]
    assert svc.model_view(old, usage)["active_strategies"] == []


def test_a_strategy_with_no_model_name_uses_the_default_model_like_the_strategy_itself(reg):
    m = model(reg)
    strategy(reg, "default-live", None)
    assert [
        u["strategy"] for u in svc.model_view(m, svc.active_strategy_usage(reg))["active_strategies"]
    ] == ["default-live"]


def test_the_real_question_suffix_is_applied_the_way_the_strategy_applies_it(reg, monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "ML_REAL_QUESTION_SUFFIX", "_barrier_cal")
    base = model(reg, "swing_classifier", horizon=15)
    cal = model(reg, "swing_classifier_barrier_cal", horizon=15)
    strategy(reg, "large-live", "swing_classifier")
    usage = svc.active_strategy_usage(reg)
    assert svc.model_view(base, usage)["active_strategies"] == []
    assert [u["strategy"] for u in svc.model_view(cal, usage)["active_strategies"]] == ["large-live"]


def test_unreadable_strategies_mean_unknown_not_empty(reg):
    v = svc.model_view(model(reg), None)
    assert v["active_strategies"] is None and "Unknown" in v["active_strategies_note"]


# --------------------------------------------------------------- 3. provenance is stored-only


def test_the_model_file_is_never_opened_and_its_fingerprint_is_unknown_unless_stored(
    reg, monkeypatch, tmp_path
):
    f = tmp_path / "m.joblib"
    f.write_bytes(b"x")
    m = model(reg, artifact_path=str(f))

    def boom(*a, **k):
        raise AssertionError("the model file must not be read")

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(Path, "open", boom)
    monkeypatch.setattr(Path, "read_bytes", boom)
    assert svc.provenance(m)["model_file_fingerprint"] == "Unknown"


def test_a_stored_file_fingerprint_is_shown_as_stored(reg):
    m = model(reg, metrics={"artifact_sha256": "ab" * 32, "calibration": {"x": 1}})
    p = svc.provenance(m)
    assert p["model_file_fingerprint"] == "ab" * 32 and p["calibration"] == "Calibrated"


def test_calibration_is_unknown_without_metrics_and_not_recorded_when_absent(reg):
    assert svc.provenance(model(reg, "swing_classifier", "v1", metrics={}))["calibration"] == "Unknown"
    assert (
        svc.provenance(model(reg, "swing_classifier", "v2", metrics={"roc_auc": 0.6}))["calibration"]
        == "No calibration recorded"
    )


def test_input_and_universe_fingerprints_are_deterministic_and_react_to_changes(reg):
    a = svc.provenance(
        model(reg, "swing_classifier", "v1", feature_names=["a", "b"], training_symbols=["Y", "X"])
    )
    b = svc.provenance(
        model(reg, "swing_classifier", "v2", feature_names=["a", "b"], training_symbols=["X", "Y"])
    )
    c = svc.provenance(
        model(reg, "swing_classifier", "v3", feature_names=["b", "a"], training_symbols=["X", "Y", "Z"])
    )
    assert (
        a["inputs_fingerprint"] == b["inputs_fingerprint"]
        and a["training_universe_fingerprint"] == b["training_universe_fingerprint"]
    )
    assert (
        c["inputs_fingerprint"] != a["inputs_fingerprint"]
        and c["training_universe_fingerprint"] != a["training_universe_fingerprint"]
    )


def test_an_empty_model_shows_none_for_what_is_not_stored(reg):
    p = svc.provenance(model(reg, feature_names=[], training_symbols=[]))
    assert (
        p["n_inputs"] is None
        and p["inputs_fingerprint"] is None
        and p["train_end"] is None
        and p["n_samples"] is None
    )


# --------------------------------------------------------------- 5. metrics honesty


def test_missing_metrics_are_none_not_zero_and_replay_blocks_are_never_filled(reg):
    e = svc.evidence(model(reg, roc_auc=None))
    h = e["historical"]
    assert h["held_out_auc"]["value"] is None and h["precision_at_threshold"]["value"] is None
    for k in ("top5_ranking", "net_return_after_costs", "drawdown"):
        assert h[k]["value"] is None and h[k]["note"] == "Not measured"
    assert "top-5" in h["held_out_auc"]["label"].lower() and "not top-5" in h["held_out_auc"]["label"].lower()
    assert e["forward"]["value"] is None


def test_a_stored_auc_is_shown_as_is(reg):
    assert svc.evidence(model(reg, roc_auc=0.61))["historical"]["held_out_auc"]["value"] == 0.61


# --------------------------------------------------------------- 4. priorities: deterministic, versioned


def order(db):
    return [s["slot_key"] for s in svc.list_slots(db)["slots"]]


def test_the_seeded_order_is_the_owners_and_unranked_slots_follow_in_a_fixed_order(reg):
    assert order(reg) == [
        "15d-large", "15d-midcap", "10d-large",
        "15d-smallcap", "10d-midcap", "10d-smallcap", "5d-large", "5d-midcap", "5d-smallcap",
    ]  # fmt: skip
    st = {s["slot_key"]: s["research_status"] for s in svc.list_slots(reg)["slots"]}
    assert st["5d-large"] == st["5d-midcap"] == st["5d-smallcap"] == "researching"
    assert st["15d-large"] == "not_started"


def test_duplicate_priorities_are_allowed_and_ordered_deterministically(reg):
    for key in ("5d-smallcap", "10d-midcap", "15d-smallcap"):
        v = reg.get(ModelResearchSlot, key).version
        svc.update_slot(reg, key, v, svc.Change(priority_set=True, priority=1), None, "owner")
    first = order(reg)
    assert first[:4] == [
        "15d-large",
        "15d-smallcap",
        "10d-midcap",
        "5d-smallcap",
    ]  # all priority 1: longer horizon first
    assert order(reg) == first  # same answer every time


def test_priority_can_be_cleared_and_must_be_in_range(reg):
    v = reg.get(ModelResearchSlot, "15d-large").version
    out = svc.update_slot(reg, "15d-large", v, svc.Change(priority_set=True, priority=None), None, "owner")
    assert out["priority"] is None and out["version"] == v + 1
    for bad in (0, 10, -1):
        with pytest.raises(svc.InvalidChange):
            svc.update_slot(
                reg, "15d-large", out["version"], svc.Change(priority_set=True, priority=bad), None, "owner"
            )


def test_a_stale_update_is_refused_and_the_first_change_survives(reg):
    v = reg.get(ModelResearchSlot, "10d-large").version
    svc.update_slot(reg, "10d-large", v, svc.Change(note_set=True, note="first owner"), None, "a")
    with pytest.raises(svc.VersionConflict) as exc:
        svc.update_slot(reg, "10d-large", v, svc.Change(note_set=True, note="second owner"), None, "b")
    assert exc.value.current["note"] == "first owner" and exc.value.current["version"] == v + 1
    assert reg.get(ModelResearchSlot, "10d-large").note == "first owner"


def test_status_and_note_validation(reg):
    v = reg.get(ModelResearchSlot, "10d-large").version
    with pytest.raises(svc.InvalidChange):
        svc.update_slot(
            reg, "10d-large", v, svc.Change(status="validated"), None, "o"
        )  # not a research label
    with pytest.raises(svc.InvalidChange):
        svc.update_slot(reg, "10d-large", v, svc.Change(note_set=True, note="x" * 2001), None, "o")
    with pytest.raises(svc.InvalidChange):
        svc.update_slot(reg, "10d-large", v, svc.Change(), None, "o")
    with pytest.raises(LookupError):
        svc.update_slot(reg, "99d-nothing", 1, svc.Change(status="paused"), None, "o")
    assert "validated" not in svc.RESEARCH_STATUSES and "active" not in svc.RESEARCH_STATUSES


# --------------------------------------------------------------- 5. the write changes nothing else


def _counts(db):
    out = {}
    for t in (
        "ml_models",
        "strategies",
        "predictions",
        "signals",
        "orders",
        "positions",
        "trades",
        "instruments",
    ):
        out[t] = db.execute(text(f"select count(*) from {t}")).scalar()
    return out


def test_changing_status_priority_and_note_touches_only_the_slot_and_the_audit_log(client, reg, monkeypatch):
    model(reg)
    strategy(reg, "live", "swing_classifier")
    own = headers(reg, "owner")

    import swing_trade_ml.ml.registry as ml_registry

    def boom(*a, **k):
        raise AssertionError("must never be called")

    monkeypatch.setattr(ml_registry, "activate_model", boom)
    before = _counts(reg)
    audits = reg.scalar(select(func.count()).select_from(AuditLog))
    snapshot = (
        reg.execute(select(MLModel.id, MLModel.status)).all(),
        reg.execute(select(Strategy.id, Strategy.is_active)).all(),
    )
    v = reg.get(ModelResearchSlot, "15d-large").version
    r = client.patch(
        "/api/v1/model-registry/slots/15d-large",
        headers=own,
        json={
            "expected_version": v,
            "research_status": "researching",
            "priority": 4,
            "note": "start with large caps",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["research_status"], body["priority"], body["note"], body["version"]) == (
        "researching",
        4,
        "start with large caps",
        v + 1,
    )
    assert _counts(reg) == before
    assert reg.scalar(select(func.count()).select_from(AuditLog)) == audits + 1
    assert (
        reg.execute(select(MLModel.id, MLModel.status)).all(),
        reg.execute(select(Strategy.id, Strategy.is_active)).all(),
    ) == snapshot
    row = reg.scalars(select(AuditLog).where(AuditLog.action == "model_slot.update")).one()
    assert row.target_id == "15d-large" and row.after["priority"] == 4


def test_changing_the_label_to_researching_does_not_change_what_the_slot_reports_about_models(reg):
    model(reg, "swing_classifier", horizon=15, status="TRAINED")
    before = svc.list_slots(reg)["slots"][0]["models"]
    v = reg.get(ModelResearchSlot, "15d-large").version
    svc.update_slot(reg, "15d-large", v, svc.Change(status="researching"), None, "o")
    assert svc.list_slots(reg)["slots"][0]["models"] == before


# --------------------------------------------------------------- authorization over HTTP


ROUTES = [
    ("get", "/api/v1/model-registry/slots", None),
    ("get", "/api/v1/model-registry/models/1", None),
    ("patch", "/api/v1/model-registry/slots/15d-large", {"expected_version": 1, "priority": 2}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_only_the_owner_gets_in(client, reg, method, path, body):
    call = getattr(client, method)
    kw = {"json": body} if body else {}
    assert call(path, **kw).status_code in (401, 403)
    for role in ("member", "tester"):
        assert call(path, headers=headers(reg, role), **kw).status_code == 403, role
    assert reg.get(ModelResearchSlot, "15d-large").priority == 1  # nothing changed by the refused calls


def test_the_owner_reads_the_slots_and_a_model(client, reg):
    own = headers(reg, "owner")
    m = model(reg)
    out = client.get("/api/v1/model-registry/slots", headers=own).json()
    assert (
        len(out["slots"]) == 9 and out["unassigned"] == [] and "does not mean validated" in out["status_note"]
    )
    one = client.get(f"/api/v1/model-registry/models/{m.id}", headers=own).json()
    assert one["slot"] == "5d-large" and one["registry_status"] == "ACTIVE"
    assert client.get("/api/v1/model-registry/models/999999", headers=own).status_code == 404


def test_the_patch_rejects_anything_but_the_three_fields_and_a_missing_change(client, reg):
    own = headers(reg, "owner")
    p = "/api/v1/model-registry/slots/15d-large"
    assert client.patch(p, headers=own, json={"expected_version": 1, "model_id": 2}).status_code == 422
    assert (
        client.patch(p, headers=own, json={"expected_version": 1, "deployment_status": "active"}).status_code
        == 422
    )
    assert client.patch(p, headers=own, json={"expected_version": 1}).status_code == 422
    assert (
        client.patch(p, headers=own, json={"priority": 3}).status_code == 422
    )  # must name the version it saw
    assert (
        client.patch(p, headers=own, json={"expected_version": 1, "research_status": "validated"}).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/model-registry/slots/nope", headers=own, json={"expected_version": 1, "priority": 2}
        ).status_code
        == 404
    )


def test_a_conflicting_patch_returns_409_with_the_current_slot(client, reg):
    own = headers(reg, "owner")
    p = "/api/v1/model-registry/slots/15d-large"
    assert client.patch(p, headers=own, json={"expected_version": 1, "priority": 5}).status_code == 200
    r = client.patch(p, headers=own, json={"expected_version": 1, "priority": 6})
    assert r.status_code == 409 and r.json()["detail"]["current"]["priority"] == 5


# --------------------------------------------------------------- isolation


FORBIDDEN_PREFIXES = (
    "swing_trade_ml.brain",
    "swing_trade_ml.ml.train",
    "swing_trade_ml.ml.registry",
    "swing_trade_ml.workers",
    "swing_trade_ml.strategies",
    "swing_trade_ml.services.engine",
    "swing_trade_ml.services.execution",
)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found


@pytest.mark.parametrize(
    "rel", ["services/model_registry.py", "api/v1/endpoints/model_registry.py", "db/models/registry.py"]
)
def test_the_registry_imports_no_brain_training_activation_or_trading_code(rel):
    bad = [i for i in _imports(PKG / rel) if i.startswith(FORBIDDEN_PREFIXES)]
    assert bad == [], bad
    src = (PKG / rel).read_text(encoding="utf-8")
    assert "activate_model" not in src and "/activate" not in src


def test_nothing_in_the_brain_ml_strategies_workers_or_trading_imports_the_registry():
    users = []
    for d in ("brain", "ml", "strategies", "workers", "services"):
        for f in (PKG / d).rglob("*.py"):
            if f.name == "model_registry.py":
                continue
            if any(
                i.endswith(("model_registry", "db.models.registry", "ModelResearchSlot"))
                or "model_registry" in i
                for i in _imports(f)
            ):
                users.append(f.relative_to(PKG).as_posix())
    assert users == []


def test_the_registry_routes_are_get_and_patch_only_and_the_activate_route_is_untouched(client):
    from swing_trade_ml.api.v1.endpoints import model_registry

    assert {m for r in model_registry.router.routes for m in r.methods} <= {"GET", "PATCH"}
    paths = client.app.openapi()["paths"]
    assert "post" in paths["/api/v1/ml/models/{model_id}/activate"]
    assert not any("activate" in p for p in paths if "model-registry" in p)
    ml_src = (PKG / "api/v1/endpoints/ml.py").read_text(encoding="utf-8")
    assert "model_registry" not in ml_src


# --------------------------------------------------------------- migration safety and rollback


def _run(db_session, fn):
    ctx = MigrationContext.configure(db_session.connection())
    with Operations.context(ctx):
        fn()


def test_the_migration_seeds_nine_slots_creates_a_missing_table_and_is_safe_to_run_twice(db_session):
    mod = _migration()
    db_session.execute(
        text("drop table model_research_slots")
    )  # DDL is transactional on Postgres; rolled back at the end
    _run(db_session, mod.upgrade)
    rows = db_session.execute(
        text(
            "select slot_key, research_status, priority, version from model_research_slots order by slot_key"
        )
    ).all()
    assert len(rows) == 9
    got = {r[0]: (r[1], r[2]) for r in rows}
    assert (
        got["15d-large"] == ("not_started", 1)
        and got["15d-midcap"] == ("not_started", 2)
        and got["10d-large"] == ("not_started", 3)
    )
    assert all(got[k][0] == "researching" for k in ("5d-large", "5d-midcap", "5d-smallcap"))
    db_session.execute(
        text("update model_research_slots set note='keep me', priority=7 where slot_key='15d-large'")
    )
    _run(db_session, mod.upgrade)  # second run: nothing overwritten
    assert db_session.execute(
        text("select note, priority from model_research_slots where slot_key='15d-large'")
    ).one() == ("keep me", 7)
    assert db_session.scalar(text("select count(*) from model_research_slots")) == 9


def test_the_migration_chains_from_the_h05_head_and_the_head_is_single():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    assert _migration().down_revision == "h05l4n3e1a2b"
    cfg = Config(str(MIGRATION.parents[2] / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATION.parents[1]))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["mrs5p1a8c3d2"]


def test_the_downgrade_keeps_the_table_and_the_owners_notes(db_session):
    mod = _migration()
    seed(db_session)
    db_session.execute(
        text("update model_research_slots set note='my research note' where slot_key='15d-large'")
    )
    _run(db_session, mod.downgrade)
    assert (
        db_session.scalar(text("select note from model_research_slots where slot_key='15d-large'"))
        == "my research note"
    )


def test_the_migration_touches_no_other_table():
    src = MIGRATION.read_text(encoding="utf-8")
    assert 'create_table(\n            "model_research_slots"' in src
    assert "alter_table" not in src and "drop_table" not in src and "add_column" not in src
    assert not any(w in src.lower() for w in ("insert into ml_models", "update ml_models", "strategies"))
