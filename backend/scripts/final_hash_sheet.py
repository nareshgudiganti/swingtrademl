"""FINAL HASH SHEET for the sector candidates SX5 / SX10. Deterministic, read-only, DB-free, fits NO model.

  python scripts/final_hash_sheet.py <FULL 40-hex commit> [--out sheet.json] [--protocol LABEL=PATH ...]

Refuses to run unless
  * the commit argument is the full 40-hex string AND equals `git rev-parse HEAD` of this repository, and
  * the working tree is clean (no modified and no untracked file).
So the sheet always names a commit that contains exactly the files that were hashed. The FINAL commit can only be
fixed after every other change (protocol drafts, registry, harness) is committed; regenerate the sheet at that point.

What it prints (JSON, sorted keys):
  feature manifests of A_53 / R_37 / C_56 with BOTH column-list hashes
    feature_list_sha256  = the harness canonical form (sector_walkforward.feature_list_sha256): the one the harness
                           records, the holdout registry and the approval file bind.  <- the one named in the signed text
    manifest_sha256      = sha256(json.dumps(list(columns))) with Python's default separators; human cross-reference.
  per candidate: row-list hashes (committed row-list file), DatasetSpec config sha256, harness config sha256, fold
  definition sha256 (dev+holdout and dev-only), exclusion file + keys sha256, events input sha256;
  the recipe (sx_recipe) sha256 with its library versions; the dependency environment (python, platform, tracked
  library versions, sha256 of the sorted `pip freeze` output); protocol-file sha256 (TO_BE_FILLED_AT_SIGNING
  unless a --protocol LABEL=PATH is given). The matrix hash (dataset_sha256) needs the database build and is carried
  from --prior-sheet when given, labelled as carried.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sector_walkforward as wf
from swing_trade_ml.ml import sx_recipe
from swing_trade_ml.ml.sector_reconcile import keys_sha256

REPO = Path(__file__).resolve().parents[2]
EVID_REL = "docs/brain/evidence/sector_prep"
STOCK_SPLIT_REL = "docs/brain/evidence/stock_split/stock_split_ev15.json"
CUTOFF = date(2026, 12, 31)
SCHEMA = "final_hash_sheet_v1"
PLACEHOLDER = "TO_BE_FILLED_AT_SIGNING"
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class SheetRefused(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------ small hashes
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def plain_manifest_sha256(columns) -> str:
    """Human-checkable cross-reference: sha256 of json.dumps(list) with Python's DEFAULT separators (', ' and ': ')."""
    return hashlib.sha256(json.dumps(list(columns)).encode("utf-8")).hexdigest()


def canonical_feature_list_sha256(columns) -> str:
    """Independent re-implementation of the harness form: compact separators, sort_keys, UTF-8, ensure_ascii."""
    return hashlib.sha256(
        json.dumps(list(columns), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ------------------------------------------------------------------------------------------ git guard
def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SheetRefused(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def check_commit_and_clean(repo: Path, commit: str) -> str:
    if not HEX40.match(commit or ""):
        raise SheetRefused("the commit must be the FULL 40-character lowercase hex string")
    head = _git(repo, "rev-parse", "HEAD").strip()
    if head != commit:
        raise SheetRefused(f"commit argument {commit} is not the repository HEAD {head}")
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=all").strip()
    if dirty:
        raise SheetRefused(
            "the working tree is not clean (commit or remove these first):\n"
            + "\n".join(dirty.splitlines()[:20])
        )
    return head


# ------------------------------------------------------------------------------------------ environment
def pip_freeze_lines() -> tuple[list[str], str]:
    r = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, check=False)
    if r.returncode == 0 and r.stdout.strip():
        return sorted(ln.strip() for ln in r.stdout.splitlines() if ln.strip()), "pip freeze"
    from importlib import metadata

    lines = sorted(f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions())
    return lines, "importlib.metadata (pip not available)"


def project_version(repo: Path) -> str | None:
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (repo / "backend" / "pyproject.toml").read_text("utf-8"))
    return m.group(1) if m else None


def environment(repo: Path) -> dict:
    lines, source = pip_freeze_lines()
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "tracked_library_versions": sx_recipe.installed_versions(),
        "project_version": project_version(repo),
        "pip_freeze_source": source,
        "pip_freeze_lines": len(lines),
        "pip_freeze_sorted_sha256": sha256_bytes("\n".join(lines).encode("utf-8")),
        "venv_convention": "<repo>/backend/.venv",
        "note": "bit-identical predictions are NOT guaranteed across platforms / CPU / library builds",
    }


