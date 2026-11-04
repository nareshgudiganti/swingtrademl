"""Selection-lab start wrapper: pure tests (fake git, fake clock, fake runner, no database)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.brain import selection_lab_run as real_runner
from swing_trade_ml.brain import selection_lab_start as start

IST = ZoneInfo("Asia/Kolkata")
OK_NOW = datetime(2026, 12, 5, 0, 0, tzinfo=IST)
FILES = ("a.py", "b.py")
EV = {"B1": "a" * 40, "B2": "b" * 40, "B3": "c" * 40}  # evidence commits
TAG_HEAD = "object abc\ntype commit\ntag t\ntagger T <t@x> 1796000000 +0530"


class FakeGit:
    def __init__(self):
        self.tags = {"sl-protocol-v1", start.PHASE_B_RESULT_TAG, *start.PHASE_B_TAGS}
        self.lightweight: set[str] = set()
        self.ancestors = set(self.tags)
        self.tag_text: dict[str, str] = {}
        self.order_ok = {(EV["B1"], EV["B2"]), (EV["B2"], EV["B3"])}
        self.commit_missing: dict[str, set[str]] = {}
        self.ancestors |= set(EV.values())
        self.ledger = ""
        self.status = ""
        self.head_blobs = {"a.py": "h1", "b.py": "h2"}
        self.tag_blobs = {"a.py": "h1", "b.py": "h2"}
        self.fail: set[str] = set()  # command names that return exit 128
        self.ignored = True

    def __call__(self, *a):
        cmd = a[0]
        if cmd in self.fail:
            return 128, ""
        if cmd == "rev-parse":
            if "--verify" in a:
                tag = a[-1].split("/")[-1].split("^")[0]
                return (0, "tagsha\n") if tag in self.tags else (1, "")
            return 0, "headsha\n"
        if cmd == "merge-base":
            tag = a[2].split("/")[-1]
            if len(a) > 3 and a[3] != "HEAD":
                return (0, "") if (a[2], a[3]) in self.order_ok else (1, "")
            return (0, "") if tag in self.ancestors else (1, "")
        if cmd == "cat-file":
            tag = a[-1].split("/")[-1]
            if a[1] == "-t":
                return 0, ("commit\n" if tag in self.lightweight else "tag\n")
            return 0, self.tag_text.get(tag, TAG_HEAD + "\n\nmsg\n")
        if cmd == "show":
            return 0, self.ledger
        if cmd == "status":
            return 0, self.status
        if cmd == "ls-tree":
            blobs = self.head_blobs if a[1] == "HEAD" else self.tag_blobs
            p = a[-1]
            if p in self.commit_missing.get(a[1], ()):
                return 0, ""
            return 0, (f"100644 blob {blobs[p]}\t{p}\n" if p in blobs else "")
        if cmd == "check-ignore":
            return (0 if self.ignored else 1), ""
        raise AssertionError(a)


class FakeRunner:
    TAG = "sl-protocol-v1"
    FROZEN_FILES = FILES
    refusal_reasons = staticmethod(real_runner.refusal_reasons)

    def __init__(self, exit_code=0):
        self.calls = []
        self.exit_code = exit_code

    def git_state(self, repo):
        return True, [], False

    def amendment_signed(self, repo):
        return True

    def main(self, argv):
        self.calls.append(list(argv))
        return self.exit_code


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write_phase_b_record(env, outcome="NO_SURVIVOR", survivor=None, **tweak):
    """Write a terminal record shaped like phase_b_finish.py output, plus the matching fake git state."""
    d = env.root / start.PHASE_B_RESULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    cands, ledger_rows = {}, []
    split = "9" * 64
    for cid in start.PHASE_B_CANDIDATES:
        name = f"phase_b_{cid}.json"
        (d / name).write_bytes(f"result {cid}\n".encode())
        files = {name: _sha(f"result {cid}\n".encode())}
        row = start.PHASE_B_LEDGER_MARKER.format(cid=cid)
        ledger_rows.append(row)
        man = {
            "schema": start.PHASE_B_MANIFEST_SCHEMA,
            "candidate": cid,
            "files": files,
            "split_sha256": split,
            "ledger_row": row,
            "ledger_row_sha256": _sha(row.encode()),
        }
        mraw = json.dumps(man, sort_keys=True, indent=1).encode() + b"\n"
        (d / f"MANIFEST_{cid}.json").write_bytes(mraw)
        ok = cid == survivor
        label = start.PHASE_B_NO_WARNING if ok else "FAIL"
        cands[cid] = {
            "survives": ok,
            "pass_rows": {start.PHASE_B_BEATS_ID: label, start.PHASE_B_REJECT_ID: start.PHASE_B_NO_WARNING},
            "result_files": files,
            "manifest_file": f"MANIFEST_{cid}.json",
            "manifest_sha256": _sha(mraw),
            "evidence_commit": EV[cid],
        }
        for n in (name, f"MANIFEST_{cid}.json"):
            env.git.head_blobs[f"{start.PHASE_B_RESULT_DIR}/{n}"] = f"b{n}"
            env.git.tag_blobs[f"{start.PHASE_B_RESULT_DIR}/{n}"] = f"b{n}"
    rec = {
        "schema": start.PHASE_B_RESULT_SCHEMA,
        "outcome": outcome,
        "survivor": survivor,
        "selection": {
            "method": start.PHASE_B_RANK_METHOD,
            "outcome": outcome,
            "survivor": survivor,
            "survivors": [survivor] if survivor else [],
            "ranking": [{"candidate": survivor}] if survivor else [],
        },
        "written_at_ist": "2026-12-01T10:00:00+05:30",
        "split": {"sha256": split},
        "evidence_manifest": {"per_candidate_sha256": {c: v["manifest_sha256"] for c, v in cands.items()}},
        "candidates": cands,
    }
    rec.update(tweak)
    raw = json.dumps(rec, sort_keys=True, indent=2).encode() + b"\n"
    (d / "PHASE_B_RESULT.json").write_bytes(raw)
    digest = _sha(raw)
    env.git.head_blobs[start.PHASE_B_RESULT_REL] = "rj"
    env.git.tag_blobs[start.PHASE_B_RESULT_REL] = "rj"
    env.git.tag_blobs[start.LEDGER] = "ledger"
    ledger_rows.append(f"| x | {start.PHASE_B_RESULT_ROW_MARKER}: {outcome}. sha256 {digest} |")
    env.git.ledger = "\n".join(ledger_rows)
    env.git.tag_text[start.PHASE_B_RESULT_TAG] = (
        f"{TAG_HEAD}\n\noutcome={outcome}\n\nsurvivor={survivor or 'none'}\n\nresult_sha256={digest}\n\n"
        f"ledger_row={start.PHASE_B_RESULT_ROW_MARKER}\n\nwritten_at_ist=2026-12-01T10:00:00+05:30\n"
    )
    if outcome == "SURVIVOR_SELECTED":
        env.git.tags.add(start.PHASE_B_LOCK_TAG)
        env.git.ancestors.add(start.PHASE_B_LOCK_TAG)
        env.git.tag_text[start.PHASE_B_LOCK_TAG] = (
            f"{TAG_HEAD}\n\nsurvivor={survivor}\n\nresult_tag={start.PHASE_B_RESULT_TAG}\n"
        )
    return rec, digest


def rewrite_json(env, rec):
    """Replace the record bytes and keep the tag message and ledger in step (so only the tweak is wrong)."""
    raw = json.dumps(rec, sort_keys=True).encode()
    (env.root / start.PHASE_B_RESULT_REL).write_bytes(raw)
    old = env.git.tag_text[start.PHASE_B_RESULT_TAG].split("result_sha256=")[1].split()[0]
    env.git.tag_text[start.PHASE_B_RESULT_TAG] = env.git.tag_text[start.PHASE_B_RESULT_TAG].replace(
        old, _sha(raw)
    )
    env.git.ledger = env.git.ledger.replace(old, _sha(raw))


@pytest.fixture
def env(tmp_path):
    e = SimpleNamespace(git=FakeGit(), runner=FakeRunner(), root=tmp_path, now=OK_NOW)
    write_phase_b_record(e)
    return e


def go(env, *argv, now=None):
    clock = now or env.now
    return start.main(list(argv), runner=env.runner, git=env.git, repo_root=env.root, now_fn=lambda: clock)


def audit_lines(env):
    p = env.root / start.AUDIT_REL
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_all_pass_calls_runner_with_args_unchanged(env):
    assert go(env, "S0", "--technical-rerun") == 0
    assert env.runner.calls == [["S0", "--technical-rerun"]]
    lines = audit_lines(env)
    assert [x["event"] for x in lines] == ["start_attempt", "runner_finished"]
    assert lines[0]["decision"] == "permitted" and lines[1]["exit_code"] == 0
    assert lines[0]["candidate"] == "S0" and lines[0]["git_head"] == "headsha"
    assert lines[0]["tag_commit"] == "tagsha" and "utc" in lines[0] and "ist" in lines[0]


def test_runner_exit_code_is_returned_and_logged(env):
    env.runner.exit_code = 2
    assert go(env, "S0") == 2
    assert audit_lines(env)[-1]["exit_code"] == 2


@pytest.mark.parametrize(
    ("now", "ok"),
    [
        (datetime(2026, 12, 4, 23, 59, tzinfo=IST), False),
        (datetime(2026, 12, 5, 0, 0, tzinfo=IST), True),
        (datetime(2026, 12, 4, 18, 29, tzinfo=UTC), False),
        (datetime(2026, 12, 4, 18, 30, tzinfo=UTC), True),
        (datetime(2026, 11, 3, 12, 0, tzinfo=UTC), False),
    ],
)
def test_date_boundary(now, ok):
    assert start.check_date(now)["ok"] is ok


def test_naive_clock_refuses(env):
    assert go(env, "S0", now=datetime(2026, 12, 6)) == 2
    assert env.runner.calls == []


def refuses(env, *argv):
    assert go(env, *argv) == 2
    assert env.runner.calls == []
    lines = audit_lines(env)
    assert len(lines) == 1 and lines[0]["decision"] == "refused"
    return lines[0]


def test_before_date_refuses(env):
    env.now = datetime(2026, 12, 4, 23, 59, tzinfo=IST)
    rec = refuses(env, "S0")
    assert any(c["check"] == "date" and not c["ok"] for c in rec["checks"])


def test_missing_protocol_tag_refuses(env):
    env.git.tags.discard("sl-protocol-v1")
    refuses(env, "S0")


def test_tag_not_ancestor_refuses(env):
    env.git.ancestors.discard("sl-protocol-v1")
    refuses(env, "S0")


def test_dirty_tree_refuses(env):
    env.git.status = "?? new.txt\n"
    refuses(env, "S0")


def test_changed_frozen_file_refuses(env):
    env.git.head_blobs["a.py"] = "other"
    refuses(env, "S0")


@pytest.mark.parametrize("side", ["head", "tag"])
def test_one_side_absent_refuses(env, side):
    getattr(env.git, f"{side}_blobs").pop("a.py")
    refuses(env, "S0")


def test_absent_in_both_passes_with_warning(env, capsys):
    env.git.head_blobs.pop("a.py")
    env.git.tag_blobs.pop("a.py")
    assert go(env, "S0") == 0
    assert "a.py" in capsys.readouterr().out
    assert audit_lines(env)[0]["checks"][4]["warnings"]


@pytest.mark.parametrize("cmd", ["status", "ls-tree", "merge-base", "rev-parse", "check-ignore"])
def test_git_error_refuses(env, cmd):
    env.git.fail.add(cmd)
    assert go(env, "S0") == 2
    assert env.runner.calls == []


def phase_b_reasons(env):
    rec = refuses(env, "S0")
    return [r for c in rec["checks"] if c["check"] == "phase_b_lock" for r in c["reasons"]]


def test_valid_no_survivor_record_passes(env):
    assert go(env, "S0") == 0


def test_valid_survivor_record_passes(env):
    write_phase_b_record(env, "SURVIVOR_SELECTED", "B2")
    assert go(env, "S0") == 0


def test_missing_record_refuses(env):
    (env.root / start.PHASE_B_RESULT_REL).unlink()
    assert any("missing from the working tree" in r for r in phase_b_reasons(env))


def test_missing_result_tag_refuses(env):
    env.git.tags.discard(start.PHASE_B_RESULT_TAG)
    assert any("phase-b-result does not exist" in r for r in phase_b_reasons(env))


def test_lightweight_result_tag_refuses(env):
    env.git.lightweight.add(start.PHASE_B_RESULT_TAG)
    assert any("lightweight" in r for r in phase_b_reasons(env))


def test_result_tag_not_ancestor_refuses(env):
    env.git.ancestors.discard(start.PHASE_B_RESULT_TAG)
    assert any("not in HEAD" in r for r in phase_b_reasons(env))


def test_phase_b_tag_missing_refuses(env):
    env.git.tags.discard("evidence-defs-v2")
    assert any("evidence-defs-v2" in r for r in phase_b_reasons(env))


def test_json_modified_after_tag_refuses(env):
    env.git.head_blobs[start.PHASE_B_RESULT_REL] = "other"
    assert any("differs from the version at tag" in r for r in phase_b_reasons(env))


def test_json_bytes_changed_hash_mismatch_with_tag_refuses(env):
    p = env.root / start.PHASE_B_RESULT_REL
    p.write_bytes(p.read_bytes() + b" ")
    assert any("does not match the tag message" in r for r in phase_b_reasons(env))


def test_hash_mismatch_with_ledger_refuses(env):
    digest = env.git.ledger.split("sha256 ")[1].strip()
    env.git.ledger = env.git.ledger.replace(digest, "f" * 64)
    assert any("'Phase B result record' row" in r for r in phase_b_reasons(env))


def test_tag_message_outcome_differs_refuses(env):
    t = start.PHASE_B_RESULT_TAG
    env.git.tag_text[t] = env.git.tag_text[t].replace("outcome=NO_SURVIVOR", "outcome=SURVIVOR_SELECTED")
    assert any("outcome in the tag message" in r for r in phase_b_reasons(env))


def test_wf_protocol_v2_present_with_no_survivor_refuses(env):
    env.git.tags.add(start.PHASE_B_LOCK_TAG)
    assert any("inconsistent" in r for r in phase_b_reasons(env))


def test_wf_protocol_v2_missing_with_survivor_refuses(env):
    write_phase_b_record(env, "SURVIVOR_SELECTED", "B1")
    env.git.tags.discard(start.PHASE_B_LOCK_TAG)
    assert any("wf-protocol-v2 does not exist" in r for r in phase_b_reasons(env))


def test_wf_protocol_v2_lightweight_with_survivor_refuses(env):
    write_phase_b_record(env, "SURVIVOR_SELECTED", "B1")
    env.git.lightweight.add(start.PHASE_B_LOCK_TAG)
    assert any("lightweight" in r for r in phase_b_reasons(env))


def test_wf_protocol_v2_names_other_survivor_refuses(env):
    write_phase_b_record(env, "SURVIVOR_SELECTED", "B1")
    env.git.tag_text[start.PHASE_B_LOCK_TAG] = env.git.tag_text[start.PHASE_B_LOCK_TAG].replace("B1", "B3")
    assert any("does not name survivor" in r for r in phase_b_reasons(env))


def test_malformed_json_refuses(env):
    raw = b"{not json"
    (env.root / start.PHASE_B_RESULT_REL).write_bytes(raw)
    t = start.PHASE_B_RESULT_TAG
    old = env.git.tag_text[t].split("result_sha256=")[1].split()[0]
    env.git.tag_text[t] = env.git.tag_text[t].replace(old, _sha(raw))  # hashes agree; only the JSON is bad
    assert any("not valid JSON" in r for r in phase_b_reasons(env))


def test_wrong_schema_refuses(env):
    write_phase_b_record(env, schema="other")
    assert any("schema" in r for r in phase_b_reasons(env))


def test_unknown_outcome_refuses(env):
    write_phase_b_record(env, outcome="AMBIGUOUS")
    assert any("outcome 'AMBIGUOUS'" in r for r in phase_b_reasons(env))


def test_record_timestamp_too_late_refuses(env):
    write_phase_b_record(env, written_at_ist="2026-12-05T00:00:00+05:30")
    assert any("written_at_ist" in r for r in phase_b_reasons(env))


def test_tag_created_too_late_refuses(env):
    t = start.PHASE_B_RESULT_TAG
    env.git.tag_text[t] = env.git.tag_text[t].replace("1796000000", "1796500000")
    assert any("created after 2026-12-04" in r for r in phase_b_reasons(env))


def test_missing_candidate_refuses(env):
    rec, _ = write_phase_b_record(env)
    del rec["candidates"]["B3"]
    rewrite_json(env, rec)
    assert any("all of B1, B2, B3" in r for r in phase_b_reasons(env))


def test_result_file_changed_refuses(env):
    (env.root / start.PHASE_B_RESULT_DIR / "phase_b_B2.json").write_bytes(b"tampered")
    assert any("phase_b_B2.json" in r and "sha256 differs" in r for r in phase_b_reasons(env))


def test_result_file_blob_changed_since_tag_refuses(env):
    env.git.head_blobs[f"{start.PHASE_B_RESULT_DIR}/phase_b_B1.json"] = "x"
    assert any("phase_b_B1.json at HEAD differs" in r for r in phase_b_reasons(env))


def test_no_survivor_with_surviving_candidate_refuses(env):
    rec, _ = write_phase_b_record(env)
    rec["candidates"]["B1"]["survives"] = True
    rewrite_json(env, rec)
    assert any("names or marks a surviving candidate" in r for r in phase_b_reasons(env))


def test_survivor_not_marked_surviving_refuses(env):
    rec, _ = write_phase_b_record(env, "SURVIVOR_SELECTED", "B1")
    rec["candidates"]["B1"]["survives"] = False
    rewrite_json(env, rec)
    assert any("did not survive" in r for r in phase_b_reasons(env))


def test_ledger_candidate_row_missing_refuses(env):
    env.git.ledger = env.git.ledger.replace("Phase B candidate B1", "x")
    assert any("candidate B1" in r for r in phase_b_reasons(env))


def test_ledger_candidate_row_duplicated_refuses(env):
    env.git.ledger += "\nPhase B candidate B2"
    assert any("candidate B2" in r for r in phase_b_reasons(env))


@pytest.mark.parametrize("cmd", ["cat-file", "show", "ls-tree", "merge-base"])
def test_phase_b_git_error_fails_closed(env, cmd):
    env.git.fail.add(cmd)
    refuses(env, "S0")


def test_runner_guard_refusal_is_included(env):
    env.runner.amendment_signed = lambda repo: False
    refuses(env, "S0")


def test_runner_helper_exception_refuses(env):
    def boom(repo):
        raise OSError("git gone")

    env.runner.git_state = boom
    refuses(env, "S0")


def test_audit_unwritable_refuses_and_never_calls_runner(env):
    (env.root / "backend").mkdir()
    (env.root / "backend" / "data").write_text("a file, not a folder", encoding="utf-8")
    assert go(env, "S0") == 2
    assert env.runner.calls == []


def test_audit_not_gitignored_refuses(env):
    env.git.ignored = False
    assert go(env, "S0") == 2
    assert env.runner.calls == []
    assert audit_lines(env) == []


def test_check_only_never_calls_runner_and_logs_once(env, capsys):
    assert go(env, "S0", "--check-only") == 0
    assert env.runner.calls == []
    lines = audit_lines(env)
    assert len(lines) == 1 and lines[0]["decision"] == "would_permit" and lines[0]["check_only"]


def test_check_only_prints_every_reason(env, capsys):
    env.now = datetime(2026, 11, 3, tzinfo=UTC)
    env.git.status = "M x\n"
    assert go(env, "S0", "--check-only") == 2
    out = capsys.readouterr().out
    assert "Too early" in out and "uncommitted" in out
    assert env.runner.calls == []


def test_audit_line_written_before_runner_call(env):
    seen = []
    env.runner.main = lambda argv: seen.append(len(audit_lines(env))) or 0
    go(env, "S0")
    assert seen == [1]


def test_every_refusal_writes_exactly_one_line(env):
    env.git.status = "M x"
    go(env, "S0")
    go(env, "S1")
    assert len(audit_lines(env)) == 2


def test_phase_b_constants_match_phase_b():
    import swing_trade_ml.brain.service  # noqa: F401  (import order: phase_b alone has a circular import)
    from swing_trade_ml.brain import phase_b

    assert tuple(t for t in phase_b.REQUIRED_TAGS) == start.PHASE_B_TAGS
    assert start.PHASE_B_LEDGER_MARKER == phase_b.LEDGER_MARKER
    assert tuple(phase_b.CANDIDATES) == start.PHASE_B_CANDIDATES


def test_real_runner_exposes_what_the_wrapper_uses():
    for name in ("TAG", "FROZEN_FILES", "git_state", "amendment_signed", "refusal_reasons", "main"):
        assert hasattr(real_runner, name)


# ---- no direct call path to the frozen runner outside the wrapper

REPO = Path(__file__).resolve().parents[2]
ALLOWED = {
    "backend/src/swing_trade_ml/brain/selection_lab_start.py",
    "backend/src/swing_trade_ml/brain/selection_lab_run.py",
}
# a way of RUNNING the runner (not just importing a helper from it)
DIRECT = re.compile(
    r"-m\s+swing_trade_ml\.brain\.selection_lab_run|selection_lab_run\.main|selection_lab_run\s+import\s+[^\n]*\bmain\b|selection_lab_run\.py"
)


def _scan_files():
    for root in ("backend/src", "scripts", ".github", "backend/scripts", "Makefile", "docker-compose.yml"):
        p = REPO / root
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix in {
                    ".py",
                    ".sh",
                    ".ps1",
                    ".yml",
                    ".yaml",
                    ".toml",
                    ".cfg",
                    ".bat",
                }:
                    yield f


def test_no_code_script_or_workflow_calls_the_runner_directly():
    bad = []
    for f in _scan_files():
        rel = f.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        if DIRECT.search(f.read_text(encoding="utf-8", errors="ignore")):
            bad.append(rel)
    assert bad == [], f"use brain.selection_lab_start instead: {bad}"


def test_non_frozen_docs_point_to_the_wrapper():
    doc = (REPO / "docs/brain/SELECTION-LAB-START.md").read_text(encoding="utf-8")
    assert "selection_lab_start" in doc and "not a hard lock" in doc


def test_console_entry_is_declared():
    toml = (REPO / "backend/pyproject.toml").read_text(encoding="utf-8")
    assert 'selection-lab-start = "swing_trade_ml.brain.selection_lab_start:main"' in toml


@pytest.mark.parametrize(
    "line",
    [
        "python -m swing_trade_ml.brain.selection_lab_run S0",
        "from swing_trade_ml.brain import selection_lab_run; selection_lab_run.main(['S0'])",
        "from swing_trade_ml.brain.selection_lab_run import main",
        "python backend/src/swing_trade_ml/brain/selection_lab_run.py S0",
    ],
)
def test_the_scanner_pattern_catches_direct_calls(line):
    assert DIRECT.search(line)
    assert not DIRECT.search("from swing_trade_ml.brain.selection_lab_run import collect_db")


# ---- reconciliation with brain/phase_b_finish.py (record, manifests, tag message, evidence commits)


def reasons_now(env):
    return start.check_phase_b_lock(env.git, env.root)["reasons"]


def test_manifest_missing_refuses(env):
    (env.root / start.PHASE_B_RESULT_DIR / "MANIFEST_B2.json").unlink()
    assert any("MANIFEST_B2.json is missing" in r for r in phase_b_reasons(env))


def test_manifest_changed_since_tag_refuses(env):
    env.git.head_blobs[f"{start.PHASE_B_RESULT_DIR}/MANIFEST_B1.json"] = "x"
    assert any("MANIFEST_B1.json at HEAD differs" in r for r in phase_b_reasons(env))


def test_manifest_bytes_differ_from_record_refuses(env):
    p = env.root / start.PHASE_B_RESULT_DIR / "MANIFEST_B3.json"
    p.write_bytes(p.read_bytes() + b" ")
    assert any("MANIFEST_B3.json sha256 differs" in r for r in phase_b_reasons(env))


def _tamper_manifest(env, cid, **change):
    p = env.root / start.PHASE_B_RESULT_DIR / f"MANIFEST_{cid}.json"
    m = json.loads(p.read_text())
    m.update(change)
    raw = json.dumps(m).encode()
    p.write_bytes(raw)
    rec = json.loads((env.root / start.PHASE_B_RESULT_REL).read_text())
    rec["candidates"][cid]["manifest_sha256"] = _sha(raw)
    rec["evidence_manifest"]["per_candidate_sha256"][cid] = _sha(raw)
    rewrite_json(env, rec)


def test_manifest_wrong_schema_refuses(env):
    _tamper_manifest(env, "B1", schema="nope")
    assert any("wrong schema or candidate" in r for r in phase_b_reasons(env))


def test_manifest_file_hashes_differ_refuses(env):
    _tamper_manifest(env, "B2", files={"phase_b_B2.json": "0" * 64})
    assert any("file hashes differ" in r for r in phase_b_reasons(env))


def test_manifest_split_hash_differs_refuses(env):
    _tamper_manifest(env, "B2", split_sha256="1" * 64)
    assert any("split hash differs" in r for r in phase_b_reasons(env))


def test_manifest_ledger_row_not_in_ledger_refuses(env):
    _tamper_manifest(env, "B3", ledger_row="| not there |", ledger_row_sha256=_sha(b"| not there |"))
    assert any("ledger row is not in the ledger" in r for r in phase_b_reasons(env))


def test_manifest_file_name_in_record_wrong_refuses(env):
    rec, _ = write_phase_b_record(env)
    rec["candidates"]["B1"]["manifest_file"] = "../evil.json"
    rewrite_json(env, rec)
    assert any("manifest_file is not" in r for r in phase_b_reasons(env))


def test_evidence_commit_not_ancestor_refuses(env):
    env.git.ancestors.discard(EV["B2"])
    assert any("B2 evidence commit is not in HEAD" in r for r in phase_b_reasons(env))


def test_evidence_commit_missing_item_refuses(env):
    env.git.commit_missing[EV["B1"]] = {f"{start.PHASE_B_RESULT_DIR}/MANIFEST_B1.json"}
    assert any("does not contain MANIFEST_B1.json" in r for r in phase_b_reasons(env))


def test_evidence_commit_missing_ledger_refuses(env):
    env.git.commit_missing[EV["B3"]] = {start.LEDGER}
    assert any("does not contain the ledger" in r for r in phase_b_reasons(env))


def test_candidates_committed_together_refuses(env):
    rec, _ = write_phase_b_record(env)
    rec["candidates"]["B2"]["evidence_commit"] = EV["B1"]
    rewrite_json(env, rec)
    assert any("committed together" in r for r in phase_b_reasons(env))


def test_evidence_commits_out_of_order_refuses(env):
    env.git.order_ok.discard((EV["B2"], EV["B3"]))
    assert any("evidence commit of B2 is not before that of B3" in r for r in phase_b_reasons(env))


def test_bad_evidence_commit_value_refuses(env):
    rec, _ = write_phase_b_record(env)
    rec["candidates"]["B1"]["evidence_commit"] = "--upload-pack=x"
    rewrite_json(env, rec)
    assert any("no valid evidence_commit" in r for r in phase_b_reasons(env))


def test_survives_flag_differs_from_labels_refuses(env):
    rec, _ = write_phase_b_record(env, "SURVIVOR_SELECTED", "B1")
    rec["candidates"]["B1"]["pass_rows"][start.PHASE_B_BEATS_ID] = "FAIL"
    rewrite_json(env, rec)
    assert any("stored survives differs" in r for r in phase_b_reasons(env))


def test_no_survivor_but_labels_show_survivor_refuses(env):
    rec, _ = write_phase_b_record(env)
    rec["candidates"]["B2"]["pass_rows"][start.PHASE_B_BEATS_ID] = start.PHASE_B_NO_WARNING
    rewrite_json(env, rec)
    assert any("labels show a survivor" in r or "stored survives differs" in r for r in phase_b_reasons(env))


def test_selection_block_missing_or_other_method_refuses(env):
    rec, _ = write_phase_b_record(env)
    rec["selection"]["method"] = "other"
    rewrite_json(env, rec)
    assert any("selection block is missing" in r for r in phase_b_reasons(env))


def test_selection_survivor_disagrees_refuses(env):
    rec, _ = write_phase_b_record(env, "SURVIVOR_SELECTED", "B2")
    rec["selection"]["survivor"] = "B1"
    rewrite_json(env, rec)
    assert any("selection block disagrees" in r for r in phase_b_reasons(env))


def test_selection_ranking_not_led_by_survivor_refuses(env):
    rec, _ = write_phase_b_record(env, "SURVIVOR_SELECTED", "B2")
    rec["selection"]["ranking"] = [{"candidate": "B1"}]
    rewrite_json(env, rec)
    assert any("ranking does not put" in r for r in phase_b_reasons(env))


def test_tag_message_survivor_differs_refuses(env):
    t = start.PHASE_B_RESULT_TAG
    env.git.tag_text[t] = env.git.tag_text[t].replace("survivor=none", "survivor=B1")
    assert any("survivor in the tag message" in r for r in phase_b_reasons(env))


def test_tag_message_without_ledger_row_line_refuses(env):
    t = start.PHASE_B_RESULT_TAG
    env.git.tag_text[t] = env.git.tag_text[t].replace("ledger_row=", "other=")
    assert any("ledger_row line" in r for r in phase_b_reasons(env))


def test_wf_tag_without_result_tag_line_refuses(env):
    write_phase_b_record(env, "SURVIVOR_SELECTED", "B1")
    env.git.tag_text[start.PHASE_B_LOCK_TAG] = env.git.tag_text[start.PHASE_B_LOCK_TAG].replace(
        "result_tag=", "x="
    )
    assert any("result_tag=" in r for r in phase_b_reasons(env))


def test_old_result_marker_alone_is_not_enough(env):
    env.git.ledger = env.git.ledger.replace(start.PHASE_B_RESULT_ROW_MARKER, "Phase B result")
    assert any("Phase B result record' row" in r for r in phase_b_reasons(env))


def test_finish_module_constants_match_wrapper():
    import swing_trade_ml.brain.service  # noqa: F401  (import order: service before phase_b)

    try:
        from swing_trade_ml.brain import phase_b, phase_b_finish
    except ImportError:
        pytest.skip("phase_b_finish is not on this branch yet")
    assert phase_b_finish.SCHEMA == start.PHASE_B_RESULT_SCHEMA
    assert phase_b_finish.MANIFEST_SCHEMA == start.PHASE_B_MANIFEST_SCHEMA
    assert phase_b_finish.RANK_METHOD == start.PHASE_B_RANK_METHOD
    assert phase_b_finish.RESULT_MARKER == start.PHASE_B_RESULT_ROW_MARKER
    assert phase_b_finish.RESULT_TAG == start.PHASE_B_RESULT_TAG
    assert phase_b_finish.WF_TAG == start.PHASE_B_LOCK_TAG
    assert phase_b_finish.EVIDENCE_REL == start.PHASE_B_RESULT_DIR
    assert tuple(phase_b_finish.OUTCOMES) == start.PHASE_B_OUTCOMES
    assert phase_b.NO_WARNING == start.PHASE_B_NO_WARNING
