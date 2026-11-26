"""#525: the production image installs from a constraints file, so a rebuild cannot change model-serving libraries."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_LIBS = ("lightgbm", "scikit-learn", "numpy", "pandas", "scipy", "joblib")


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def _pins() -> dict[str, str]:
    pins = {}
    for line in _text("backend/constraints.txt").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+]+)", line)
            assert m, f"not an exact pin: {line!r}"
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_model_relevant_libraries_are_pinned_exactly():
    pins = _pins()
    for lib in MODEL_LIBS:
        assert lib in pins, f"{lib} is not pinned in backend/constraints.txt"


def test_every_direct_runtime_dependency_is_pinned():
    block = _text("backend/pyproject.toml").split("dependencies = [", 1)[1].split("\n]", 1)[0]
    pins = _pins()
    for name in re.findall(r'^\s*"([A-Za-z0-9_.\-]+)', block, flags=re.M):
        assert name.lower().replace("_", "-") in pins, f"{name} missing from constraints.txt"


def test_pins_satisfy_the_pyproject_lower_bounds():
    from packaging.requirements import Requirement
    from packaging.version import Version

    block = _text("backend/pyproject.toml").split("dependencies = [", 1)[1].split("\n]", 1)[0]
    pins = _pins()
    for raw in re.findall(r'^\s*"([^"]+)"', block, flags=re.M):
        req = Requirement(raw)
        pinned = pins[req.name.lower().replace("_", "-")]
        assert req.specifier.contains(Version(pinned)), f"{req.name}=={pinned} violates {req.specifier}"


def test_dockerfile_installs_with_the_constraints_file():
    docker = _text("backend/Dockerfile")
    builder, runtime = docker.split("AS runtime", 1)
    assert "COPY pyproject.toml constraints.txt" in builder
    assert "pip wheel --constraint constraints.txt" in builder
    assert "COPY constraints.txt" in runtime
    assert "pip install --no-index --constraint constraints.txt" in runtime