# ------------------------------------------------------------------------------------------ pieces
def manifests() -> dict:
    out = {}
    for arm, cols in wf.build_arms().items():
        out[arm] = {
            "n_columns": len(cols),
            "columns": list(cols),
            "feature_list_sha256": wf.feature_list_sha256(cols),
            "manifest_sha256": plain_manifest_sha256(cols),
        }
        if out[arm]["feature_list_sha256"] != canonical_feature_list_sha256(
            cols
        ):  # two implementations agree
            raise SheetRefused(f"{arm}: harness hash differs from the independent re-computation")
    return out


def read_rowlist(path: Path) -> list[str]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return [ln for ln in fh.read().split("\n") if ln]


def dataset_spec(candidate: str, symbols, exclusions_csv: Path) -> sr.DatasetSpec:
    h = sr.CANDIDATE_HORIZON[candidate]
    kind, target, stop = sr.PROTOCOL_LABELS[candidate]
    return sr.DatasetSpec(
        candidate=candidate,
        symbols=tuple(symbols),
        horizon_days=h,
        target_return=target,
        stop_return=stop,
        label_kind=kind,
        data_cutoff=CUTOFF,
        exclusions=sr.load_exclusions_csv(exclusions_csv),
    )


def harness_config(embargo: int, seed: int = wf.PINNED_SEED, min_train_rows: int = wf.MIN_TRAIN_ROWS) -> dict:
    """Identical to the dict run_walkforward hashes (net_fn False: no cost model in the pre-registered run)."""
    return {
        "harness": wf.HARNESS_VERSION,
        "top_k": wf.TOP_K,
        "min_stocks": wf.MIN_STOCKS,
        "random_draws": wf.RANDOM_DRAWS,
        "random_seed": wf.RANDOM_SEED,
        "min_train_rows": min_train_rows,
        "embargo": embargo,
        "seed": seed,
        "net_fn": False,
    }


