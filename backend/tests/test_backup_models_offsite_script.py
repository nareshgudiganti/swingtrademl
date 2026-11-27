# ruff: noqa: E501
"""#328: infra/deploy/backup-models-offsite.sh uploads model cards with the model files, run for real under bash.

Stand-in docker/rclone/openssl/python3 as in test_daily_backup_script.py: docker hands out a manifest and files from
a temp folder, rclone copies into a temp "remote", openssl "encrypts" by copying. Each card must arrive once, under
its sha256, byte-identical, and a card whose bytes differ from the manifest must not be uploaded.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from swing_trade_ml.ml import backup_manifest as bm

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "backup-models-offsite.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("sha256sum") is None, reason="needs bash and sha256sum"
)

DOCKER = """#!/usr/bin/env bash
case "$1" in
  exec) exit 0 ;;
  cp) src=${2#*:}
      if [ "$src" = /tmp/manifest.json ]; then cp "$STUB_MANIFEST" "$3"; else cp "$STUB_MODEL_DIR/$(basename "$src")" "$3"; fi ;;
  *) echo "stub docker: unexpected $*" >&2; exit 97 ;;
esac
"""
RCLONE = """#!/usr/bin/env bash
case "$1" in
  lsf) [ -e "$STUB_REMOTE_DIR/${2#*:*/}" ] && basename "$2"; exit 0 ;;
  copy) d="$STUB_REMOTE_DIR/$(basename "$3")"; mkdir -p "$d"; cp "$2" "$d/" ;;
  *) echo "stub rclone: unexpected $*" >&2; exit 97 ;;
esac
"""
OPENSSL = """#!/usr/bin/env bash
while [ $# -gt 0 ]; do case "$1" in -in) in=$2; shift;; -out) out=$2; shift;; esac; shift; done
cp "$in" "$out"
"""


def _setup(tmp: Path):
    models = tmp / "models"
    models.mkdir()
    artifact = models / "sl1_S1_lane_v1.joblib"
    artifact.write_bytes(b"model bytes")
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    card = models / (artifact.name + bm.CARD_SUFFIX)
    card.write_text(json.dumps({"artifact_sha256": sha}), encoding="utf-8")
    rows = [
        {"id": 1, "name": "sl1_S1_lane", "version": "v1", "status": "TRAINED", "artifact_path": str(artifact)}
    ]
    manifest = bm.build_manifest(rows, models)
    (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    b = tmp / "bin"
    b.mkdir()
    py = Path(sys.executable).as_posix()
    for name, body in {
        "docker": DOCKER,
        "rclone": RCLONE,
        "openssl": OPENSSL,
        "python3": f'#!/usr/bin/env bash\nexec "{py}" "$@"\n',
    }.items():
        (b / name).write_text(body, encoding="utf-8", newline="\n")
        (b / name).chmod(0o755)
    # The checkout may hold the script with CRLF endings (Windows); the server runs it with LF.
    script = tmp / "backup-models-offsite.sh"
    script.write_bytes(SCRIPT.read_bytes().replace(b"\r\n", b"\n"))
    remote = tmp / "remote"
    remote.mkdir()
    (tmp / "pass").write_text("x\n", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{b}{os.pathsep}{os.environ['PATH']}",
        "STUB_MANIFEST": str(tmp / "manifest.json"),
        "STUB_MODEL_DIR": str(models),
        "STUB_REMOTE_DIR": str(remote),
        "BACKUP_REMOTE": "gdrive:backups",
        "PASSPHRASE_FILE": str(tmp / "pass"),
    }
    return script, env, remote, artifact, card


def _run(script, env):
    return subprocess.run(
        [BASH, str(script), "20261125_0100"], capture_output=True, text=True, env=env, timeout=120
    )


def test_the_card_is_uploaded_once_under_its_sha256_beside_its_model_file(tmp_path):
    script, env, remote, artifact, card = _setup(tmp_path)
    done = _run(script, env)
    assert done.returncode == 0, done.stderr
    uploaded = {p.name: p.read_bytes() for p in (remote / "models").iterdir()}
    for f in (artifact, card):
        assert uploaded[hashlib.sha256(f.read_bytes()).hexdigest() + ".enc"] == f.read_bytes()
    assert len(uploaded) == 2
    assert (remote / "manifests" / "manifest-20261125_0100.json.enc").is_file()
    assert "uploaded 2, already there 0, failed 0" in done.stdout

    again = _run(script, env)  # a second night: nothing is uploaded twice
    assert again.returncode == 0 and "uploaded 0, already there 2, failed 0" in again.stdout


def test_a_card_that_changed_after_the_manifest_was_written_is_not_uploaded(tmp_path):
    script, env, remote, artifact, card = _setup(tmp_path)
    card.write_text('{"artifact_sha256": "tampered"}', encoding="utf-8")
    done = _run(script, env)
    assert done.returncode != 0
    assert "does not match its recorded sha256" in done.stderr
    assert [p.name for p in (remote / "models").iterdir()] == [
        hashlib.sha256(artifact.read_bytes()).hexdigest() + ".enc"
    ]
