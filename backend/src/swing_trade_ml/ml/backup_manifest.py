"""A written record of every model file: what the offsite backup and the restore drill check against.

`ml/backup.py` copies the files; nothing recorded their sha256 anywhere the database could be compared to.
This module writes one JSON record (name, version, status, file name, size, sha256) for every `ml_models`
row plus the `brain_meta_v*` combiner files (which have no row), and compares a restored database and a
folder of files against that record.

The comparison part is pure standard library on purpose: `scripts/verify_restore.py` loads this file by
path and runs it on a PC without the app installed. Only `write_manifest` touches the database, and only
reads it.

Write one:  python -m swing_trade_ml.ml.backup_manifest write --out /tmp/manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

MANIFEST_NAME = "manifest.json"
FORMAT = 1
_BRAIN_META = re.compile(r"^brain_meta_v\d+\.(joblib|json)$")


def file_name_of(artifact_path: str | None) -> str | None:
    """Last path component of a stored artifact path, whether it was written on Linux or Windows."""
    if not artifact_path:
        return None
    return PureWindowsPath(artifact_path.replace("\\", "/")).name or None


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def build_manifest(
    rows: list[dict[str, Any]],
    model_dir: Path,
    now: datetime | None = None,
    resolve: Any = None,
) -> dict[str, Any]:
    """`rows`: dicts with id, name, version, status, artifact_path. A row's file is its artifact_path if that
    exists, else the same file name inside `model_dir`. A row whose file cannot be found is recorded with
    missing=True, never skipped: the gap is the finding."""
    models: list[dict[str, Any]] = []
    for row in rows:
        fname = file_name_of(row.get("artifact_path"))
        found: Path | None = None
        if row.get("artifact_path"):
            direct = Path(row["artifact_path"])
            if direct.is_file():
                found = direct
        if found is None and fname and (model_dir / fname).is_file():
            found = model_dir / fname
        if resolve is not None and found is None:
            found = resolve(row)
        entry: dict[str, Any] = {
            "id": row["id"],
            "name": row["name"],
            "version": row["version"],
            "status": row["status"],
            "file": fname,
            "size": None,
            "sha256": None,
            "missing": found is None,
        }
        if found is not None:
            entry["sha256"], entry["size"] = sha256_file(found)
        models.append(entry)

    extra: list[dict[str, Any]] = []
    if model_dir.is_dir():
        for path in sorted(model_dir.iterdir()):
            if path.is_file() and _BRAIN_META.match(path.name):
                sha, size = sha256_file(path)
                extra.append({"file": path.name, "size": size, "sha256": sha})
    return {
        "format": FORMAT,
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "models": models,
        "extra_files": extra,
    }


def hash_folder(folder: Path) -> dict[str, tuple[str, int]]:
    """{file name: (sha256, size)} for every file directly inside `folder`."""
    return {p.name: sha256_file(p) for p in sorted(folder.iterdir()) if p.is_file()} if folder.is_dir() else {}


def compare(
    manifest: dict[str, Any],
    restored_rows: list[dict[str, Any]],
    files: dict[str, tuple[str, int]],
) -> dict[str, Any]:
    """Check a restored database and a folder of files against the manifest. Returns counts and the list of
    problems; `ok` is True only when there are none.

    - hash_mismatch: file present but sha256/size differs from the manifest
    - missing_file: manifest says the file existed, the backup folder does not have it
    - missing_at_source: the manifest itself records the file as already gone when the backup was made
    - row_not_in_manifest / manifest_not_in_db: the restored table and the manifest disagree on which models exist
    - field_diff: same model (name, version) but status or file name differs
    - orphan_file: a file in the backup folder that no row or extra-file entry accounts for
    """
    problems: list[dict[str, str]] = []

    def add(kind: str, what: str) -> None:
        problems.append({"kind": kind, "what": what})

    by_key = {(m["name"], m["version"]): m for m in manifest.get("models", [])}
    db_key = {(r["name"], r["version"]): r for r in restored_rows}

    for key in sorted(set(db_key) - set(by_key)):
        add("row_not_in_manifest", f"{key[0]} {key[1]}")
    for key in sorted(set(by_key) - set(db_key)):
        add("manifest_not_in_db", f"{key[0]} {key[1]}")

    expected_files: set[str] = set()
    checked = 0
    for key in sorted(set(by_key) & set(db_key)):
        m, r = by_key[key], db_key[key]
        label = f"{key[0]} {key[1]}"
        if m.get("status") != r.get("status"):
            add("field_diff", f"{label}: status manifest={m.get('status')} database={r.get('status')}")
        db_file = file_name_of(r.get("artifact_path"))
        if m.get("file") != db_file:
            add("field_diff", f"{label}: file manifest={m.get('file')} database={db_file}")
    for m in manifest.get("models", []):
        label = f"{m['name']} {m['version']}"
        if m.get("missing") or not m.get("sha256"):
            add("missing_at_source", label)
            continue
        expected_files.add(m["file"])
        checked += _check_one(label, m, files, add)
    for e in manifest.get("extra_files", []):
        expected_files.add(e["file"])
        checked += _check_one(e["file"], e, files, add)
    for fname in sorted(set(files) - expected_files):
        add("orphan_file", fname)

    count = {k: sum(1 for p in problems if p["kind"] == k) for k in sorted({p["kind"] for p in problems})}
    return {
        "ok": not problems,
        "db_rows": len(restored_rows),
        "manifest_models": len(by_key),
        "manifest_extra_files": len(manifest.get("extra_files", [])),
        "files_in_backup": len(files),
        "files_verified": checked,
        "problem_counts": count,
        "problems": problems,
    }


def _check_one(label: str, entry: dict[str, Any], files: dict[str, tuple[str, int]], add: Any) -> int:
    got = files.get(entry["file"])
    if got is None:
        add("missing_file", f"{label}: {entry['file']}")
        return 0
    if got[0] != entry["sha256"] or got[1] != entry["size"]:
        add("hash_mismatch", f"{label}: {entry['file']}")
        return 0
    return 1


def write_manifest(out: Path) -> dict[str, Any]:
    """Read-only against the database. Imports the app lazily so the functions above stay standalone."""
    from sqlalchemy import select

    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.db.session import session_scope

    with session_scope() as db:
        rows = [
            {"id": m.id, "name": m.name, "version": m.version, "status": str(getattr(m.status, "value", m.status)), "artifact_path": m.artifact_path}
            for m in db.execute(select(MLModel).order_by(MLModel.name, MLModel.version)).scalars()
        ]
    manifest = build_manifest(rows, Path(settings.MODEL_ARTIFACT_DIR))
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write the manifest from the live registry (read-only)")
    w.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = write_manifest(args.out)
    missing = [m for m in manifest["models"] if m["missing"]]
    print(f"manifest: {len(manifest['models'])} models, {len(manifest['extra_files'])} extra files, {len(missing)} missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
