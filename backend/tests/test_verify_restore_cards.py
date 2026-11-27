# ruff: noqa: E501
"""#328: the restore drill (scripts/verify_restore.py) brings back model rows, model files AND model cards, run for real.

It restores a small dump into a throwaway drill_scratch_* database on the local Docker Postgres (the script never
touches any other database and drops the scratch one afterwards), then checks every file and card. Skipped when
the local Postgres container does not answer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from swing_trade_ml.ml import backup_manifest as bm

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_restore.py"
CONTAINER = "stml-postgres"


def _postgres_answers() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        done = subprocess.run(
            ["docker", "exec", CONTAINER, "psql", "-U", "swingtrade", "-d", "postgres", "-tAc", "select 1"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and done.stdout.strip() == "1"


pytestmark = pytest.mark.skipif(not _postgres_answers(), reason="needs the local Docker Postgres container")


def _backup(tmp: Path) -> tuple[Path, Path]:
    folder = tmp / "backup"
    files = folder / "files"
    files.mkdir(parents=True)
    lab = files / "lab_v1.joblib"
    lab.write_bytes(b"lab model")
    lab_sha = hashlib.sha256(lab.read_bytes()).hexdigest()
    card = files / ("lab_v1.joblib" + bm.CARD_SUFFIX)
    card.write_text(json.dumps({"artifact_sha256": lab_sha}), encoding="utf-8")
    gen = files / "gen_v2.joblib"
    gen.write_bytes(b"general model")
    gen_sha = hashlib.sha256(gen.read_bytes()).hexdigest()
    rows = [
        {
            "id": 1,
            "name": "lab",
            "version": "v1",
            "status": "TRAINED",
            "artifact_path": "/app/data/models/lab_v1.joblib",
        },
        {
            "id": 2,
            "name": "gen",
            "version": "v2",
            "status": "ACTIVE",
            "artifact_path": "/app/data/models/gen_v2.joblib",
            "card_artifact_sha256": gen_sha,
        },
    ]
    manifest = bm.build_manifest(rows, files)
    (folder / bm.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    metrics = json.dumps({"card": {"artifact_sha256": gen_sha}})
    (folder / "database.sql").write_text(
        "-- PostgreSQL database dump\n"
        "CREATE TABLE ml_models (id integer, name text, version text, status text, artifact_path text, metrics json);\n"
        "INSERT INTO ml_models VALUES (1, 'lab', 'v1', 'TRAINED', '/app/data/models/lab_v1.joblib', '{}');\n"
        f"INSERT INTO ml_models VALUES (2, 'gen', 'v2', 'ACTIVE', '/app/data/models/gen_v2.joblib', '{metrics}');\n",
        encoding="utf-8",
    )
    return folder, card


def _drill(folder: Path, tmp: Path) -> tuple[int, dict, str]:
    out = tmp / "result.json"
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--backup-dir",
            str(folder),
            "--container",
            CONTAINER,
            "--json-out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    result = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return done.returncode, result, done.stdout + done.stderr


def test_the_drill_restores_rows_files_and_cards_and_every_card_names_its_restored_file(tmp_path):
    folder, _ = _backup(tmp_path)
    code, result, text = _drill(folder, tmp_path)
    assert code == 0, text
    cmp = result["compare"]
    assert cmp["ok"] and cmp["files_verified"] == 3 and cmp["manifest_cards"] == 1
    assert "model cards name their file (1 files; 0 differ)" in text and "OVERALL: PASS" in text
    assert "dropped" in text  # the scratch database is gone again


def test_the_drill_fails_when_a_restored_card_does_not_match(tmp_path):
    folder, card = _backup(tmp_path)
    card.write_text(json.dumps({"artifact_sha256": "0" * 64}), encoding="utf-8")  # changed after the backup
    code, result, text = _drill(folder, tmp_path)
    assert code == 1
    assert result["compare"]["problem_counts"] == {"hash_mismatch": 1}
    assert "OVERALL: FAIL" in text
