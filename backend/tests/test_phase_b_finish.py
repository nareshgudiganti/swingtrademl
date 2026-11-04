"""Phase B completion record: pure tests (tmp_path fixtures, fake git, injected clock). No DB, no network."""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import pytest

import swing_trade_ml.brain.service  # noqa: F401  (import-order trap)
from swing_trade_ml.brain import phase_b as pb
from swing_trade_ml.brain import phase_b_finish as pf

IST = pb.IST
GOOD_NOW = datetime(2026, 12, 2, 10, 0, tzinfo=IST)
SPLIT_BYTES = b'{"split": "fixture"}\n'
SPLIT_SHA = pf.sha256_bytes(SPLIT_BYTES)
IDS = ("B1", "B2", "B3")


def make_result(
    cid: str,
    *,
    survives: bool,
    edge_low=0.004,
    edge=0.006,
    avg=0.01,
    mom_low=0.001,
    split_sha=SPLIT_SHA,
    ledger_row="",
) -> dict:
    beats = pb.NO_WARNING if survives else pb.FAIL
    return {
        "manifest": {
            "candidate": {"id": cid, "name": pb.CANDIDATES[cid].name},
            "protocol": f"{pb.PROTOCOL_ID} v{pb.PROTOCOL_VERSION}",
            "defs_version": f"{pb.DEFS_VERSION} (adds to evidence-defs-v1)",
            "code_commit": f"abc{cid[-1]}000",
            "stocks": {"split_sha256": split_sha},
            "exposure_ledger_row": ledger_row,
        },
        "candidate": {"id": cid, "name": pb.CANDIDATES[cid].name},
        "window": [pb.DEV_START.isoformat(), pb.DEV_END.isoformat()],
        "trading_days": 380,
        "folds": 14,
        "trade_level": {
            "candidate": {
                "ideas": 500,
                "days": 200,
                "avg_net": avg,
                "edge_low": edge_low,
                "edge_per_day": edge,
            },
            "every_stock": {"avg_net": 0.002},
            "momentum": {"avg_net": 0.003},
        },
        "edge_vs_momentum": {"edge_low": mom_low},
        "reject_check": {"label": pb.NO_WARNING},
        "checks": [
            {
                "id": "phase_b_beats_every_stock_and_momentum",
                "label": beats,
                "value": {"candidate": avg, "every_stock": 0.002, "momentum": 0.003},
            },
            {"id": "reject_set", "label": pb.NO_WARNING, "value": {}},
            {"id": "statistical_confidence", "label": pb.NO_WARNING, "value": {"low": edge_low}},
            {"id": "mid_small_cap_index", "label": pb.NOT_TESTABLE, "value": None},
        ],
        "survives": survives,
    }


class FakeGit:
    """Dict-driven git. `table` maps an args tuple to (rc, stdout); anything unknown fails (rc 128)."""

    def __init__(self):
        self.table: dict[tuple, tuple[int, str]] = {}
        self.calls: list[tuple] = []

    def __call__(self, args):
        a = tuple(args)
        self.calls.append(a)
        return self.table.get(a, (128, ""))