def candidate_block(candidate: str, repo: Path, symbols, rowlist_name: str, prior: dict | None) -> dict:
    evid = repo / EVID_REL
    h = sr.CANDIDATE_HORIZON[candidate]
    ex_csv = evid / f"excluded_rows_h{h}_v2.csv"
    spec = dataset_spec(candidate, symbols, ex_csv)
    keys = read_rowlist(evid / rowlist_name)
    ex_keys = sorted(f"{s}|{d}" for s, d in spec.exclusions)
    hcfg = harness_config(embargo=h)
    folds_full = wf.default_folds(include_holdout=True)
    folds_dev = wf.default_folds(include_holdout=False)
    events = evid / "events_input_v2.csv"
    block = {
        "horizon_days": h,
        "rows": len(keys),
        "rowlist_file": f"{EVID_REL}/{rowlist_name}",
        "rowlist_file_gz_sha256": sha256_file(evid / rowlist_name),
        "rowlist_text_sha256 (decompressed, as written)": sha256_bytes(
            ("\n".join(keys) + "\n").encode("utf-8")
        ),
        "dataset_rowlist_sha256 (keys_sha256: sorted SYMBOL|YYYY-MM-DD, newline separated)": keys_sha256(
            keys
        ),
        "datasetspec_config_sha256": spec.config_sha256(),
        "n_symbols": len(spec.symbols),
        "data_cutoff": CUTOFF.isoformat(),
        "harness_config": hcfg,
        "harness_config_sha256": hashlib.sha256(
            json.dumps(hcfg, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "fold_definition_sha256_dev_and_holdout (the one bound for a holdout run)": wf.folds_sha256(
            folds_full, h, h
        ),
        "fold_definition_sha256_dev_only": wf.folds_sha256(folds_dev, h, h),
        "exclusion_file": f"{EVID_REL}/{ex_csv.name}",
        "exclusion_file_sha256": sha256_file(ex_csv),
        "exclusion_rows": len(ex_keys),
        "exclusion_keys_sha256": keys_sha256(ex_keys),
        "events_input_file": f"{EVID_REL}/{events.name}",
        "events_input_sha256": sha256_file(events),
        "dataset_matrix_sha256": None,
        "dataset_matrix_sha256_status": "needs the database build (sr.matrix_sha256 of the assembled matrix); not recomputed here",
    }
    if prior and candidate in prior.get("candidates", {}):
        carried = prior["candidates"][candidate]
        for k, v in carried.items():
            if k.startswith("dataset_matrix_sha256"):
                block["dataset_matrix_sha256"] = v
                block["dataset_matrix_sha256_status"] = "CARRIED from --prior-sheet, not recomputed here"
    return block


def used_symbols(repo: Path) -> list[str]:
    used = json.loads((repo / STOCK_SPLIT_REL).read_text("utf-8"))["used_49"]
    return [s for s in used if sf.resolve_sector_index(s) is not None]


def build_sheet(
    repo: Path,
    commit: str,
    *,
    protocols: dict[str, Path] | None = None,
    prior: dict | None = None,
    symbols=None,
    rowlists: dict[str, str] | None = None,
) -> dict:
    rowlists = rowlists or {"SX5": "sx5_47_rows_v3.txt.gz", "SX10": "sx10_47_rows_v3.txt.gz"}
    syms = list(symbols) if symbols is not None else used_symbols(repo)
    recipe = sx_recipe.SXRecipe()
    protocol_hashes = {
        "SX5_protocol": PLACEHOLDER,
        "SX10_protocol": PLACEHOLDER,
        "recipe_document": PLACEHOLDER,
        "authorisation_text": PLACEHOLDER,
    }
    for label, p in (protocols or {}).items():
        protocol_hashes[label] = sha256_file(Path(p))
    return {
        "schema": SCHEMA,
        "commit": commit,
        "status": "UNSIGNED. Computed without the database; nothing trained.",
        "hash_convention": {
            "named_in_signed_text": "feature_list_sha256 (harness canonical form)",
            "algorithm": 'sha256( json.dumps(list(columns), sort_keys=True, separators=(",", ":")).encode("utf-8") ).hexdigest()',
            "cross_reference_only": "manifest_sha256 = sha256( json.dumps(list(columns)).encode('utf-8') )",
        },
        "environment": environment(repo),
        "recipe": {
            "recipe_version": recipe.recipe_version,
            "sx_recipe_sha256": recipe.sha256(),
            "library_versions": recipe.versions,
            "canonical_json": recipe.canonical_json(),
        },
        "arms": manifests(),
        "candidates": {c: candidate_block(c, repo, syms, rowlists[c], prior) for c in ("SX5", "SX10")},
        "protocol_file_sha256": protocol_hashes,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("commit", help="the FULL 40-hex commit; must equal `git rev-parse HEAD`")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--out", default=None, help="write the JSON here as well as printing it")
    ap.add_argument("--protocol", action="append", default=[], metavar="LABEL=PATH")
    ap.add_argument(
        "--prior-sheet", default=None, help="an earlier sheet to carry dataset_matrix_sha256 from"
    )
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    try:
        check_commit_and_clean(repo, a.commit)
        protos = dict(p.split("=", 1) for p in a.protocol)
        prior = json.loads(Path(a.prior_sheet).read_text("utf-8")) if a.prior_sheet else None
        sheet = build_sheet(repo, a.commit, protocols={k: Path(v) for k, v in protos.items()}, prior=prior)
    except SheetRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    text = json.dumps(sheet, indent=1, sort_keys=True) + "\n"
    if a.out:
        Path(a.out).write_text(text, "utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
