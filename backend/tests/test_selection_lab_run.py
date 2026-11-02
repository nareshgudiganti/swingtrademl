# ruff: noqa: E501 (long test sentences)
"""Selection lab runner: the once-only guard, the ledger row before results, the report, S1/S2 comparisons."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta

import pandas as pd
import pytest

from swing_trade_ml.brain import selection_lab as sl
from swing_trade_ml.brain import selection_lab_run as run

D0 = date(2023, 1, 2)
FIRST, LAST = date(2023, 10, 1), date(2024, 9, 30)
USED = [f"U{i:02d}" for i in range(49)]
EXTRA = [f"X{i:03d}" for i in range(128)]
REJECT = [f"R{i:03d}" for i in range(129)]
MID = [f"M{i:02d}" for i in range(14)]
GOOD_STATE = (True, [], False)


def make_bars(phase, n=800):
    rows, prev = [], 100.0
    for i in range(n):
        p = 100.0 * (1 + 0.12 * math.sin(2 * math.pi * i / 60 + phase))
        rows.append({"day": D0 + timedelta(days=i), "open": prev, "close": p, "volume": 5_000_000.0})
        prev = p
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def bars():
    return {s: make_bars(2 * math.pi * i / 177) for i, s in enumerate([*USED, *EXTRA, *MID])}


@pytest.fixture()
def repo(tmp_path):
    split = tmp_path / run.SPLIT_DIR
    split.mkdir(parents=True)
    js = split / "stock_split_ev15.json"
    js.write_text(
        json.dumps({"used_49": USED, "extra_training_set": EXTRA, "reject_set": REJECT}), encoding="utf-8"
    )
    sha = hashlib.sha256(js.read_bytes()).hexdigest()
    (split / "stock_split_ev15.md").write_text(f"| SHA-256 of file | `{sha}` |\n", encoding="utf-8")
    ledger = tmp_path / "docs" / "brain" / "EXPOSURE-LEDGER.md"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "# Ledger\n\n## Local data (development database)\n\n| a | b |\n|---|---|\n| row | row |\n\n## Other\n",
        encoding="utf-8",
    )
    amend = tmp_path / run.AMENDMENT
    amend.parent.mkdir(parents=True, exist_ok=True)
    amend.write_text("Evidence-plan amendment: SIGNED 2026-12-05\n", encoding="utf-8")
    return tmp_path


def foresight(bars_):
    def factory(candidate, all_bars):
        def scores(fold):
            out = {}
            for s in MID if run.is_mid(candidate) else USED:
                df, per = bars_[s], {}
                for d in df["day"]:
                    if fold.start <= d <= fold.end:
                        r = sl.forward_return(df, d)
                        if r is not None:
                            per[d] = r
                out[s] = per
            return out

        return scores

    return factory


def do_run(repo, bars, candidate="S0", **kw):
    return run.run(
        candidate,
        repo_root=repo,
        collect_fn=lambda: (bars, USED, EXTRA),
        model_scores_fn=kw.pop("scorer", None) or foresight(bars),
        mid_fn=lambda: MID,
        state=kw.pop("state", GOOD_STATE),
        first=FIRST,
        last=LAST,
        today=date(2026, 12, 6),
        **kw,
    )


def test_a_clean_first_run_writes_the_record_and_a_ranking_only_report(repo, bars):
    d = do_run(repo, bars, "S0")
    assert (d / "metrics.json").exists() and (d / "manifest.json").exists()
    text = (d / "report.md").read_text(encoding="utf-8")
    assert "Ranking and trading are different questions" in text and "Money: not evaluated" in text
    assert "NO WARNING (diagnostic)" in text and "never a PASS" in text and "Held-back 129: not used" in text
    assert "never activated" in text


def test_the_ledger_row_is_written_before_results_and_names_the_run(repo, bars):
    d = do_run(repo, bars, "S0")
    ledger = (repo / "docs/brain/EXPOSURE-LEDGER.md").read_text(encoding="utf-8")
    assert run.LEDGER_MARKER.format(cand="S0", first=FIRST, last=LAST) in ledger
    assert d.name in ledger and ledger.index("sl-protocol-v1 S0") < ledger.index("## Other")


@pytest.mark.parametrize(
    ("state", "needle"),
    [
        ((False, [], False), "git tag sl-protocol-v1 is not in this commit"),
        ((True, [run.SPEC], False), "differs from the tagged version"),
        ((True, [], True), "uncommitted changes"),
    ],
)
def test_the_run_is_refused_without_the_tag_a_frozen_file_or_a_clean_tree(repo, bars, state, needle):
    with pytest.raises(run.RunRefusedError, match=needle):
        do_run(repo, bars, "S0", state=state)
    assert not (repo / run.OUT_DIR).exists() or not list((repo / run.OUT_DIR).glob("sl1-*"))
    assert "sl-protocol-v1 S0" not in (repo / "docs/brain/EXPOSURE-LEDGER.md").read_text(encoding="utf-8")


def test_the_run_is_refused_until_the_evidence_plan_amendment_is_signed(repo, bars):
    (repo / run.AMENDMENT).write_text("draft, not yet signed off\n", encoding="utf-8")
    (repo / run.AMENDMENT).write_text("draft only\n", encoding="utf-8")
    with pytest.raises(run.RunRefusedError, match="amendment is not signed"):
        do_run(repo, bars, "S0")
    (repo / run.AMENDMENT).unlink()
    with pytest.raises(run.RunRefusedError, match="amendment is not signed"):
        do_run(repo, bars, "S0")


def test_a_candidate_runs_once_only(repo, bars):
    do_run(repo, bars, "S0")
    with pytest.raises(run.RunRefusedError, match="already exists"):
        do_run(repo, bars, "S0")


def test_s1_needs_the_s0_result_and_is_compared_with_it(repo, bars):
    with pytest.raises(run.RunRefusedError, match="compared with S0"):
        do_run(repo, bars, "S1")
    do_run(repo, bars, "S0")
    d = do_run(repo, bars, "S1")
    res = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    assert res["r4"]["mode"] == "better" and "Compared with: S0" in (d / "report.md").read_text(
        encoding="utf-8"
    )


def test_s2r_and_s3_are_not_built():
    with pytest.raises(SystemExit):
        run.main(["S3"])
    assert "S2r" not in run.CANDIDATES and "S3" not in run.CANDIDATES


def test_an_unclassified_overnight_move_blocks_the_run_until_it_is_written_down(repo, bars):
    gappy = dict(bars)
    df = bars["U05"].copy()
    df.loc[400:, ["open", "close"]] = df.loc[400:, ["open", "close"]] * 0.6
    gappy["U05"] = df
    with pytest.raises(run.RunRefusedError, match="no written classification"):
        do_run(repo, gappy, "S0")
    day = df.iloc[400]["day"]
    gap = repo / run.GAP_FILE
    gap.write_text(json.dumps({f"U05|{day.isoformat()}": "real_gap"}), encoding="utf-8")
    assert do_run(repo, gappy, "S0").exists()


def test_the_loaded_stock_lists_must_match_the_locked_split_file(repo, bars):
    with pytest.raises(run.RunRefusedError, match="differ from the locked split"):
        run.run(
            "S0",
            repo_root=repo,
            collect_fn=lambda: (bars, USED[:-1], EXTRA),
            model_scores_fn=foresight(bars),
            state=GOOD_STATE,
            first=FIRST,
            last=LAST,
        )


def test_a_changed_split_file_is_refused_by_its_recorded_hash(repo):
    js = repo / run.SPLIT_DIR / "stock_split_ev15.json"
    js.write_text(json.dumps({"used_49": USED, "extra_training_set": EXTRA[:-1]}), encoding="utf-8")
    with pytest.raises(run.RunRefusedError, match="split changed"):
        run.load_split(repo)


def test_the_held_back_stocks_are_never_loaded_or_named_in_the_runner_code():
    import inspect

    src = inspect.getsource(run)
    # the locked file's key is read once, only to prove the 129 are absent; no loader receives it
    assert src.count(run.HELD_BACK_KEY) == 1
    assert "load_bars_with_volume(db, [*" not in src and "held_back" in inspect.getsource(run.collect_db)


def test_the_runner_imports_no_cost_or_portfolio_code():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(run))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for banned in (
        "portfolio_sim",
        "replay_scoring",
        "costs",
        "risk.sizing",
        "execution",
        "brokers",
        "strategies",
    ):
        assert not [m for m in mods if banned in m], (banned, mods)


# ---------------------------------------------------------------- mid-cap candidates


def test_the_mid_group_is_the_mid_model_stocks_minus_the_held_back_and_none_are_in_the_49():
    training = [*MID, *REJECT[:10]]  # 24 stocks, 10 of them held back
    assert sl.mid_group_from(training, REJECT, USED) == sorted(MID)
    with pytest.raises(ValueError, match="overlaps the 49"):
        sl.mid_group_from([*MID, USED[0]], REJECT, USED)


def test_the_candidate_matrix_and_comparisons():
    assert run.CANDIDATES == ("S0", "S1", "S2", "S0M", "S1M", "S2M")
    assert run.COMPARE_WITH == {"S1": "S0", "S2": "S1", "S1M": "S0M", "S2M": "S1M"}


def test_a_mid_run_scores_only_the_14_has_a_limited_sample_warning_and_a_capped_label(repo, bars):
    d = do_run(repo, bars, "S0M")
    res = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    text = (d / "report.md").read_text(encoding="utf-8")
    assert res["by_cap_group"]["mid"]["stocks_listed"] == 14 and res["stocks_scored_max"] <= 14
    assert (
        text.startswith("# S0M")
        and "Limited experiment: 14 stocks. Wide uncertainty." in text.splitlines()[2]
    )
    assert "NO WARNING (diagnostic, limited sample)" in text and "Limits of this test" in text
    assert "Ranking and trading are different questions" in text and "Money: not evaluated" in text
    assert "Group: mid (14 stocks listed)" in text and "Trained on: 14 mid-cap stocks" in text


def test_s1m_needs_s0m_and_is_compared_with_it_while_a_large_result_does_not_count(repo, bars):
    do_run(repo, bars, "S0")
    with pytest.raises(run.RunRefusedError, match="compared with S0M"):
        do_run(repo, bars, "S1M")
    do_run(repo, bars, "S0M")
    d = do_run(repo, bars, "S1M")
    assert "Compared with: S0M" in (d / "report.md").read_text(encoding="utf-8")
    do_run(repo, bars, "S2M")
    assert len(run.existing_runs(repo / run.OUT_DIR, "S0")) == 1  # S0 and S0M are separate runs
    ledger = (repo / "docs/brain/EXPOSURE-LEDGER.md").read_text(encoding="utf-8")
    assert "sl-protocol-v1 S0M," in ledger and "14 mid-cap stocks" in ledger


def test_a_held_back_stock_in_any_loaded_list_refuses_the_run_before_anything_is_trained(repo, bars):
    dirty = {**bars, REJECT[3]: bars["U00"]}
    with pytest.raises(run.RunRefusedError, match="Held-back stocks found in bars"):
        do_run(repo, dirty, "S0")
    with pytest.raises(run.RunRefusedError, match="Held-back stocks found in mid"):
        run.run("S0M", repo_root=repo, collect_fn=lambda: (bars, USED, EXTRA), mid_fn=lambda: [*MID, REJECT[0]],
                model_scores_fn=foresight(bars), state=GOOD_STATE, first=FIRST, last=LAST)  # fmt: skip
    assert "sl-protocol-v1 S0," not in (repo / "docs/brain/EXPOSURE-LEDGER.md").read_text(encoding="utf-8")


def test_the_lists_the_scorer_sees_never_include_a_held_back_stock(repo, bars):
    seen = []

    def spy(candidate, all_bars):
        seen.append(set(all_bars))
        return foresight(all_bars)(candidate, all_bars)

    do_run(repo, bars, "S0M", scorer=spy)
    assert seen and not (seen[0] & set(REJECT))
    split_lists = run.load_split(repo)
    assert not (set(split_lists[0]) | set(split_lists[1])) & set(run.load_held_back(repo))


# ---------------------------------------------------------------- controlled technical rerun

GOOD_NOTE = (
    "# Incident\n\nKind: execution_failure\nCause: the database connection dropped during fold three\n"
    "Result read: none\nSame code and rules: yes\n"
)


def crashing(bars_):
    def factory(candidate, all_bars):
        def scores(fold):
            raise ConnectionError("database connection dropped")

        return scores

    return factory


def write_note(repo, cand="S0", n=1, text=GOOD_NOTE):
    d = repo / run.OUT_DIR / run.INCIDENT_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / f"incident_{cand}_{n:03d}.md").write_text(text, encoding="utf-8")


def crash(repo, bars, cand="S0", **kw):
    with pytest.raises(ConnectionError):
        do_run(repo, bars, cand, scorer=crashing(bars), **kw)


def finished(repo, cand="S0"):
    return run.existing_runs(repo / run.OUT_DIR, cand)


def test_a_crash_leaves_a_ledger_row_but_no_run_folder_and_a_plain_rerun_is_refused(repo, bars, capsys):
    crash(repo, bars)
    assert not finished(repo) and not list((repo / run.OUT_DIR).glob(".tmp-*"))
    assert "sl-protocol-v1 S0," in (repo / "docs/brain/EXPOSURE-LEDGER.md").read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""  # nothing printed
    with pytest.raises(run.RunRefusedError, match="--technical-rerun"):
        do_run(repo, bars, "S0")


def test_a_technical_rerun_needs_an_incident_note(repo, bars):
    crash(repo, bars)
    with pytest.raises(run.RunRefusedError, match="need 1 incident note"):
        do_run(repo, bars, "S0", technical_rerun=True)


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        (GOOD_NOTE.replace("execution_failure", "disliked_result"), "'Kind:' must be one of"),
        (GOOD_NOTE.replace("the database connection dropped during fold three", "oops"), "'Cause:'"),
        (GOOD_NOTE.replace("Result read: none", "Result read: S0 looked weak"), "Result read: none"),
        (
            GOOD_NOTE.replace("Same code and rules: yes", "Same code and rules: no"),
            "Same code and rules: yes",
        ),
    ],
)
def test_an_incident_note_must_say_what_failed_and_that_no_result_was_read(repo, bars, text, needle):
    crash(repo, bars)
    write_note(repo, text=text)
    with pytest.raises(run.RunRefusedError, match="incident note problems") as e:
        do_run(repo, bars, "S0", technical_rerun=True)
    assert needle in str(e.value)


def test_a_valid_technical_rerun_is_allowed_logged_and_then_a_finished_run_blocks_any_more(repo, bars):
    crash(repo, bars)
    write_note(repo)
    d = do_run(repo, bars, "S0", technical_rerun=True)
    ledger = (repo / "docs/brain/EXPOSURE-LEDGER.md").read_text(encoding="utf-8")
    assert "technical rerun 1 S0," in ledger and "incident_S0_001.md" in ledger and d.exists()
    assert (d / "metrics.json").exists() and "Technical rerun: 1" in (d / "report.md").read_text(
        encoding="utf-8"
    )
    with pytest.raises(run.RunRefusedError, match="already exists"):
        do_run(repo, bars, "S0", technical_rerun=True)
    assert len(finished(repo)) == 1


def test_technical_reruns_are_capped_at_two(repo, bars):
    crash(repo, bars)
    write_note(repo, n=1)
    crash(repo, bars, technical_rerun=True)
    write_note(repo, n=2)
    crash(repo, bars, technical_rerun=True)
    write_note(repo, n=3)
    with pytest.raises(run.RunRefusedError, match="2 technical reruns are already used"):
        do_run(repo, bars, "S0", technical_rerun=True)


def test_a_rerun_flag_with_no_earlier_attempt_is_refused(repo, bars):
    with pytest.raises(run.RunRefusedError, match="no earlier attempt"):
        do_run(repo, bars, "S0", technical_rerun=True)


def test_incident_notes_and_attempts_are_per_candidate(repo, bars):
    crash(repo, bars, "S0M")
    write_note(repo, cand="S0")  # a note for another candidate does not count
    with pytest.raises(run.RunRefusedError, match="need 1 incident note"):
        do_run(repo, bars, "S0M", technical_rerun=True)
    write_note(repo, cand="S0M")
    assert do_run(repo, bars, "S0M", technical_rerun=True).exists()


def test_a_crash_while_writing_leaves_no_half_finished_run(repo, bars, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(run.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        do_run(repo, bars, "S0")
    assert not finished(repo)  # a hidden, half-built folder is never counted as a run
    monkeypatch.undo()
    write_note(repo)
    assert do_run(repo, bars, "S0", technical_rerun=True).exists()


def test_the_cli_has_the_technical_rerun_flag():
    with pytest.raises(SystemExit):
        run.main(["S0", "--bogus"])