class Repo:
    def __init__(self, root: Path, survives=(False, False, False), **overrides):
        self.root = root
        self.git = FakeGit()
        self.survives = dict(zip(IDS, survives, strict=True))
        self.overrides = overrides
        self.build()

    def p(self, rel):
        return self.root / rel

    def build(self):
        root = self.root
        (root / pf.SPLIT_REL).mkdir(parents=True)
        (root / pf.SPLIT_REL / pb.SPLIT_FILE).write_bytes(SPLIT_BYTES)
        (root / pf.SPLIT_REL / pb.SPLIT_NOTE).write_text(
            f"| SHA-256 of file | `{SPLIT_SHA}` |\n", encoding="utf-8"
        )
        (root / pf.EVIDENCE_REL).mkdir(parents=True)
        lines = [
            "# ledger",
            "",
            "## Local data (development database)",
            "",
            "| a | b | c | d | e |",
            "|---|---|---|---|---|",
            "| old row | x | y | z | w |",
        ]
        rows = {}
        for cid in IDS:
            rows[cid] = pb.ledger_row(
                cid,
                run_day=datetime(2026, 11, 10).date(),
                report_name=f"phase_b_{cid}.md",
                window=(pb.DEV_START, pb.DEV_END),
            )
            lines.append(rows[cid])
        lines += ["", "## Production data", "", "| p | q |"]
        (root / pf.LEDGER_REL).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        g = self.git.table
        for cid in IDS:
            kw = dict(self.overrides.get(cid, {}))
            res = make_result(cid, survives=self.survives[cid], ledger_row=rows[cid], **kw)
            _, js = pb.output_paths(cid, root / pf.EVIDENCE_REL)
            md, _ = pb.output_paths(cid, root / pf.EVIDENCE_REL)
            js.write_text(json.dumps(res, indent=1), encoding="utf-8", newline="\n")
            md.write_text(f"report {cid}\n", encoding="utf-8", newline="\n")
        # tags
        for i, t in enumerate(pb.REQUIRED_TAGS):
            g[("cat-file", "-t", t)] = (0, "tag\n")
            g[("rev-parse", t)] = (0, f"obj{i}\n")
            g[("rev-parse", f"{t}^{{commit}}")] = (0, f"com{i}\n")
            g[("merge-base", "--is-ancestor", t, "HEAD")] = (0, "")
        g[("tag", "-l", pf.RESULT_TAG)] = (0, "")
        g[("status", "--porcelain", "--untracked-files=all")] = (0, "")
        g[("rev-parse", "HEAD")] = (0, "headsha\n")
        g[("rev-parse", f"HEAD:{pf.PHASE_B_PY_REL}")] = (0, "blob1\n")
        g[("rev-parse", f"{pb.SETTINGS_TAG}^{{commit}}:{pf.PHASE_B_PY_REL}")] = (0, "blob1\n")
        # manifests, written by the tool itself so hashes are real
        for n, cid in enumerate(IDS):
            m, why = pf.build_candidate_manifest(root, cid, self.git, GOOD_NOW)
            assert not why, why
            mp = pf.manifest_path(root, cid)
            mp.write_text(pf.dumps(m), encoding="utf-8", newline="\n")
            c = f"evid{n}"
            md, js = pb.output_paths(cid, root / pf.EVIDENCE_REL)
            rels = [f"{pf.EVIDENCE_REL}/{x.name}" for x in (md, js, mp)]
            g[("log", "--format=%H", "--diff-filter=A", "--", rels[2])] = (0, c + "\n")
            g[("show", "--name-only", "--format=", c)] = (0, "\n".join([*rels, pf.LEDGER_REL]) + "\n")
            for rel in rels[:2]:
                g[("log", "--format=%H", "--", rel)] = (0, c + "\n")
            g[("merge-base", "--is-ancestor", c, "HEAD")] = (0, "")
            g[("rev-parse", f"abc{cid[-1]}000:{pf.PHASE_B_PY_REL}")] = (0, "blob1\n")
            if n:
                g[("merge-base", "--is-ancestor", f"evid{n - 1}", c)] = (0, "")
        self.commit_g = g

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def run(self, argv=(), now=GOOD_NOW):
        buf = io.StringIO()
        rc = pf.main(list(argv), root=self.root, git=self.git, now_fn=lambda: now, out=buf)
        return rc, buf.getvalue()


@pytest.fixture
def no_survivor(tmp_path):
    return Repo(tmp_path)


def reasons(repo, now=GOOD_NOW):
    return pf.prepare(repo.root, repo.git, now).reasons


