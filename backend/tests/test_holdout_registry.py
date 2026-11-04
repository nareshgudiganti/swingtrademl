"""Pure tests (tmp_path only, no database, no model fit on real data) for ml/holdout_registry.py and its hook."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from swing_trade_ml.ml import holdout_registry as hr
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sector_walkforward as wf

from test_sector_walkforward import HOLD, lstsq_fit, make_matrix, spec_for  # noqa: E402

H64 = lambda c: c * 64  # noqa: E731
RECIPE = H64("e")
ARMS = {
    a: {"feature_list_sha256": H64(str(i)), "fit_recipe_sha256": RECIPE}
    for i, a in enumerate(("A_53", "R_37", "C_56"))
}


def bound(horizon=5, **kw):
    b = {
        "candidate": hr.HORIZON_CANDIDATE[horizon],
        "horizon": horizon,
        "protocol_id": "sx-protocol-test",
        "protocol_sha256": H64("a"),
        "dataset_sha256": H64("b"),
        "config_sha256": H64("c"),
        "harness_config_sha256": H64("d"),
        "fold_definition_sha256": H64("f"),
        "code_version": "commit-1",
        "arms": ARMS,
    }
    b.update(kw)
    return b


def run_of(horizon=5, **kw):
    return bound(horizon, **kw)


@pytest.fixture
def paths(tmp_path):
    return {"registry_path": tmp_path / "reg" / "R.jsonl", "lock_path": tmp_path / "lock" / "h.lock"}


def authorise(paths, eid="ev5", horizon=5, **kw):
    kw.setdefault("signer", "owner")
    kw.setdefault("signed_date", "2026-11-06")
    kw.setdefault("reason", "first holdout")
    return hr.append_authorisation(
        eid, authorisation_text="I authorise this", bound=bound(horizon), **kw, **paths
    )


def start(paths, horizon=5, **kw):
    return hr.require_authorised_and_mark_started(run_of(horizon, **kw), **paths)


def complete(paths, eid="ev5"):
    return hr.mark_completed(eid, {a: [H64("9")] for a in ARMS}, **paths)


def lines(paths):
    return paths["registry_path"].read_text(encoding="utf-8").split("\n")[:-1]


# ------------------------------------------------------------------------------------------ authorisation
def test_no_authorisation_refuses_and_the_real_registry_has_none_today(paths):
    with pytest.raises(hr.HoldoutRefused, match="no owner authorisation"):
        start(paths)
    assert not paths["registry_path"].exists()  # a refusal writes nothing
    # the committed repository registry: no AUTHORISED entry exists today
    real = hr.REGISTRY_PATH
    if real.exists():
        assert hr.verify(real, Path(paths["lock_path"]))["events"] == {}


def test_authorisation_needs_signer_date_and_text_hash_and_exact_arms(paths):
    for bad in ({"signer": " "}, {"signed_date": "06/11/2026"}, {"reason": ""}):
        with pytest.raises(hr.HoldoutRefused):
            authorise(paths, **bad)
    with pytest.raises(hr.HoldoutRefused, match="arms"):
        hr.append_authorisation(
            "x",
            authorisation_text="t",
            signer="o",
            signed_date="2026-11-06",
            reason="r",
            bound=bound(arms={"A_53": ARMS["A_53"], "R_37": ARMS["R_37"]}),
            **paths,
        )
    e = authorise(paths)
    assert e["body"]["authorisation_text_sha256"] == hr.sha256_text("I authorise this")
    assert e["seq"] == 0 and e["prev_sha256"] == hr.GENESIS


def test_authorised_writes_started_before_any_fit_and_completes(paths):
    authorise(paths)
    eid = start(paths)
    assert eid == "ev5"
    assert hr.event_states(**paths) == {"ev5": "STARTED"}
    complete(paths)
    assert hr.event_states(**paths) == {"ev5": "COMPLETED"}
    types = [json.loads(x)["type"] for x in lines(paths)]
    assert types == ["AUTHORISED", "STARTED", "COMPLETED"]


def test_completed_must_cover_exactly_the_authorised_arms(paths):
    authorise(paths)
    start(paths)
    with pytest.raises(hr.HoldoutRefused, match="exactly the authorised arms"):
        hr.mark_completed("ev5", {"A_53": [H64("9")]}, **paths)


# ------------------------------------------------------------------------------------------ refusals
def test_second_start_for_the_same_horizon_is_refused_whatever_else_changes(paths):
    authorise(paths)
    start(paths)
    complete(paths)
    for variant in (run_of(), run_of(code_version="other"), run_of(protocol_sha256=H64("1"))):
        with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
            hr.require_authorised_and_mark_started(variant, **paths)


def test_partial_or_different_arms_are_refused(paths):
    authorise(paths)
    partial = {a: ARMS[a] for a in ("A_53", "R_37")}
    with pytest.raises(hr.HoldoutRefused, match="partial"):
        hr.require_authorised_and_mark_started(run_of(arms=partial), **paths)
    swapped = {**ARMS, "C_57": ARMS["C_56"]}
    del swapped["C_56"]
    with pytest.raises(hr.HoldoutRefused, match="arm set"):
        hr.require_authorised_and_mark_started(run_of(arms=swapped), **paths)
    assert hr.event_states(**paths) == {"ev5": "AUTHORISED"}  # nothing was consumed


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_sha256", H64("0")),
        ("protocol_sha256", H64("0")),
        ("config_sha256", H64("0")),
        ("harness_config_sha256", H64("0")),
        ("fold_definition_sha256", H64("0")),
        ("code_version", "commit-2"),
        ("horizon", 10),
    ],
)
def test_hash_or_code_mismatch_is_refused_and_consumes_nothing(paths, field, value):
    authorise(paths)
    kw = {field: value}
    if field == "horizon":
        kw["candidate"] = "SX10"
    with pytest.raises(hr.HoldoutRefused):
        hr.require_authorised_and_mark_started(run_of(**kw), **paths)
    assert hr.event_states(**paths) == {"ev5": "AUTHORISED"}


def test_arm_feature_or_recipe_hash_mismatch_is_refused(paths):
    authorise(paths)
    for key in ("feature_list_sha256", "fit_recipe_sha256"):
        arms = {**ARMS, "C_56": {**ARMS["C_56"], key: H64("0")}}
        with pytest.raises(hr.HoldoutRefused, match="C_56"):
            hr.require_authorised_and_mark_started(run_of(arms=arms), **paths)


def test_two_horizons_are_independent(paths):
    authorise(paths, "ev5", 5)
    authorise(paths, "ev10", 10)
    start(paths, 5)
    complete(paths, "ev5")
    assert start(paths, 10) == "ev10"
    assert hr.event_states(**paths) == {"ev5": "COMPLETED", "ev10": "STARTED"}


def test_new_event_for_a_consumed_horizon_needs_a_signed_superseding_authorisation(paths):
    authorise(paths)
    start(paths)
    complete(paths)
    with pytest.raises(hr.HoldoutRefused, match="supersedes_event_id"):
        authorise(paths, "ev5b", reason="please")
    with pytest.raises(hr.HoldoutRefused, match="supersedes_event_id"):
        authorise(paths, "ev5b", supersedes_event_id="nope", reason="x")
    authorise(paths, "ev5b", supersedes_event_id="ev5", reason="owner re-run because X")
    assert start(paths) == "ev5b"
    with pytest.raises(hr.HoldoutRefused, match="supersedes_event_id"):
        authorise(paths, "ev5c", reason="r")


# ------------------------------------------------------------------------------------------ crash / recovery
def test_crash_after_started_keeps_the_holdout_consumed(paths):
    authorise(paths)
    start(paths)  # process dies here: no COMPLETED
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        start(paths)
    hr.mark_aborted("ev5", "machine rebooted", **paths)
    assert hr.event_states(**paths) == {"ev5": "ABORTED"}
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        start(paths)


def test_recovery_authorisation_reopens_exactly_one_attempt_and_is_append_only(paths):
    authorise(paths)
    start(paths)
    before = lines(paths)
    with pytest.raises(hr.HoldoutRefused, match="no holdout predictions"):
        hr.append_recovery_authorisation(
            "ev5",
            authorisation_text="t",
            signer="o",
            signed_date="2026-11-06",
            reason="crash",
            no_predictions_or_metrics_observed=False,
            **paths,
        )
    rec = hr.append_recovery_authorisation(
        "ev5",
        authorisation_text="recovery text",
        signer="owner",
        signed_date="2026-11-07",
        reason="power cut",
        no_predictions_or_metrics_observed=True,
        **paths,
    )
    assert rec["body"]["started_entry_sha256"] == hr._line_sha(before[1])
    assert lines(paths)[: len(before)] == before  # earlier lines untouched
    assert hr.event_states(**paths) == {"ev5": "RECOVERY_AUTHORISED"}
    assert start(paths) == "ev5"
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        start(paths)  # one recovery = one further attempt
    complete(paths)
    hr.verify(**paths)
    with pytest.raises(hr.HoldoutRefused):
        hr.append_recovery_authorisation(
            "ev5",
            authorisation_text="t",
            signer="o",
            signed_date="2026-11-07",
            reason="r",
            no_predictions_or_metrics_observed=True,
            **paths,
        )


def test_recovery_cannot_start_with_different_hashes(paths):
    authorise(paths)
    start(paths)
    hr.append_recovery_authorisation(
        "ev5",
        authorisation_text="t",
        signer="o",
        signed_date="2026-11-07",
        reason="r",
        no_predictions_or_metrics_observed=True,
        **paths,
    )
    with pytest.raises(hr.HoldoutRefused):
        start(paths, dataset_sha256=H64("0"))


# ------------------------------------------------------------------------------------------ tamper
def _setup_three(paths):
    authorise(paths)
    start(paths)
    complete(paths)


def _write(paths, ls):
    paths["registry_path"].write_bytes(("\n".join(ls) + "\n").encode("utf-8"))  # no CRLF translation


def test_verify_passes_on_untouched_registry(paths):
    _setup_three(paths)
    rep = hr.verify(**paths)
    assert rep["entries"] == 3 and rep["events"] == {"ev5": "COMPLETED"}


def test_edit_is_detected(paths):
    _setup_three(paths)
    ls = lines(paths)
    ls[0] = ls[0].replace("owner", "mallory")
    _write(paths, ls)
    with pytest.raises(hr.RegistryCorrupt):
        hr.verify(**paths)


def test_whitespace_or_noncanonical_edit_is_detected(paths):
    _setup_three(paths)
    ls = lines(paths)
    ls[1] = json.dumps(json.loads(ls[1]), indent=1).replace("\n", " ")
    _write(paths, ls)
    with pytest.raises(hr.RegistryCorrupt, match="canonical"):
        hr.verify(**paths)


def test_delete_middle_and_reorder_are_detected(paths):
    _setup_three(paths)
    ls = lines(paths)
    _write(paths, [ls[0], ls[2]])
    with pytest.raises(hr.RegistryCorrupt):
        hr.verify(**paths)
    _write(paths, [ls[1], ls[0], ls[2]])
    with pytest.raises(hr.RegistryCorrupt):
        hr.verify(**paths)


def test_truncated_tail_is_detected_on_this_machine_by_the_guard(paths):
    _setup_three(paths)
    ls = lines(paths)
    _write(paths, ls[:2])  # chain alone cannot see this; the local guard can
    with pytest.raises(hr.RegistryCorrupt, match="truncated"):
        hr.verify(**paths)
    with pytest.raises(hr.HoldoutRefused):
        start(paths)  # and an attacker cannot re-open the holdout that way


def test_deleting_the_registry_after_use_does_not_reopen_the_holdout(paths):
    authorise(paths)
    start(paths)
    paths["registry_path"].unlink()
    with pytest.raises(hr.HoldoutRefused):
        start(paths)


def test_partial_line_is_detected(paths):
    _setup_three(paths)
    with open(paths["registry_path"], "ab") as fh:
        fh.write(b'{"seq":3')
    with pytest.raises(hr.RegistryCorrupt, match="newline"):
        hr.verify(**paths)


def test_a_forged_state_sequence_is_detected_even_with_a_valid_chain(paths):
    """Someone recomputes the chain after removing STARTED: replay rules still catch COMPLETED-without-STARTED."""
    _setup_three(paths)
    ls = lines(paths)
    e2 = json.loads(ls[2])
    e2["seq"], e2["prev_sha256"] = 1, hr._line_sha(ls[0])
    _write(paths, [ls[0], hr._canon(e2)])
    with pytest.raises(hr.RegistryCorrupt, match="COMPLETED needs state STARTED"):
        hr.verify(**paths)


def test_appends_are_pure_appends(paths):
    authorise(paths)
    a = paths["registry_path"].read_bytes()
    start(paths)
    b = paths["registry_path"].read_bytes()
    assert b.startswith(a) and len(b) > len(a)


# ------------------------------------------------------------------------------------------ concurrency
def test_threads_cannot_both_start(paths):
    authorise(paths)
    n, barrier, results = 8, threading.Barrier(8), []

    def go():
        barrier.wait()
        try:
            start(paths)
            results.append("ok")
        except hr.HoldoutRefused:
            results.append("refused")

    ts = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count("ok") == 1 and results.count("refused") == n - 1
    hr.verify(**paths)


SCRIPT = """
import sys
from swing_trade_ml.ml import holdout_registry as hr
b = {b!r}
try:
    hr.require_authorised_and_mark_started(b, registry_path=sys.argv[1], lock_path=sys.argv[2])
    print("OK")
