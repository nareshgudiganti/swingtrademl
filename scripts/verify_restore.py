#!/usr/bin/env python
"""Restore drill for database records AND model files (owner request, offsite backup).

Given a backup folder:
    manifest.json            written by swing_trade_ml.ml.backup_manifest at backup time
    database.sql[.gz]        a pg_dump or pg_dumpall of the app database
    files/                   the model files (and brain_meta_v* files) named as in the manifest
this script
  1. restores the dump into a SCRATCH database (drill_scratch_<timestamp>) on a local Docker Postgres,
  2. recomputes the sha256 of every file and compares it with the manifest,
  3. compares the restored ml_models rows with the manifest and the files (every row has a file, every
     file has a row, version and status as recorded),
  4. prints a PASS/FAIL table, drops the scratch database (also on failure) and exits 0 / 1.

Safety: it only ever runs SQL inside a database whose name starts with drill_scratch_, except "select 1",
"create database drill_scratch_*" and "drop database drill_scratch_*" on the maintenance database. It never
connects to the app database. No credentials are read: it talks to the container with `docker exec`
(local socket), so it needs Docker and a running Postgres container, nothing else.

    python scripts/verify_restore.py --backup-dir <folder> [--container stml-postgres] [--db-user swingtrade]
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PREFIX = "drill_scratch_"
APP_DB = "swing_trade_ml"
KEY_TABLES = ["instruments", "candles", "positions", "trades", "orders", "signals", "brain_runs",
              "brain_decisions", "ml_models", "users", "portfolio_snapshots"]
HARMLESS = ("already exists", "must be owner of extension", "role \"")  # roles of the source server may not exist here


def _load_manifest_module():
    path = Path(__file__).resolve().parents[1] / "backend" / "src" / "swing_trade_ml" / "ml" / "backup_manifest.py"
    spec = importlib.util.spec_from_file_location("backup_manifest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["backup_manifest"] = module  # dataclass-free, but keeps the loader happy
    spec.loader.exec_module(module)
    return module


class Pg:
    """psql inside a container over the local socket."""

    def __init__(self, container: str, user: str):
        self.base = ["docker", "exec", container, "psql", "-U", user, "-X", "-q"]

    def sql(self, db: str, statement: str, timeout: int = 600) -> str:
        done = subprocess.run(self.base + ["-d", db, "-v", "ON_ERROR_STOP=1", "-tAc", statement],
                              capture_output=True, text=True, timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError(f"psql failed in {db}: {done.stderr.strip()[:400]}")
        return done.stdout.strip()

    def restore(self, db: str, lines) -> list[str]:
        """Feed SQL text lines to psql (errors do not stop it). Returns the ERROR lines."""
        proc = subprocess.Popen(
            ["docker", "exec", "-i"] + self.base[2:] + ["-d", db, "-v", "ON_ERROR_STOP=0", "-f", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        errors: list[str] = []
        reader = threading.Thread(target=lambda: errors.extend(
            ln.decode("utf-8", "replace").rstrip() for ln in proc.stderr), daemon=True)
        reader.start()
        for line in lines:
            proc.stdin.write(line.encode("utf-8"))
        proc.stdin.close()
        proc.wait()
        reader.join(10)
        return [e for e in errors if "ERROR:" in e]


def dump_lines(path: Path, app_db: str):
    """Text lines of the dump. For a pg_dumpall (header says 'database cluster dump'), only the app
    database's section (between its connect line and the next one); a plain pg_dump is passed through.
    Connect and CREATE/ALTER DATABASE lines are dropped so nothing can leave the scratch database."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        first = [line for _, line in zip(range(15), handle)]
    is_all = any("database cluster dump" in h for h in first)
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        in_app = not is_all
        for line in handle:
            if line.startswith("\\connect "):
                in_app = line.split()[1].strip('"') == app_db
                continue
            if line.startswith(("CREATE DATABASE", "ALTER DATABASE", "DROP DATABASE")):
                continue
            if in_app:
                yield line


