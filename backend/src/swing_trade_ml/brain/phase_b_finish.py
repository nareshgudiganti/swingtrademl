"""Phase B completion record (docs: docs/brain/PHASE-B-FINISH.md).

Reads the three finished Phase B results and, only when every precondition holds, writes ONE file
(`PHASE_B_RESULT.json`) and ONE exposure-ledger row. Dry run by default. It never commits, tags,
pushes, creates `wf-protocol-v2`, calls the network or database, or reads `.env`. It imports
`phase_b` for constants and `survives`; it never edits it (`phase_b.py` stays byte-identical to the
`phase-b-settings` tag).

Run (owner, 2026-11-09 to 2026-12-04 IST only):
    python -m swing_trade_ml.brain.phase_b_finish              # dry run, writes nothing
    python -m swing_trade_ml.brain.phase_b_finish --apply      # writes the two things
    python -m swing_trade_ml.brain.phase_b_finish --manifest B1 [--apply]   # one candidate's manifest
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import swing_trade_ml.brain.service  # noqa: F401  (import-order trap: service before phase_b)
from swing_trade_ml.brain import phase_b as pb

SCHEMA = "phase-b-result-v1"
MANIFEST_SCHEMA = "phase-b-candidate-manifest-v1"
RANK_METHOD = "phase-b-completion-v1"
RESULT_NAME = "PHASE_B_RESULT.json"
RESULT_TAG = "phase-b-result"
WF_TAG = "wf-protocol-v2"
RESULT_MARKER = "Phase B result record"
WINDOW_START = pb.PHASE_B_START  # 2026-11-09
WINDOW_END = date(2026, 12, 4)  # inclusive, IST calendar date
OUTCOMES = ("SURVIVOR_SELECTED", "NO_SURVIVOR")
LABELS = (pb.NO_WARNING, pb.FAIL, pb.INCONCLUSIVE, pb.NOT_TESTABLE)
ROUND = 6  # decimals used when comparing figures for the tie ladder

EVIDENCE_REL = "docs/brain/evidence/phase_b"
LEDGER_REL = "docs/brain/EXPOSURE-LEDGER.md"
SPLIT_REL = "docs/brain/evidence/stock_split"
PHASE_B_PY_REL = "backend/src/swing_trade_ml/brain/phase_b.py"

# The tie ladder, in order. Each entry: (name, path into the stored result JSON). Higher wins.
# After the last entry, the lower candidate id wins (B1 < B2 < B3). No discretion anywhere.
LADDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("edge_low", ("trade_level", "candidate", "edge_low")),
    ("edge_per_day", ("trade_level", "candidate", "edge_per_day")),
    ("avg_net", ("trade_level", "candidate", "avg_net")),
    ("edge_vs_momentum_low", ("edge_vs_momentum", "edge_low")),
)

GitFn = Callable[[Sequence[str]], tuple[int, str]]
NowFn = Callable[[], datetime]


def make_git(root: Path) -> GitFn:
    def run(args: Sequence[str]) -> tuple[int, str]:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
        return p.returncode, p.stdout

    return run


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def dumps(obj) -> str:
    """Deterministic: sorted keys, LF, trailing newline."""
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def ist_now(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("the clock must be timezone-aware")
    return now.astimezone(pb.IST)


# ------------------------------------------------------------------ small readers


def _dig(d, path: Sequence[str]):
    for k in path:
        if not isinstance(d, Mapping) or k not in d:
            return None
        d = d[k]
    return d


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def check_value(result: Mapping, check_id: str) -> Mapping | None:
    for c in result.get("checks") or []:
        if isinstance(c, Mapping) and c.get("id") == check_id:
            return c
    return None


def ledger_rows(text: str, marker: str) -> list[tuple[int, str]]:
    return [(i, ln) for i, ln in enumerate(text.splitlines()) if ln.startswith("|") and marker in ln]


# ------------------------------------------------------------------ result validation


def validate_result(cid: str, data, *, split_sha: str | None, ledger_text: str) -> list[str]:
    """Why one stored candidate result cannot be trusted. Empty list means complete and consistent."""
    why: list[str] = []
    p = f"{cid}:"
    if not isinstance(data, Mapping):
        return [f"{p} the result JSON is not an object."]
    need = (
        "manifest",
        "candidate",
        "window",
        "trading_days",
        "folds",
        "trade_level",
        "edge_vs_momentum",
        "reject_check",
        "checks",
        "survives",
    )
    missing = [k for k in need if k not in data]
    if missing:
        return [f"{p} incomplete result, missing keys: {', '.join(missing)}."]
    if _dig(data, ("candidate", "id")) != cid:
        why.append(f"{p} the result names candidate {_dig(data, ('candidate', 'id'))!r}.")
    if _dig(data, ("manifest", "candidate", "id")) != cid:
        why.append(f"{p} the manifest names candidate {_dig(data, ('manifest', 'candidate', 'id'))!r}.")
    if list(data["window"]) != [pb.DEV_START.isoformat(), pb.DEV_END.isoformat()]:
        why.append(f"{p} wrong window {data['window']!r}; Phase B uses {pb.DEV_START} to {pb.DEV_END}.")
    man = data["manifest"] if isinstance(data["manifest"], Mapping) else {}
    if man.get("protocol") != f"{pb.PROTOCOL_ID} v{pb.PROTOCOL_VERSION}":
        why.append(f"{p} wrong protocol {man.get('protocol')!r}.")
    if not str(man.get("defs_version", "")).startswith(pb.DEFS_VERSION):
        why.append(f"{p} wrong definitions version {man.get('defs_version')!r}.")
    if not str(man.get("code_commit", "")).strip() or "uncommitted" in str(man.get("code_commit")):
        why.append(
            f"{p} the run was made on an unclean tree or has no code commit ({man.get('code_commit')!r})."
        )
    if _dig(man, ("stocks", "split_sha256")) != split_sha:
        why.append(f"{p} the result's stock split hash does not match the locked split file.")
    row = man.get("exposure_ledger_row")
    if not row or row not in ledger_text.splitlines():
        why.append(f"{p} the manifest's exposure-ledger row is not in the ledger.")
    for name in ("trading_days", "folds"):
        if not isinstance(data[name], int) or isinstance(data[name], bool) or data[name] <= 0:
            why.append(f"{p} {name} must be a positive whole number.")
    if not isinstance(data["survives"], bool):
        why.append(f"{p} 'survives' is not true/false.")
    for c in data["checks"] if isinstance(data["checks"], list) else []:
        if not isinstance(c, Mapping) or c.get("label") not in LABELS:
            why.append(f"{p} a check has a missing or unknown label ({c!r:.80}).")
            break
    beats = check_value(data, "phase_b_beats_every_stock_and_momentum")
    rej = check_value(data, "reject_set")
    stat = check_value(data, "statistical_confidence")
    if not (beats and rej and stat):
        why.append(f"{p} a required check is missing (beats-baselines, reject_set, statistical_confidence).")
        return why
    derived = pb.survives(beats_label=beats["label"], reject=rej["label"])
    if isinstance(data["survives"], bool) and derived != data["survives"]:
        why.append(
            f"{p} INCONSISTENT: stored survives={data['survives']} but the signed rule on the stored "
            f"labels gives {derived}."
        )
    if _dig(data, ("reject_check", "label")) != rej["label"]:
        why.append(f"{p} reject_check.label differs from the reject_set check label.")
    tc = _dig(data, ("trade_level", "candidate"))
    if not isinstance(tc, Mapping):
        why.append(f"{p} trade_level.candidate is missing.")
        return why
    for k in ("ideas", "days"):
        if not isinstance(tc.get(k), int):
            why.append(f"{p} trade_level.candidate.{k} is missing.")
    if _dig(beats, ("value", "candidate")) != tc.get("avg_net"):
        why.append(f"{p} the beats-baselines value differs from trade_level.candidate.avg_net.")
    if _dig(beats, ("value", "every_stock")) != _dig(data, ("trade_level", "every_stock", "avg_net")):
        why.append(f"{p} the every-stock figure differs between checks and trade_level.")
    if _dig(beats, ("value", "momentum")) != _dig(data, ("trade_level", "momentum", "avg_net")):
        why.append(f"{p} the momentum figure differs between checks and trade_level.")
    if _dig(stat, ("value", "low")) != tc.get("edge_low"):
        why.append(f"{p} statistical_confidence.low differs from trade_level.candidate.edge_low.")
    if data["survives"] is True:
        for name, path in LADDER:
            v = _dig(data, path)
            if v is not None and not _num(v):
                why.append(f"{p} survivor figure {name} is not a number.")
    return why


def rank_key(data: Mapping) -> tuple:
    out = []
    for _, path in LADDER:
        v = _dig(data, path)
        out.append(round(float(v), ROUND) if _num(v) else float("-inf"))
    return tuple(out)


def select_outcome(results: Mapping[str, Mapping]) -> dict:
    """Mechanical outcome from validated results. Never invents a survivor."""
    survivors = sorted(
        c
        for c, r in results.items()
        if pb.survives(
            beats_label=check_value(r, "phase_b_beats_every_stock_and_momentum")["label"],
            reject=check_value(r, "reject_set")["label"],
        )
    )
    ranking = sorted(survivors, key=lambda c: (tuple(-x for x in rank_key(results[c])), c))
    rows = []
    for c in ranking:
        vals = {
            n: (round(float(_dig(results[c], p)), ROUND) if _num(_dig(results[c], p)) else None)
            for n, p in LADDER
        }
        rows.append({"candidate": c, "figures": vals})
    decided_by = None
    if len(ranking) >= 2:
        a, b = rank_key(results[ranking[0]]), rank_key(results[ranking[1]])
        decided_by = "candidate_id"
        for (name, _), x, y in zip(LADDER, a, b, strict=True):
            if x != y:
                decided_by = name
                break
    elif len(ranking) == 1:
        decided_by = "only_survivor"
    return {
        "method": RANK_METHOD,
        "outcome": "SURVIVOR_SELECTED" if ranking else "NO_SURVIVOR",
        "survivor": ranking[0] if ranking else None,
        "survivors": survivors,
        "ranking": rows,
        "decided_by": decided_by,
    }


# ------------------------------------------------------------------ git-backed checks


@dataclass
class Plan:
    reasons: list[str] = field(default_factory=list)
    result: dict | None = None
    result_text: str | None = None
    ledger_row: str | None = None
    commands: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons and self.result is not None


def _tag_info(git: GitFn, tag: str, why: list[str]) -> dict | None:
    rc, out = git(("cat-file", "-t", tag))
    if rc != 0:
        why.append(f"Tag {tag} does not exist.")
        return None
    if out.strip() != "tag":
        why.append(f"Tag {tag} is not annotated (it is a {out.strip()}).")
        return None
    rc, obj = git(("rev-parse", tag))
    rc2, com = git(("rev-parse", f"{tag}^{{commit}}"))
    rc3, _ = git(("merge-base", "--is-ancestor", tag, "HEAD"))
    if rc != 0 or rc2 != 0:
        why.append(f"Tag {tag} cannot be resolved.")
        return None
    if rc3 != 0:
        why.append(f"Tag {tag} is not an ancestor of HEAD.")
        return None
    return {"tag_object": obj.strip(), "commit": com.strip()}


def _blob(git: GitFn, rev: str) -> str | None:
    rc, out = git(("rev-parse", f"{rev}:{PHASE_B_PY_REL}"))
    return out.strip() if rc == 0 and out.strip() else None


def _read_json(path: Path, why: list[str], label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        why.append(f"{label} cannot be read as JSON ({type(e).__name__}).")
        return None


def manifest_path(root: Path, cid: str) -> Path:
    return root / EVIDENCE_REL / f"MANIFEST_{cid}.json"


def build_candidate_manifest(
    root: Path, cid: str, git: GitFn, now: datetime
) -> tuple[dict | None, list[str]]:
    """The evidence manifest of one finished candidate: hashes of its two outputs and its ledger row."""
    why: list[str] = []
    today = ist_now(now).date()
    if not (WINDOW_START <= today <= WINDOW_END):
        why.append(f"Today is {today} IST; manifests are written {WINDOW_START} to {WINDOW_END} only.")
    out_dir = root / EVIDENCE_REL
    md, js = pb.output_paths(cid, out_dir)
    ledger = root / LEDGER_REL
    for p in (md, js, ledger):
        if not p.exists():
            why.append(f"{cid}: {p.name} is missing.")
    if manifest_path(root, cid).exists():
        why.append(f"{cid}: its manifest already exists (duplicate); manifests are never rewritten.")
    if why:
        return None, why
    split_dir = root / SPLIT_REL
    split_sha = pb.recorded_split_hash(split_dir)
    ltext = ledger.read_text(encoding="utf-8")
    data = _read_json(js, why, f"{cid} result")
    if data is not None:
        why += validate_result(cid, data, split_sha=split_sha, ledger_text=ltext)
    rows = ledger_rows(ltext, pb.LEDGER_MARKER.format(cid=cid))
    if len(rows) != 1:
        why.append(f"{cid}: the ledger has {len(rows)} rows for it, expected exactly 1.")
    tags = {}
    for t in pb.REQUIRED_TAGS:
        info = _tag_info(git, t, why)
        if info:
            tags[t] = info["tag_object"]
    if why:
        return None, why
    m = {
        "schema": MANIFEST_SCHEMA,
        "candidate": cid,
        "written_at_ist": ist_now(now).isoformat(timespec="seconds"),
        "code_commit": data["manifest"]["code_commit"],
        "phase_b_py_blob": _blob(git, "HEAD"),
        "split_sha256": split_sha,
        "tags": tags,
        "files": {md.name: sha256_file(md), js.name: sha256_file(js)},
        "ledger_row": rows[0][1],
        "ledger_row_sha256": sha256_bytes(rows[0][1].encode("utf-8")),
        "survives": data["survives"],
    }
    return m, []


# ------------------------------------------------------------------ the main plan


def _add_commit(git: GitFn, rel: str) -> str | None:
    rc, out = git(("log", "--format=%H", "--diff-filter=A", "--", rel))
    lines = [x for x in out.split() if x]
    return lines[-1] if rc == 0 and lines else None


def prepare(root: Path, git: GitFn, now: datetime) -> Plan:
    plan = Plan()
    why = plan.reasons
    now_ist = ist_now(now)
    today = now_ist.date()
    if today < WINDOW_START:
        why.append(f"Today is {today} IST, before {WINDOW_START}: Phase B has not started.")
    if today > WINDOW_END:
        why.append(f"Today is {today} IST, after the deadline {WINDOW_END}: no record may be written.")

    tags = {}
    for t in pb.REQUIRED_TAGS:
        info = _tag_info(git, t, why)
        if info:
            tags[t] = info
    rc, out = git(("tag", "-l", RESULT_TAG))
    if rc != 0 or out.strip():
        why.append(f"Duplicate: tag {RESULT_TAG} already exists (or cannot be checked).")
    rc, out = git(("status", "--porcelain", "--untracked-files=all"))
    if rc != 0 or out.strip():
        why.append("The working tree is not clean (or cannot be checked).")

    out_dir = root / EVIDENCE_REL
    result_path = out_dir / RESULT_NAME
    if result_path.exists():
        why.append(f"Duplicate: {RESULT_NAME} already exists.")
    ledger = root / LEDGER_REL
    if not ledger.exists():
        why.append("The exposure ledger is missing.")
        return plan
    ltext = ledger.read_text(encoding="utf-8")
    if ledger_rows(ltext, RESULT_MARKER):
        why.append(f"Duplicate: the ledger already has a '{RESULT_MARKER}' row.")

    split_dir = root / SPLIT_REL
    split_file = split_dir / pb.SPLIT_FILE
    want = pb.recorded_split_hash(split_dir)
    split_sha = None
    if not split_file.exists() or want is None:
        why.append("The stock split file or its recorded hash is missing.")
    else:
        split_sha = pb.file_sha256(split_file)
        if split_sha != want:
            why.append("The stock split file does not match its recorded hash.")
            split_sha = None

    results: dict[str, dict] = {}
    for cid in pb.CANDIDATES:
        md, js = pb.output_paths(cid, out_dir)
        if not md.exists() or not js.exists():
            why.append(f"{cid}: result files missing ({md.name}, {js.name}); Phase B is incomplete.")
            continue
        data = _read_json(js, why, f"{cid} result")
        if data is None:
            continue
        before = len(why)
        why += validate_result(cid, data, split_sha=split_sha, ledger_text=ltext)
        n = len(ledger_rows(ltext, pb.LEDGER_MARKER.format(cid=cid)))
        if n != 1:
            why.append(f"{cid}: the ledger has {n} rows for it, expected exactly 1.")
        if len(why) == before and n == 1:
            results[cid] = data

    # cross-candidate consistency
    if len(results) == len(pb.CANDIDATES):
        for name in ("trading_days", "folds"):
            vals = {c: r[name] for c, r in results.items()}
            if len(set(vals.values())) != 1:
                why.append(f"INCONSISTENT: {name} differs between candidates {vals}.")

    # per-candidate manifests, commit order
    commits: dict[str, str] = {}
    blob_head = _blob(git, "HEAD")
    blob_tag = _blob(git, f"{pb.SETTINGS_TAG}^{{commit}}") if pb.SETTINGS_TAG in tags else None
    if blob_head is None or blob_head != blob_tag:
        why.append("phase_b.py at HEAD differs from the phase-b-settings tag (or cannot be read).")
    manifests: dict[str, dict] = {}
    for cid in pb.CANDIDATES:
        mp = manifest_path(root, cid)
        md, js = pb.output_paths(cid, out_dir)
        if not mp.exists():
            why.append(f"{cid}: evidence manifest {mp.name} is missing.")
            continue
        m = _read_json(mp, why, f"{cid} manifest")
        if m is None:
            continue
        manifests[cid] = m
        if m.get("schema") != MANIFEST_SCHEMA or m.get("candidate") != cid:
            why.append(f"{cid}: manifest has the wrong schema or candidate.")
            continue
        for p in (md, js):
            if m.get("files", {}).get(p.name) != (sha256_file(p) if p.exists() else None):
                why.append(
                    f"{cid}: {p.name} does not match the sha256 in its manifest (changed after commit)."
                )
        if m.get("split_sha256") != split_sha:
            why.append(f"{cid}: manifest split hash differs.")
        for t, info in tags.items():
            if m.get("tags", {}).get(t) != info["tag_object"]:
                why.append(f"{cid}: manifest tag object for {t} differs.")
        if m.get("ledger_row") not in ltext.splitlines():
            why.append(f"{cid}: manifest ledger row is not in the ledger.")
        rels = [f"{EVIDENCE_REL}/{p.name}" for p in (md, js)] + [f"{EVIDENCE_REL}/{mp.name}"]
        c = _add_commit(git, rels[2])
        if c is None:
            why.append(f"{cid}: manifest {mp.name} is not committed.")
            continue
        rc, shown = git(("show", "--name-only", "--format=", c))
        files = set(shown.split())
        for rel in [*rels, LEDGER_REL]:
            if rel not in files:
                why.append(
                    f"{cid}: commit {c[:9]} does not contain {rel}; outputs were not committed together."
                )
        for rel in rels[:2]:
            rc, lg = git(("log", "--format=%H", "--", rel))
            if lg.split() != [c]:
                why.append(f"{cid}: {rel} was changed after its evidence commit.")
        rc, _ = git(("merge-base", "--is-ancestor", c, "HEAD"))
        if rc != 0:
            why.append(f"{cid}: its evidence commit is not an ancestor of HEAD.")
        cc = str(results.get(cid, {}).get("manifest", {}).get("code_commit", "")).strip()
        if cc and _blob(git, cc) != blob_tag:
            why.append(f"{cid}: phase_b.py at its run commit {cc} differs from the settings tag.")
        commits[cid] = c
    # each candidate's outputs committed before the next candidate ran (order of ledger rows)
    order = sorted(
        (i for cid in pb.CANDIDATES for i, _ in ledger_rows(ltext, pb.LEDGER_MARKER.format(cid=cid))[:1])
    )
    by_line = {}
    for cid in pb.CANDIDATES:
        r = ledger_rows(ltext, pb.LEDGER_MARKER.format(cid=cid))
        if r:
            by_line[r[0][0]] = cid
    seq = [by_line[i] for i in order if by_line.get(i) in commits]
    for a, b in itertools.pairwise(seq):
        if commits[a] == commits[b]:
            why.append(
                f"{a} and {b} were committed together; each candidate must be committed before the next run."
            )
            continue
        rc, _ = git(("merge-base", "--is-ancestor", commits[a], commits[b]))
        if rc != 0:
            why.append(f"{a}'s evidence commit is not before {b}'s.")
    # time order of manifests
    stamps = [m.get("written_at_ist") for m in manifests.values()]
    try:
        newest = max(datetime.fromisoformat(s) for s in stamps if s)
        if newest > now_ist:
            why.append("A manifest is dated in the future.")
    except ValueError:
        why.append("A manifest has an unreadable timestamp.")

    if why or len(results) != len(pb.CANDIDATES):
        return plan

    sel = select_outcome(results)
    rc, head = git(("rev-parse", "HEAD"))
    cands = {}
    for cid, r in sorted(results.items()):
        md, js = pb.output_paths(cid, out_dir)
        ledger_rows(ltext, pb.LEDGER_MARKER.format(cid=cid))
        cands[cid] = {
            "name": r["candidate"]["name"],
            "survives": r["survives"],
            "pass_rows": {c["id"]: c["label"] for c in r["checks"]},
            "B1_B2_B3_rule_rows": {
                "beats_every_stock_and_momentum": check_value(r, "phase_b_beats_every_stock_and_momentum")[
                    "label"
                ],
                "reject_set": check_value(r, "reject_set")["label"],
            },
            "figures": {n: _dig(r, p) for n, p in LADDER},
            "avg_net_every_stock": _dig(r, ("trade_level", "every_stock", "avg_net")),
            "avg_net_momentum": _dig(r, ("trade_level", "momentum", "avg_net")),
            "ideas": _dig(r, ("trade_level", "candidate", "ideas")),
            "days": _dig(r, ("trade_level", "candidate", "days")),
            "code_commit_run": r["manifest"]["code_commit"],
            "evidence_commit": commits[cid],
            "ledger_marker": pb.LEDGER_MARKER.format(cid=cid),
            "result_files": {md.name: sha256_file(md), js.name: sha256_file(js)},
            "manifest_file": manifest_path(root, cid).name,
            "manifest_sha256": sha256_file(manifest_path(root, cid)),
        }
    man_hashes = {c: v["manifest_sha256"] for c, v in cands.items()}
    first = next(iter(results.values()))
    plan.result = {
        "schema": SCHEMA,
        "outcome": sel["outcome"],
        "survivor": sel["survivor"],
        "selection": sel,
        "written_at_ist": now_ist.isoformat(timespec="seconds"),
        "deadline_ist": "2026-12-04T23:59:59+05:30",
        "code_commit_finish": head.strip(),
        "protocol": f"{pb.PROTOCOL_ID} v{pb.PROTOCOL_VERSION}",
        "defs_version": pb.DEFS_VERSION,
        "tags": tags,
        "split": {"file": f"{SPLIT_REL}/{pb.SPLIT_FILE}", "sha256": split_sha},
        "window": [pb.DEV_START.isoformat(), pb.DEV_END.isoformat()],
        "counts": {
            "candidates": len(results),
            "survivors": len(sel["survivors"]),
            "trading_days": first["trading_days"],
            "folds": first["folds"],
        },
        "candidates": cands,
        "evidence_manifest": {
            "per_candidate_sha256": man_hashes,
            "combined_sha256": sha256_bytes(dumps(man_hashes).encode("utf-8")),
        },
        "ledger": {"result_row_marker": RESULT_MARKER},
        "wf_protocol_v2_expected": sel["outcome"] == "SURVIVOR_SELECTED",
    }
    plan.result_text = dumps(plan.result)
    digest = sha256_bytes(plan.result_text.encode("utf-8"))
    label = sel["outcome"] if not sel["survivor"] else f"{sel['outcome']}: {sel['survivor']}"
    nxt = (
        "Decision review in December; lab may start from 2026-12-05 subject to Amendment 3, evidence and "
        "readiness gates; no automatic promotion"
        if not sel["survivor"]
        else "wf-protocol-v2 lock by 2026-12-04 (separate owner step)"
    )
    plan.ledger_row = (
        f"| {pb.DEV_START.isoformat()} to {pb.DEV_END.isoformat()} (49 stocks; reject set of 129) | "
        f"{RESULT_MARKER}: {label}. No data looked at beyond B1, B2, B3 | Recorded only; {nxt} | "
        f"{today.isoformat()} | `phase_b/{RESULT_NAME}` sha256 {digest} |"
    )
    plan.commands = commands_for(plan.result, digest, today)
    return plan


def commands_for(result: Mapping, digest: str, today: date) -> list[str]:
    outcome = result["outcome"]
    survivor = result["survivor"] or "none"
    cmds = [
        f"git add {EVIDENCE_REL}/{RESULT_NAME} {LEDGER_REL}",
        f'git commit -m "Phase B result: {outcome} ({survivor})"',
        (
            f'git tag -a {RESULT_TAG} -m "outcome={outcome}" -m "survivor={survivor}" '
            f'-m "result_sha256={digest}" -m "ledger_row={RESULT_MARKER}" '
            f'-m "written_at_ist={result["written_at_ist"]}"'
        ),
    ]
    if outcome == "SURVIVOR_SELECTED":  # NEVER printed for NO_SURVIVOR
        cmds.append(
            f"# then, by the owner, only after the tag above: git tag -a {WF_TAG} {RESULT_TAG} "
            f'-m "survivor={survivor}" -m "result_tag={RESULT_TAG}"'
        )
    return cmds


# ------------------------------------------------------------------ writing


def insert_ledger_row(text: str, row: str) -> str:
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## Local data"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    last = max(i for i in range(start, end) if lines[i].startswith("|"))
    lines.insert(last + 1, row)
    return "\n".join(lines) + "\n"


def apply_plan(root: Path, plan: Plan) -> None:
    assert plan.ok and plan.result_text is not None and plan.ledger_row is not None
    rp = root / EVIDENCE_REL / RESULT_NAME
    lp = root / LEDGER_REL
    old = lp.read_bytes()
    try:
        rp.write_text(plan.result_text, encoding="utf-8", newline="\n")
        new = insert_ledger_row(old.decode("utf-8"), plan.ledger_row)
        lp.write_text(new, encoding="utf-8", newline="\n")
        if sha256_file(rp) != sha256_bytes(plan.result_text.encode("utf-8")):
            raise OSError("record hash mismatch after writing")
        if plan.ledger_row not in lp.read_text(encoding="utf-8").splitlines():
            raise OSError("ledger row missing after writing")
    except Exception:
        lp.write_bytes(old)
        rp.unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------ command line


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    git: GitFn | None = None,
    now_fn: NowFn | None = None,
    out=None,
) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="phase_b_finish", description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    ap.add_argument(
        "--manifest", choices=sorted(pb.CANDIDATES), help="write one candidate's evidence manifest"
    )
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    def say(s: str = "") -> None:
        print(s, file=out)

    if root is None:
        root = args.root or Path(__file__).resolve().parents[5]
    git = git or make_git(root)
    now = (now_fn or (lambda: datetime.now(UTC)))()

    if args.manifest:
        m, why = build_candidate_manifest(root, args.manifest, git, now)
        if why:
            say("REFUSED, nothing written:")
            for w in why:
                say(f"- {w}")
            return 2
        text = dumps(m)
        if not args.apply:
            say(f"DRY RUN: would write {manifest_path(root, args.manifest).name}\n{text}")
            return 0
        manifest_path(root, args.manifest).write_text(text, encoding="utf-8", newline="\n")
        say(f"Wrote {manifest_path(root, args.manifest)}")
        say("Now commit this candidate's md, json, MANIFEST and ledger row together, before the next run:")
        say(f"git add {EVIDENCE_REL} {LEDGER_REL}")
        say(f'git commit -m "Phase B {args.manifest}: result and evidence manifest"')
        return 0

    plan = prepare(root, git, now)
    if not plan.ok:
        say("REFUSED, nothing written:")
        for w in plan.reasons:
            say(f"- {w}")
        return 2
    say(f"Outcome: {plan.result['outcome']}  survivor: {plan.result['survivor']}")
    say(f"Ranking basis: {json.dumps(plan.result['selection']['ranking'])}")
    if not args.apply:
        say("DRY RUN: nothing written. Would write:")
        say(f"- {EVIDENCE_REL}/{RESULT_NAME}")
        say(f"- one ledger row: {plan.ledger_row}")
        return 0
    apply_plan(root, plan)
    say("Wrote the record and one ledger row. Now, by the owner (this tool never commits or tags):")
    for c in plan.commands:
        say(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