def edit_result(repo, cid, fn):
    _, js = pb.output_paths(cid, repo.root / pf.EVIDENCE_REL)
    d = json.loads(js.read_text(encoding="utf-8"))
    fn(d)
    js.write_text(json.dumps(d, indent=1), encoding="utf-8", newline="\n")
    # refresh the manifest so only the intended defect remains
    mp = pf.manifest_path(repo.root, cid)
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["files"][js.name] = pf.sha256_file(js)
    mp.write_text(pf.dumps(m), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- valid outcomes


def test_valid_no_survivor(no_survivor):
    plan = pf.prepare(no_survivor.root, no_survivor.git, GOOD_NOW)
    assert plan.ok, plan.reasons
    r = plan.result
    assert r["outcome"] == "NO_SURVIVOR" and r["survivor"] is None
    assert r["wf_protocol_v2_expected"] is False
    assert set(r["candidates"]) == set(IDS) and r["counts"]["survivors"] == 0
    assert r["split"]["sha256"] == SPLIT_SHA
    assert r["written_at_ist"] <= "2026-12-04T23:59:59+05:30"
    assert all(len(v["result_files"]) == 2 for v in r["candidates"].values())


def test_valid_survivor_selected(tmp_path):
    repo = Repo(tmp_path, survives=(False, True, False))
    plan = pf.prepare(repo.root, repo.git, GOOD_NOW)
    assert plan.ok, plan.reasons
    assert plan.result["outcome"] == "SURVIVOR_SELECTED" and plan.result["survivor"] == "B2"
    assert plan.result["wf_protocol_v2_expected"] is True
    assert plan.result["selection"]["decided_by"] == "only_survivor"


def test_deterministic_bytes(no_survivor):
    a = pf.prepare(no_survivor.root, no_survivor.git, GOOD_NOW).result_text
    b = pf.prepare(no_survivor.root, no_survivor.git, GOOD_NOW).result_text
    assert a == b and a.endswith("\n") and "\r" not in a


# ---------------------------------------------------------------- tie rule


def test_multiple_survivors_best_edge_low_wins(tmp_path):
    repo = Repo(
        tmp_path,
        survives=(True, True, True),
        B1={"edge_low": 0.002},
        B2={"edge_low": 0.009},
        B3={"edge_low": 0.005},
    )
    plan = pf.prepare(repo.root, repo.git, GOOD_NOW)
    assert plan.result["survivor"] == "B2"
    assert plan.result["selection"]["decided_by"] == "edge_low"
    assert [x["candidate"] for x in plan.result["selection"]["ranking"]] == ["B2", "B3", "B1"]


def test_tie_on_first_criterion_goes_to_next(tmp_path):
    repo = Repo(
        tmp_path,
        survives=(True, True, False),
        B1={"edge_low": 0.004, "edge": 0.006},
        B2={"edge_low": 0.004, "edge": 0.008},
    )
    plan = pf.prepare(repo.root, repo.git, GOOD_NOW)
    assert plan.result["survivor"] == "B2"
    assert plan.result["selection"]["decided_by"] == "edge_per_day"


def test_rounding_makes_float_noise_a_tie(tmp_path):
    repo = Repo(
        tmp_path,
        survives=(True, True, False),
        B1={"edge_low": 0.0040000001},
        B2={"edge_low": 0.004},
    )
    plan = pf.prepare(repo.root, repo.git, GOOD_NOW)
    assert plan.result["survivor"] == "B1"  # identical after rounding, falls to the id
    assert plan.result["selection"]["decided_by"] == "candidate_id"


def test_remaining_tie_lower_candidate_id(tmp_path):
    repo = Repo(tmp_path, survives=(False, True, True))
    plan = pf.prepare(repo.root, repo.git, GOOD_NOW)
    assert plan.result["survivor"] == "B2"
    assert plan.result["selection"]["decided_by"] == "candidate_id"


def test_missing_edge_low_ranks_last(tmp_path):
    repo = Repo(tmp_path, survives=(True, True, False), B1={"edge_low": None}, B2={"edge_low": 0.001})
    plan = pf.prepare(repo.root, repo.git, GOOD_NOW)
    assert plan.ok, plan.reasons
    assert plan.result["survivor"] == "B2"


# ---------------------------------------------------------------- incomplete


def test_missing_candidate_file(no_survivor):
    _, js = pb.output_paths("B3", no_survivor.root / pf.EVIDENCE_REL)
    js.unlink()
    assert any("incomplete" in r.lower() for r in reasons(no_survivor))


def test_only_md_exists(no_survivor):
    _md, js = pb.output_paths("B2", no_survivor.root / pf.EVIDENCE_REL)
    js.unlink()
    assert any("B2" in r and "missing" in r for r in reasons(no_survivor))


def test_missing_ledger_row(no_survivor):
    lp = no_survivor.root / pf.LEDGER_REL
    text = "\n".join(
        ln for ln in lp.read_text(encoding="utf-8").splitlines() if "Phase B candidate B2" not in ln
    )
    lp.write_text(text + "\n", encoding="utf-8")
    assert any("B2" in r and "ledger" in r for r in reasons(no_survivor))


def test_missing_candidate_manifest(no_survivor):
    pf.manifest_path(no_survivor.root, "B1").unlink()
    assert any("manifest" in r and "missing" in r for r in reasons(no_survivor))


def test_truncated_result_missing_keys(no_survivor):
    edit_result(no_survivor, "B1", lambda d: d.pop("checks"))
    assert any("missing keys" in r for r in reasons(no_survivor))


# ---------------------------------------------------------------- invalid


def test_malformed_json(no_survivor):
    _, js = pb.output_paths("B1", no_survivor.root / pf.EVIDENCE_REL)
    js.write_text("{not json", encoding="utf-8")
    assert any("cannot be read as JSON" in r for r in reasons(no_survivor))


def test_wrong_window(no_survivor):
    edit_result(no_survivor, "B2", lambda d: d.update(window=["2025-01-01", "2026-08-15"]))
    assert any("wrong window" in r for r in reasons(no_survivor))


def test_split_hash_mismatch_in_result(no_survivor):
    edit_result(no_survivor, "B3", lambda d: d["manifest"]["stocks"].update(split_sha256="0" * 64))
    assert any("split hash" in r for r in reasons(no_survivor))


def test_split_file_edited_after_lock(no_survivor):
    (no_survivor.root / pf.SPLIT_REL / pb.SPLIT_FILE).write_bytes(b"changed\n")
    assert any("recorded hash" in r for r in reasons(no_survivor))


def test_unknown_label(no_survivor):
    edit_result(no_survivor, "B1", lambda d: d["checks"][0].update(label="PASS"))
    assert any("unknown label" in r for r in reasons(no_survivor))


def test_unclean_run_commit(no_survivor):
    edit_result(
        no_survivor, "B1", lambda d: d["manifest"].update(code_commit="abc1000 (with uncommitted changes)")
    )
    assert any("unclean" in r for r in reasons(no_survivor))


def test_tags_missing_or_lightweight(no_survivor):
    g = no_survivor.git.table
    g[("cat-file", "-t", "evidence-defs-v1")] = (0, "commit\n")
    del g[("cat-file", "-t", "phase-b-settings")]
    rs = reasons(no_survivor)
    assert any("not annotated" in r for r in rs) and any("does not exist" in r for r in rs)


def test_tag_not_ancestor(no_survivor):
    no_survivor.git.table[("merge-base", "--is-ancestor", "evidence-defs-v2", "HEAD")] = (1, "")
    assert any("not an ancestor" in r for r in reasons(no_survivor))


def test_phase_b_py_changed_after_settings_tag(no_survivor):
    no_survivor.git.table[("rev-parse", f"HEAD:{pf.PHASE_B_PY_REL}")] = (0, "other\n")
    assert any("phase_b.py" in r for r in reasons(no_survivor))


# ---------------------------------------------------------------- duplicate


def test_duplicate_record_file(no_survivor):
    (no_survivor.root / pf.EVIDENCE_REL / pf.RESULT_NAME).write_text("{}", encoding="utf-8")
    assert any("Duplicate" in r for r in reasons(no_survivor))


def test_duplicate_tag(no_survivor):
    no_survivor.git.table[("tag", "-l", pf.RESULT_TAG)] = (0, "phase-b-result\n")
    assert any("Duplicate" in r and "tag" in r for r in reasons(no_survivor))


def test_duplicate_ledger_row(no_survivor):
    lp = no_survivor.root / pf.LEDGER_REL
    text = lp.read_text(encoding="utf-8").replace("| old row |", f"| {pf.RESULT_MARKER}: NO_SURVIVOR |", 1)
    lp.write_text(text, encoding="utf-8")
    assert any("Duplicate" in r and "ledger" in r for r in reasons(no_survivor))


def test_duplicate_candidate_ledger_row(no_survivor):
    lp = no_survivor.root / pf.LEDGER_REL
    lines = lp.read_text(encoding="utf-8").splitlines()
    row = next(ln for ln in lines if "Phase B candidate B1" in ln)
    lp.write_text("\n".join([*lines, row]) + "\n", encoding="utf-8")
    assert any("B1" in r and "expected exactly 1" in r for r in reasons(no_survivor))


# ---------------------------------------------------------------- inconsistent


def test_json_says_survives_but_rule_fails(no_survivor):
    edit_result(no_survivor, "B1", lambda d: d.update(survives=True))
    assert any("INCONSISTENT" in r and "B1" in r for r in reasons(no_survivor))


def test_json_says_fails_but_rule_passes(tmp_path):
    repo = Repo(tmp_path, survives=(True, False, False))
    edit_result(repo, "B1", lambda d: d.update(survives=False))
    assert any("INCONSISTENT" in r for r in reasons(repo))


def test_candidate_id_mismatch(no_survivor):
    edit_result(no_survivor, "B2", lambda d: d["candidate"].update(id="B3"))
    assert any("names candidate" in r for r in reasons(no_survivor))


def test_manifest_candidate_id_mismatch(no_survivor):
    edit_result(no_survivor, "B2", lambda d: d["manifest"]["candidate"].update(id="B1"))
    assert any("manifest names candidate" in r for r in reasons(no_survivor))


def test_counts_differ_between_candidates(no_survivor):
    edit_result(no_survivor, "B3", lambda d: d.update(trading_days=379))
    assert any("INCONSISTENT" in r and "trading_days" in r for r in reasons(no_survivor))


def test_figures_differ_between_checks_and_trade_level(no_survivor):
    edit_result(no_survivor, "B1", lambda d: d["trade_level"]["candidate"].update(edge_low=0.5))
    assert any("edge_low" in r for r in reasons(no_survivor))


def test_result_changed_after_manifest(no_survivor):
    _, js = pb.output_paths("B1", no_survivor.root / pf.EVIDENCE_REL)
    d = json.loads(js.read_text(encoding="utf-8"))
    d["extra"] = "edited"
    js.write_text(json.dumps(d), encoding="utf-8")
    assert any("does not match the sha256" in r for r in reasons(no_survivor))


def test_outputs_not_committed_together(no_survivor):
    c = "evid1"
    no_survivor.git.table[("show", "--name-only", "--format=", c)] = (0, "unrelated.txt\n")
    assert any("not contain" in r for r in reasons(no_survivor))


def test_candidates_committed_together_refused(no_survivor):
    g = no_survivor.git.table
    for key in list(g):
        if key[:2] == ("log", "--format=%H") and "evid2" in g[key][1]:
            g[key] = (0, "evid1\n")
    assert any("committed together" in r or "not before" in r for r in reasons(no_survivor))


def test_evidence_commit_order_wrong(no_survivor):
    no_survivor.git.table[("merge-base", "--is-ancestor", "evid0", "evid1")] = (1, "")
    assert any("not before" in r for r in reasons(no_survivor))


def test_result_file_changed_in_later_commit(no_survivor):
    _md, js = pb.output_paths("B1", no_survivor.root / pf.EVIDENCE_REL)
    rel = f"{pf.EVIDENCE_REL}/{js.name}"
    no_survivor.git.table[("log", "--format=%H", "--", rel)] = (0, "later\nevid0\n")
    assert any("changed after its evidence commit" in r for r in reasons(no_survivor))


# ---------------------------------------------------------------- dirty tree and date


def test_dirty_tree(no_survivor):
    no_survivor.git.table[("status", "--porcelain", "--untracked-files=all")] = (0, " M file\n")
    assert any("not clean" in r for r in reasons(no_survivor))


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 8, 23, 59, tzinfo=IST),
        datetime(2026, 12, 5, 0, 0, tzinfo=IST),
        datetime(2026, 12, 4, 20, 0, tzinfo=pf.UTC),  # 01:30 on 5 Dec in India: too late
    ],
)
def test_wrong_date_refuses(no_survivor, now):
    rs = reasons(no_survivor, now)
    assert any("IST" in r for r in rs)
    rc, out = no_survivor.run(["--apply"], now=now)
    assert rc != 0 and "REFUSED" in out


