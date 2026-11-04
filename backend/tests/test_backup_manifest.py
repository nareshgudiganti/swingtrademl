"""Pure tests (no database) for the backup manifest and the restore-drill comparison."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
from pathlib import Path

from swing_trade_ml.ml import backup_manifest as bm


def _rows(tmp: Path):
    (tmp / "a_v1.joblib").write_bytes(b"alpha")
    (tmp / "b_v1.joblib").write_bytes(b"bravo")
    (tmp / "brain_meta_v1.joblib").write_bytes(b"meta")
    (tmp / "brain_meta_v1.json").write_bytes(b"{}")
    (tmp / "random.txt").write_bytes(b"ignored")
    return [
        {"id": 1, "name": "a", "version": "v1", "status": "ACTIVE", "artifact_path": "/app/data/models/a_v1.joblib"},
        {"id": 2, "name": "b", "version": "v1", "status": "TRAINED", "artifact_path": "C:\\x\\models\\b_v1.joblib"},
        {"id": 3, "name": "gone", "version": "v1", "status": "TRAINED", "artifact_path": "/app/data/models/gone_v1.joblib"},
    ]


def test_file_name_of_handles_both_path_styles():
    assert bm.file_name_of("/app/data/models/x.joblib") == "x.joblib"
    assert bm.file_name_of("D:\\m\\x.joblib") == "x.joblib"
    assert bm.file_name_of(None) is None


def test_manifest_records_sha_size_missing_and_brain_meta(tmp_path):
    manifest = bm.build_manifest(_rows(tmp_path), tmp_path)
    by = {m["name"]: m for m in manifest["models"]}
    assert by["a"]["sha256"] == hashlib.sha256(b"alpha").hexdigest()
    assert by["a"]["size"] == 5 and not by["a"]["missing"]
    assert by["b"]["missing"] is False  # found by file name in the model folder
    assert by["gone"]["missing"] is True and by["gone"]["sha256"] is None
    assert [e["file"] for e in manifest["extra_files"]] == ["brain_meta_v1.joblib", "brain_meta_v1.json"]


def _good(tmp_path):
    rows = _rows(tmp_path)[:2]
    manifest = bm.build_manifest(rows, tmp_path)
    files = {k: v for k, v in bm.hash_folder(tmp_path).items() if k != "random.txt"}
    return manifest, rows, files


def test_compare_passes_when_everything_matches(tmp_path):
    manifest, rows, files = _good(tmp_path)
    report = bm.compare(manifest, rows, files)
    assert report["ok"] and report["files_verified"] == 4 and report["problems"] == []


def test_compare_flags_hash_mismatch_missing_and_orphan(tmp_path):
    manifest, rows, files = _good(tmp_path)
    files["a_v1.joblib"] = ("0" * 64, 5)
    del files["b_v1.joblib"]
    files["stray.joblib"] = ("1" * 64, 1)
    report = bm.compare(manifest, rows, files)
    assert not report["ok"]
    assert report["problem_counts"] == {"hash_mismatch": 1, "missing_file": 1, "orphan_file": 1}


def test_compare_flags_registry_disagreement(tmp_path):
    manifest, rows, files = _good(tmp_path)
    restored = [dict(rows[0], status="ARCHIVED"), {"id": 9, "name": "new", "version": "v1", "status": "TRAINED", "artifact_path": "/x/new.joblib"}]
    report = bm.compare(manifest, restored, files)
    kinds = report["problem_counts"]
    assert kinds["field_diff"] == 1  # a: status changed
    assert kinds["row_not_in_manifest"] == 1  # new
    assert kinds["manifest_not_in_db"] == 1  # b


def test_compare_reports_file_lost_before_backup(tmp_path):
    rows = _rows(tmp_path)
    manifest = bm.build_manifest(rows, tmp_path)
    files = {k: v for k, v in bm.hash_folder(tmp_path).items() if k != "random.txt"}
    report = bm.compare(manifest, rows, files)
    assert report["problem_counts"] == {"missing_at_source": 1}


def test_dump_lines_takes_only_app_section_of_a_dumpall(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts" / "verify_restore.py"
    spec = importlib.util.spec_from_file_location("verify_restore", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = (
        "-- PostgreSQL database cluster dump\nCREATE ROLE x;\n\\connect postgres\nSELECT 'other';\n"
        "CREATE DATABASE swing_trade_ml;\n\\connect swing_trade_ml\nSELECT 'app';\n\\connect template1\nSELECT 'x';\n"
    )
    f = tmp_path / "database.sql.gz"
    f.write_bytes(gzip.compress(text.encode()))
    assert list(mod.dump_lines(f, "swing_trade_ml")) == ["SELECT 'app';\n"]
    plain = tmp_path / "database.sql"
    plain.write_bytes(b"-- PostgreSQL database dump\nSELECT 1;\n")
    assert list(mod.dump_lines(plain, "swing_trade_ml")) == ["-- PostgreSQL database dump\n", "SELECT 1;\n"]
