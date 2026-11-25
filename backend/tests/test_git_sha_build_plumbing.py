# ruff: noqa: E501
"""#328 slice 2a: the commit sha reaches the running image, so a model card can record its code version.

Release scripts export GIT_SHA from the release commit, compose passes it as a build arg to the api and worker
images, the Dockerfile bakes it into the environment, and ml.model_card reads it."""

from __future__ import annotations

from pathlib import Path

from swing_trade_ml.ml import model_card as mc

ROOT = Path(__file__).resolve().parents[2]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_dockerfile_bakes_the_arg_into_the_runtime_environment():
    docker = _text("backend/Dockerfile")
    runtime = docker.split("AS runtime", 1)[1]
    assert "ARG GIT_SHA=" in runtime and "ENV GIT_SHA=$GIT_SHA" in runtime
    # after every cached layer (apt-get, pip), just before the user switch, so a new sha rebuilds nothing heavy
    assert runtime.index("apt-get install") < runtime.index("ARG GIT_SHA=") < runtime.index("USER appuser")
    assert runtime.index("COPY src ./src") < runtime.index("ARG GIT_SHA=")


def test_compose_passes_the_sha_to_both_images():
    compose = _text("docker-compose.yml")
    assert compose.count("GIT_SHA: ${GIT_SHA:-}") == 2
    assert compose.index("GIT_SHA: ${GIT_SHA:-}") < compose.index("container_name: stml-api")


def test_release_scripts_export_the_release_commit_before_building():
    prod = _text("infra/deploy/release.sh")
    assert prod.index('export GIT_SHA="$release_sha"') < prod.index('"${compose[@]}" build api worker frontend')
    staging = _text("infra/staging/release-staging.sh")
    assert staging.index('export GIT_SHA="$release_sha"') < staging.index('"${compose[@]}" build api frontend')


def test_model_card_reads_the_baked_value(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    assert mc.git_state()["sha"] == "0123456789abcdef0123456789abcdef01234567"