def test_last_day_allowed_until_midnight_ist(no_survivor):
    assert pf.prepare(no_survivor.root, no_survivor.git, datetime(2026, 12, 4, 23, 59, tzinfo=IST)).ok
    early = reasons(no_survivor, datetime(2026, 11, 9, 0, 0, tzinfo=IST))
    assert not any("before" in r for r in early)  # the date window opens at 00:00 IST on 9 Nov
    assert early == [
        "A manifest is dated in the future."
    ]  # only because the fixture manifests are dated 2 Dec


def test_naive_clock_rejected(no_survivor):
    with pytest.raises(ValueError):
        pf.prepare(no_survivor.root, no_survivor.git, datetime(2026, 12, 2, 10, 0))


# ---------------------------------------------------------------- dry run and apply


def test_dry_run_writes_nothing(no_survivor):
    before = no_survivor.snapshot()
    rc, out = no_survivor.run([])
    assert rc == 0 and "DRY RUN" in out and "NO_SURVIVOR" in out
    assert no_survivor.snapshot() == before


def test_refusal_writes_nothing(no_survivor):
    no_survivor.git.table[("status", "--porcelain", "--untracked-files=all")] = (0, " M x\n")
    before = no_survivor.snapshot()
    rc, _ = no_survivor.run(["--apply"])
    assert rc != 0 and no_survivor.snapshot() == before


