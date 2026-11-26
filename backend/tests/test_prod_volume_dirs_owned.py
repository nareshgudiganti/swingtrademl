"""Every named volume the prod worker mounts under /app/data must be created and chowned in the Dockerfile.

A fresh named volume mounts root-owned unless the image already has the directory owned by appuser, and the
worker runs as appuser, so a missing entry fails only at runtime, swallowed by the job's error handler
(independent review of #550)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _worker_named_volume_targets() -> set[str]:
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    worker = compose.split("\n  worker:", 1)[1].split("\n  frontend:", 1)[0]
    return {dst for _src, dst in re.findall(r"^\s+- ([A-Za-z0-9_]+):(/app/data/[^\s:]+)", worker, flags=re.M)}


def test_every_worker_data_volume_dir_exists_and_is_appuser_owned_in_the_image():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    mkdir = re.search(r"RUN mkdir -p ([^&\n]+)&& chown -R appuser:appuser /app", dockerfile)
    assert mkdir, "Dockerfile no longer creates and chowns the data directories"
    created = set(mkdir.group(1).split())
    targets = _worker_named_volume_targets()
    assert "/app/data/model_backups" in targets  # the parser still sees the known volume
    missing = sorted(targets - created)
    assert not missing, f"named volumes not created/chowned in the Dockerfile: {missing}"
