"""The off-server copy: an authenticated zip of every registered artifact.

The server-side backup lives on the same disk as the models, so it does not
survive losing the server. This route is how a copy leaves it — and it must
never hand out server paths or secrets while doing so.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime

from swing_trade_ml.db.models.ml import MLModel

HEADERS = {"X-API-Key": "test-api-key"}
URL = "/api/v1/ml/backup/models.zip"


def _model(db_session, name, version, path, status="ACTIVE") -> MLModel:
    model = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=status,
        artifact_path=str(path),
        feature_names=["a"],
        trained_at=datetime.now(UTC),
    )
    db_session.add(model)
    db_session.flush()
    return model


def test_download_requires_auth(client):
    assert client.get(URL).status_code in (401, 403)


def test_zip_holds_every_version_with_verifiable_manifest(client, db_session, tmp_path):
    (tmp_path / "a_v2.joblib").write_bytes(b"champion-bytes")
    (tmp_path / "a_v1.joblib").write_bytes(b"archived-bytes")
    _model(db_session, "swing_classifier", "v2", tmp_path / "a_v2.joblib")
    _model(db_session, "swing_classifier", "v1", tmp_path / "a_v1.joblib", status="ARCHIVED")
    _model(db_session, "swing_classifier", "v0", tmp_path / "gone.joblib", status="ARCHIVED")

    resp = client.get(URL, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    manifest = json.loads(archive.read("manifest.json"))
    by_version = {e["version"]: e for e in manifest["artifacts"]}
    assert set(by_version) == {"v0", "v1", "v2"}

    for version, payload in (("v2", b"champion-bytes"), ("v1", b"archived-bytes")):
        entry = by_version[version]
        assert entry["missing"] is False
        assert entry["size"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
        assert archive.read(entry["file"]) == payload
        assert entry["produced_at"]

    assert by_version["v0"]["missing"] is True
    assert by_version["v0"]["file"] is None


def test_nothing_server_specific_leaks(client, db_session, tmp_path):
    (tmp_path / "m.joblib").write_bytes(b"x")
    _model(db_session, "m", "v1", tmp_path / "m.joblib")
    _model(db_session, "n", "v1", tmp_path / "nope.joblib")

    resp = client.get(URL, headers=HEADERS)

    manifest_text = zipfile.ZipFile(io.BytesIO(resp.content)).read("manifest.json").decode()
    assert str(tmp_path) not in manifest_text
    assert str(tmp_path).replace("\\", "/") not in manifest_text
    assert "test-api-key" not in manifest_text
    assert "test-api-key" not in "".join(f"{k}{v}" for k, v in resp.headers.items())