def find_dump(folder: Path) -> Path:
    for name in ("database.sql.gz", "database.sql"):
        if (folder / name).is_file():
            return folder / name
    found = sorted(folder.glob("database*.sql*"))
    if not found:
        raise RuntimeError(f"no database.sql[.gz] in {folder}")
    return found[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore drill: database + model files + registry")
    ap.add_argument("--backup-dir", required=True, type=Path)
    ap.add_argument("--container", default="stml-postgres")
    ap.add_argument("--db-user", default="swingtrade")
    ap.add_argument("--app-db", default=APP_DB, help="name of the app database inside a pg_dumpall")
    ap.add_argument("--json-out", type=Path, help="also write the result as JSON")
    args = ap.parse_args()

    bm = _load_manifest_module()
    folder = args.backup_dir
    manifest_path = folder / bm.MANIFEST_NAME
    if not manifest_path.is_file():
        print(f"FAIL: no {bm.MANIFEST_NAME} in {folder}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dump = find_dump(folder)

    pg = Pg(args.container, args.db_user)
    t0 = time.time()
    try:
        # Liveness: a real query, with a 15 s limit (a port check proves nothing).
        subprocess.run(pg.base + ["-d", "postgres", "-tAc", "select 1"], capture_output=True, text=True,
                       timeout=15, check=True)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: Postgres in container '{args.container}' did not answer SELECT 1 within 15 s ({exc})",
              file=sys.stderr)
        return 1

    scratch = PREFIX + datetime.now().strftime("%Y%m%d_%H%M%S")
    assert scratch.startswith(PREFIX)
    result: dict = {"scratch": scratch, "dump": str(dump)}
    created = False
    try:
        pg.sql("postgres", f"create database {scratch} template template0")
        created = True
        try:
            pg.sql(scratch, "create extension if not exists timescaledb", timeout=60)
            pg.sql(scratch, "select timescaledb_pre_restore()", timeout=60)
            timescale = True
        except RuntimeError:
            timescale = False
        errors = pg.restore(scratch, dump_lines(dump, args.app_db))
        if timescale:
            pg.sql(scratch, "select timescaledb_post_restore()", timeout=120)
        real_errors = [e for e in errors if not any(h in e for h in HARMLESS)]
        restore_seconds = time.time() - t0

        tables = {}
        for t in KEY_TABLES:
            try:
                tables[t] = int(pg.sql(scratch, f"select count(*) from {t}"))
            except RuntimeError:
                tables[t] = None
        raw = pg.sql(scratch, "select coalesce(json_agg(row_to_json(t)), '[]') from "
                              "(select id, name, version, status, artifact_path from ml_models order by id) t")
        rows = json.loads(raw)
        files = bm.hash_folder(folder / "files")
        cmp = bm.compare(manifest, rows, files)
        result.update(compare=cmp, tables=tables, restore_errors=len(real_errors), seconds=round(restore_seconds, 1))
        db_ok = len(real_errors) == 0 and tables.get("ml_models") is not None
        ok = db_ok and cmp["ok"]

        print(f"\nBackup folder : {folder}")
        print(f"Dump          : {dump.name} -> scratch database {scratch}")
        print(f"Restore time  : {restore_seconds:.1f} s   restore errors (non-trivial): {len(real_errors)}")
        for e in real_errors[:5]:
            print("   ", e[:200])
        print(f"\n{'TABLE':<22}{'ROWS':>12}")
        for t, n in tables.items():
            print(f"{t:<22}{('MISSING' if n is None else n):>12}")
        print(f"\n{'CHECK':<44}{'RESULT':>10}")
        c = cmp["problem_counts"]

        def n(*kinds: str) -> int:
            return sum(c.get(k, 0) for k in kinds)

        expected = cmp["manifest_models"] - n("missing_at_source") + cmp["manifest_extra_files"]
        lines = [
            ("database restored (no real errors)", db_ok),
            (f"ml_models rows restored ({cmp['db_rows']})", tables.get("ml_models") is not None),
            (f"files hash-verified ({cmp['files_verified']} of {expected})", cmp["files_verified"] == expected),
            (f"sha256 mismatches ({n('hash_mismatch')})", n("hash_mismatch") == 0),
            (f"rows with no file ({n('missing_file', 'missing_at_source')})", n("missing_file", "missing_at_source") == 0),
            (f"files with no row / orphans ({n('orphan_file')})", n("orphan_file") == 0),
            (f"manifest vs database rows ({n('row_not_in_manifest', 'manifest_not_in_db')} differ)",
             n("row_not_in_manifest", "manifest_not_in_db") == 0),
            (f"status/version/file name as recorded ({n('field_diff')} differ)", n("field_diff") == 0),
        ]
        for label, good in lines:
            print(f"{label:<44}{'PASS' if good else 'FAIL':>10}")
        for p in cmp["problems"][:40]:
            print(f"   {p['kind']}: {p['what']}")
        if len(cmp["problems"]) > 40:
            print(f"   ... {len(cmp['problems']) - 40} more")
        print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
        result["ok"] = ok
        if args.json_out:
            args.json_out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if created and scratch.startswith(PREFIX):
            try:
                pg.sql("postgres", f"drop database if exists {scratch} with (force)")
                print(f"(scratch database {scratch} dropped)")
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: could not drop {scratch}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
