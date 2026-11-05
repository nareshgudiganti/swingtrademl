"""Security tests for the holdout registry (2026-11-08 review): exposure gate, recovery rules, concurrency,
durability. Pure: synthetic data, scratch registries, no real holdout is ever run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from swing_trade_ml.ml import holdout_registry as hr
from swing_trade_ml.ml import sector_walkforward as wf

from test_holdout_registry import (  # noqa: F401  (fixtures are collected from the importing module)
    ARMS,
    H64,
    RECIPE,
    _lock_in_tmp,
    authorise,
    authorise_ctx,
    complete,
    expose,
    lines,
    locs,
    matrix,
    paths,
    real_ctx,
    real_kwargs,
    run_of,
    start,
)
from test_sector_walkforward import lstsq_fit  # noqa: E402

HOLD_LOCK = None


def recover(paths, text="recovery text", eid="ev5", observed=True):
    return hr.append_recovery_authorisation(
        eid,
        authorisation_text=text,
        signer="owner",
        signed_date="2026-11-08",
        reason="power cut",
        no_predictions_or_metrics_observed=observed,
        **paths,
    )


def types(paths):
    return [json.loads(x)["type"] for x in lines(paths)]


# ------------------------------------------------------------------------------------------ exposure gate
def test_exposure_marker_is_chained_and_after_it_no_recovery_is_possible_whatever_the_owner_says(paths):
    authorise(paths)
    start(paths)
    e = expose(paths)
    assert e["type"] == "RESULTS_EXPOSED" and e["body"]["exposure_point"] == hr.EXPOSURE_POINT
    assert hr.event_states(**paths) == {"ev5": "RESULTS_EXPOSED"}
    with pytest.raises(hr.HoldoutRefused, match="exposed"):
        recover(paths)
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        start(paths, marker="m2")
    n = len(lines(paths))
    hr.mark_aborted("ev5", "crash after exposure", **paths)
    assert hr.event_states(**paths) == {"ev5": "ABORTED"}
    with pytest.raises(hr.HoldoutRefused, match="exposed"):  # an ABORTED event that was exposed stays closed
        recover(paths, "other text")
    assert len(lines(paths)) == n + 1
    hr.verify(**paths)


def test_forged_recovery_after_exposure_is_rejected_by_the_replay_even_with_a_valid_chain(paths):
    authorise(paths)
    start(paths)
    expose(paths)
    entries = hr._load(paths["registry_path"], paths["lock_path"])
    info = hr._replay(entries)["ev5"]
    body = {
        **info["bound"],
        "signer": "o",
        "signed_date": "2026-11-08",
        "reason": "r",
        "authorisation_text_sha256": hr.sha256_text("forged"),
        "started_entry_sha256": info["started_sha"],
        "no_predictions_or_metrics_observed": True,
    }
    with pytest.raises(hr.HoldoutRefused, match="exposed"):
        hr._append(paths["registry_path"], paths["lock_path"], entries, hr.T_RECOVER, "ev5", body)


def test_completed_requires_results_exposed_first(paths):
    authorise(paths)
    start(paths)
    with pytest.raises(hr.HoldoutRefused, match="RESULTS_EXPOSED"):
        hr.mark_completed("ev5", {a: [H64("9")] for a in ARMS}, **paths)
    expose(paths)
    hr.mark_completed("ev5", {a: [H64("9")] for a in ARMS}, **paths)
    assert types(paths) == ["AUTHORISED", "STARTED", "RESULTS_EXPOSED", "COMPLETED"]


def test_exposure_marker_only_from_started_and_only_once(paths):
    authorise(paths)
    with pytest.raises(hr.HoldoutRefused):
        expose(paths)  # nothing started
    start(paths)
    expose(paths)
    with pytest.raises(hr.HoldoutRefused):
        expose(paths)


def test_new_event_after_exposure_needs_a_new_protocol_id(paths):
    authorise(paths)
    start(paths)
    complete(paths)
    with pytest.raises(hr.HoldoutRefused, match="NEW protocol id"):
        authorise(paths, "ev5b", supersedes_event_id="ev5", reason="again")
    authorise(paths, "ev5b", supersedes_event_id="ev5", reason="again", proto="sx-protocol-v2")


# ------------------------------------------------------------------------------------------ recovery rules
def test_recovery_binds_started_line_and_hashes_and_carries_signer_date_text(paths):
    authorise(paths)
    start(paths)
    started = hr._line_sha(lines(paths)[1])
    r = recover(paths)["body"]
    assert r["started_entry_sha256"] == started
    assert r["signer"] == "owner" and r["signed_date"] == "2026-11-08"
    assert r["authorisation_text_sha256"] == hr.sha256_text("recovery text")
    for k in hr.BOUND_SCALARS:
        assert k in r
    assert r["arms"] == ARMS


def test_second_recovery_is_refused(paths):
    authorise(paths)
    start(paths)
    recover(paths)
    start(paths, marker="m2")  # the recovered attempt crashes as well
    with pytest.raises(hr.HoldoutRefused, match="single recovery"):
        recover(paths, "another text")
    entries = hr._load(paths["registry_path"], paths["lock_path"])
    assert [e["type"] for e in entries].count("RECOVERY_AUTHORISATION") == 1


def test_recovery_after_completed_is_refused(paths):
    authorise(paths)
    start(paths)
    complete(paths)
    with pytest.raises(hr.HoldoutRefused):
        recover(paths)


def test_recovery_with_a_changed_hash_is_refused(paths):
    authorise(paths)
    start(paths)
    entries = hr._load(paths["registry_path"], paths["lock_path"])
    info = hr._replay(entries)["ev5"]
    good = {
        **info["bound"],
        "signer": "o",
        "signed_date": "2026-11-08",
        "reason": "r",
        "authorisation_text_sha256": hr.sha256_text("x"),
        "started_entry_sha256": info["started_sha"],
        "no_predictions_or_metrics_observed": True,
    }
    for patch in (
        {"dataset_sha256": H64("0")},
        {"started_entry_sha256": H64("0")},
        {"code_version": "other"},
    ):
        with pytest.raises(hr.HoldoutRefused):
            hr._append(
                paths["registry_path"], paths["lock_path"], entries, hr.T_RECOVER, "ev5", {**good, **patch}
            )
    assert hr.event_states(**paths) == {"ev5": "STARTED"}


def test_a_recovery_cannot_reuse_a_previous_authorisation_text(paths):
    authorise(paths, "ev5")
    authorise(paths, "ev10", 10)
    start(paths, 5)
    start(paths, 10)
    with pytest.raises(hr.HoldoutRefused, match="already used"):
        recover(paths, text="I authorise this")  # the text of the original authorisation
    recover(paths, "recovery text", "ev5")
    with pytest.raises(hr.HoldoutRefused, match="already used"):
        recover(paths, "recovery text", "ev10")


def test_recovery_refused_when_a_holdout_record_file_exists_or_locations_are_unknown(paths):
    authorise(paths)
    start(paths)
    out = Path(paths["registry_path"]).parent.parent / "run_out" / "SX5" / "run_abc"
    out.mkdir(parents=True)
    (out / "dev_000_A_53.json").write_text("{}")  # development records are fine
    recover_ok_probe = None  # noqa: F841
    (out / "holdout_007_A_53.json").write_text("{}")
    with pytest.raises(hr.HoldoutRefused, match="record files exist"):
        recover(paths)
    assert hr.event_states(**paths) == {"ev5": "STARTED"}
    # a STARTED entry that named no locations cannot be proven clean
    p2 = {
        "registry_path": Path(paths["registry_path"]).with_name("R2.jsonl"),
        "lock_path": paths["lock_path"].with_name("l2.lock"),
    }
    authorise(p2)
    hr.require_authorised_and_mark_started(run_of(), **p2)
    with pytest.raises(hr.HoldoutRefused, match="no record locations"):
        recover(p2)


def test_recovered_start_needs_a_fresh_marker_directory(paths):
    authorise(paths)
    start(paths)
    recover(paths)
    with pytest.raises(hr.HoldoutRefused, match="fresh marker"):
        start(paths)  # same marker file as the crashed run
    fresh = Path(locs(paths, "m2")["marker_file"])
    fresh.parent.mkdir(parents=True)
    fresh.write_text("{}")
    with pytest.raises(hr.HoldoutRefused, match="fresh marker"):
        start(paths, marker="m2")  # exists already
    with pytest.raises(hr.HoldoutRefused, match="fresh marker"):
        hr.require_authorised_and_mark_started(run_of(), **paths)  # no locations at all
    assert start(paths, marker="m3") == "ev5"


# ------------------------------------------------------------------------------------------ harness orderings
def _fit_with_hooks(on_fit_holdout=None, on_predict_holdout=None, n_dev=None):
    count = [0]
    calls = {"predict": 0}

    def fit(X, y, meta, *, seed):
        count[0] += 1
        holdout = count[0] > n_dev
        if holdout and on_fit_holdout:
            on_fit_holdout()
        inner = lstsq_fit(X, y, meta, seed=seed)

        def predict(Xt):
            if holdout:
                calls["predict"] += 1
                if on_predict_holdout:
                    on_predict_holdout()
            return inner(Xt)

        return predict

    fit.recipe_sha256 = RECIPE
    return fit, calls


def test_hard_kill_between_fit_and_marker_leaves_a_recoverable_state_and_no_prediction(
    matrix, tmp_path, real_ctx, monkeypatch
):
    protocol, b, reg, sp = real_ctx
    authorise_ctx(real_ctx, tmp_path)
    lock = tmp_path / "lk" / "l.lock"
    n_dev = 3 * (len(__import__("test_sector_walkforward").HOLD) - 1)
    fit, calls = _fit_with_hooks(n_dev=n_dev)

    def boom(*a, **k):
        raise OSError("disk full / killed while writing the exposure marker")

    monkeypatch.setattr(hr, "mark_results_exposed", boom)
    kw, sp = real_kwargs(tmp_path, "k1", matrix, protocol, fit=fit)
    with pytest.raises(OSError):
        wf.run_walkforward(sp, matrix, **kw)
    assert calls["predict"] == 0  # no holdout prediction was ever produced
    monkeypatch.undo()
    monkeypatch.setattr(hr, "LOCK_PATH", lock)
    assert hr.event_states(reg, lock) == {"int5": "STARTED"}
    # no exposure: the owner may recover; the old marker (same marker_dir) still blocks, a fresh one works
    hr.append_recovery_authorisation(
        "int5",
        authorisation_text="rec",
        signer="owner",
        signed_date="2026-11-08",
        reason="crash before marker",
        no_predictions_or_metrics_observed=True,
        registry_path=reg,
        lock_path=lock,
    )
    kw_same, _ = real_kwargs(tmp_path, "k1", matrix, protocol)
    with pytest.raises(wf.HoldoutAlreadyUsed):
        wf.run_walkforward(sp, matrix, **kw_same)
    kw2, _ = real_kwargs(tmp_path, "k2", matrix, protocol)
    wf.run_walkforward(sp, matrix, **kw2)
    assert hr.event_states(reg, lock) == {"int5": "COMPLETED"}
    t = [json.loads(x)["type"] for x in reg.read_text().splitlines()]
    assert t == ["AUTHORISED", "STARTED", "RECOVERY_AUTHORISATION", "STARTED", "RESULTS_EXPOSED", "COMPLETED"]


def test_the_marker_is_on_disk_before_the_first_holdout_prediction_and_a_kill_after_it_is_final(
    matrix, tmp_path, real_ctx
):
    protocol, b, reg, sp = real_ctx
    authorise_ctx(real_ctx, tmp_path)
    lock = tmp_path / "lk" / "l.lock"
    seen = []

    def at_predict():
        seen.append(hr.event_states(reg, lock))
        raise RuntimeError("killed after the first holdout prediction")

    n_dev = 3 * (len(__import__("test_sector_walkforward").HOLD) - 1)
    fit, calls = _fit_with_hooks(on_predict_holdout=at_predict, n_dev=n_dev)
    kw, sp = real_kwargs(tmp_path, "x1", matrix, protocol, fit=fit)
    with pytest.raises(RuntimeError, match="killed"):
        wf.run_walkforward(sp, matrix, **kw)
    assert seen == [{"int5": "RESULTS_EXPOSED"}]  # marker was durable BEFORE predict produced anything
    with pytest.raises(hr.HoldoutRefused, match="exposed"):
        hr.append_recovery_authorisation(
            "int5",
            authorisation_text="rec",
            signer="owner",
            signed_date="2026-11-08",
            reason="r",
            no_predictions_or_metrics_observed=True,
            registry_path=reg,
            lock_path=lock,
        )
    kw2, _ = real_kwargs(tmp_path, "x2", matrix, protocol)
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        wf.run_walkforward(sp, matrix, **kw2)


def test_records_on_disk_without_a_completed_entry_also_close_recovery(
    matrix, tmp_path, real_ctx, monkeypatch
):
    """Crash after the records were written but before COMPLETED: marker exists, so no recovery."""
    protocol, b, reg, sp = real_ctx
    authorise_ctx(real_ctx, tmp_path)
    lock = tmp_path / "lk" / "l.lock"
    monkeypatch.setattr(hr, "mark_completed", lambda *a, **k: (_ for _ in ()).throw(OSError("killed")))
    kw, sp = real_kwargs(tmp_path, "r1", matrix, protocol)
    with pytest.raises(OSError):
        wf.run_walkforward(sp, matrix, **kw)
    assert hr.event_states(reg, lock) == {"int5": "RESULTS_EXPOSED"}
    assert list((tmp_path / "r1").rglob("holdout_*.json"))
    with pytest.raises(hr.HoldoutRefused, match="exposed"):
        hr.append_recovery_authorisation(
            "int5",
            authorisation_text="rec",
            signer="owner",
            signed_date="2026-11-08",
            reason="r",
            no_predictions_or_metrics_observed=True,
            registry_path=reg,
            lock_path=lock,
        )


# ------------------------------------------------------------------------------------------ durability
def test_torn_append_is_refused_and_never_counts_as_an_entry(paths, monkeypatch):
    authorise(paths)
    before = paths["registry_path"].read_bytes()
    real_write = os.write

    def torn(fd, data):
        real_write(fd, bytes(data)[: len(bytes(data)) // 2])
        raise OSError("power cut mid-append")

    monkeypatch.setattr(os, "write", torn)
    with pytest.raises(OSError):
        start(paths)
    monkeypatch.undo()
    raw = paths["registry_path"].read_bytes()
    assert raw.startswith(before) and not raw.endswith(b"\n") and len(raw) > len(before)
    with pytest.raises(hr.RegistryCorrupt, match="newline"):
        hr.verify(**paths)
    with pytest.raises(hr.HoldoutRefused):
        start(paths)  # everything refuses until the owner repairs the tail in git
    with pytest.raises(hr.HoldoutRefused):
        expose(paths)


def test_truncated_inside_the_last_line_and_crlf_conversion_are_detected(paths):
    authorise(paths)
    start(paths)
    expose(paths)
    raw = paths["registry_path"].read_bytes()
    paths["registry_path"].write_bytes(raw[:-20])
    with pytest.raises(hr.RegistryCorrupt):
        hr.verify(**paths)
    paths["registry_path"].write_bytes(raw.replace(b"\n", b"\r\n"))
    with pytest.raises(hr.RegistryCorrupt):
        hr.verify(**paths)


def test_registry_is_protected_from_line_ending_conversion_and_is_empty_today():
    root = Path(hr.__file__).resolve().parents[4]
    attrs = (root / ".gitattributes").read_text(encoding="utf-8")
    assert "HOLDOUT-REGISTRY.jsonl -text" in attrs
    assert hr.REGISTRY_PATH.stat().st_size == 0


def test_short_writes_are_completed(paths, monkeypatch):
    authorise(paths)
    real_write = os.write

    def dribble(fd, data):
        return real_write(fd, bytes(data)[:7])

    monkeypatch.setattr(os, "write", dribble)
    start(paths)
    monkeypatch.undo()
    assert hr.event_states(**paths) == {"ev5": "STARTED"}


# ------------------------------------------------------------------------------------------ guard / clones
def test_missing_or_stale_guard_does_not_reopen_a_consumed_horizon(paths, tmp_path):
    authorise(paths)
    start(paths)
    complete(paths)
    guard = hr._guard_path(paths["lock_path"])
    stale = json.loads(guard.read_text())
    guard.unlink()  # a second clone: no guard at all
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        start(paths, marker="m9")
    stale["line_sha256"] = stale["line_sha256"][:1]  # stale guard: knows only the AUTHORISED line
    stale["n_entries"] = 1
    guard.write_text(json.dumps(stale))
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        start(paths, marker="m9")
    # a second clone with a copy of the committed registry and its own lock/guard paths
    clone = {"registry_path": paths["registry_path"], "lock_path": tmp_path / "clone2" / "x.lock"}
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        hr.require_authorised_and_mark_started(run_of(), locations=locs(paths, "m9"), **clone)


def test_guard_ahead_of_an_older_registry_copy_is_refused(paths, tmp_path):
    authorise(paths)
    old_copy = paths["registry_path"].read_bytes()
    start(paths)
    paths["registry_path"].write_bytes(old_copy)  # older checkout of the registry
    with pytest.raises(hr.RegistryCorrupt, match="truncated"):
        hr.verify(**paths)


# ------------------------------------------------------------------------------------------ cross-process
RACE = """
import sys, os, time
from pathlib import Path
from swing_trade_ml.ml import holdout_registry as hr
reg, lock, op, arg, gofile = sys.argv[1:6]
b = {b!r}
while not Path(gofile).exists():
    time.sleep(0.001)