def test_apply_writes_only_record_and_one_ledger_row(no_survivor):
    before = no_survivor.snapshot()
    rc, out = no_survivor.run(["--apply"])
    assert rc == 0
    after = no_survivor.snapshot()
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {str(Path(pf.EVIDENCE_REL) / pf.RESULT_NAME), str(Path(pf.LEDGER_REL))}
    old = before[str(Path(pf.LEDGER_REL))].decode().splitlines()
    new = after[str(Path(pf.LEDGER_REL))].decode().splitlines()
    assert [x for x in new if x not in old] and len(new) == len(old) + 1
    assert [x for x in old if x not in new] == []  # append-only
    rec = (no_survivor.root / pf.EVIDENCE_REL / pf.RESULT_NAME).read_bytes()
    assert pf.sha256_bytes(rec) in "\n".join(new)
    assert pf.RESULT_TAG in out and "git tag -a" in out


def test_apply_never_commits_or_tags(no_survivor):
    no_survivor.run(["--apply"])
    verbs = {c[0] for c in no_survivor.git.calls}
    assert verbs <= {"cat-file", "rev-parse", "merge-base", "tag", "status", "log", "show"}
    assert all(c[:1] != ("tag",) or c[1:2] == ("-l",) for c in no_survivor.git.calls)