except hr.HoldoutRefused:
    print("REFUSED")
"""


def test_two_processes_cannot_both_start(paths):
    authorise(paths)
    src = Path(hr.__file__).resolve().parents[2]
    env = {"PYTHONPATH": str(src), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    cmd = [
        sys.executable,
        "-c",
        SCRIPT.format(b=run_of()),
        str(paths["registry_path"]),
        str(paths["lock_path"]),
    ]
    procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, env=env) for _ in range(2)]
    outs = sorted(p.communicate(timeout=120)[0].strip() for p in procs)
    assert outs == ["OK", "REFUSED"]
    hr.verify(**paths)


# ------------------------------------------------------------------------------------------ location
def test_default_registry_is_repository_fixed_and_not_under_any_run_path(monkeypatch):
    monkeypatch.undo()  # drop the autouse tmp lock path: look at the real module constants
    repo = Path(wf.__file__).resolve().parents[4]
    assert hr.REGISTRY_PATH == repo / "docs" / "brain" / "evidence" / "sector_prep" / "HOLDOUT-REGISTRY.jsonl"
    assert hr.LOCK_PATH == repo / "backend" / "data" / "research_holdout.lock"
    assert sr.RESEARCH_ROOT not in hr.REGISTRY_PATH.parents
    import inspect

    src = inspect.getsource(wf.run_walkforward)
    assert "holdout_registry_path" in src and "out_root" not in inspect.getsource(hr.gate_for_run)


# ------------------------------------------------------------------------------------------ harness integration
@pytest.fixture(scope="module")
def matrix():
    return make_matrix()


def recipe_fit(fn=lstsq_fit):
    def f(X, y, meta, *, seed):
        return fn(X, y, meta, seed=seed)

    f.recipe_sha256 = RECIPE
    return f


def real_kwargs(tmp_path, sub, matrix, protocol, *, fit=None, **kw):
    sp = spec_for()
    appr = tmp_path / "appr.json"
    appr.write_text(
        json.dumps(
            {
                "protocol_id": "t",
                "approved_by": "unit",
                "candidate": "SX5",
                "config_sha256": sp.config_sha256(),
            }
        )
    )
    return dict(
        fit_fn=fit or recipe_fit(),
        code_version="commit-1",
        folds=HOLD,
        approval_path=appr,
        out_root=tmp_path / sub,
        marker_dir=tmp_path / (sub + "_m"),
        holdout_protocol_path=protocol,
        holdout_registry_path=tmp_path / "reg" / "R.jsonl",
        **kw,
    ), sp


@pytest.fixture
def real_ctx(tmp_path, matrix, monkeypatch):
    """Capture the values the harness would bind, then authorise exactly those."""
    protocol = tmp_path / "protocol.md"
    protocol.write_text("sx protocol text", encoding="utf-8")
    seen = {}
    orig = hr.gate_for_run

    def spy(**kw):
        seen.update(kw["run"])
        return orig(**kw)

    monkeypatch.setattr(hr, "gate_for_run", spy)
    kw, sp = real_kwargs(tmp_path, "probe", matrix, protocol)
    with pytest.raises(hr.HoldoutRefused, match="no owner authorisation"):
        wf.run_walkforward(sp, matrix, **kw)
    b = {
        **{k: seen[k] for k in hr.BOUND_SCALARS if k != "protocol_id" and k != "protocol_sha256"},
        "protocol_id": "sx-protocol-test",
        "protocol_sha256": hr.sha256_file(protocol),
        "arms": {
            a: {"feature_list_sha256": s, "fit_recipe_sha256": RECIPE}
            for a, s in seen["arm_feature_shas"].items()
        },
    }
    return protocol, b, kw["holdout_registry_path"], sp


def authorise_ctx(ctx, tmp_path):
    protocol, b, reg, sp = ctx
    hr.append_authorisation(
        "int5",
        authorisation_text="owner says yes",
        signer="owner",
        signed_date="2026-11-06",
        reason="test",
        bound=b,
        registry_path=reg,
        lock_path=tmp_path / "lk" / "l.lock",
    )


@pytest.fixture(autouse=True)
def _lock_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "LOCK_PATH", tmp_path / "lk" / "l.lock")


def test_harness_refuses_without_authorisation_and_never_fits_the_holdout(matrix, tmp_path, real_ctx):
    protocol, b, reg, sp = real_ctx
    calls = []

    def fit(X, y, meta, *, seed):
        calls.append(1)
        return lstsq_fit(X, y, meta, seed=seed)

    fit.recipe_sha256 = RECIPE
    kw, sp = real_kwargs(tmp_path, "n1", matrix, protocol, fit=fit)
    with pytest.raises(hr.HoldoutRefused):
        wf.run_walkforward(sp, matrix, **kw)
    assert calls == []  # refused by the read-only pre-check, before even the development folds


def test_harness_writes_started_before_the_first_holdout_fit_and_crash_keeps_it_consumed(
    matrix, tmp_path, real_ctx
):
    protocol, b, reg, sp = real_ctx
    authorise_ctx(real_ctx, tmp_path)
    seen_states = []
    n_dev = 3 * (len(HOLD) - 1)
    count = [0]

    def fit(X, y, meta, *, seed):
        count[0] += 1
        if count[0] > n_dev:  # first holdout fit
            seen_states.append(hr.event_states(reg, tmp_path / "lk" / "l.lock"))
            raise RuntimeError("boom")
        return lstsq_fit(X, y, meta, seed=seed)

    fit.recipe_sha256 = RECIPE
    kw, sp = real_kwargs(tmp_path, "c1", matrix, protocol, fit=fit)
    with pytest.raises(RuntimeError, match="boom"):
        wf.run_walkforward(sp, matrix, **kw)
    assert seen_states == [{"int5": "STARTED"}]
    kw2, _ = real_kwargs(tmp_path, "c2", matrix, protocol)
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        wf.run_walkforward(sp, matrix, **kw2)


def test_out_root_marker_dir_run_name_and_protocol_copy_cannot_bypass(matrix, tmp_path, real_ctx):
    protocol, b, reg, sp = real_ctx
    authorise_ctx(real_ctx, tmp_path)
    kw, sp = real_kwargs(tmp_path, "ok1", matrix, protocol)
    res = wf.run_walkforward(sp, matrix, **kw)
    assert hr.event_states(reg, tmp_path / "lk" / "l.lock") == {"int5": "COMPLETED"}
    done = [json.loads(x) for x in reg.read_text().splitlines()][-1]
    assert set(done["body"]["holdout_records"]) == {"A_53", "R_37", "C_57"}
    assert all(
        s in {r["record_sha256"] for r in res.records}
        for v in done["body"]["holdout_records"].values()
        for s in v
    )
    copy = tmp_path / "elsewhere" / "protocol_copy.md"
    copy.parent.mkdir()
    copy.write_bytes(protocol.read_bytes())
    kw2, _ = real_kwargs(tmp_path, "totally/other/root", matrix, copy)
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        wf.run_walkforward(sp, matrix, **kw2)
    # the old per-run marker is still a second guard (a fresh registry would not help with the same marker_dir)
    kw3, _ = real_kwargs(tmp_path, "ok1", matrix, protocol)
    with pytest.raises(wf.HoldoutAlreadyUsed):
        wf.run_walkforward(sp, matrix, **kw3)


def test_harness_needs_protocol_file_recipe_hash_and_refuses_dev_folds_reaching_the_holdout(
    matrix, tmp_path, real_ctx
):
    protocol, b, reg, sp = real_ctx
    kw, sp = real_kwargs(tmp_path, "g1", matrix, protocol)
    with pytest.raises(hr.HoldoutRefused, match="holdout_protocol_path"):
        wf.run_walkforward(sp, matrix, **{**kw, "holdout_protocol_path": None})
    with pytest.raises(hr.HoldoutRefused, match="recipe_sha256"):
        wf.run_walkforward(sp, matrix, **{**kw, "fit_fn": lstsq_fit})
    sneaky = wf.make_folds(date(2026, 1, 1), date(2026, 3, 1))  # kind "dev" but inside the holdout window
    with pytest.raises(hr.HoldoutRefused, match="not a holdout fold"):
        wf.run_walkforward(sp, matrix, **{**kw, "folds": sneaky})


def test_synthetic_runs_do_not_touch_the_registry(matrix, tmp_path):
    reg = tmp_path / "reg" / "R.jsonl"
    wf.run_walkforward(
        spec_for(),
        matrix,
        fit_fn=lstsq_fit,
        code_version="x",
        folds=HOLD,
        synthetic=True,
        out_root=tmp_path / "s",
        marker_dir=tmp_path / "s_m",
        holdout_registry_path=reg,
    )
    assert not reg.exists()
