"""#328 guard: nothing outside ml/promotion.py (and the `activate_model` function it wraps) may change which
model serves.

Scans, with the AST: every module under backend/src/swing_trade_ml, backend/scripts, the repo's scripts/,
and any alembic migration not in the pinned list below (the pinned ones are applied history). Reads of the
active model (comparisons, `.in_(...)`, `.where(...)`) are fine; writes are not. No DB needed.

What it reports:
- any reference to `activate_model` outside ml/promotion.py (calls, renamed imports, getattr by name);
- a write of ModelStatus.ACTIVE / ARCHIVED (by name, alias, `enums.ModelStatus.X`, `ModelStatus("ACTIVE")`)
  outside `registry.activate_model`;
- the strings "ACTIVE" / "ARCHIVED" written to a `status`, and any `model_role` write, through assignment,
  keyword argument (constructors, `.values(...)`), dict key (`.update({...})`) or `setattr`;
- bulk ORM updates of MLModel (`query(MLModel)...update`, `update(MLModel)`) and raw SQL writes to ml_models;
- `set_mode(...)` calls (the brain module switch, which turns M06 on) outside the gated callers.
It cannot see a fully dynamic `setattr(obj, name, value)`; the API paths that do that are gated in code.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import swing_trade_ml

PKG = Path(swing_trade_ml.__file__).resolve().parent
BACKEND = PKG.parents[1]
REPO = BACKEND.parent
FREEZE = Path(__file__).resolve().parent / "trial_freeze.json"

#: The only module allowed to reference activate_model (besides its own definition and a plain re-export).
ACTIVATE_CALLERS = {"swing_trade_ml/ml/promotion.py"}
PLAIN_REEXPORT = {"swing_trade_ml/ml/__init__.py"}
#: (file, function) allowed to write ModelStatus.ACTIVE / ARCHIVED and bulk-update MLModel.
STATUS_WRITER = ("swing_trade_ml/ml/registry.py", "activate_model")
#: model_role writers and the only value each may write ("final" = shadow-lane model, scored, never served).
ROLE_WRITERS = {"swing_trade_ml/shadow_lanes/lane_freeze.py": {"final"}}
#: set_mode callers. The API and CLI gate M06-on with an approval; m09 store is trial-frozen and reached only
#: through the brain API's proposal accept, which refuses an M06-on proposal (see blocker test below).
SET_MODE_CALLERS = {
    "swing_trade_ml/api/v1/endpoints/brain.py",
    "swing_trade_ml/cli.py",
    "swing_trade_ml/brain/modules/m09_learn/store.py",
}
STATUS_WORDS = {"ACTIVE", "ARCHIVED"}
_SQL_WRITE = re.compile(
    r"\b(UPDATE\s+ml_models|INSERT\s+INTO\s+ml_models|DELETE\s+FROM\s+ml_models)\b", re.IGNORECASE
)
#: Applied migrations (history). Any migration not listed here is scanned.
PINNED_MIGRATIONS = frozenset(
    {
        "20260101_0000_initial_schema.py",
        "20260804_1100_user_auth_providers.py",
        "20260805_1319_advisory_and_pyramiding.py",
        "20260806_1500_confidence_decay_alert.py",
        "20260809_0900_max_daily_buys.py",
        "20260822_0900_trailing_stop.py",
        "20260822_1500_finance_module.py",
        "20260825_1000_finance_module_v2.py",
        "20260827_1200_finance_module_v3.py",
        "20260901_1400_finance_recurring_daily.py",
        "20260907_1200_recurring_bill_category_optional.py",
        "20260913_0528_signal_outcome_columns.py",
        "20260913_0602_mutual_funds.py",
        "20260913_1230_mutual_fund_holding_source.py",
        "20260915_1040_barrier_label_definition.py",
        "20260915_1500_partial_profit_booking.py",
        "20260915_1600_portfolio_risk_layer.py",
        "20260915_1800_long_term_advisory.py",
        "20260920_0900_broker_stop_groundwork.py",
        "20260921_1000_broker_fills.py",
        "20260921_1400_market_feeds.py",
        "20260921_1600_avoid_lists.py",
        "20260929_1200_subscription_plans.py",
        "20260929_1500_plan_settings.py",
        "20260930_0900_brain_core.py",
        "20260930_1800_brain_console.py",
        "20261001_0900_feature_snapshots.py",
        "20261001_1500_brain_alerts.py",
        "20261002_1000_brain_run_context.py",
        "20261002_1400_brain_episodes.py",
        "20261002_1700_brain_experience.py",
        "20261002_2000_brain_track.py",
        "20261003_0900_brain_learning.py",
        "20261003_1200_brain_learning_runs.py",
        "20261004_0900_brain_golive_stage.py",
        "20261004_1000_brain_approvals.py",
        "20261004_1600_brain_run_queue.py",
        "20261004_1800_plans_free_pro.py",
        "20261005_1200_service1_p0.py",
        "20261005_1300_merge_plans_service1.py",
        "20261008_1000_brain_weekly_health.py",
        "20261008_1200_position_score_history.py",
        "20261008_1500_stock_score_history.py",
        "20261013_1800_candle_arrivals.py",
        "20261013_2200_brain_daily_checks.py",
        "20261016_1200_p0_security.py",
        "20261017_2000_horizon_experiments.py",
        "20261020_1200_alert_settings.py",
        "20261025_1200_user_watchlist.py",
        "20261025_1210_invite_requests.py",
        "20261026_1200_capital_deposits.py",
        "20261026_1500_company_filings.py",
        "20261030_1200_h05_lane.py",
        "20261101_1200_model_research_slots.py",
        "20261102_1200_lane_shadow.py",
        "20261103_1200_model_role.py",
        "20261103_1500_h05_append_only.py",
        "20261103_1800_corporate_actions.py",
        "20261109_1200_watchlist_buy_price.py",
        "20261109_2100_watchlist_quantity.py",
        "20261110_1000_owner_private.py",
        "20261110_1000_user_name_mobile.py",
        "20261110_1200_auth_tokens.py",
        "20261110_1400_billing.py",
        "20261110_1600_stock_score_by_model.py",
        "20261111_1000_merge_heads.py",
        "20261111_1200_account_deletions.py",
        "20261111_1200_service_keys.py",
        "20261111_1200_watchlist_sales.py",
        "20261111_1400_admin_mfa.py",
        "20261123_1200_identity_phase1.py",
        "20261124_1200_horizon_records.py",
        "20261124_1400_module_switches.py",
        "20261125_1200_simulation_persistence.py",
        "20261126_1200_signal_key.py",
        "20261126_1200_simulation_rule_ref.py",
    }
)


def sources(root: Path | None = None) -> list[tuple[str, Path]]:
    """(label, path) of every file to scan. With `root`, every .py under it (used by the self-tests)."""
    if root is not None:
        return [(p.relative_to(root).as_posix(), p) for p in sorted(root.rglob("*.py"))]
    found = [(p.relative_to(PKG.parent).as_posix(), p) for p in sorted(PKG.rglob("*.py"))]
    for folder in (BACKEND / "scripts", REPO / "scripts"):
        if folder.is_dir():
            found += [(p.relative_to(REPO).as_posix(), p) for p in sorted(folder.rglob("*.py"))]
    versions = BACKEND / "alembic" / "versions"
    found += [
        (p.relative_to(REPO).as_posix(), p)
        for p in sorted(versions.glob("*.py"))
        if p.name not in PINNED_MIGRATIONS and p.name != "__init__.py"
    ]
    return found


class _Scan(ast.NodeVisitor):
    def __init__(self, rel: str):
        self.rel = rel
        self.found: list[str] = []
        self.funcs: list[str] = []
        self.reads = 0  # depth inside a comparison / .in_() / .where() / .filter()
        self.ms_names = {"ModelStatus"}  # names bound to ModelStatus in this module

    # -- helpers
    def flag(self, node: ast.AST, what: str) -> None:
        self.found.append(f"{self.rel}:{getattr(node, 'lineno', '?')} {what}")

    def in_status_writer(self) -> bool:
        return (self.rel, self.funcs[-1] if self.funcs else None) == STATUS_WRITER

    def is_ms(self, node: ast.AST) -> bool:
        """Is `node` the ModelStatus enum (by name, alias or `x.ModelStatus`)?"""
        return (isinstance(node, ast.Name) and node.id in self.ms_names) or (
            isinstance(node, ast.Attribute) and node.attr == "ModelStatus"
        )

    def bad_status_value(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and node.attr in STATUS_WORDS and self.is_ms(node.value):
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value in STATUS_WORDS  # ModelStatus values are upper case
        return False

    def check_field(self, node: ast.AST, field: str | None, value: ast.AST) -> None:
        if field == "status" and self.bad_status_value(value) and not self.in_status_writer():
            self.flag(node, "writes an active/archived status")
        if field == "model_role":
            literal = value.value if isinstance(value, ast.Constant) else object()
            if literal not in ROLE_WRITERS.get(self.rel, set()):
                self.flag(node, f"writes model_role={literal!r}")

    @staticmethod
    def field_name(target: ast.AST) -> str | None:
        if isinstance(target, ast.Attribute):
            return target.attr
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            return target.value
        if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
            return target.slice.value if isinstance(target.slice.value, str) else None
        return None

    # -- imports
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "ModelStatus":
                self.ms_names.add(alias.asname or alias.name)
            allowed = ACTIVATE_CALLERS | PLAIN_REEXPORT
            if alias.name == "activate_model" and (alias.asname or self.rel not in allowed):
                self.flag(node, f"imports activate_model as {alias.asname or alias.name}")
        self.generic_visit(node)

    # -- scopes
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.funcs.append(node.name)
        self.generic_visit(node)
        self.funcs.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Compare(self, node: ast.Compare) -> None:
        self.reads += 1
        self.generic_visit(node)
        self.reads -= 1

    # -- names
    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "activate_model" and self.rel not in ACTIVATE_CALLERS:
            self.flag(node, "references activate_model")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "activate_model" and self.rel not in ACTIVATE_CALLERS:
            self.flag(node, "references activate_model")
        if (
            node.attr in STATUS_WORDS
            and self.is_ms(node.value)
            and not self.reads
            and not self.in_status_writer()
        ):
            self.flag(node, f"writes ModelStatus.{node.attr}")
        self.generic_visit(node)

    # -- writes
    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Attribute | ast.Subscript):
                self.check_field(node, self.field_name(target), node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and isinstance(node.target, ast.Attribute):
            self.check_field(node, node.target.attr, node.value)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if key is not None:
                self.check_field(node, self.field_name(key), value)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _SQL_WRITE.search(node.value):
            self.flag(node, "raw SQL write to ml_models")

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        reads = name in {"in_", "where", "filter", "filter_by", "notin_"}
        for kw in [] if reads else node.keywords:  # filter_by(status=...) is a read
            self.check_field(node, kw.arg, kw.value)
        if name == "setattr" and len(node.args) == 3:
            self.check_field(node, self.field_name(node.args[1]), node.args[2])
        if (
            name == "getattr"
            and any(isinstance(a, ast.Constant) and a.value == "activate_model" for a in node.args)
            and self.rel not in ACTIVATE_CALLERS
        ):
            self.flag(node, "looks up activate_model by name")
        if self.is_ms(fn) and node.args and self.bad_status_value(node.args[0]) and not self.reads:
            self.flag(node, "builds an active/archived ModelStatus from a string")
        if name == "set_mode" and self.rel not in SET_MODE_CALLERS:
            self.flag(node, "switches a brain module (set_mode)")
        if name == "update" and not self.in_status_writer() and self._chain_has_mlmodel(fn):
            self.flag(node, "bulk-updates MLModel")
        if isinstance(fn, ast.Name) and fn.id in {"update", "insert"} and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id == "MLModel" and not self.in_status_writer():
                self.flag(node, f"{fn.id}(MLModel) statement")
        self.reads += reads
        self.generic_visit(node)
        self.reads -= reads

    @staticmethod
    def _chain_has_mlmodel(fn: ast.AST) -> bool:
        node = fn.value if isinstance(fn, ast.Attribute) else None
        while node is not None:
            if isinstance(node, ast.Call):
                if any(isinstance(a, ast.Name) and a.id == "MLModel" for a in node.args):
                    return True
                node = node.func
            elif isinstance(node, ast.Attribute):
                node = node.value
            else:
                return False
        return False


def find_activation_writes(root: Path | None = None) -> list[str]:
    found: list[str] = []
    for rel, path in sources(root):
        scan = _Scan(rel)
        scan.visit(ast.parse(path.read_text(encoding="utf-8")))
        found += scan.found
    return found


def test_no_activation_path_outside_promotion():
    assert find_activation_writes() == []


def test_the_scan_covers_scripts_and_new_migrations():
    labels = [label for label, _ in sources()]
    assert any(label.startswith("swing_trade_ml/ml/") for label in labels)
    assert any(label.startswith("scripts/") for label in labels)
    pinned = {p.name for p in (BACKEND / "alembic" / "versions").glob("*.py")} - {"__init__.py"}
    assert pinned <= PINNED_MIGRATIONS  # every migration on this branch is reviewed history


EVASIONS = {
    "string_status.py": "def f(m):\n    m.status = 'ACTIVE'\n",
    "aliased_enum.py": (
        "from swing_trade_ml.core.enums import ModelStatus as MS\ndef f(m):\n    m.status = MS.ACTIVE\n"
    ),
    "qualified_enum.py": (
        "from swing_trade_ml.core import enums\ndef f(m):\n    m.status = enums.ModelStatus.ACTIVE\n"
    ),
    "dict_update.py": "def f(db, M):\n    db.query(M).filter(M.id == 1).update({'status': 'ACTIVE'})\n",
    "setattr_status.py": "def f(m):\n    setattr(m, 'status', 'ACTIVE')\n",
    "renamed_import.py": (
        "from swing_trade_ml.ml.registry import activate_model as go\ndef f(db):\n    go(db, 1)\n"
    ),
    "constructor_role.py": "def f(MLModel):\n    return MLModel(name='x', model_role='prod')\n",
    "raw_sql.py": "def f(db):\n    db.execute(\"UPDATE ml_models SET status = 'ACTIVE' WHERE id = 1\")\n",
    "values_kw.py": "def f(update, M):\n    return update(M).values(status='ARCHIVED')\n",
    "enum_from_string.py": (
        "from swing_trade_ml.core.enums import ModelStatus\ndef f(m):\n    m.status = ModelStatus('ACTIVE')\n"
    ),
    "getattr_lookup.py": "def f(registry, db):\n    getattr(registry, 'activate_model')(db, 1)\n",
    "bulk_update.py": "def f(db, MLModel):\n    db.query(MLModel).update({MLModel.version: 'v9'})\n",
    "set_mode.py": "def f(db, service):\n    service.set_mode(db, 'M06', 'on', by='x')\n",
    "role_assign.py": "def f(m):\n    m.model_role = 'prod'\n",
}


def test_every_known_evasion_is_caught(tmp_path):
    """Regression for the 8 evasions the #328 review listed (string status, aliased enum, qualified enum,
    dict .update, setattr, renamed import, constructor model_role, raw SQL) plus a few more."""
    for name, src in EVASIONS.items():
        folder = tmp_path / name.removesuffix(".py")
        folder.mkdir()
        (folder / name).write_text(src, encoding="utf-8")
        assert find_activation_writes(folder), f"not caught: {name}"


def test_reads_are_not_flagged(tmp_path):
    (tmp_path / "reads.py").write_text(
        "from swing_trade_ml.core.enums import ModelStatus as MS\n"
        "def f(db, M, m):\n"
        "    a = db.query(M).filter(M.status == MS.ACTIVE).all()\n"
        "    b = db.query(M).filter(M.status.in_([MS.ACTIVE, MS.ARCHIVED])).all()\n"
        "    c = m.status in (MS.TRAINED, MS.ARCHIVED)\n"
        "    m.status = MS.TRAINED\n"
        "    d = db.query(M).filter_by(status=MS.ACTIVE).all()\n"
        "    return a, b, c, d, m.status == 'ACTIVE'\n",
        encoding="utf-8",
    )
    assert find_activation_writes(tmp_path) == []


def test_api_cli_and_trainer_route_through_promotion():
    for rel in ("api/v1/endpoints/ml.py", "cli.py"):
        src = (PKG / rel).read_text(encoding="utf-8")
        assert re.search(r"promotion\.(promote|rollback)\b", src), rel
    train = (PKG / "ml/train.py").read_text(encoding="utf-8")
    assert "activate_model" not in train and "promote(" not in train  # train never activates


# ------------------------------------------------------------------ known gaps in frozen files (blockers)


def _frozen() -> set[str]:
    return set(json.loads(FREEZE.read_text(encoding="utf-8"))["files"])


def test_blocker_m06_serves_the_newest_saved_combiner():
    """BLOCKER (#328, frozen, not edited): M06 serves the newest saved combiner. A later
    `swingtrade brain meta-train` save changes what M06 serves while it is on, with no approval; the switch
    to "on" itself is now gated (API + CLI). The combiner loads its base models by name+version with no
    status or hash check (`DatedReader.model_bundle`, brain/reader.py)."""
    import inspect

    from swing_trade_ml.brain import reader
    from swing_trade_ml.brain.modules.m06_reason import artifact

    assert {
        "brain/modules/m06_reason/artifact.py",
        "brain/modules/m06_reason/module.py",
        "brain/reader.py",
    } <= _frozen()
    assert "versions[-1]" in inspect.getsource(artifact.load_latest)
    bundle = inspect.getsource(reader.DatedReader.model_bundle)
    assert "load_artifact(" in bundle and "artifact_sha256" not in bundle


def test_blocker_predict_loads_model_files_without_a_hash_check():
    """BLOCKER (#328, frozen, not edited): ml/predict.py serves the active model with load_artifact, not the
    verified loader, so a file swapped on disk after promotion is not refused at serving time."""
    import inspect

    from swing_trade_ml.ml import predict

    assert "ml/predict.py" in _frozen()
    src = inspect.getsource(predict)
    assert "load_artifact(" in src and "load_model_artifact" not in src


def test_blocker_brain_set_mode_and_m09_accept_are_frozen_and_gated_at_the_edges():
    """brain/service.py set_mode and m09 store.accept are trial-frozen, so the M06-on gate lives in the brain
    API (PUT /brain/modules, proposal accept) and the CLI. This fails if they leave the freeze list."""
    assert {"brain/service.py", "brain/modules/m09_learn/store.py"} <= _frozen()
