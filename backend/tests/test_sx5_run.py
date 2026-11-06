"""backend/scripts/sx5_run.py: the guarded SX5 development-run driver.

SYNTHETIC data and a stub fit ONLY: no database, no real model, no holdout, the real registry and the real research
folder are never written. Shows that the driver

  1. is a dry run by default and a dry run writes nothing (no data read, no fit, no verdict, no lock file);
  2. refuses a real run before 2026-12-04, without the approval file or the SEPARATE training authorisation, with a
     holdout authorisation, with a dirty tree, with a commit or hash mismatch, with MDE_H typed as percentage points, and
     with a consumed registry, and refuses before it reads any data;
  3. refuses (before any fit) when the assembled data differs from the authorisation;
  4. on a valid synthetic start runs the 34 DEVELOPMENT folds x 3 arms only, never a holdout fold or record, never the
     registry, calls the verdict exactly ONCE, and writes the verdict write-once and read-only;
  5. is deterministic (same inputs, same records and verdict text);
  6. uses the same DatasetSpec, recipe and folds the protocol signs.
"""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from datetime import date
from pathlib import Path

import pytest

from swing_trade_ml.brain import service as _brain_service  # noqa: F401  (import order: avoids a repo circular import)
from swing_trade_ml.ml import holdout_registry as hr
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sector_walkforward as wf
from swing_trade_ml.ml import sx_verdict as v
from test_sector_walkforward import lstsq_fit, make_matrix

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sx5_run.py"
REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sx5_run", SCRIPT)
drv = importlib.util.module_from_spec(_spec)
sys.modules["sx5_run"] = drv  # a dataclass in the script needs its module registered
_spec.loader.exec_module(drv)

HEAD = "a1" * 20
OTHER = "b2" * 20
OK_DAY = date(2026, 12, 5)
ENV_WORDS = {v.PASS, v.FAIL, v.INCONCLUSIVE, v.PENDING_HOLDOUT}


@pytest.fixture(scope="module")
def synthetic_matrix():
    # long enough for all 34 development folds (2023-07-01 .. 2026-01-31) and then some (holdout-period rows exist)
    return make_matrix(n_days=1100, seed=3)


def stub_fit_builder(recipe, *, spec, approval_path, allow_real_data):
    return lstsq_fit


def write_files(tmp: Path, matrix, *, approval_over=None, auth_over=None, mde_h=0.0018):
    """Valid approval + authorisation for the REAL spec and the synthetic matrix, with overrides."""
    spec = drv.build_spec(REPO)
    params = drv.build_params(0.0018)  # the SIGNED parameter set; `mde_h` below is what the file CLAIMS
    protocol = REPO / drv.PROTOCOL_REL
    auth = {
        "schema": drv.AUTH_SCHEMA,
        "candidate": "SX5",
        "scope": "development_only",
        "training_authorised": True,
        "protocol_id": "unit-protocol",
        "authorised_by": "unit test (not the owner)",
        "authorised_on": "2026-12-05",
        "statement": "synthetic test authorisation",
        "code_commit": HEAD,
        "mde_h": mde_h,
        **drv.bound_values(REPO, spec, params, protocol),
        **drv.load_time_values(matrix),
    }
    approval = {
        "protocol_id": "unit-protocol",
        "approved_by": "unit",
        "candidate": "SX5",
        "config_sha256": spec.config_sha256(),
        "code_commit": HEAD,
    }
    approval.update(approval_over or {})
    auth.update(auth_over or {})
    ap, au = tmp / "approval.json", tmp / "authorisation.json"
    ap.write_text(json.dumps(approval), encoding="utf-8")
    au.write_text(json.dumps(auth), encoding="utf-8")
    return ap, au


def make_ctx(tmp: Path, matrix, *, today=OK_DAY, porcelain="", head=HEAD, **kw):
    ap, au = write_files(tmp, matrix, **kw)
    return drv.Context(
        repo=REPO,
        today=today,
        approval_path=ap,
        authorisation_path=au,
        registry_path=tmp / "reg" / "R.jsonl",
        lock_path=tmp / "lk" / "l.lock",
        git=lambda repo: (head, porcelain),
    )


class Spy:
    """Counts calls to the data loader, the fit builder and the verdict; patches the assembler."""

    def __init__(self, monkeypatch, matrix):
        self.loads = self.builds = self.verdicts = 0
        real_verdict = v.compute_verdict

        def counting_verdict(*a, **k):
            self.verdicts += 1
            self.verdict_kwargs = k
            return real_verdict(*a, **k)

        monkeypatch.setattr(v, "compute_verdict", counting_verdict)
        monkeypatch.setattr(sr, "assemble_training_matrix", lambda spec, inputs: matrix)

    def loader(self, symbols):
        self.loads += 1
        return None

    def builder(self, *a, **k):
        self.builds += 1
        return stub_fit_builder(*a, **k)