def test_never_wf_protocol_v2_on_no_survivor(no_survivor):
    rc, out = no_survivor.run(["--apply"])
    assert rc == 0 and pf.WF_TAG not in out
    r = json.loads((no_survivor.root / pf.EVIDENCE_REL / pf.RESULT_NAME).read_text(encoding="utf-8"))
    assert r["wf_protocol_v2_expected"] is False and r["survivor"] is None


def test_survivor_prints_wf_protocol_v2_only_after_result_tag(tmp_path):
    repo = Repo(tmp_path, survives=(True, False, False))
    rc, out = repo.run(["--apply"])
    assert rc == 0
    assert out.index("git tag -a phase-b-result") < out.index(pf.WF_TAG)


def test_apply_twice_is_a_duplicate(no_survivor):
    assert no_survivor.run(["--apply"])[0] == 0
    rc, out = no_survivor.run(["--apply"])
    assert rc != 0 and "Duplicate" in out


def test_commands_for_no_survivor_have_no_wf():
    cmds = pf.commands_for(
        {"outcome": "NO_SURVIVOR", "survivor": None, "written_at_ist": "x"}, "h" * 64, GOOD_NOW.date()
    )
    assert not any(pf.WF_TAG in c for c in cmds)


def test_never_invents_a_survivor(no_survivor):
    results = {
        c: json.loads(pb.output_paths(c, no_survivor.root / pf.EVIDENCE_REL)[1].read_text("utf-8"))
        for c in IDS
    }
    sel = pf.select_outcome(results)
    assert sel["outcome"] == "NO_SURVIVOR" and sel["survivor"] is None and sel["ranking"] == []


