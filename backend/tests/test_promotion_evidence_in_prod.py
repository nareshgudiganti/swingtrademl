"""#328: promotion evidence is re-hashed from disk. The production image has no docs/ folder (REPO_ROOT
lands in site-packages), so docker-compose.prod.yml mounts docs/model-audit under EVIDENCE_ROOT. These
tests fail if the mount and the folder check_evidence looks in drift apart."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from swing_trade_ml.ml import promotion

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"


class _Loader(yaml.SafeLoader):
    """Compose tags such as !reset and !override are not plain YAML; read them as their value."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode) else None
    ),
)


def _api() -> dict:
    return yaml.load(COMPOSE.read_text(encoding="utf-8"), Loader=_Loader)["services"]["api"]


def test_prod_api_sets_evidence_root_and_mounts_audit_folder_under_it():
    api = _api()
    root = api["environment"]["EVIDENCE_ROOT"]
    mounts = [v.split(":") for v in api["volumes"]]
    audit = [m for m in mounts if m[0].rstrip("/").endswith("docs/model-audit")]
    assert audit, "prod api must mount docs/model-audit"
    assert audit[0][1] == f"{root}/docs/model-audit"
    assert audit[0][-1] == "ro"


def test_check_evidence_reads_from_evidence_root(tmp_path, monkeypatch):
    mount = tmp_path / "evidence" / "docs" / "model-audit"
    mount.mkdir(parents=True)
    f = mount / "r.md"
    f.write_text("evidence", encoding="utf-8")
    monkeypatch.setattr(promotion, "REPO_ROOT", tmp_path / "elsewhere")
    monkeypatch.setenv("EVIDENCE_ROOT", str(tmp_path / "evidence"))
    ref = {"path": "docs/model-audit/r.md", "sha256": hashlib.sha256(b"evidence").hexdigest()}
    assert promotion.check_evidence([ref]) == [ref]


def test_without_evidence_root_a_missing_folder_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(promotion, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("EVIDENCE_ROOT", raising=False)
    with pytest.raises(promotion.PromotionError, match="not found"):
        promotion.check_evidence([{"path": "docs/model-audit/r.md", "sha256": "0" * 64}])