def tree(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else None


# ------------------------------------------------------------------------------------------------ 1. the dry run
def test_dry_run_is_the_default_and_writes_nothing(tmp_path, monkeypatch, capsys, synthetic_matrix):
    def boom(*a, **k):
        raise AssertionError("a dry run must not read data, fit, or compute a verdict")

    monkeypatch.setattr(sr, "load_inputs_readonly", boom)
    monkeypatch.setattr(sr, "assemble_training_matrix", boom)
    monkeypatch.setattr(wf, "run_walkforward", boom)
    monkeypatch.setattr(v, "compute_verdict", boom)
    monkeypatch.setattr(hr, "LOCK_PATH", tmp_path / "lk" / "l.lock")
    before = (
        tree(sr.RESEARCH_ROOT),
        tree(tmp_path),
        (REPO / drv.EVID_REL / "HOLDOUT-REGISTRY.jsonl").stat().st_size,
    )
    assert drv.main(["--repo", str(REPO), "--registry", str(tmp_path / "R.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "FAIL" in out
    plan = json.loads(out.split("\nChecks:")[0])
    assert plan["development_folds"] == 34 and plan["holdout"] == "never touched by this script"
    assert plan["records_would_be"].startswith("34 folds x 3 arms = 102")
    assert plan["real_run_allowed_now"] is False
    after = (
        tree(sr.RESEARCH_ROOT),
        tree(tmp_path),
        (REPO / drv.EVID_REL / "HOLDOUT-REGISTRY.jsonl").stat().st_size,
    )
    assert before == after  # no research folder, no lock file, no registry change


def test_real_run_only_with_the_run_flag_and_refuses_with_nothing_given(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sr, "load_inputs_readonly", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read data"))
    )
    monkeypatch.setattr(hr, "LOCK_PATH", tmp_path / "lk" / "l.lock")
    monkeypatch.delenv(sr.APPROVAL_ENV, raising=False)
    assert drv.main(["--run", "--registry", str(tmp_path / "R.jsonl")]) == 2
    assert "REFUSED" in capsys.readouterr().err


# --------------------------------------------------------------------------------- 2. refusals, before any data
def _dirty(tmp, m):
    return make_ctx(tmp, m, porcelain=" M backend/x.py\n")


REFUSALS = {
    "before the earliest date": lambda tmp, m: make_ctx(tmp, m, today=date(2026, 12, 3)),
    "no approval file": lambda tmp, m: _no(make_ctx(tmp, m), "approval_path"),
    "no authorisation file": lambda tmp, m: _no(make_ctx(tmp, m), "authorisation_path"),
    "authorisation also opens the holdout": lambda tmp, m: make_ctx(
        tmp, m, auth_over={"holdout_authorised": True}
    ),
    "scope is not development_only": lambda tmp, m: make_ctx(
        tmp, m, auth_over={"scope": "development_and_holdout"}
    ),
    "training not authorised": lambda tmp, m: make_ctx(tmp, m, auth_over={"training_authorised": False}),
    "authorisation dated before 4 Dec": lambda tmp, m: make_ctx(
        tmp, m, auth_over={"authorised_on": "2026-12-03"}
    ),
    "authorisation dated in the future": lambda tmp, m: make_ctx(
        tmp, m, auth_over={"authorised_on": "2026-12-09"}
    ),
    "dirty tree": _dirty,
    "HEAD differs from the approval commit": lambda tmp, m: make_ctx(tmp, m, head=OTHER),
    "approval commit differs": lambda tmp, m: make_ctx(tmp, m, approval_over={"code_commit": OTHER}),
    "approval names another configuration": lambda tmp, m: make_ctx(
        tmp, m, approval_over={"config_sha256": "0" * 64}
    ),
    "protocol hash differs": lambda tmp, m: make_ctx(tmp, m, auth_over={"protocol_sha256": "0" * 64}),
    "verdict code hash differs": lambda tmp, m: make_ctx(tmp, m, auth_over={"verdict_code_sha256": "0" * 64}),
    "recipe hash differs": lambda tmp, m: make_ctx(tmp, m, auth_over={"recipe_sha256": "0" * 64}),
    "lock file hash differs": lambda tmp, m: make_ctx(tmp, m, auth_over={"lock_file_sha256": "0" * 64}),
    "MDE_H typed as percentage points": lambda tmp, m: make_ctx(tmp, m, mde_h=0.18),
    "MDE_H differs from the signed parameter hash": lambda tmp, m: make_ctx(
        tmp, m, auth_over={"mde_h": 0.0020}
    ),
}


def _no(ctx, field):
    setattr(ctx, field, None)
    return ctx


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_a_real_run_is_refused_before_any_data_is_read(name, tmp_path, monkeypatch, synthetic_matrix):
    monkeypatch.delenv(sr.APPROVAL_ENV, raising=False)
    spy = Spy(monkeypatch, synthetic_matrix)
    ctx = REFUSALS[name](tmp_path, synthetic_matrix)
    out_root = tmp_path / "out"
    with pytest.raises(drv.RunRefused):
        drv.run_real(ctx, load_inputs=spy.loader, fit_builder=spy.builder, out_root=out_root)
    assert spy.loads == 0 and spy.builds == 0 and spy.verdicts == 0
    assert not out_root.exists() and not (tmp_path / "reg").exists()


def test_a_consumed_registry_refuses(tmp_path, monkeypatch, synthetic_matrix):
    monkeypatch.setattr(hr, "_load", lambda rp, lp: [])
    monkeypatch.setattr(hr, "_replay", lambda entries: {"ev1": {"state": "STARTED", "horizon": 5}})
    spy = Spy(monkeypatch, synthetic_matrix)
    ctx = make_ctx(tmp_path, synthetic_matrix)
    with pytest.raises(drv.RunRefused, match="consumed events"):
        drv.run_real(ctx, load_inputs=spy.loader, fit_builder=spy.builder, out_root=tmp_path / "out")
    assert spy.loads == 0


def test_a_corrupt_registry_refuses(tmp_path, monkeypatch, synthetic_matrix):
    def corrupt(rp, lp):
        raise hr.RegistryCorrupt("synthetic corruption")

    monkeypatch.setattr(hr, "_load", corrupt)
    spy = Spy(monkeypatch, synthetic_matrix)
    with pytest.raises(drv.RunRefused, match="does not verify"):
        drv.run_real(make_ctx(tmp_path, synthetic_matrix), load_inputs=spy.loader, out_root=tmp_path / "out")
    assert spy.loads == 0


# ------------------------------------------------------------------------- 3. data must equal the authorisation
@pytest.mark.parametrize("key", ["dataset_sha256", "rowlist_sha256"])
def test_data_that_differs_from_the_authorisation_is_refused_before_any_fit(
    key, tmp_path, monkeypatch, synthetic_matrix
):
    spy = Spy(monkeypatch, synthetic_matrix)
    ctx = make_ctx(tmp_path, synthetic_matrix, auth_over={key: "0" * 64})
    out_root = tmp_path / "out"
    with pytest.raises(drv.RunRefused, match=key):
        drv.run_real(ctx, load_inputs=spy.loader, fit_builder=spy.builder, out_root=out_root)
    assert spy.loads == 1 and spy.builds == 0 and spy.verdicts == 0 and not out_root.exists()


# --------------------------------------------------------------------------------- 4. a valid synthetic start
@pytest.fixture(scope="module")
def good(tmp_path_factory, synthetic_matrix):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("sx5good")
    mp.setattr(hr, "LOCK_PATH", tmp / "lk" / "l.lock")
    spy = Spy(mp, synthetic_matrix)
    ctx = make_ctx(tmp, synthetic_matrix)
    res = drv.run_real(ctx, load_inputs=spy.loader, fit_builder=spy.builder, out_root=tmp / "out1")
    yield {"tmp": tmp, "ctx": ctx, "res": res, "spy": spy, "matrix": synthetic_matrix}
    mp.undo()


def test_the_run_is_development_only_three_arms_34_folds(good):
    run_dir = Path(good["res"]["run_dir"])
    files = sorted(p.name for p in run_dir.glob("*.json"))
    recs = [n for n in files if n[:4] in ("dev_", "hold")]
    assert len(recs) == 34 * 3
    assert all(n.startswith("dev_") for n in recs)
    assert not list(run_dir.glob("holdout_*"))
    manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["holdout_included"] is False
    assert manifest["code_version"] == HEAD
    assert manifest["seed"] == wf.PINNED_SEED == 42
    assert good["res"]["outcome"] in ENV_WORDS
    # the data was loaded once and the fit builder built once
    assert good["spy"].loads == 1 and good["spy"].builds == 1


def test_nothing_about_the_holdout_was_created(good):
    tmp = good["tmp"]
    assert not (tmp / "reg").exists()  # registry never created
    assert not list(tmp.rglob("*holdout_used*"))  # no holdout marker
    assert not (tmp / "out1" / "_holdout_markers" / "SX5.holdout_used.json").exists()


def test_the_verdict_is_called_exactly_once_with_development_records_only(good):
    assert good["spy"].verdicts == 1
    assert "holdout_records" not in good["spy"].verdict_kwargs
    assert good["spy"].verdict_kwargs.get("holdout_completed", False) is False


def test_the_verdict_files_are_written_once_and_read_only(good):
    run_dir = Path(good["res"]["run_dir"])
    for name in ("VERDICT_dev.json", "VERDICT_dev.txt", "RUN_CONTEXT.json"):
        p = run_dir / name
        assert p.is_file() and not p.stat().st_mode & stat.S_IWRITE
        with pytest.raises(FileExistsError):
            drv._write_once(p, "overwrite")
    txt = (run_dir / "VERDICT_dev.txt").read_text("utf-8")
    assert txt.startswith("Cohort: 47 large stocks")  # the protocol's report header comes first
    js = json.loads((run_dir / "VERDICT_dev.json").read_text("utf-8"))
    assert js["outcome"] == good["res"]["outcome"] and js["verdict_code_sha256"] == v.verdict_code_sha256()
    ctx = json.loads((run_dir / "RUN_CONTEXT.json").read_text("utf-8"))
    assert ctx["code_commit"] == HEAD and ctx["outcome"] == js["outcome"]


def test_a_second_run_into_the_same_folder_is_refused(good, monkeypatch):
    spy = Spy(monkeypatch, good["matrix"])
    with pytest.raises(wf.HarnessRefused, match="already exists"):
        drv.run_real(
            good["ctx"], load_inputs=spy.loader, fit_builder=spy.builder, out_root=good["tmp"] / "out1"
        )


# ------------------------------------------------------------------------------------------- 5. deterministic
def test_same_inputs_give_the_same_records_and_verdict_text(good, monkeypatch):
    spy = Spy(monkeypatch, good["matrix"])
    res2 = drv.run_real(
        good["ctx"], load_inputs=spy.loader, fit_builder=spy.builder, out_root=good["tmp"] / "out2"
    )
    d1, d2 = Path(good["res"]["run_dir"]), Path(res2["run_dir"])
    assert d1.name == d2.name  # same run id
    assert (d1 / "VERDICT_dev.json").read_text("utf-8") == (d2 / "VERDICT_dev.json").read_text("utf-8")
    assert (d1 / "VERDICT_dev.txt").read_text("utf-8") == (d2 / "VERDICT_dev.txt").read_text("utf-8")
    for p in sorted(d1.glob("dev_*.json")):
        assert p.read_bytes() == (d2 / p.name).read_bytes()


# ------------------------------------------------------------------ 6. same spec, recipe and folds as the protocol
def test_the_spec_and_recipe_are_the_signed_ones():
    spec = drv.build_spec(REPO)
    protocol = (REPO / drv.PROTOCOL_REL).read_text("utf-8")
    sheet = json.loads((REPO / drv.EVID_REL / "final_hashes_v4.json").read_text("utf-8"))["candidates"]["SX5"]
    assert spec.config_sha256() == sheet["datasetspec_config_sha256"]
    assert spec.config_sha256() in protocol
    assert len(spec.symbols) == 47 and sheet["n_symbols"] == 47
    assert len(spec.exclusions) == 187
    assert (
        drv.bound_values(REPO, spec, drv.build_params(0.0018), REPO / drv.PROTOCOL_REL)["recipe_sha256"]
        in protocol
    )
    folds = wf.default_folds(include_holdout=False)
    assert len(folds) == 34 and {f.kind for f in folds} == {"dev"}
    assert wf.folds_sha256(folds, 5, 5) == sheet["fold_definition_sha256_dev_only"]


def test_the_default_verdict_parameters_are_the_signed_set_with_only_mde_h_supplied():
    p = drv.build_params(0.0018)
    assert (p.horizon, p.burn_in_folds, p.last_fold_index, p.holm_mode, p.idea_rule) == (
        5,
        4,
        33,
        "single_horizon",
        "no_repeat",
    )
    with pytest.raises(v.VerdictRefused):
        drv.build_params(0.18)  # percentage points typed as a fraction


# ------------------------------------------------------------------------------------------- source guarantees
def test_the_driver_cannot_open_the_holdout_or_touch_production():
    src = SCRIPT.read_text("utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    for bad in (
        "holdout_records",
        "include_holdout=True",
        "append_authorisation",
        "append_recovery",
        "mark_started",
        "mark_results_exposed",
        "mark_completed",
        "gate_for_run",
        "SessionLocal",
        "sqlalchemy",
        "psycopg",
        "ml_models",
        "MODEL_ARTIFACT_DIR",
        "ml.predict",
        "git commit",
        "git tag",
    ):
        assert bad not in code, bad
    assert "include_holdout=False" in code and "compute_verdict(result.records, params)" in code
    assert code.count("compute_verdict(") == 1


def test_nothing_in_the_app_imports_the_driver():
    root = Path(wf.__file__).resolve().parents[1]
    for p in root.rglob("*.py"):
        assert "sx5_run" not in p.read_text("utf-8"), p