def test_inconclusive_part_does_not_survive():
    r = make_result("B1", survives=True)
    r["checks"][1]["label"] = pb.INCONCLUSIVE
    r["survives"] = False
    assert pf.select_outcome({"B1": r})["outcome"] == "NO_SURVIVOR"


# ---------------------------------------------------------------- per-candidate manifest


def test_manifest_command_dry_run_and_apply(tmp_path):
    repo = Repo(tmp_path)
    pf.manifest_path(repo.root, "B2").unlink()
    before = repo.snapshot()
    rc, out = repo.run(["--manifest", "B2"])
    assert rc == 0 and "DRY RUN" in out and repo.snapshot() == before
    rc, out = repo.run(["--manifest", "B2", "--apply"])
    assert rc == 0 and pf.manifest_path(repo.root, "B2").exists()
    rc, out = repo.run(["--manifest", "B2", "--apply"])
    assert rc != 0 and "duplicate" in out


def test_manifest_refuses_without_result_file(tmp_path):
    repo = Repo(tmp_path)
    pf.manifest_path(repo.root, "B3").unlink()
    pb.output_paths("B3", repo.root / pf.EVIDENCE_REL)[1].unlink()
    rc, _ = repo.run(["--manifest", "B3", "--apply"])
    assert rc != 0


def test_phase_b_py_not_modified_and_constants_not_duplicated():
    assert pf.WINDOW_START == pb.PHASE_B_START
    assert pf.RESULT_TAG not in pb.REQUIRED_TAGS and pf.WF_TAG not in pb.REQUIRED_TAGS
    src = Path(pf.__file__).read_text(encoding="utf-8")
    assert '"push"' not in src and '("commit"' not in src and '("tag", "-a"' not in src
    assert "wf-protocol-v2" not in pb.__doc__ if pb.__doc__ else True


def test_run_order_must_be_b1_b2_b3(no_survivor):
    lp = no_survivor.root / pf.LEDGER_REL
    lines = lp.read_text(encoding="utf-8").splitlines()
    i1 = next(i for i, ln in enumerate(lines) if pb.LEDGER_MARKER.format(cid="B1") in ln)
    i2 = next(i for i, ln in enumerate(lines) if pb.LEDGER_MARKER.format(cid="B2") in ln)
    lines[i1], lines[i2] = lines[i2], lines[i1]
    lp.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    assert any("order B1, B2, B3" in r for r in reasons(no_survivor))


def test_wf_tag_command_points_at_the_commit_not_a_nested_tag():
    cmds = pf.commands_for(
        {"outcome": "SURVIVOR_SELECTED", "survivor": "B2", "written_at_ist": "x"}, "h" * 64, GOOD_NOW.date()
    )
    assert any(f"git tag -a {pf.WF_TAG} {pf.RESULT_TAG}~0 " in c for c in cmds)