try:
    if op == "start":
        hr.require_authorised_and_mark_started(b, registry_path=reg, lock_path=lock,
            locations={{"marker_file": arg, "record_dirs": [str(Path(arg).parent.parent / "SX5")]}})
    elif op == "recover":
        hr.append_recovery_authorisation("ev5", authorisation_text=arg, signer="o", signed_date="2026-11-08",
            reason="r", no_predictions_or_metrics_observed=True, registry_path=reg, lock_path=lock)
    elif op == "expose":
        hr.mark_results_exposed("ev5", registry_path=reg, lock_path=lock)
    print("OK")
except hr.HoldoutRefused as e:
    print("REFUSED")
"""


def race(paths, tmp_path, jobs):
    src = Path(hr.__file__).resolve().parents[2]
    env = {"PYTHONPATH": str(src), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    go = tmp_path / "go"
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                RACE.format(b=run_of()),
                str(paths["registry_path"]),
                str(paths["lock_path"]),
                op,
                arg,
                str(go),
            ],
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
        for op, arg in jobs
    ]
    go.write_text("go")
    return [p.communicate(timeout=120)[0].strip() for p in procs]


def test_race_two_recoveries_exactly_one_wins(paths, tmp_path):
    authorise(paths)
    start(paths)
    outs = race(paths, tmp_path, [("recover", "text A"), ("recover", "text B")])
    assert sorted(outs) == ["OK", "REFUSED"]
    assert types(paths).count("RECOVERY_AUTHORISATION") == 1
    hr.verify(**paths)


def test_race_recovery_against_exposure_never_yields_both(paths, tmp_path):
    for i in range(2):
        p = {
            "registry_path": Path(paths["registry_path"]).with_name(f"R{i}.jsonl"),
            "lock_path": paths["lock_path"].with_name(f"l{i}.lock"),
        }
        (tmp_path / f"d{i}").mkdir()
        authorise(p)
        start(p)
        outs = race(p, tmp_path / f"d{i}", [("recover", f"text {i}"), ("expose", "-")])
        t = types(p)
        assert sorted(outs) == ["OK", "REFUSED"] or outs == ["OK", "OK"] and False
        assert ("RECOVERY_AUTHORISATION" in t) != ("RESULTS_EXPOSED" in t)  # never both, never neither
        hr.verify(**p)


def test_race_start_against_recovery_is_serialised(paths, tmp_path):
    authorise(paths)
    start(paths)
    marker = str(Path(locs(paths, "m2")["marker_file"]))
    outs = race(paths, tmp_path, [("recover", "text A"), ("start", marker)])
    t = types(paths)
    assert outs[0] == "OK"
    assert t[:2] == ["AUTHORISED", "STARTED"] and "RECOVERY_AUTHORISATION" in t
    if outs[1] == "OK":
        assert t[-2:] == ["RECOVERY_AUTHORISATION", "STARTED"]  # start only ever ran after the recovery
    else:
        assert t[-1] == "RECOVERY_AUTHORISATION"
    hr.verify(**paths)


KILLER = """
import os, sys
from swing_trade_ml.ml import holdout_registry as hr
lk = hr._FileLock(sys.argv[1]); lk.__enter__(); print("LOCKED", flush=True); os._exit(3)
"""


def test_lock_is_released_when_the_holder_dies_and_a_stale_lock_file_is_harmless(paths):
    src = Path(hr.__file__).resolve().parents[2]
    env = {"PYTHONPATH": str(src), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    p = subprocess.run(
        [sys.executable, "-c", KILLER, str(paths["lock_path"])],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert "LOCKED" in p.stdout and p.returncode == 3
    assert paths["lock_path"].exists()  # the stale file is still there
    authorise(paths)  # takes the lock at once: the OS freed it when the holder died
    assert start(paths) == "ev5"
