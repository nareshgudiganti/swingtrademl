"""Pure tests (no database) for the backup manifest and the restore-drill comparison."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
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


def test_model_offsite_copy_is_off_unless_the_flag_file_exists():
    """Owner decision Q11: the model upload stays disabled until the owner creates the flag file on the droplet."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2] / "infra" / "deploy" / "daily-backup.sh").read_text()
    call = script.index("backup-models-offsite.sh\" \"$stamp\"")
    gate = script.index("/root/.backup-models-enabled")
    assert gate < call, "the flag check must come before the upload call"
    assert "switched off" in script


# ---------------------------------------------------------------- #328: model cards in the backup


def _card(folder: Path, artifact: str, artifact_sha: str | None) -> Path:
    path = folder / (artifact + bm.CARD_SUFFIX)
    path.write_text(json.dumps({"artifact_sha256": artifact_sha, "card_version": 1}), encoding="utf-8")
    return path


def _carded(tmp_path):
    rows = _rows(tmp_path)[:2]
    _card(tmp_path, "a_v1.joblib", hashlib.sha256(b"alpha").hexdigest())
    rows[1]["card_artifact_sha256"] = hashlib.sha256(b"bravo").hexdigest()  # b: card kept in metrics["card"]
    manifest = bm.build_manifest(rows, tmp_path)
    files = {k: v for k, v in bm.hash_folder(tmp_path).items() if k != "random.txt"}
    return manifest, rows, files


def test_manifest_records_each_sidecar_card_with_its_checksum(tmp_path):
    manifest, _, _ = _carded(tmp_path)
    side = tmp_path / ("a_v1.joblib" + bm.CARD_SUFFIX)
    assert manifest["cards"] == [{
        "for": "a v1", "file": side.name, "size": side.stat().st_size,
        "sha256": hashlib.sha256(side.read_bytes()).hexdigest(),
        "artifact_sha256": hashlib.sha256(b"alpha").hexdigest(),
    }]
    by = {m["name"]: m for m in manifest["models"]}
    assert by["b"]["metrics_card_artifact_sha256"] == hashlib.sha256(b"bravo").hexdigest()
    assert by["a"]["metrics_card_artifact_sha256"] is None


def test_compare_passes_with_cards_and_counts_them_as_verified_files(tmp_path):
    manifest, rows, files = _carded(tmp_path)
    report = bm.compare(manifest, rows, files)
    assert report["ok"], report["problems"]
    assert report["files_verified"] == 5 and report["manifest_cards"] == 1


def test_a_card_lost_or_altered_after_backup_is_flagged(tmp_path):
    manifest, rows, files = _carded(tmp_path)
    name = "a_v1.joblib" + bm.CARD_SUFFIX
    altered = dict(files, **{name: ("f" * 64, files[name][1])})
    assert bm.compare(manifest, rows, altered)["problem_counts"] == {"hash_mismatch": 1}
    lost = {k: v for k, v in files.items() if k != name}
    assert bm.compare(manifest, rows, lost)["problem_counts"] == {"missing_file": 1}


def test_a_card_that_names_other_bytes_than_its_model_file_is_flagged(tmp_path):
    rows = _rows(tmp_path)[:2]
    _card(tmp_path, "a_v1.joblib", "0" * 64)
    manifest = bm.build_manifest(rows, tmp_path)
    files = {k: v for k, v in bm.hash_folder(tmp_path).items() if k != "random.txt"}
    report = bm.compare(manifest, rows, files)
    assert report["problem_counts"] == {"card_mismatch": 1}


def test_a_restored_metrics_card_must_name_the_restored_file(tmp_path):
    manifest, rows, files = _carded(tmp_path)
    restored = [rows[0], dict(rows[1], card_artifact_sha256="9" * 64)]
    assert bm.compare(manifest, restored, files)["problem_counts"] == {"card_mismatch": 1}


def test_a_card_file_without_a_manifest_entry_is_an_orphan(tmp_path):
    manifest, rows, files = _good(tmp_path)
    files["zz_v1.joblib" + bm.CARD_SUFFIX] = ("2" * 64, 3)
    assert bm.compare(manifest, rows, files)["problem_counts"] == {"orphan_file": 1}


def test_an_older_manifest_without_cards_still_compares(tmp_path):
    manifest, rows, files = _good(tmp_path)
    manifest.pop("cards", None)
    for m in manifest["models"]:
        m.pop("metrics_card_artifact_sha256", None)
    assert bm.compare(manifest, rows, files)["ok"]


def test_the_offsite_upload_list_includes_cards():
    infra = Path(__file__).resolve().parents[2] / "infra" / "deploy"
    script = (infra / "backup-models-offsite.sh").read_text()
    assert 'm.get("cards", [])' in script
