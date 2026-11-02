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
    return {s: make_bars(2 * math.pi * i / 177) for i, s in enumerate([*USED, *EXTRA])}


@pytest.fixture()
def repo(tmp_path):
    split = tmp_path / run.SPLIT_DIR
    split.mkdir(parents=True)
    js = split / "stock_split_ev15.json"
    js.write_text(json.dumps({"used_49": USED, "extra_training_set": EXTRA}), encoding="utf-8")
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
            for s in USED:
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
        model_scores_fn=foresight(bars),
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


def test_the_held_back_stocks_are_never_loaded_or_named():
    import inspect

    src = inspect.getsource(run)
    assert "reject_set" not in src
